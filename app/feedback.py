"""Feedback from the app: short anonymous messages, read in the admin dashboard.

    GET  /api/v1/feedback/challenge   a one-time proof-of-work challenge
    POST /api/v1/feedback             the message, with the solved challenge

Feedback is anonymous like everything else the app sends: the message, its kind, and the
build that sent it (store channel, versionCode, Android API level). No account, device id,
address or contact detail is stored.

Abuse and spam are handled without identifying anyone:

- Proof of work. Every message needs a fresh challenge (signed by this server, valid for ten
  minutes, usable once) and a nonce that gives SHA-256("<challenge>:<nonce>") `difficulty`
  leading zero bits. A phone finds one in about a second; a script pays that for every
  message. The difficulty rises with the volume of the last hour.
- Limits. Per address (kept in memory only, never stored) and overall per hour and per day;
  past them the API answers 429. Behind the CDN the address is the CDN edge's, which many
  users share, so the per-address limits are generous.
- Content. Text is normalized (control and bidi-override characters removed, whitespace
  collapsed) and must be MIN_CHARS–MAX_CHARS long. A message that looks like spam (many links,
  one character repeated, hardly any letters) goes to the Spam folder instead of the inbox,
  and the same text sent again only bumps a counter on the first copy. The sender gets the
  same answer either way, so a spammer can't tell what was filtered.
- Storage. Messages are deleted after RETENTION_DAYS; past MAX_STORED the oldest spam,
  archived and read ones go first, and when only unread ones are left new ones are refused.
- The catalog feature flag `feedback` (dashboard → Settings) turns it off here and in the app.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("feedback")

MIN_CHARS = 10
MAX_CHARS = 1000
KINDS = ("problem", "idea", "other")
STATUSES = ("new", "read", "archived", "spam")
FOLDERS = {"inbox": ("new", "read"), "archived": ("archived",), "spam": ("spam",)}

CHALLENGE_SECONDS = 600
BASE_DIFFICULTY = 18
# Messages received in the last hour from which each extra bit of difficulty applies (max 21).
DIFFICULTY_STEPS = (20, 60, 150)

# (window in seconds, messages): per address, and for everyone together.
ADDRESS_LIMITS = ((600, 6), (3600, 20))
GLOBAL_LIMITS = ((3600, 200), (86400, 1000))
MAX_ADDRESSES = 10_000

DUPLICATE_SECONDS = 7 * 86400
MAX_STORED = 20_000
RETENTION_DAYS = 365

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  INTEGER NOT NULL,
    kind        TEXT    NOT NULL,
    text        TEXT    NOT NULL,
    fingerprint TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    spam_reason TEXT    NOT NULL DEFAULT '',
    repeats     INTEGER NOT NULL DEFAULT 0,
    channel     TEXT    NOT NULL,
    app_version INTEGER NOT NULL,
    os_version  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS feedback_status ON feedback (status, id);
CREATE INDEX IF NOT EXISTS feedback_created ON feedback (created_at);
CREATE INDEX IF NOT EXISTS feedback_fingerprint ON feedback (fingerprint);
CREATE TABLE IF NOT EXISTS used_challenges (
    id      TEXT    PRIMARY KEY,
    expires INTEGER NOT NULL
) WITHOUT ROWID;
"""

# Direction overrides and isolates would let a message reorder how the dashboard shows it.
BIDI_CONTROLS = re.compile("[‪-‮⁦-⁩]")
SPACES = re.compile(r"[^\S\n]+")
BLANK_LINES = re.compile(r"\n{3,}")
LINK = re.compile(
    r"(?i)(?:https?://|www\.)\S+"
    r"|\b[a-z0-9-]{2,}\.(?:com|net|org|ir|io|me|xyz|top|info|link|site|online|shop|app|biz|click|cc|ru)\b"
    r"|\bt\.me/\S+|(?<!\w)@[a-z][a-z0-9_]{4,}"
)
REPEATED = re.compile(r"(.)\1{19,}", re.S)
# Arabic letters that Persian writes differently, and every digit, mapped to one form so
# variants of the same text are recognized as repeats.
UNIFY = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "آ": "ا"})


class Refused(Exception):
    """A message that isn't taken: the HTTP status and a short machine-readable reason."""

    def __init__(self, status: int, reason: str, retry_after: int | None = None) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.retry_after = retry_after


@dataclass(frozen=True)
class Message:
    kind: str
    text: str
    challenge: str
    nonce: str
    channel: str
    app_version: int
    os_version: int


def normalize(text: str) -> str:
    """The text as stored: NFC, no control or bidi-override characters, tidy whitespace.
    Zero-width (non-)joiners stay: Persian spelling uses them."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = BIDI_CONTROLS.sub("", text)
    text = "".join(c for c in text if c in "\n‌‍" or unicodedata.category(c)[0] != "C")
    text = "\n".join(SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return BLANK_LINES.sub("\n\n", text).strip()


def fingerprint(text: str) -> str:
    """Same for texts that differ only in case, punctuation, spacing, digits or letter forms."""
    core = "".join(c for c in text.casefold().translate(UNIFY) if c.isalnum())
    core = "".join(str(unicodedata.digit(c)) if c.isdigit() else c for c in core)
    return hashlib.sha256(core.encode("utf-8")).hexdigest()


def spam_reason(text: str) -> str | None:
    if len(LINK.findall(text)) > 2:
        return "links"
    if REPEATED.search(text):
        return "repeated"
    visible = [c for c in text if not c.isspace()]
    if sum(c.isalpha() for c in visible) < len(visible) * 0.4:
        return "symbols"
    if len(visible) >= 40 and len({c.casefold() for c in visible}) < 8:
        return "repetitive"
    return None


def leading_zero_bits(digest: bytes) -> int:
    return len(digest) * 8 - int.from_bytes(digest, "big").bit_length()


def difficulty_for(recent: int) -> int:
    return BASE_DIFFICULTY + sum(recent >= step for step in DIFFICULTY_STEPS)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class FeedbackStore:
    def __init__(self, path: Path, secret: bytes | None = None) -> None:
        self._path = path
        self._secret = secret
        self._ready = False
        self._lock = threading.Lock()  # one submission at a time: limits are checked, then counted
        self._addresses: dict[str, deque[float]] = {}
        self._pruned_at = 0.0

    # --- challenges ---------------------------------------------------------------------

    def challenge(self) -> dict[str, Any]:
        now = int(time.time())
        difficulty = difficulty_for(self._received_since(now - 3600))
        payload = f"v1.{now}.{difficulty}.{_b64(secrets.token_bytes(12))}"
        return {"challenge": f"{payload}.{self._sign(payload)}", "difficulty": difficulty, "expiresIn": CHALLENGE_SECONDS}

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self._key(), payload.encode("ascii"), hashlib.sha256).digest()[:16])

    def _key(self) -> bytes:
        """From SUPERAPP_FEEDBACK_SECRET, or a random key kept next to the database."""
        if self._secret is None:
            configured = os.environ.get("SUPERAPP_FEEDBACK_SECRET")
            if configured:
                self._secret = configured.encode("utf-8")
            else:
                path = self._path.parent / "secret"
                path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    self._secret = path.read_bytes()
                else:
                    with os.fdopen(fd, "wb") as file:
                        self._secret = secrets.token_bytes(32)
                        file.write(self._secret)
        return self._secret

    def _check_challenge(self, db: sqlite3.Connection, challenge: str, nonce: str, now: int) -> None:
        parts = challenge.split(".")
        if len(parts) != 5 or parts[0] != "v1" or not hmac.compare_digest(self._sign(".".join(parts[:4])), parts[4]):
            raise Refused(409, "challenge")
        try:
            issued, difficulty = int(parts[1]), int(parts[2])
        except ValueError:
            raise Refused(409, "challenge")
        if not now - CHALLENGE_SECONDS <= issued <= now + 60:
            raise Refused(409, "challenge")
        if leading_zero_bits(hashlib.sha256(f"{challenge}:{nonce}".encode("ascii")).digest()) < difficulty:
            raise Refused(409, "challenge")
        try:
            db.execute("INSERT INTO used_challenges (id, expires) VALUES (?, ?)", (parts[3], issued + CHALLENGE_SECONDS))
        except sqlite3.IntegrityError:
            raise Refused(409, "challenge")

    # --- receiving ------------------------------------------------------------------------

    def submit(self, message: Message, address: str) -> int:
        """Stores a message; returns its id (or the id of the earlier copy it repeats).
        Raises Refused when it isn't taken."""
        text = normalize(message.text)
        if not MIN_CHARS <= len(text) <= MAX_CHARS or message.kind not in KINDS:
            raise Refused(400, "invalid")
        now = int(time.time())
        with self._lock, self._db() as db:
            self._check_challenge(db, message.challenge, message.nonce, now)
            self._check_address(address, now)
            for window, limit in GLOBAL_LIMITS:
                if self._count_since(db, now - window) >= limit:
                    raise Refused(429, "busy", retry_after=min(window, 3600))
            self._prune(db, now)
            digest = fingerprint(text)
            earlier = db.execute(
                "SELECT id FROM feedback WHERE fingerprint = ? AND created_at >= ? ORDER BY id DESC LIMIT 1",
                (digest, now - DUPLICATE_SECONDS),
            ).fetchone()
            if earlier:
                db.execute("UPDATE feedback SET repeats = repeats + 1 WHERE id = ?", (earlier[0],))
                return earlier[0]
            reason = spam_reason(text)
            cursor = db.execute(
                "INSERT INTO feedback (created_at, kind, text, fingerprint, status, spam_reason, channel, app_version, os_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (now, message.kind, text, digest, "spam" if reason else "new", reason or "", message.channel, message.app_version, message.os_version),
            )
            return cursor.lastrowid

    def _check_address(self, address: str, now: float) -> None:
        longest = max(window for window, _ in ADDRESS_LIMITS)
        times = self._addresses.get(address)
        if times is None:
            if len(self._addresses) >= MAX_ADDRESSES:
                # Forget addresses with nothing in the window; if every slot is busy, the oldest.
                self._addresses = {a: t for a, t in self._addresses.items() if t and t[-1] > now - longest}
                if len(self._addresses) >= MAX_ADDRESSES:
                    del self._addresses[min(self._addresses, key=lambda a: self._addresses[a][-1])]
            times = self._addresses[address] = deque()
        while times and times[0] <= now - longest:
            times.popleft()
        for window, limit in ADDRESS_LIMITS:
            recent = [t for t in times if t > now - window]
            if len(recent) >= limit:
                raise Refused(429, "rate", retry_after=max(1, int(recent[0] + window - now)))
        times.append(now)

    def _count_since(self, db: sqlite3.Connection, since: int) -> int:
        return db.execute("SELECT COUNT(*) FROM feedback WHERE created_at >= ?", (since,)).fetchone()[0]

    def _received_since(self, since: int) -> int:
        if not self._path.exists():
            return 0
        with self._db() as db:
            return self._count_since(db, since)

    def _prune(self, db: sqlite3.Connection, now: int) -> None:
        db.execute("DELETE FROM used_challenges WHERE expires < ?", (now,))
        if now - self._pruned_at >= 3600:
            db.execute("DELETE FROM feedback WHERE created_at < ?", (now - RETENTION_DAYS * 86400,))
            self._pruned_at = now
        excess = db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] - MAX_STORED + 1
        for status in ("spam", "archived", "read"):
            if excess <= 0:
                return
            excess -= db.execute(
                "DELETE FROM feedback WHERE id IN (SELECT id FROM feedback WHERE status = ? ORDER BY id LIMIT ?)", (status, excess)
            ).rowcount
        if excess > 0:
            raise Refused(429, "full", retry_after=3600)

    # --- the dashboard --------------------------------------------------------------------

    def page(self, folder: str, before: int | None, limit: int) -> dict[str, Any]:
        statuses = FOLDERS[folder]
        marks = ",".join("?" * len(statuses))
        items: list[dict[str, Any]] = []
        if self._path.exists():
            with self._db() as db:
                rows = db.execute(
                    f"SELECT * FROM feedback WHERE status IN ({marks}) AND id < ? ORDER BY id DESC LIMIT ?",
                    (*statuses, before or 2**62, limit + 1),
                ).fetchall()
            items = [_item(row) for row in rows]
        more = len(items) > limit
        return {"items": items[:limit], "next": items[limit - 1]["id"] if more else None, "counts": self.counts()}

    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys(STATUSES, 0)
        if self._path.exists():
            with self._db() as db:
                counts.update({status: n for status, n in db.execute("SELECT status, COUNT(*) FROM feedback GROUP BY status")})
        return {"unread": counts["new"], "inbox": counts["new"] + counts["read"], "archived": counts["archived"], "spam": counts["spam"]}

    def set_status(self, item_id: int, status: str) -> dict[str, Any] | None:
        with self._db() as db:
            db.execute("UPDATE feedback SET status = ? WHERE id = ?", (status, item_id))
            row = db.execute("SELECT * FROM feedback WHERE id = ?", (item_id,)).fetchone()
        return _item(row) if row else None

    def mark_all_read(self) -> int:
        with self._db() as db:
            return db.execute("UPDATE feedback SET status = 'read' WHERE status = 'new'").rowcount

    def delete(self, item_id: int) -> bool:
        with self._db() as db:
            return db.execute("DELETE FROM feedback WHERE id = ?", (item_id,)).rowcount > 0

    def empty_spam(self) -> int:
        with self._db() as db:
            return db.execute("DELETE FROM feedback WHERE status = 'spam'").rowcount

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        """A connection that commits on success and is always closed."""
        if not self._ready:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self._path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=NORMAL")
            if not self._ready:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript(SCHEMA)
                self._ready = True
            with db:
                yield db
        finally:
            db.close()


def _item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "createdAt": row["created_at"],
        "kind": row["kind"],
        "text": row["text"],
        "status": row["status"],
        "spamReason": row["spam_reason"] or None,
        "repeats": row["repeats"],
        "channel": row["channel"],
        "appVersion": row["app_version"],
        "osVersion": row["os_version"],
    }
