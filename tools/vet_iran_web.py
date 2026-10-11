#!/usr/bin/env python3
"""Gathers the evidence tools/build_iran_web_pack.py decides on, for every candidate site
(the catalog's, the Iran-access pack's and tools/iran_web_candidates.py's):

  hosting   the start URL's host resolved by an Iranian resolver (TCI), and the network
            each address is announced from (Team Cymru): an Iranian network means it stays
            reachable on the national network when international internet is cut.
  myket     Myket's search results for the site's Persian and English names: package and
            title of each, to find the site's own app.
  bazaar    (--bazaar) Cafe Bazaar's search results for the Persian name, and whether each
            package is on Myket too: Myket's search misses some apps (Bale, Rubika), and
            an app usually has the same package in both stores.

Writes JSON (default: vetting.json, bazaar.json with --bazaar) to review; nothing in the
repository changes.

    python3 tools/vet_iran_web.py [--bazaar] [--only id,id] [--out path]
"""
import argparse
import concurrent.futures
import html
import ipaddress
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_iran_access_pack as access  # noqa: E402
from iran_web_candidates import EXTRA_SERVICES  # noqa: E402

RESOLVER = "217.218.155.155"  # TCI's public resolver, in Iran
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
MYKET_SEARCH = "https://myket.ir/Search/Apps?keyword={keyword}&page=0"
MYKET_APP = "https://myket.ir/app/{package}"
BAZAAR_SEARCH = "https://api.cafebazaar.ir/rest-v1/process/SearchV2Request"


def candidates():
    """id, host, fa name, en name, where it comes from."""
    catalog = json.load(open(os.path.join(HERE, "..", "data", "catalog.json"), encoding="utf-8"))
    rows = [(s["id"], s["url"], s["name"].get("fa", ""), s["name"].get("en", ""), "catalog")
            for s in catalog["services"] if "pack" not in s]
    rows += [(e[0], e[2], e[3], e[4], "iran-access") for e in access.SERVICES]
    rows += [(e[0], e[2], e[3], e[4], "extra") for e in EXTRA_SERVICES]
    return rows


def dig(name, kind="A", server=RESOLVER):
    command = ["dig", "+short", "+time=4", "+tries=2", *([f"@{server}"] if server else []), name, kind]
    out = subprocess.run(command, capture_output=True, text=True, timeout=30).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


COUNTRY = {}
AS_COUNTRY = {}


def country(ip):
    """The network the address is announced from (Team Cymru's DNS interface), and the
    country that network is registered in. The prefix's own country can mislead: Iranian
    networks announce some prefixes registered in the UAE."""
    key = ".".join(ip.split(".")[:3])
    if key not in COUNTRY:
        reverse = ".".join(reversed(ip.split(".")))
        answer = dig(f"{reverse}.origin.asn.cymru.com", "TXT", server=None)
        fields = answer[0].strip('"').split("|") if answer else []
        asn = fields[0].strip().split()[0] if len(fields) > 2 else "?"
        if asn not in AS_COUNTRY:
            answer = dig(f"AS{asn}.asn.cymru.com", "TXT", server=None) if asn != "?" else []
            parts = answer[0].strip('"').split("|") if answer else []
            AS_COUNTRY[asn] = (parts[1].strip(), parts[4].strip()) if len(parts) > 4 else ("?", "?")
        COUNTRY[key] = {"asn": asn, "country": AS_COUNTRY[asn][0], "network": AS_COUNTRY[asn][1]}
    return COUNTRY[key]


def hosting(url):
    host = urllib.parse.urlsplit(url).hostname
    answers = dig(host)
    addresses = [a for a in answers if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", a)]
    # A private address only works inside the organization's own network.
    private = [ip for ip in addresses if ipaddress.ip_address(ip).is_private]
    places = [{"ip": ip, **country(ip)} for ip in addresses if ip not in private]
    return {"host": host, "cname": [a for a in answers if a not in addresses], "ips": places, "private": private,
            "iran": bool(places) and all(p["country"] == "IR" for p in places)}


def get(url, timeout=25):
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "fa"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "ignore")


def myket_search(keyword):
    for attempt in range(4):
        try:
            page = get(MYKET_SEARCH.format(keyword=urllib.parse.quote(keyword)))
            break
        except Exception as error:  # rate limits and timeouts: back off
            time.sleep(5 * (attempt + 1))
    else:
        return None
    results = []
    for match in re.finditer(r'data-package-name="([^"]+)" title="([^"]*)"', page):
        results.append({"package": match.group(1), "title": html.unescape(match.group(2))})
    return results[:8]


def bazaar_search(query):
    body = {"properties": {"language": 2, "clientID": "x", "deviceID": "x", "clientVersion": "web"},
            "singleRequest": {"searchV2Request": {"query": query, "scope": "", "offset": 0, "limit": 6}}}
    for attempt in range(4):
        try:
            request = urllib.request.Request(BAZAAR_SEARCH, json.dumps(body).encode(), {"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                reply = json.load(response)
            break
        except Exception:
            time.sleep(5 * (attempt + 1))
    else:
        return None
    rows = reply["singleReply"]["searchV2Reply"]["page"]["pageBodyInfo"]["pageBody"]["rows"]
    hits = []
    for row in rows:
        for key in ("simpleAppItem", "appItem"):
            info = (row.get(key) or {}).get("info")
            if info:
                hits.append({"package": info["packageName"], "title": info.get("name", ""),
                             "installs": info.get("installCountVerbose", "")})
    return hits[:6]


def on_myket(package):
    request = urllib.request.Request(MYKET_APP.format(package=package), headers={"User-Agent": UA}, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status == 200
    except urllib.error.HTTPError as error:
        return False if error.code == 404 else None
    except Exception:
        return None


def bazaar(rows, out):
    done = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}

    def one(row):
        sid, url, fa, en, source = row
        hits = bazaar_search(fa or en)
        for hit in (hits or [])[:3]:
            hit["onMyket"] = on_myket(hit["package"])
        time.sleep(0.5)
        return {"id": sid, "fa": fa, "en": en, "bazaar": hits}

    todo = [r for r in rows if r[0] not in done or done[r[0]].get("bazaar") is None]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        for index, entry in enumerate(pool.map(one, todo), 1):
            done[entry["id"]] = entry
            if index % 20 == 0:
                json.dump(done, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                print(f"bazaar {index}/{len(todo)}", flush=True)
    json.dump(done, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {out}: {len(done)} sites")


DEVELOPERS = {}


def developer(package):
    """Who published a Myket app: tells a site's own app from someone else's wrapper (for
    reviewing matches by hand: python3 -c 'import vet_iran_web as v; print(v.developer("ir.divar"))')."""
    if package not in DEVELOPERS:
        try:
            page = html.unescape(get(MYKET_APP.format(package=package)))
            text = re.sub(r"<[^>]+>", "\n", page)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            DEVELOPERS[package] = lines[lines.index("سازنده") + 1] if "سازنده" in lines else "?"
        except Exception:
            DEVELOPERS[package] = "?"
        time.sleep(0.6)
    return DEVELOPERS[package]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--bazaar", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()
    only = set(filter(None, args.only.split(",")))
    rows = [r for r in candidates() if not only or r[0] in only]
    if args.bazaar:
        return bazaar(rows, args.out or "bazaar.json")
    args.out = args.out or "vetting.json"
    done = {}
    if os.path.exists(args.out):
        done = json.load(open(args.out, encoding="utf-8"))

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        hosts = dict(zip([r[0] for r in rows], pool.map(lambda r: hosting(r[1]), rows)))

    def search(row):
        sid, url, fa, en, source = row
        entry = done.get(sid, {})
        entry.update(id=sid, url=url, fa=fa, en=en, source=source, hosting=hosts[sid])
        if "myket" not in entry or entry["myket"] is None or only:
            searches = {}
            for keyword in dict.fromkeys(k for k in (fa, en) if k):
                searches[keyword] = myket_search(keyword)
                time.sleep(0.8)
            entry["myket"] = searches
        return entry

    # A few at a time: Myket answers in about two seconds, and backs off clients that hurry.
    with concurrent.futures.ThreadPoolExecutor(3) as pool:
        for index, entry in enumerate(pool.map(search, rows), 1):
            done[entry["id"]] = entry
            if index % 20 == 0:
                json.dump(done, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                print(f"{index}/{len(rows)}", flush=True)
    json.dump(done, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {args.out}: {len(done)} sites")


if __name__ == "__main__":
    main()
