"""The API's content: data/catalog.json and data/release.json.

Files are re-read when they change on disk, so a deploy that replaces them takes effect on
the next request without a restart. A file that fails the checks below never replaces good
content that is already being served.

QA scenarios (scenarios/*.json, enabled with SUPERAPP_SCENARIOS=lab,force-update) overlay the
content for testing; production runs without any.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("superapp.content")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SUPERAPP_DATA_DIR", ROOT / "data"))
SCENARIO_DIR = ROOT / "scenarios"

CHANNEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ContentError(ValueError):
    """The data files are unusable."""


@dataclass(frozen=True)
class Content:
    catalog: dict[str, Any]
    release: dict[str, Any]
    # Scenario effects, for QA only.
    forced_status: int | None = None
    raw_catalog: str | None = None
    scenarios: tuple[str, ...] = field(default_factory=tuple)


def deep_merge(base: Any, patch: Any) -> Any:
    """RFC 7386-style merge for objects; arrays and scalars are replaced, null deletes."""
    if not isinstance(patch, dict) or not isinstance(base, dict):
        return copy.deepcopy(patch)
    merged = dict(base)
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = deep_merge(base.get(key), value)
    return merged


def check_release(release: Any) -> dict[str, Any]:
    if not isinstance(release, dict):
        raise ContentError("release.json must be an object")
    default = release.get("default")
    if not isinstance(default, dict) or not isinstance(default.get("minimumSupportedVersion"), int):
        raise ContentError("release.json: default.minimumSupportedVersion (int) is required")
    channels = release.get("channels", {})
    if not isinstance(channels, dict):
        raise ContentError("release.json: channels must be an object")
    for name, rule in {"default": default, **channels}.items():
        if name != "default" and not CHANNEL_PATTERN.match(name):
            raise ContentError(f"release.json: invalid channel name {name!r}")
        if not isinstance(rule, dict):
            raise ContentError(f"release.json: {name} must be an object")
        for key in ("minimumSupportedVersion", "latestVersion"):
            if key in rule and (not isinstance(rule[key], int) or rule[key] < 0):
                raise ContentError(f"release.json: {name}.{key} must be a non-negative int")
        url = rule.get("updateUrl")
        if url is not None and not (isinstance(url, str) and url.startswith("https://")):
            raise ContentError(f"release.json: {name}.updateUrl must be an https URL")
    return release


def check_catalog(catalog: Any) -> dict[str, Any]:
    if not isinstance(catalog, dict) or catalog.get("schemaVersion") != 1:
        raise ContentError("catalog.json: schemaVersion must be 1")
    services = catalog.get("services")
    if not isinstance(services, list) or not any(isinstance(s, dict) and s.get("enabled", True) for s in services):
        raise ContentError("catalog.json: at least one enabled service is required")
    return catalog


class ContentStore:
    """Serves the latest valid content, reloading the files when they change."""

    def __init__(self, data_dir: Path = DATA_DIR, scenarios: list[str] | None = None):
        self._data_dir = Path(data_dir)
        self._scenarios = [self._load_scenario(name) for name in scenarios or []]
        self._scenario_names = tuple(scenarios or [])
        self._lock = threading.Lock()
        self._stamp: tuple[tuple[int, int, int], ...] | None = None
        self._content: Content | None = None
        self.get()  # fail fast on startup when the files are unusable

    def get(self) -> Content:
        stamp = self._file_stamp()
        if stamp != self._stamp:
            with self._lock:
                if stamp != self._stamp:
                    self._reload(stamp)
        assert self._content is not None
        return self._content

    def _file_stamp(self) -> tuple[tuple[int, int, int], ...]:
        # Inode too: deploys replace files by rename, and some filesystems keep coarse mtimes.
        stats = [(self._data_dir / name).stat() for name in ("catalog.json", "release.json")]
        return tuple((st.st_ino, st.st_size, st.st_mtime_ns) for st in stats)

    def _reload(self, stamp: tuple[tuple[int, int, int], ...]) -> None:
        try:
            catalog = check_catalog(json.loads((self._data_dir / "catalog.json").read_text(encoding="utf-8")))
            release = check_release(json.loads((self._data_dir / "release.json").read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            if self._content is None:
                raise ContentError(str(error)) from error
            # Keep serving what worked; a half-uploaded or broken file must not reach clients.
            log.error("Content reload failed; still serving the previous content: %s", error)
            self._stamp = stamp
            return
        self._content = self._apply_scenarios(catalog, release)
        self._stamp = stamp
        log.info("Content loaded: %d services", len(catalog.get("services", [])))

    def _apply_scenarios(self, catalog: dict[str, Any], release: dict[str, Any]) -> Content:
        status, raw = None, None
        for scenario in self._scenarios:
            special = {"appendCategories", "appendServices", "patchServices", "raw", "status", "release"}
            catalog = deep_merge(catalog, {k: v for k, v in scenario.items() if k not in special})
            catalog["categories"] = catalog.get("categories", []) + scenario.get("appendCategories", [])
            catalog["services"] = catalog.get("services", []) + scenario.get("appendServices", [])
            patches = scenario.get("patchServices", {})
            catalog["services"] = [
                deep_merge(s, patches[s.get("id")]) if s.get("id") in patches else s for s in catalog["services"]
            ]
            release = deep_merge(release, scenario.get("release", {}))
            status = scenario.get("status", status)
            raw = scenario.get("raw", raw)
        return Content(catalog, release, status, raw, self._scenario_names)

    @staticmethod
    def _load_scenario(name: str) -> dict[str, Any]:
        path = SCENARIO_DIR / f"{name}.json"
        if not CHANNEL_PATTERN.match(name) or not path.exists():
            available = ", ".join(sorted(p.stem for p in SCENARIO_DIR.glob("*.json")))
            raise ContentError(f"Unknown scenario {name!r}. Available: {available}")
        return json.loads(path.read_text(encoding="utf-8"))


def resolve_release(release: dict[str, Any], channel: str) -> dict[str, Any]:
    """The update policy for one store channel: its overrides on top of the defaults."""
    rule = {**release.get("default", {}), **release.get("channels", {}).get(channel, {})}
    minimum = rule.get("minimumSupportedVersion", 0)
    resolved: dict[str, Any] = {
        "minimumSupportedVersion": minimum,
        "latestVersion": max(rule.get("latestVersion", minimum), minimum),
        "forceUpdate": bool(rule.get("forceUpdate", False)),
    }
    for key in ("updateUrl", "message", "optionalMessage"):
        if rule.get(key) is not None:
            resolved[key] = rule[key]
    return resolved


def update_status(app_version: int, policy: dict[str, Any]) -> str:
    """Same rule as the app's VersionPolicyEvaluator: REQUIRED (hard), OPTIONAL (soft) or NONE."""
    minimum = policy["minimumSupportedVersion"]
    if policy["forceUpdate"]:
        minimum = max(minimum, policy["latestVersion"])
    if app_version < minimum:
        return "REQUIRED"
    if app_version < policy["latestVersion"]:
        return "OPTIONAL"
    return "NONE"
