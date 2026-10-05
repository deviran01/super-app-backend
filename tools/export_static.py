#!/usr/bin/env python3
"""Packages the config for a static host: one folder to upload anywhere (object storage,
CDN, GitHub Pages, any web server). The app reads <folder URL>/config.json; image paths in
the document are relative, so the folder works at any URL, root or sub-path.

    python3 tools/export_static.py                    # → dist/daricheh-config/
    python3 tools/export_static.py --out /tmp/site

Refuses to export a document a release build would reject or degrade (plain-http URLs,
QA-only entries). A logo or icon whose file is missing is dropped from the exported copy
with a warning: the app shows a monogram instead of requesting a missing file every launch.
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(HERE, "..", "public")
DEFAULT_OUT = os.path.join(HERE, "..", "dist", "daricheh-config")


def problems(config):
    """Everything that would make a release build reject or degrade the document."""
    found = []
    if config.get("schemaVersion") != 1:
        found.append("schemaVersion must be 1")
    app = config.get("app") or {}
    if not isinstance(app.get("minimumSupportedVersion"), int):
        found.append("app.minimumSupportedVersion is required")
    for channel, rule in (app.get("channels") or {}).items():
        latest = rule.get("latestVersion", app.get("latestVersion"))
        minimum = rule.get("minimumSupportedVersion", app.get("minimumSupportedVersion"))
        if isinstance(latest, int) and isinstance(minimum, int) and latest < minimum:
            found.append(f"app.channels.{channel}: latestVersion < minimumSupportedVersion")

    def check_url(value, where):
        if isinstance(value, str) and value.startswith("http://"):
            found.append(f"{where}: release builds only accept https ({value})")

    def check_image(value, where):
        if value:
            check_url(value, where)

    check_url(app.get("updateUrl"), "app.updateUrl")
    for category in config.get("categories", []):
        check_image(category.get("icon"), f"category {category.get('id')}")
    for service in config.get("services", []):
        where = f"service {service.get('id')}"
        check_url(service.get("url"), where)
        check_image(service.get("logo"), where)
        if service.get("categoryId") == "lab":
            found.append(f"{where}: QA lab entries don't belong in production")
    if not any(s.get("enabled", True) for s in config.get("services", [])):
        found.append("no enabled service")
    return found


def drop_missing_images(config):
    """Removes image fields whose local file doesn't exist; returns what was dropped."""
    dropped = []
    for entries, field in ((config.get("categories", []), "icon"), (config.get("services", []), "logo")):
        for entry in entries:
            value = entry.get(field)
            if value and "://" not in value and not os.path.exists(os.path.join(PUBLIC, value.lstrip("/"))):
                dropped.append(f"{entry.get('id')}: {value}")
                del entry[field]
    return dropped


def images(config):
    paths = [c.get("icon") for c in config.get("categories", [])] + [s.get("logo") for s in config.get("services", [])]
    return sorted({p.lstrip("/") for p in paths if p and "://" not in p})


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    with open(os.path.join(PUBLIC, "config.json"), encoding="utf-8") as f:
        config = json.load(f)
    issues = problems(config)
    if issues:
        sys.exit("Not exported:\n  " + "\n  ".join(issues))
    for missing in drop_missing_images(config):
        print(f"warning: no image file for {missing}; the app will show a monogram")

    shutil.rmtree(args.out, ignore_errors=True)
    os.makedirs(args.out)
    # Minified: the app downloads this on every launch (revalidated with ETag when possible).
    with open(os.path.join(args.out, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, separators=(",", ":"))
    for path in images(config):
        target = os.path.join(args.out, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(os.path.join(PUBLIC, path), target)
    size = os.path.getsize(os.path.join(args.out, "config.json"))
    print(f"Exported {os.path.normpath(args.out)}: config.json ({size // 1024} KB), {len(images(config))} images.")
    print("Upload the folder's contents, then set daricheh.configUrls.release to <its URL>/config.json.")


if __name__ == "__main__":
    main()
