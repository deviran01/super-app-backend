#!/usr/bin/env python3
"""Daricheh development config server (standard library only).

Serves public/ as static files — exactly what a production static host would serve — and
GET /config.json with optional QA scenarios applied. Supports ETag / If-None-Match like a
production CDN.

    python3 server.py                       # sample config on :8080
    python3 server.py --scenario lab        # + local QA test pages service
    python3 server.py --scenario force-update --scenario maintenance

Scenarios live in scenarios/*.json (see README.md). The app reaches the
server through `adb reverse tcp:8080 tcp:8080` (debug/QA builds read
http://127.0.0.1:8080/config.json).
"""
import argparse
import copy
import hashlib
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(HERE, "public")
SCENARIOS = os.path.join(HERE, "scenarios")
CONFIG_PATH = "/config.json"


def deep_merge(base, patch):
    """RFC 7386-style merge for objects; arrays and scalars are replaced."""
    if not isinstance(patch, dict) or not isinstance(base, dict):
        return copy.deepcopy(patch)
    merged = dict(base)
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = deep_merge(base.get(key), value)
    return merged


def apply_scenario(config, scenario):
    """A scenario may merge-patch the document and add/patch catalog entries by id."""
    special = {"appendCategories", "appendServices", "patchServices", "raw", "status"}
    config = deep_merge(config, {k: v for k, v in scenario.items() if k not in special})
    config["categories"] = config.get("categories", []) + scenario.get("appendCategories", [])
    config["services"] = config.get("services", []) + scenario.get("appendServices", [])
    patches = scenario.get("patchServices", {})
    config["services"] = [deep_merge(s, patches[s.get("id")]) if s.get("id") in patches else s for s in config["services"]]
    return config


def load_scenarios(names):
    loaded = []
    for name in names:
        path = os.path.join(SCENARIOS, f"{name}.json")
        if not os.path.exists(path):
            sys.exit(f"Unknown scenario '{name}'. Available: {', '.join(sorted(f[:-5] for f in os.listdir(SCENARIOS)))}")
        with open(path, encoding="utf-8") as f:
            loaded.append(json.load(f))
    return loaded


class Handler(SimpleHTTPRequestHandler):
    scenarios = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=PUBLIC, **kwargs)

    def do_GET(self):
        if urlparse(self.path).path == CONFIG_PATH:
            return self.serve_config()
        return super().do_GET()

    def serve_config(self):
        for scenario in self.scenarios:
            if "status" in scenario:  # e.g. simulate the backend being down
                self.send_response(scenario["status"])
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        with open(os.path.join(PUBLIC, "config.json"), encoding="utf-8") as f:
            config = json.load(f)
        raw = None
        for scenario in self.scenarios:
            raw = scenario.get("raw", raw)
            config = apply_scenario(config, scenario)
        body = (raw if raw is not None else json.dumps(config, ensure_ascii=False)).encode("utf-8")
        etag = '"%s"' % hashlib.sha256(body).hexdigest()[:32]
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # Logos and icons are immutable per path in this sample; let clients cache them.
        if urlparse(self.path).path != CONFIG_PATH:
            self.send_header("Cache-Control", "public, max-age=86400")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("[config-server] " + fmt % args + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--scenario", action="append", default=[], help="apply scenarios/<name>.json (repeatable)")
    args = parser.parse_args()
    Handler.scenarios = load_scenarios(args.scenario)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving {PUBLIC} on http://{args.host}:{args.port} (config: {CONFIG_PATH}, scenarios: {args.scenario or 'none'})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
