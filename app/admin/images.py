"""Images uploaded from the dashboard, normalized to what the app expects.

- Service logos: an opaque full-bleed square, 256 px PNG (the app clips it to its shape).
- Category icons: a single-color glyph, 128 px, alpha only (the app tints it).

Files are named after their content (`logos/snapp-1a2b3c4d.png`), so a changed image gets a
new URL and no cache (the app's, or the CDN's 7-day one) ever shows the old one.
"""
from __future__ import annotations

import hashlib
import io
import re
import threading
import urllib.request
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
LOGO_SIZE = 256
ICON_SIZE = 128
PACKAGE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$")
# The app shows logos at 256 px and icons at 128, so 4 MP (a 2048 px square) is plenty. A
# decoded picture plus its working copies is several times its pixel count × 4 bytes, and the
# container has 192 MB in all: bigger pictures are refused before decoding (Pillow itself only
# warns up to 2× this), and one picture is converted at a time.
MAX_PIXELS = 4_200_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
_CONVERTING = threading.BoundedSemaphore(1)
TOO_LARGE = "the image is too large; use one up to 2048×2048 pixels"


class ImageError(ValueError):
    pass


def _open(data: bytes) -> Image.Image:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageError(f"the image is larger than {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    try:
        with warnings.catch_warnings():
            # Pillow warns about big images itself; the explicit check below refuses them.
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
        if image.format not in {"PNG", "JPEG", "WEBP"}:
            raise ImageError("use a PNG, JPEG or WebP image")
        # Only the header is read so far: refuse huge pictures before decoding them.
        if image.width * image.height > MAX_PIXELS:
            raise ImageError(TOO_LARGE)
        if image.format == "JPEG":
            image.draft("RGB", (1024, 1024))  # decode a photo at a reduced scale
        image.load()
    except Image.DecompressionBombError as error:  # Pillow's own refusal, above 2× MAX_PIXELS
        raise ImageError(TOO_LARGE) from error
    except (UnidentifiedImageError, OSError) as error:
        raise ImageError("not a PNG, JPEG or WebP image") from error
    ImageOps.exif_transpose(image, in_place=True)
    return image


def logo_png(data: bytes) -> bytes:
    with _CONVERTING:
        return _logo_png(data)


def icon_png(data: bytes) -> bytes:
    with _CONVERTING:
        return _icon_png(data)


def _logo_png(data: bytes) -> bytes:
    image = _open(data).convert("RGBA")
    side = min(image.size)
    left, top = (image.width - side) // 2, (image.height - side) // 2
    square = image.crop((left, top, left + side, top + side)).resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)
    opaque = Image.new("RGB", square.size, "white")
    opaque.paste(square, mask=square.getchannel("A"))
    out = io.BytesIO()
    opaque.save(out, "PNG", optimize=True)
    return out.getvalue()


def _icon_png(data: bytes) -> bytes:
    image = _open(data)
    if "A" in image.getbands() or "transparency" in image.info:
        alpha = image.convert("RGBA").getchannel("A")
    else:
        # No transparency: a dark glyph on a light background; darkness becomes coverage.
        alpha = ImageOps.invert(image.convert("L"))
    alpha.thumbnail((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
    canvas = Image.new("LA", (ICON_SIZE, ICON_SIZE), (255, 0))
    glyph = Image.merge("LA", (Image.new("L", alpha.size, 255), alpha))
    canvas.paste(glyph, ((ICON_SIZE - alpha.width) // 2, (ICON_SIZE - alpha.height) // 2))
    out = io.BytesIO()
    canvas.save(out, "PNG", optimize=True)
    return out.getvalue()


def save(public_dir: Path, folder: str, name: str, png: bytes) -> str:
    """Writes the image under its content hash and returns its path relative to public/."""
    digest = hashlib.sha256(png).hexdigest()[:8]
    relative = f"{folder}/{name}-{digest}.png"
    target = Path(public_dir) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temp = target.with_name(f".{target.name}.tmp")
        temp.write_bytes(png)
        temp.replace(target)
    return relative


def fetch_store_icon(package: str) -> bytes:
    """The app icon from the package's Cafe Bazaar listing (512 px)."""
    if not PACKAGE_RE.match(package):
        raise ImageError("not an Android package name, e.g. cab.snapp.passenger")
    url = f"https://s.cafebazaar.ir/images/icons/{package}_512x512.webp"
    request = urllib.request.Request(url, headers={"User-Agent": "daricheh-admin/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = response.read(MAX_UPLOAD_BYTES + 1)
    except OSError as error:
        raise ImageError(f"Cafe Bazaar has no icon for {package} (or is unreachable)") from error
    return data
