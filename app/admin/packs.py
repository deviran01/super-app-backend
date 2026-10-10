"""Packs that ship with the code (app/packs/<id>.json, built by tools/build_iran_access_pack.py).

The server owns data/, so a pack reaches the live catalog through the dashboard: adding it
copies its categories, services and compare groups into the draft, switched off, and the
admin publishes as usual. From then on they are ordinary catalog entries, edited in the
dashboard. Adding again (after a deploy brings new entries) copies only what the draft
doesn't have yet, so edits made since are kept.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PACK_DIR = Path(__file__).resolve().parent.parent / "packs"
PARTS = ("categories", "services", "compareGroups")


@lru_cache(maxsize=1)
def bundled() -> dict[str, dict[str, Any]]:
    packs = {}
    for path in sorted(PACK_DIR.glob("*.json")):
        pack = json.loads(path.read_text(encoding="utf-8"))
        packs[pack["id"]] = pack
    return packs


def summary(pack: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """What the pack holds, and how much of it adding would bring into the draft."""
    merged = merge({"catalog": catalog}, pack)["catalog"]
    out: dict[str, Any] = {key: pack.get(key) for key in ("id", "title", "description")}
    for part in PARTS:
        out[part] = len(pack.get(part, []))
        out[f"new_{part}"] = len(merged[part]) - len(catalog.get(part, []))
    out["added"] = any(p.get("id") == pack["id"] for p in catalog.get("packs", []))
    return out


def merge(document: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    """The draft with [pack] added: switched off when it's new, and only the entries whose id
    the draft doesn't use yet. New categories go after the last one, new services last in
    their category; compare groups keep the members the draft has (at least two)."""
    catalog = copy.deepcopy(document["catalog"])
    packs = catalog.setdefault("packs", [])
    if not any(p.get("id") == pack["id"] for p in packs):
        packs.append({key: pack[key] for key in ("id", "title", "description") if key in pack} | {"active": False})
    for part in PARTS:
        items = catalog.setdefault(part, [])
        have = {item.get("id") for item in items}
        top = max((item.get("order", 0) for item in items), default=0)
        new = [item for item in pack.get(part, []) if item["id"] not in have]
        for index, item in enumerate(new, 1):
            item = {**copy.deepcopy(item), "pack": pack["id"]}
            if part == "categories":
                item["order"] = top + index
            elif part == "services":
                item["order"] = top + index * 10
            else:
                services = {s.get("id") for s in catalog["services"]}
                item["serviceIds"] = [sid for sid in item["serviceIds"] if sid in services]
                if len(item["serviceIds"]) < 2:
                    continue
            items.append(item)
    return {**document, "catalog": catalog}
