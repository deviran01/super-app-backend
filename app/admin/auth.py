"""Admin accounts and sessions.

- Passwords are stored as scrypt hashes with a per-user salt (data/admin/admins.json).
- A session is an HMAC-signed cookie (key in data/admin/secret.key) carrying the username,
  an expiry and the account's session epoch; signing out or changing the password bumps the
  epoch, which ends every session of that account.
- The cookie is HttpOnly, SameSite=Strict and (in production) Secure with the __Host-
  prefix; every state-changing request must also carry the X-Superapp-Admin header, which a
  cross-site page can't send without a CORS preflight that this API never grants.
- Failed sign-ins lock the username (and the client address) for a while.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, Request

from .store import write_json_atomically

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
MIN_PASSWORD = 10
SESSION_SECONDS = 12 * 3600
MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60
CSRF_HEADER = "x-superapp-admin"

# scrypt below takes 16 MiB per hash; at most two at a time keeps a burst of sign-ins
# inside the container's memory limit.
_HASHING = threading.BoundedSemaphore(2)

SECURE_COOKIES = os.environ.get("SUPERAPP_DEV") != "1"
COOKIE = "__Host-superapp_admin" if SECURE_COOKIES else "superapp_admin"


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    with _HASHING:
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, maxmem=64 * 1024 * 1024)
    return base64.b64encode(salt).decode(), base64.b64encode(digest).decode()


def check_password_rules(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"use at least {MIN_PASSWORD} characters")


@dataclass
class Admin:
    username: str
    created_at: float
    created_by: str


class AdminAccounts:
    def __init__(self, admin_dir: Path):
        self.path = Path(admin_dir) / "admins.json"
        self.key_path = Path(admin_dir) / "secret.key"
        self._lock = threading.Lock()
        self._failures: dict[str, tuple[int, float]] = {}
        Path(admin_dir).mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(secrets.token_bytes(32))
        self._key = self.key_path.read_bytes()

    # --- accounts ---------------------------------------------------------------------

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"admins": []}

    def _save(self, data: dict) -> None:
        write_json_atomically(self.path, data)
        os.chmod(self.path, 0o600)

    def list(self) -> list[Admin]:
        return [Admin(a["username"], a["createdAt"], a.get("createdBy", "")) for a in self._load()["admins"]]

    def create(self, username: str, password: str, created_by: str) -> Admin:
        username = username.strip().lower()
        if not USERNAME_RE.match(username):
            raise ValueError("username: 3–32 lowercase letters, digits, '.', '-' or '_'")
        check_password_rules(password)
        with self._lock:
            data = self._load()
            if any(a["username"] == username for a in data["admins"]):
                raise ValueError(f"{username!r} already exists")
            salt, digest = hash_password(password)
            # A random first epoch: sessions of a deleted account with the same name stay invalid.
            entry = {"username": username, "salt": salt, "hash": digest, "epoch": secrets.randbelow(2**31), "createdAt": time.time(), "createdBy": created_by}
            data["admins"].append(entry)
            self._save(data)
        return Admin(username, entry["createdAt"], created_by)

    def delete(self, username: str, by: str) -> None:
        with self._lock:
            data = self._load()
            if username == by:
                raise ValueError("you can't remove your own account")
            remaining = [a for a in data["admins"] if a["username"] != username]
            if len(remaining) == len(data["admins"]):
                raise KeyError(username)
            data["admins"] = remaining
            self._save(data)

    def set_password(self, username: str, password: str) -> None:
        check_password_rules(password)
        with self._lock:
            data = self._load()
            for admin in data["admins"]:
                if admin["username"] == username:
                    admin["salt"], admin["hash"] = hash_password(password)
                    admin["epoch"] = admin.get("epoch", 0) + 1  # sign out everywhere
                    self._save(data)
                    return
            raise KeyError(username)

    def end_sessions(self, username: str) -> None:
        with self._lock:
            data = self._load()
            for admin in data["admins"]:
                if admin["username"] == username:
                    admin["epoch"] = admin.get("epoch", 0) + 1
                    self._save(data)

    # --- sign in ----------------------------------------------------------------------

    def verify(self, username: str, password: str, client: str) -> bool:
        username = username.strip().lower()
        now = time.time()
        if len(self._failures) > 10_000:  # forget expired lockouts
            self._failures = {k: v for k, v in self._failures.items() if v[1] > now}
        keys = (f"user:{username}", f"ip:{client}")
        with self._lock:
            for key in keys:
                count, until = self._failures.get(key, (0, 0.0))
                if count >= MAX_FAILURES and now < until:
                    raise PermissionError(int(until - now))
            # Counted before hashing, so a burst of parallel attempts can't all get through;
            # a lock that has expired starts a fresh count instead of re-locking at once.
            for key in keys:
                count, until = self._failures.get(key, (0, 0.0))
                self._failures[key] = ((count if now < until else 0) + 1, now + LOCK_SECONDS)
        admin = next((a for a in self._load()["admins"] if a["username"] == username), None)
        # Hash even for unknown users, so timing doesn't reveal which usernames exist.
        salt = base64.b64decode(admin["salt"]) if admin else b"0" * 16
        _, digest = hash_password(password, salt)
        ok = admin is not None and hmac.compare_digest(digest, admin["hash"])
        if ok:
            with self._lock:
                for key in keys:
                    self._failures.pop(key, None)
        return ok

    def issue(self, username: str) -> str:
        admin = next(a for a in self._load()["admins"] if a["username"] == username)
        payload = json.dumps({"u": username, "e": admin.get("epoch", 0), "x": int(time.time()) + SESSION_SECONDS}).encode()
        body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        return f"{body}.{self._sign(body)}"

    def resolve(self, token: str | None) -> str | None:
        """The username a valid, unexpired, unrevoked session token belongs to."""
        if not token or "." not in token:
            return None
        body, signature = token.rsplit(".", 1)
        # Bytes: a cookie may carry non-ASCII text, which compare_digest rejects as str.
        if not hmac.compare_digest(signature.encode("utf-8", "surrogateescape"), self._sign(body).encode()):
            return None
        try:
            payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except ValueError:
            return None
        if payload.get("x", 0) < time.time():
            return None
        admin = next((a for a in self._load()["admins"] if a["username"] == payload.get("u")), None)
        if admin is None or admin.get("epoch", 0) != payload.get("e"):
            return None
        return admin["username"]

    def _sign(self, body: str) -> str:
        return base64.urlsafe_b64encode(hmac.new(self._key, body.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def require_admin(request: Request) -> str:
    """FastAPI dependency: the signed-in admin; state-changing requests also need the CSRF header."""
    accounts: AdminAccounts = request.app.state.admin_accounts
    username = accounts.resolve(request.cookies.get(COOKIE))
    if username is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    if request.method not in ("GET", "HEAD") and request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(status_code=403, detail="Missing request header")
    return username
