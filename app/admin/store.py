"""Draft → publish workflow on top of the files the API serves.

    data/catalog.json, data/release.json   live: what the API serves (and the app sees)
    data/admin/draft.json                  the dashboard's working copy
    data/admin/history/*.json              every published version, newest kept

Edits only touch the draft. Publishing validates it, writes the live files atomically (the
API reloads them on the next request) and records the version in the history, from which
any earlier version can be restored into the draft.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .schema import Draft, normalize

HISTORY_LIMIT = 200


class Conflict(Exception):
    """The draft changed since the client loaded it (another admin saved first)."""


@dataclass
class DraftState:
    draft: dict[str, Any]
    revision: int
    updated_by: str | None
    updated_at: float | None
    live: dict[str, Any]
    live_meta: dict[str, Any]

    @property
    def dirty(self) -> bool:
        return self.draft != self.live


def write_json_atomically(path: Path, document: Any, pretty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(document, f, ensure_ascii=False, indent=2 if pretty else None)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


class AdminStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.admin_dir = self.data_dir / "admin"
        self.history_dir = self.admin_dir / "history"
        self._lock = threading.Lock()
        self.history_dir.mkdir(parents=True, exist_ok=True)
        if not any(self.history_dir.glob("*.json")):
            # The version that was live before the dashboard existed is the first entry.
            live = self._read_live()
            self._record(live, published_by="initial", note="Version before the dashboard")

    # --- reading ----------------------------------------------------------------------

    def state(self) -> DraftState:
        with self._lock:
            return self._state()

    def _state(self) -> DraftState:
        live = self._read_live()
        stored = self._read(self.admin_dir / "draft.json")
        if stored is None:
            return DraftState(live, 0, None, None, live, self._live_meta())
        return DraftState(
            draft={"catalog": stored["catalog"], "release": stored["release"]},
            revision=stored["revision"],
            updated_by=stored.get("updatedBy"),
            updated_at=stored.get("updatedAt"),
            live=live,
            live_meta=self._live_meta(),
        )

    def _read_live(self) -> dict[str, Any]:
        live = {
            "catalog": self._read(self.data_dir / "catalog.json"),
            "release": self._read(self.data_dir / "release.json"),
        }
        # Compared with the draft in the same normalized form, so filled-in defaults don't
        # show up as changes.
        try:
            return normalize(Draft.model_validate(live))
        except ValidationError:
            return live

    def _live_meta(self) -> dict[str, Any]:
        entries = self.history()
        return entries[0] if entries else {}

    @staticmethod
    def _read(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    # --- editing ----------------------------------------------------------------------

    def save_draft(self, draft: Draft, base_revision: int, user: str) -> DraftState:
        with self._lock:
            current = self._state()
            if base_revision != current.revision:
                raise Conflict(f"the draft is at revision {current.revision}, not {base_revision}")
            document = normalize(draft)
            write_json_atomically(
                self.admin_dir / "draft.json",
                {**document, "revision": current.revision + 1, "updatedBy": user, "updatedAt": time.time()},
            )
            return self._state()

    def discard(self) -> DraftState:
        with self._lock:
            (self.admin_dir / "draft.json").unlink(missing_ok=True)
            return self._state()

    def publish(self, base_revision: int, user: str, note: str) -> DraftState:
        with self._lock:
            current = self._state()
            if base_revision != current.revision:
                raise Conflict(f"the draft is at revision {current.revision}, not {base_revision}")
            # Re-validate: rules may have changed since the draft was saved.
            document = normalize(Draft.model_validate(current.draft))
            stamp = time.strftime("%Y-%m-%d.%H%M%S", time.gmtime())
            document["catalog"]["configVersion"] = stamp
            # Release first: a catalog never goes live with rules older than it expects.
            write_json_atomically(self.data_dir / "release.json", document["release"])
            write_json_atomically(self.data_dir / "catalog.json", document["catalog"])
            self._record(document, published_by=user, note=note)
            (self.admin_dir / "draft.json").unlink(missing_ok=True)
            return self._state()

    def restore(self, entry_id: str, user: str) -> DraftState:
        with self._lock:
            entry = self._read(self._entry_path(entry_id))
            if entry is None:
                raise KeyError(entry_id)
            current = self._state()
            write_json_atomically(
                self.admin_dir / "draft.json",
                {
                    "catalog": entry["catalog"],
                    "release": entry["release"],
                    "revision": current.revision + 1,
                    "updatedBy": user,
                    "updatedAt": time.time(),
                },
            )
            return self._state()

    # --- history ----------------------------------------------------------------------

    def history(self) -> list[dict[str, Any]]:
        entries = []
        for path in sorted(self.history_dir.glob("*.json"), reverse=True):
            entry = self._read(path)
            if entry:
                entries.append({key: entry[key] for key in ("id", "publishedAt", "publishedBy", "note", "summary")})
        return entries

    def entry(self, entry_id: str) -> dict[str, Any] | None:
        return self._read(self._entry_path(entry_id))

    def _entry_path(self, entry_id: str) -> Path:
        if not entry_id.replace("-", "").replace(".", "").isalnum():
            raise KeyError(entry_id)
        return self.history_dir / f"{entry_id}.json"

    def _record(self, document: dict[str, Any], published_by: str, note: str) -> None:
        now = time.time()
        entry_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now)) + f"-{int(now * 1000) % 1000:03d}"
        catalog = document.get("catalog") or {}
        services = catalog.get("services", [])
        write_json_atomically(
            self.history_dir / f"{entry_id}.json",
            {
                "id": entry_id,
                "publishedAt": now,
                "publishedBy": published_by,
                "note": note[:200],
                "summary": {
                    "services": len(services),
                    "enabled": sum(1 for s in services if s.get("enabled", True)),
                    "categories": len(catalog.get("categories", [])),
                },
                **document,
            },
        )
        for old in sorted(self.history_dir.glob("*.json"))[:-HISTORY_LIMIT]:
            old.unlink(missing_ok=True)
