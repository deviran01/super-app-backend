"""Usage statistics for the admin dashboard: daily counters, nothing else.

Two sources feed the same table:

- ``api``: the server counts its own API calls by endpoint, status, store channel and app
  version (what every request already carries; no IP or identifier is stored).
- ``app``: the app uploads anonymous daily totals (``POST /api/v1/events``) — e.g. "service
  snapp opened from home: 4" — with no device or user identifier, URL, search text or time
  finer than a day. Daily active users and installs arrive as ``active_day`` / ``first_open``
  counters that each install sends at most once per day / once ever.

Reports aren't authenticated (the app has no identity to authenticate), so the numbers are
best-effort: each report is capped, and only known events, catalog ids and channels are kept,
which bounds what a forged report can add or how many rows it can create.

Counts are buffered in memory and written to SQLite (``data/stats/stats.db``) every few
seconds and before every read.
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
from typing import Any, Iterable, Iterator

log = logging.getLogger("stats")

# Iran Standard Time (no daylight saving since 2022): "today" for API calls and report checks.
IRAN = timezone(timedelta(hours=3, minutes=30))

FLUSH_SECONDS = 10
RETENTION_DAYS = 400
MAX_REPORT_DAYS = 8
MAX_COUNTS_PER_DAY = 400
MAX_RANGE_DAYS = 366

KNOWN_CHANNELS = ("bazaar", "myket", "direct")
OTHER = "other"
OPEN_SOURCES = {"home", "favorites", "recent", "category", "search", "tabs", "quick_switch", "add_service"}
PAGE_ERRORS = {
    "offline", "host_not_found", "timeout", "connection_failed", "insecure_connection",
    "unsupported_url", "crashed", "web_view_unavailable", "generic",
}
CLEAR_SCOPES = {"cache", "service", "all"}

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
    def __init__(self, path: Path, clock=time.monotonic) -> None:
        self._path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: Counter[Key] = Counter()
        self._last_flush = clock()
        self._ready = False

    # --- writing ------------------------------------------------------------------------

    def count_api_call(self, endpoint: str, status: int, channel: str, version: int) -> None:
        self._add([((today().isoformat(), "api", endpoint, status_class(status), "", channel, version), 1)])

    def add_report(self, report: dict[str, Any], *, services: set[str], categories: set[str], channels: set[str], max_version: int) -> int:
        """Adds an app report (already shape-checked by the API model); returns the counters kept."""
        channel = report["channel"] if report["channel"] in channels else OTHER
        version = report["appVersion"] if 1 <= report["appVersion"] <= max_version else 0
        newest = today() + timedelta(days=1)  # devices ahead of Iran's date
        oldest = newest - timedelta(days=MAX_REPORT_DAYS + 1)
        ids = {SERVICE: services, CATEGORY: categories}
        kept: list[tuple[Key, int]] = []
        for entry in report["days"][:MAX_REPORT_DAYS]:
            day = _parse_day(entry["day"])
            if day is None or not oldest <= day <= newest:
                continue
            for count in entry["counts"][:MAX_COUNTS_PER_DAY]:
                rule = EVENTS.get(count["event"])
                dims = count["dims"]
                if rule is None or len(dims) != len(rule[0]):
                    continue
                if not all(dim in (ids[check] if isinstance(check, str) else check) for dim, check in zip(dims, rule[0])):
                    continue
                n = min(count["n"], rule[1])
                if n <= 0:
                    continue
                padded = (list(dims) + ["", ""])[:2]
                kept.append(((day.isoformat(), "app", count["event"], padded[0], padded[1], channel, version), n))
        self._add(kept)
        return len(kept)

    def _add(self, items: Iterable[tuple[Key, int]]) -> None:
        with self._lock:
            for key, n in items:
                self._pending[key] += n
            if self._clock() - self._last_flush >= FLUSH_SECONDS:
                self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        self._last_flush = self._clock()
        if not self._pending:
            return
        rows = [(*key, n) for key, n in self._pending.items()]
        try:
            with self._db() as db:
                db.executemany(
                    "INSERT INTO counts (day, source, event, dim1, dim2, channel, version, n) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (day, source, event, dim1, dim2, channel, version) DO UPDATE SET n = n + excluded.n",
                    rows,
                )
            self._pending.clear()
        except sqlite3.Error:
            # Kept in memory and retried on the next flush; statistics never fail a request.
            log.exception("Couldn't save %d counters", len(rows))

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        """A connection that commits on success and is always closed."""
        if not self._ready:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self._path, timeout=5)
        try:
            if not self._ready:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript(SCHEMA)
                db.execute("DELETE FROM counts WHERE day < ?", ((today() - timedelta(days=RETENTION_DAYS)).isoformat(),))
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
        with self._lock:
            self._flush_locked()
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
