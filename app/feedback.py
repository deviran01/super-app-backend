"""Feedback from the app: short anonymous messages, read in the admin dashboard.

    POST /api/v1/feedback    {kind, text, platform, channel, appVersion, osVersion}

Feedback is anonymous like everything else the app sends: the message, its kind, and the
build that sent it (store channel, versionCode, Android API level). No account, device id,
address or contact detail is stored.

Users aren't restricted: any non-empty message up to MAX_CHARS is taken. The limits only
keep a flood from taking the server or its disk down:

- the body is at most 8 KB (nginx and the API);
- per address (kept in memory only, never stored), a burst limit; behind the CDN the address
  is the CDN edge's, which many users share, so it is generous;
- for everyone together, caps per minute, hour and day, past which the API answers 429;
- the same text sent again within a week only bumps a counter on the first copy;
- at most MAX_STORED messages (the oldest spam, archived and read ones make room), deleted
  after RETENTION_DAYS.

Text is normalized (control and bidi-override characters removed, whitespace tidied) so it
shows safely in the dashboard. The catalog feature flag `feedback` (dashboard → Settings)
turns it off here and in the app.
"""
from __future__ import annotations

import hashlib
import logging
import re
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

MIN_CHARS = 1
MAX_CHARS = 1000
KINDS = ("problem", "idea", "other")
STATUSES = ("new", "read", "archived", "spam")
FOLDERS = {"inbox": ("new", "read"), "archived": ("archived",), "spam": ("spam",)}

# (window in seconds, messages): per address, and for everyone together.
ADDRESS_LIMITS = ((60, 10),)
GLOBAL_LIMITS = ((60, 60), (3600, 600), (86400, 3000))
MAX_ADDRESSES = 10_000

DUPLICATE_SECONDS = 7 * 86400
MAX_STORED = 10_000
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
"""

# Direction overrides and isolates would let a message reorder how the dashboard shows it.
BIDI_CONTROLS = re.compile("[\u202a-\u202e\u2066-\u2069]")
SPACES = re.compile(r"[^\S\n]+")
BLANK_LINES = re.compile(r"\n{3,}")
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
    channel: str
    app_version: int
    os_version: int


def normalize(text: str) -> str:
    """The text as stored: NFC, no control or bidi-override characters, tidy whitespace.
    Zero-width (non-)joiners stay: Persian spelling uses them."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = BIDI_CONTROLS.sub("", text)
    text = "".join(c for c in text if c in "\n\u200c\u200d" or unicodedata.category(c)[0] != "C")
    text = "\n".join(SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return BLANK_LINES.sub("\n\n", text).strip()


def fingerprint(text: str) -> str:
    """Same for texts that differ only in case, punctuation, spacing, digits or letter forms."""
    core = "".join(c for c in text.casefold().translate(UNIFY) if c.isalnum())
    core = "".join(str(unicodedata.digit(c)) if c.isdigit() else c for c in core)
    return hashlib.sha256(core.encode("utf-8")).hexdigest()




class FeedbackStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._ready = False
        self._lock = threading.Lock()  # one submission at a time: limits are checked, then counted
        self._addresses: dict[str, deque[float]] = {}
        self._pruned_at = 0.0

    # --- receiving ------------------------------------------------------------------------

    def submit(self, message: Message, address: str) -> int:
        """Stores a message; returns its id (or the id of the earlier copy it repeats).
        Raises Refused when it isn't taken."""
        text = normalize(message.text)
        if not MIN_CHARS <= len(text) <= MAX_CHARS or message.kind not in KINDS:
            raise Refused(400, "invalid")
        now = int(time.time())
        with self._lock, self._db() as db:
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
            cursor = db.execute(
                "INSERT INTO feedback (created_at, kind, text, fingerprint, status, channel, app_version, os_version) VALUES (?, ?, ?, ?, 'new', ?, ?, ?)",
                (now, message.kind, text, digest, message.channel, message.app_version, message.os_version),
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

    def _prune(self, db: sqlite3.Connection, now: int) -> None:
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
        "repeats": row["repeats"],
        "channel": row["channel"],
        "appVersion": row["app_version"],
        "osVersion": row["os_version"],
    }
