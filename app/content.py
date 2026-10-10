"""The API's content: data/catalog.json and data/release.json.

Files are re-read when they change on disk, so a deploy that replaces them takes effect on
the next request without a restart. A file that fails the checks below never replaces good
content that is already being served.

Packs (catalog `packs`, and `pack` on categories, services and compare groups) are sets of
services switched on and off together from the dashboard. The app gets only the switched-on
ones and never sees the bookkeeping: see served_catalog().

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
from functools import cached_property
from pathlib import Path
from typing import Any

log = logging.getLogger("superapp.content")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SUPERAPP_DATA_DIR", ROOT / "data"))
SCENARIO_DIR = ROOT / "scenarios"

CHANNEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ContentError(ValueError):
    """The data files are unusable."""


KNOWN_CHANNELS = ("bazaar", "myket", "direct")


@dataclass(frozen=True)
class Content:
    catalog: dict[str, Any]  # what the app gets
    release: dict[str, Any]
    # Scenario effects, for QA only.
    forced_status: int | None = None
    raw_catalog: str | None = None
    scenarios: tuple[str, ...] = field(default_factory=tuple)
    # data/catalog.json as published, switched-off packs included (default: [catalog]).
    catalog_file: dict[str, Any] | None = field(default=None, compare=False, repr=False)
    # Answers built from this content (body and ETag), keyed by request variant. A content
    # change creates a new Content, so nothing here can go stale.
    responses: dict[Any, Any] = field(default_factory=dict, compare=False, repr=False)

    # Derived once per content version (a frozen dataclass still allows cached_property).
    # Switched-off packs count too: usage reports about a pack that was just switched off
    # still arrive.
    @cached_property
    def service_ids(self) -> frozenset[str]:
        return self._ids("services")

    @cached_property
    def category_ids(self) -> frozenset[str]:
        return self._ids("categories")

    def _ids(self, key: str) -> frozenset[str]:
        items = [*self.catalog.get(key, []), *(self.catalog_file or {}).get(key, [])]
        return frozenset(item["id"] for item in items if isinstance(item, dict) and "id" in item)

    @cached_property
    def channels(self) -> frozenset[str]:
        return frozenset(KNOWN_CHANNELS) | frozenset((self.release.get("channels") or {}).keys())

    @cached_property
    def highest_version(self) -> int:
        rules = [self.release.get("default") or {}, *(self.release.get("channels") or {}).values()]
        versions = [v for rule in rules for k in ("latestVersion", "minimumSupportedVersion") if isinstance(v := rule.get(k), int)]
        return max(versions, default=1)


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


def served_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """The catalog as the app gets it: without the categories, services and compare groups of
    switched-off packs, and without the pack bookkeeping. Compare groups lose members that
    aren't served and are dropped below two (the app does the same)."""
    if "packs" not in catalog and not any(
        isinstance(item, dict) and "pack" in item
        for key in ("categories", "services", "compareGroups")
        for item in (catalog.get(key) if isinstance(catalog.get(key), list) else [])
    ):
        return catalog
    packs = catalog.get("packs")
    active = {p.get("id") for p in packs if isinstance(p, dict) and p.get("active") is True} if isinstance(packs, list) else set()

    def shown(items: Any) -> list[Any]:
        if not isinstance(items, list):
            return items
        return [
            {k: v for k, v in item.items() if k != "pack"} if isinstance(item, dict) else item
            for item in items
            if not isinstance(item, dict) or item.get("pack") is None or item.get("pack") in active
        ]

    served = {k: v for k, v in catalog.items() if k != "packs"}
    for key in ("categories", "services", "compareGroups"):
        if key in catalog:
            served[key] = shown(catalog[key])
    if isinstance(served.get("compareGroups"), list):
        ids = {s.get("id") for s in served.get("services") or [] if isinstance(s, dict)}
        groups = []
        for group in served["compareGroups"]:
            members = group.get("serviceIds") if isinstance(group, dict) else None
            if isinstance(members, list):
                group = {**group, "serviceIds": [sid for sid in members if sid in ids]}
                if len(group["serviceIds"]) < 2:
                    continue
            groups.append(group)
        served["compareGroups"] = groups
    return served


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
        try:
            stamp = self._file_stamp()
        except OSError as error:
            # A file missing for a moment (a manual edit, a restore): keep serving what worked.
            if self._content is None:
                raise ContentError(str(error)) from error
            return self._content
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
            catalog_file = check_catalog(json.loads((self._data_dir / "catalog.json").read_text(encoding="utf-8")))
            catalog = check_catalog(served_catalog(catalog_file))
            release = check_release(json.loads((self._data_dir / "release.json").read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            if self._content is None:
                raise ContentError(str(error)) from error
            # Keep serving what worked; a half-uploaded or broken file must not reach clients.
            log.error("Content reload failed; still serving the previous content: %s", error)
            self._stamp = stamp
            return
        self._content = self._apply_scenarios(catalog, release, catalog_file)
        self._stamp = stamp
        log.info("Content loaded: %d of %d services served", len(catalog.get("services", [])), len(catalog_file.get("services", [])))

    def _apply_scenarios(self, catalog: dict[str, Any], release: dict[str, Any], catalog_file: dict[str, Any]) -> Content:
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
        return Content(catalog, release, status, raw, self._scenario_names, catalog_file)

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
