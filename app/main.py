"""Daricheh REST API.

    GET /api/v1/config        the catalog: services, categories, rules (docs: CONFIG_SPEC.md)
    GET /api/v1/app/version   the update policy for the caller's store: minimum version
                              (hard update), latest version (soft update), store link
    GET /health               liveness for Docker
    /admin                    the admin dashboard (sign-in required; app/admin/)

Both API endpoints take `platform`, `channel` (bazaar | myket | direct) and `appVersion`,
answer with an ETag and `Cache-Control: no-cache`, and return 304 when the client's
`If-None-Match` still matches. The app sends nothing else: no user, session or device data.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from .admin.auth import AdminAccounts
from .admin.routes import router as admin_router
from .admin.store import AdminStore
from .content import CHANNEL_PATTERN, DATA_DIR, ROOT, ContentStore, resolve_release, update_status

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

PUBLIC_DIR = Path(os.environ.get("SUPERAPP_PUBLIC_DIR", ROOT / "public"))
SCENARIOS = [s.strip() for s in os.environ.get("SUPERAPP_SCENARIOS", "").split(",") if s.strip()]
# Absolute base for image URLs (production: https://superapp.2z2.ir/). Unset: the request's own
# base URL, which behind the proxy comes from the forwarded host and scheme.
PUBLIC_URL = os.environ.get("SUPERAPP_PUBLIC_URL")
IMAGE_MAX_AGE = 7 * 24 * 3600

store = ContentStore(scenarios=SCENARIOS)

app = FastAPI(
    title="Daricheh API",
    version="1",
    # Interactive docs only where asked for (local development); production exposes the API alone.
    docs_url="/docs" if os.environ.get("SUPERAPP_DOCS") == "1" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if os.environ.get("SUPERAPP_DOCS") == "1" else None,
)
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.state.admin_store = AdminStore(DATA_DIR)
app.state.admin_accounts = AdminAccounts(DATA_DIR / "admin")
app.state.public_dir = PUBLIC_DIR
app.include_router(admin_router)

ADMIN_HEADERS = {
    # Everything the dashboard loads comes from this origin; nothing may frame it.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: https:; style-src 'self'; script-src 'self'; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
}

Channel = Annotated[str, Query(pattern=CHANNEL_PATTERN.pattern, description="Store the build was published in")]
AppVersion = Annotated[int | None, Query(ge=0, description="The app's versionCode")]
Platform = Annotated[str, Query(pattern=r"^[a-z]{1,16}$")]


def _json(request: Request, payload: Any) -> Response:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _revalidated(request, body)


def _revalidated(request: Request, body: bytes, media_type: str = "application/json; charset=utf-8") -> Response:
    etag = '"%s"' % hashlib.sha256(body).hexdigest()[:32]
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    sent = {tag.strip().removeprefix("W/") for tag in request.headers.get("if-none-match", "").split(",")}
    if etag in sent:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type=media_type, headers=headers)


@app.get("/api/v1/config")
def get_config(request: Request, platform: Platform = "android", channel: Channel = "direct", appVersion: AppVersion = None) -> Response:
    content = store.get()
    if content.forced_status:
        return Response(status_code=content.forced_status)
    if content.raw_catalog is not None:
        return _revalidated(request, content.raw_catalog.encode("utf-8"))
    document = dict(content.catalog)
    # Image paths in the catalog are relative to the site root; give clients the absolute base
    # (behind the proxy this is https://<public host>/).
    document.setdefault("assetsBaseUrl", PUBLIC_URL or str(request.base_url))
    return _json(request, document)


@app.get("/api/v1/app/version")
def get_app_version(request: Request, platform: Platform = "android", channel: Channel = "direct", appVersion: AppVersion = None) -> Response:
    content = store.get()
    if content.forced_status:
        return Response(status_code=content.forced_status)
    policy = resolve_release(content.release, channel)
    if appVersion is not None:
        policy["update"] = update_status(appVersion, policy)
    return _json(request, policy)


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    store.get()
    return {"status": "ok"}


@app.middleware("http")
async def cache_and_security_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if response.status_code == 200 and path.startswith(("/logos/", "/icons/")):
        # Images keep their name until they change (uploads are named by their content).
        response.headers["Cache-Control"] = f"public, max-age={IMAGE_MAX_AGE}"
    elif path == "/admin" or path.startswith("/admin/"):
        response.headers.update(ADMIN_HEADERS)
        # Never cached anywhere: not by the browser, not by the CDN.
        response.headers["Cache-Control"] = "no-store"
    return response


for folder in ("logos", "icons"):
    if (PUBLIC_DIR / folder).is_dir():
        app.mount(f"/{folder}", StaticFiles(directory=PUBLIC_DIR / folder), name=folder)
app.mount("/admin", StaticFiles(directory=Path(__file__).parent / "admin" / "static", html=True), name="admin")
# Local QA pages for the "lab" scenario; not shipped in the production image.
if "lab" in SCENARIOS and (PUBLIC_DIR / "lab").is_dir():
    app.mount("/lab", StaticFiles(directory=PUBLIC_DIR / "lab", html=True), name="lab")
