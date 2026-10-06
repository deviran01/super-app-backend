"""Usage statistics for the admin dashboard: daily counters, nothing else.

Two sources feed the same table:

- ``api``: the server counts its own API calls by endpoint, status, store channel and app
  version (what every request already carries; no IP or identifier is stored).
- ``app``: the app uploads anonymous daily totals (``POST /api/v1/events``) — e.g. "service
  snapp opened from home: 4" — with no device or user identifier, URL, search text or time
  finer than a day. Daily active users and installs arrive as ``active_day`` / ``first_open``
  counters that each install sends at most once per day / once ever.

Reports aren't authenticated (the app has no identity to authenticate), so the numbers are
best-effort: each report is merged and capped per counter, only known events, catalog ids and
channels are kept, and the app version is stored only for users and installs, which bounds what
a forged report can add or how many rows it can create.

Counts are buffered in memory and written to SQLite (``data/stats/stats.db``) by a
background thread every few seconds, and before every read.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import AbstractSet as Set, Any, Iterable, Iterator

log = logging.getLogger("stats")

# Iran Standard Time (no daylight saving since 2022): "today" for API calls and report checks.
IRAN = timezone(timedelta(hours=3, minutes=30))

FLUSH_SECONDS = 10
MAX_PENDING_KEYS = 50_000
RETENTION_DAYS = 400
MAX_REPORT_DAYS = 8
MAX_COUNTS_PER_DAY = 400
MAX_RANGE_DAYS = 366

OTHER = "other"
OPEN_SOURCES = {"home", "favorites", "recent", "category", "search", "tabs", "quick_switch", "add_service", "link"}
PAGE_ERRORS = {
    "offline", "host_not_found", "timeout", "connection_failed", "insecure_connection",
    "unsupported_url", "crashed", "web_view_unavailable", "generic",
}
CLEAR_SCOPES = {"cache", "service", "all"}
# The only app events stored per app version (the dashboard's users/installs per version).
VERSIONED_EVENTS = {"active_day", "first_open"}

# event -> (validators of its dimensions, the most one install can add in a day)
SERVICE, CATEGORY = "service", "category"
EVENTS: dict[str, tuple[tuple[Any, ...], int]] = {
    "app_opened": ((), 500),
    "active_day": ((), 1),
    "first_open": ((), 1),
    "service_opened": ((SERVICE, OPEN_SOURCES), 2000),
    "service_closed": ((SERVICE,), 2000),
    "tab_switched": ((SERVICE,), 5000),
    "favorite_added": ((SERVICE,), 200),
    "favorite_removed": ((SERVICE,), 200),
    "category_opened": ((CATEGORY,), 1000),
    "search_used": (({"found", "none"},), 2000),
    "force_update_shown": ((), 500),
    "optional_update_shown": ((), 500),
    "update_clicked": ((), 200),
    "data_cleared": ((CLEAR_SCOPES,), 100),
    "service_load_failed": ((SERVICE, PAGE_ERRORS), 2000),
}

DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SCHEMA = """
CREATE TABLE IF NOT EXISTS counts (
    day     TEXT    NOT NULL,
    source  TEXT    NOT NULL,
    event   TEXT    NOT NULL,
    dim1    TEXT    NOT NULL DEFAULT '',
    dim2    TEXT    NOT NULL DEFAULT '',
    channel TEXT    NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 0,
    n       INTEGER NOT NULL,
    PRIMARY KEY (day, source, event, dim1, dim2, channel, version)
) WITHOUT ROWID;
"""

Key = tuple[str, str, str, str, str, str, int]


def today() -> date:
    return datetime.now(IRAN).date()


def status_class(status: int) -> str:
    if status == 304:
        return "304"
    return f"{status // 100}xx"


class StatsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()  # guards _pending only; held for microseconds
        self._write_lock = threading.Lock()  # one writer at a time
        self._pending: Counter[Key] = Counter()
        self._ready = False
        self._pruned_on: date | None = None
        self._worker: threading.Thread | None = None

    # --- writing ------------------------------------------------------------------------

    def count_api_call(self, endpoint: str, status: int, channel: str, version: int) -> None:
        self._add([((today().isoformat(), "api", endpoint, status_class(status), "", channel, version), 1)])

    def add_report(self, report: dict[str, Any], *, services: Set[str], categories: Set[str], channels: Set[str], max_version: int) -> int:
        """Adds an app report (already shape-checked by the API model); returns the counters kept.

        Entries are merged per day and counter before the per-install caps apply, so repeating
        a day or a counter inside one report can't multiply it.
        """
        channel = report["channel"] if report["channel"] in channels else OTHER
        version = report["appVersion"] if 1 <= report["appVersion"] <= max_version else 0
        newest = today() + timedelta(days=1)  # devices ahead of Iran's date
        oldest = newest - timedelta(days=MAX_REPORT_DAYS + 1)
        ids = {SERVICE: services, CATEGORY: categories}
        totals: Counter[tuple[str, str, str, str]] = Counter()
        per_day: Counter[str] = Counter()
        for entry in report["days"]:
            day = _parse_day(entry["day"])
            if day is None or not oldest <= day <= newest:
                continue
            for count in entry["counts"]:
                rule = EVENTS.get(count["event"])
                dims = count["dims"]
                if rule is None or len(dims) != len(rule[0]) or count["n"] <= 0:
                    continue
                if not all(dim in (ids[check] if isinstance(check, str) else check) for dim, check in zip(dims, rule[0])):
                    continue
                padded = (list(dims) + ["", ""])[:2]
                key = (day.isoformat(), count["event"], padded[0], padded[1])
                if key not in totals:
                    if per_day[key[0]] >= MAX_COUNTS_PER_DAY:
                        continue
                    per_day[key[0]] += 1
                totals[key] += count["n"]
        kept = [
            # The app version is kept only where the dashboard uses it (users and installs per
            # version); for every other event it would multiply rows for nothing.
            ((day, "app", event, d1, d2, channel, version if event in VERSIONED_EVENTS else 0), min(n, EVENTS[event][1]))
            for (day, event, d1, d2), n in totals.items()
        ]
        self._add(kept)
        return len(kept)

    def _add(self, items: Iterable[tuple[Key, int]]) -> None:
        dropped = 0
        with self._lock:
            for key, n in items:
                if key not in self._pending and len(self._pending) >= MAX_PENDING_KEYS:
                    dropped += 1  # a flood of distinct counters: drop until the next write
                    continue
                self._pending[key] += n
        if dropped:
            log.warning("Dropped %d counters: too many pending", dropped)
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        """Writes happen on a background thread, never on a request."""
        if self._worker is None:
            with self._lock:
                if self._worker is None:
                    self._worker = threading.Thread(target=self._run, name="stats-writer", daemon=True)
                    self._worker.start()

    def _run(self) -> None:
        while True:
            time.sleep(FLUSH_SECONDS)
            self.flush()

    def flush(self) -> None:
        with self._write_lock:
            with self._lock:
                pending, self._pending = self._pending, Counter()
            if not pending:
                return
            rows = [(*key, n) for key, n in pending.items()]
            try:
                with self._db() as db:
                    db.executemany(
                        "INSERT INTO counts (day, source, event, dim1, dim2, channel, version, n) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT (day, source, event, dim1, dim2, channel, version) DO UPDATE SET n = n + excluded.n",
                        rows,
                    )
                    self._prune(db)
            except sqlite3.Error:
                # Put back and retry on the next write; statistics never fail a request.
                log.exception("Couldn't save %d counters", len(rows))
                with self._lock:
                    self._pending.update(pending)

    def _prune(self, db: sqlite3.Connection) -> None:
        """Drops days older than the retention period, once a day."""
        current = today()
        if self._pruned_on != current:
            db.execute("DELETE FROM counts WHERE day < ?", ((current - timedelta(days=RETENTION_DAYS)).isoformat(),))
            self._pruned_on = current

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        """A connection that commits on success and is always closed."""
        if not self._ready:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self._path, timeout=5)
        try:
            db.execute("PRAGMA synchronous=NORMAL")  # safe with WAL; far fewer fsyncs
            if not self._ready:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript(SCHEMA)
                self._ready = True
            with db:
                yield db
        finally:
            db.close()

    # --- reading ------------------------------------------------------------------------

    def summary(self, days: int, channel: str | None = None) -> dict[str, Any]:
        """Everything the dashboard's Statistics page shows, for the last [days] days."""
        days = max(1, min(days, MAX_RANGE_DAYS))
        last = today()
        first = last - timedelta(days=days - 1)
        where = "day BETWEEN ? AND ?" + (" AND channel = ?" if channel else "")
        params: tuple[Any, ...] = (first.isoformat(), last.isoformat()) + ((channel,) if channel else ())
        # Channels and versions: API calls, daily active users and installs.
        audience = f"{where} AND (source = 'api' OR event IN ('active_day', 'first_open'))"
        self.flush()  # include the last seconds; readers don't block the API (WAL)
        if not self._path.exists():
            rows, by_channel, by_version = [], [], []
        else:
            with self._db() as db:
                rows = db.execute(
                    f"SELECT day, source, event, dim1, dim2, SUM(n) FROM counts WHERE {where} GROUP BY day, source, event, dim1, dim2", params
                ).fetchall()
                by_channel = db.execute(f"SELECT channel, source, event, SUM(n) FROM counts WHERE {audience} GROUP BY channel, source, event", params).fetchall()
                by_version = db.execute(f"SELECT version, source, event, SUM(n) FROM counts WHERE {audience} GROUP BY version, source, event", params).fetchall()
        return _summarize(first, last, rows, by_channel, by_version)


def _parse_day(value: str) -> date | None:
    if not DAY.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _summarize(first: date, last: date, rows, by_channel, by_version) -> dict[str, Any]:
    span = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    daily = {day: Counter() for day in span}
    api = Counter()
    events = Counter()
    services: dict[str, Counter] = {}
    sources, categories, searches, cleared, failures, errors = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()

    for day, source, event, dim1, dim2, n in rows:
        bucket = daily.setdefault(day, Counter())
        if source == "api":
            bucket["apiCalls"] += n
            api[(event, dim1)] += n
            continue
        events[event] += n
        if event == "active_day":
            bucket["activeUsers"] += n
        elif event == "first_open":
            bucket["installs"] += n
        elif event == "app_opened":
            bucket["appOpens"] += n
        elif event == "service_opened":
            bucket["serviceOpens"] += n
            services.setdefault(dim1, Counter())["opens"] += n
            sources[dim2] += n
        elif event in ("service_closed", "tab_switched", "favorite_added", "favorite_removed"):
            field = {"service_closed": "closes", "tab_switched": "switches", "favorite_added": "favoritesAdded", "favorite_removed": "favoritesRemoved"}[event]
            services.setdefault(dim1, Counter())[field] += n
        elif event == "service_load_failed":
            services.setdefault(dim1, Counter())["failures"] += n
            failures[(dim1, dim2)] += n
            errors[dim2] += n
        elif event == "category_opened":
            categories[dim1] += n
        elif event == "search_used":
            searches[dim1] += n
        elif event == "data_cleared":
            cleared[dim1] += n

    active = [daily[day]["activeUsers"] for day in span]
    api_total = sum(api.values())
    return {
        "from": first.isoformat(),
        "to": last.isoformat(),
        "totals": {
            "apiCalls": api_total,
            "apiNotModified": sum(n for (_, status), n in api.items() if status == "304"),
            "apiErrors": sum(n for (_, status), n in api.items() if status in ("4xx", "5xx")),
            "activeToday": active[-1],
            "activeAverage": round(sum(active) / len(active), 1),
            "activePeak": max(active),
            "installs": events["first_open"],
            "appOpens": events["app_opened"],
            "serviceOpens": events["service_opened"],
            "searches": sum(searches.values()),
            "searchesWithoutResults": searches["none"],
            "forceUpdateShown": events["force_update_shown"],
            "optionalUpdateShown": events["optional_update_shown"],
            "updateClicks": events["update_clicked"],
            "loadFailures": events["service_load_failed"],
        },
        "daily": [{"day": day, **{k: daily[day][k] for k in ("apiCalls", "activeUsers", "installs", "appOpens", "serviceOpens")}} for day in span],
        "api": [{"endpoint": e, "status": s, "n": n} for (e, s), n in sorted(api.items(), key=lambda item: -item[1])],
        "services": sorted(
            ({"id": sid, **{k: c[k] for k in ("opens", "closes", "switches", "favoritesAdded", "favoritesRemoved", "failures")}} for sid, c in services.items()),
            key=lambda s: (-s["opens"], -s["failures"], s["id"]),
        ),
        "sources": _ranked(sources, "source"),
        "categories": _ranked(categories, "id"),
        "errors": _ranked(errors, "error"),
        "failures": [{"service": s, "error": e, "n": n} for (s, e), n in failures.most_common(50)],
        "dataCleared": _ranked(cleared, "scope"),
        "channels": _breakdown(by_channel, "channel"),
        "versions": _breakdown(by_version, "version"),
    }


def _ranked(counter: Counter, name: str) -> list[dict[str, Any]]:
    return [{name: key, "n": n} for key, n in counter.most_common()]


def _breakdown(rows, name: str) -> list[dict[str, Any]]:
    table: dict[Any, Counter] = {}
    for key, source, event, n in rows:
        field = "apiCalls" if source == "api" else ("activeUsers" if event == "active_day" else "installs")
        table.setdefault(key, Counter())[field] += n
    return sorted(
        ({name: key, "apiCalls": c["apiCalls"], "activeUsers": c["activeUsers"], "installs": c["installs"]} for key, c in table.items()),
        key=lambda row: (-row["apiCalls"], -row["activeUsers"]),
    )
