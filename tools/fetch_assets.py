#!/usr/bin/env python3
"""Downloads the sample backend's images.

- Service logos: the company's official Android app icon from its Cafe Bazaar or Myket
  listing (the icon users already know from their home screen), else the site's own icon
  (web manifest / apple-touch-icon / icon links). Every logo is normalized to an opaque,
  full-bleed 256x256 PNG in public/logos/<id>.png: pre-rounded icons get their corners
  filled with the edge color, free-form ones are centered on white. Services with no
  reachable icon are skipped; the app shows a brand-colored monogram instead.
- Category icons: Solar "Bold Duotone" glyphs (480 Design, CC BY 4.0) rendered to
  128x128 PNGs in public/icons/categories/. They are one color with two opacity levels,
  so the app's tint keeps the duotone look.

Requires Pillow and resvg-py (pip install pillow resvg-py).
Usage: python3 tools/fetch_assets.py [--logos] [--icons] [service or category id...]
(ids limit the run to those services' logos and those categories' icons)
"""
import http.cookiejar
import io
import json
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(HERE, "..", "public")
UA = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
LOGO_SIZE = 256
ICON_SIZE = 128

# Android package of each service's official app (verified against the store listing).
BAZAAR_PACKAGES = {
    "snapp": "cab.snapp.passenger",
    "tapsi": "taxi.tap30.passenger",
    "snappbox": "com.snapp_box.android",
    "snappfood": "com.zoodfood.android",
    "tapsifood": "com.tapsi.tapsifood",
    "digikala": "com.digikala",
    "torob": "ir.torob",
    "basalam": "ir.basalam.app",
    "divar": "ir.divar",
    "sheypoor": "com.sheypoor.mobile",
    "alibaba": "ir.alibaba",
    "snapptrip": "com.pintapin.pintapin",
    "jabama": "com.jabamaguest",
    "balad": "ir.balad",
    "neshan": "org.rajman.neshan.traffic.tehran.navigator",
    "filimo": "com.aparat.filimo",
    "namava": "com.shatelland.namava.mobile",
    "aparat": "com.aparat",
    "paziresh24": "com.paziresh24.paziresh24",
    "nobitex": "market.nobitex",
    "myirancell": "com.myirancell",
    "hamrahman": "ir.mci.ecareapp",
    "mygov": "ir.gov.mygov",
    "eitaa": "ir.eitaa.messenger",
    "rubika": "app.rbmain.a",
    "karnameh": "com.karnameh",
    "beeptunes": "com.beep.tunes",
    "navaar": "ir.navaar.android",
    "fidibo": "com.fidibo.app",
    "taaghche": "ir.mservices.mybook",
    "bimebazar": "com.bimebazar.bimebazar",
    "mrbilit": "com.mrbilit.app",
    "flytoday": "ir.flytoday",
    "otaghak": "ir.otaghak.app",
    "filmnet": "ir.filmnet.android",
    "milli": "gold.milli.app",
    "technolife": "com.technolife",
    "banimode": "com.banimode.app",
}
MYKET_PACKAGES = {
    "bale": "ir.nasim",
    "jobvision": "com.jobvision.app",
    "kilid": "com.kilid.portal",
}
BAZAAR_ICON = "https://s.cafebazaar.ir/images/icons/{package}_512x512.webp"
MYKET_PAGE = "https://myket.ir/app/{package}"

CATEGORY_ICONS = {
    "transport": "car", "food": "chef-hat", "shopping": "bag-4", "classifieds": "shop-2",
    "travel": "suitcase", "maps": "map-point-wave", "entertainment": "clapperboard-play",
    "health": "health", "finance": "wallet-money", "utilities": "sim-card",
    "government": "buildings-3", "messaging": "chat-round-dots", "lab": "test-tube",
    "cars": "wheel", "music": "music-notes", "books": "book-2", "education": "square-academic-cap",
    "jobs": "case-round", "insurance": "shield-check",
}
SOLAR_JSON = "https://api.iconify.design/solar.json?icons={names}"


# Keeps cookies: some sites redirect to themselves until a cookie they set is sent back.
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def get(url, timeout=20):
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with OPENER.open(request, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", ""), response.geturl()


# --- Logos -------------------------------------------------------------------------------

def store_icon(service_id):
    """The official app icon from the store listing, or None."""
    if service_id in BAZAAR_PACKAGES:
        return get(BAZAAR_ICON.format(package=BAZAAR_PACKAGES[service_id]))[0]
    if service_id in MYKET_PACKAGES:
        page = get(MYKET_PAGE.format(package=MYKET_PACKAGES[service_id]))[0].decode("utf-8", "ignore")
        match = re.search(r"https://myket\.ir/app-icon/[\w-]+\.png", page)
        return get(match.group(0))[0] if match else None
    return None


class IconLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.icons, self.manifest = [], None

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        attrs = dict(attrs)
        rel, href = (attrs.get("rel") or "").lower(), attrs.get("href")
        if not href:
            return
        if "manifest" in rel:
            self.manifest = href
        elif "icon" in rel:
            sizes = attrs.get("sizes") or ""
            size = max((int(n) for n in re.findall(r"(\d+)x\d+", sizes)), default=180 if "apple" in rel else 32)
            self.icons.append((size, href))


def site_icon_candidates(page_url):
    html, _, final_url = get(page_url)
    parser = IconLinks()
    parser.feed(html.decode("utf-8", "ignore"))
    found = [(size, urljoin(final_url, href)) for size, href in parser.icons]
    if parser.manifest:
        try:
            manifest_url = urljoin(final_url, parser.manifest)
            manifest = json.loads(get(manifest_url)[0].decode("utf-8-sig", "ignore"))
            for icon in manifest.get("icons", []):
                size = max((int(n) for n in re.findall(r"(\d+)x\d+", icon.get("sizes", ""))), default=0)
                if "maskable" not in icon.get("purpose", ""):
                    found.append((size, urljoin(manifest_url, icon["src"])))
        except Exception as error:  # noqa: BLE001 - best effort
            print(f"  manifest failed: {error}")
    found.append((180, urljoin(final_url, "/apple-touch-icon.png")))
    return sorted(found, key=lambda item: -item[0])


def site_icon(page_url):
    for _, icon_url in site_icon_candidates(page_url):
        if icon_url.endswith(".svg"):
            continue
        try:
            data, content_type, _ = get(icon_url)
            if "html" not in content_type and Image.open(io.BytesIO(data)).width >= 128:
                return data
        except Exception:  # noqa: BLE001 - try the next candidate
            continue
    return None


def opaque_inset(image, corner):
    """Distance along a corner's diagonal to the first fully opaque pixel."""
    width, height = image.size
    alpha = image.getchannel("A")
    for step in range(min(width, height) // 2):
        x = step if corner[0] == 0 else width - 1 - step
        y = step if corner[1] == 0 else height - 1 - step
        if alpha.getpixel((x, y)) >= 250:
            return step, (x, y)
    return None, None


def normalize(data):
    """An opaque, full-bleed square logo; the app clips it to its own icon shape."""
    image = Image.open(io.BytesIO(data)).convert("RGBA")
    bbox = image.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
    if bbox is None:
        raise ValueError("empty image")
    image = image.crop(bbox)
    width, height = image.size
    corners = [(0, 0), (1, 0), (0, 1), (1, 1)]
    insets = [opaque_inset(image, corner) for corner in corners]
    alpha = image.getchannel("A")
    edges_opaque = all(
        alpha.getpixel(point) >= 250
        for point in [(width // 2, 1), (width // 2, height - 2), (1, height // 2), (width - 2, height // 2)]
    )
    is_tile = abs(width - height) <= width * 0.03 and edges_opaque and all(
        step is not None and step < width * 0.12 for step, _ in insets
    )
    if is_tile:
        # A rounded-square app icon: extend each corner's own color into its transparent corner.
        background = Image.new("RGBA", image.size)
        for (cx, cy), (_, point) in zip(corners, insets):
            inward = (point[0] + (2 if cx == 0 else -2), point[1] + (2 if cy == 0 else -2))
            color = image.getpixel(inward)[:3] + (255,)
            box = (cx * width // 2, cy * height // 2, (cx + 1) * width // 2 + 1, (cy + 1) * height // 2 + 1)
            background.paste(color, box)
        background.alpha_composite(image)
        square = background
    else:
        # A free-form mark (hexagon, emblem): center it on white with breathing room.
        side = int(max(width, height) / 0.8)
        square = Image.new("RGBA", (side, side), (255, 255, 255, 255))
        square.alpha_composite(image, ((side - width) // 2, (side - height) // 2))
    return square.convert("RGB").resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)


def fetch_logos(only=()):
    with open(os.path.join(HERE, "..", "data", "catalog.json"), encoding="utf-8") as f:
        services = [s for s in json.load(f)["services"] if not only or s["id"] in only]
    os.makedirs(os.path.join(PUBLIC, "logos"), exist_ok=True)
    missing = []
    for service in services:
        sid = service["id"]
        for source, load in (("store", lambda: store_icon(sid)), ("site", lambda: site_icon(service["url"]))):
            try:
                data = load()
                if data:
                    normalize(data).save(os.path.join(PUBLIC, "logos", f"{sid}.png"), optimize=True)
                    print(f"ok {sid} ({source})")
                    break
            except Exception as error:  # noqa: BLE001 - fall through to the next source
                print(f"  {sid}: {source} failed: {error}")
        else:
            missing.append(sid)
    print("missing logos (monogram fallback):", ", ".join(missing) or "none")


# --- Category icons ----------------------------------------------------------------------

def fetch_category_icons(only=()):
    import resvg_py  # only needed here

    icons = {c: name for c, name in CATEGORY_ICONS.items() if not only or c in only}
    names = sorted({f"{name}-bold-duotone" for name in icons.values()})
    data = json.loads(get(SOLAR_JSON.format(names=",".join(names)))[0])
    out = os.path.join(PUBLIC, "icons", "categories")
    os.makedirs(out, exist_ok=True)
    for category, name in icons.items():
        icon = data["icons"].get(f"{name}-bold-duotone")
        if icon is None:
            print(f"missing icon {category} ({name})")
            continue
        size = data.get("width", 24)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{ICON_SIZE}" height="{ICON_SIZE}" '
               f'viewBox="0 0 {size} {size}">{icon["body"].replace("currentColor", "#000")}</svg>')
        png = Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(svg_string=svg)))).convert("RGBA")
        # Keep only the alpha channel: the app supplies the color.
        png = Image.merge("LA", (Image.new("L", png.size, 0), png.getchannel("A")))
        png.save(os.path.join(out, f"{category}.png"), optimize=True)
        print(f"ok icon {category} (solar:{name}-bold-duotone)")


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")} or {"--logos", "--icons"}
    ids = {a for a in sys.argv[1:] if not a.startswith("--")}
    if "--icons" in flags:
        fetch_category_icons(ids)
    if "--logos" in flags:
        fetch_logos(ids)
    sys.exit(0)
