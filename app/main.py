"""Anar REST API.

    GET /api/v1/config        the catalog: services, categories, rules (docs: CONFIG_SPEC.md)
    GET /api/v1/app/version   the update policy for the caller's store: minimum version
                              (hard update), latest version (soft update), store link
    POST /api/v1/events       anonymous daily usage totals from the app (app/stats.py)
    GET /api/v1/feedback/challenge, POST /api/v1/feedback
                              a user's anonymous feedback message (app/feedback.py)
    GET /health               liveness for Docker
    /admin                    the admin dashboard (sign-in required; app/admin/)

Both API endpoints take `platform`, `channel` (bazaar | myket | direct) and `appVersion`,
answer with an ETag and `Cache-Control: no-cache`, and return 304 when the client's
`If-None-Match` still matches. The app sends nothing else: no user, session or device data.
Calls to these are counted per day for the dashboard's Statistics page.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .admin.auth import AdminAccounts, client_address
from .admin.routes import router as admin_router
from .admin.store import AdminStore
from .content import CHANNEL_PATTERN, DATA_DIR, ROOT, Content, ContentStore, resolve_release, update_status
from .feedback import FeedbackStore, Message, Refused
from .stats import StatsStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

PUBLIC_DIR = Path(os.environ.get("SUPERAPP_PUBLIC_DIR", ROOT / "public"))
SCENARIOS = [s.strip() for s in os.environ.get("SUPERAPP_SCENARIOS", "").split(",") if s.strip()]
# Absolute base for image URLs (production: https://superapp.2z2.ir/). Unset: the request's own
# base URL, which behind the proxy comes from the forwarded host and scheme.
PUBLIC_URL = os.environ.get("SUPERAPP_PUBLIC_URL")
IMAGE_MAX_AGE = 7 * 24 * 3600
MAX_EVENTS_BYTES = 64 * 1024
MAX_FEEDBACK_BYTES = 8 * 1024
MAX_ADMIN_JSON_BYTES = 256 * 1024
MAX_CACHED_VARIANTS = 64
# Versions above the highest one in the release rules (+ this margin) are counted as "other".
VERSION_MARGIN = 10
API_ENDPOINTS = {"/api/v1/config": "config", "/api/v1/app/version": "version", "/api/v1/events": "events", "/api/v1/feedback": "feedback"}

store = ContentStore(scenarios=SCENARIOS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    app.state.stats.flush()


app = FastAPI(
    lifespan=lifespan,
    title="Anar API",
    version="1",
    # Interactive docs only where asked for (local development); production exposes the API alone.
    docs_url="/docs" if os.environ.get("SUPERAPP_DOCS") == "1" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if os.environ.get("SUPERAPP_DOCS") == "1" else None,
)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)

app.state.admin_store = AdminStore(DATA_DIR)
app.state.admin_accounts = AdminAccounts(DATA_DIR / "admin")
app.state.public_dir = PUBLIC_DIR
app.state.stats = StatsStore(DATA_DIR / "stats" / "stats.db")
app.state.feedback = FeedbackStore(DATA_DIR / "feedback" / "feedback.db")
app.include_router(admin_router)

ADMIN_STATIC = Path(__file__).parent / "admin" / "static"


def _asset_version() -> str:
    """Content hash of the dashboard's files: a deploy that changes any of them changes every
    asset URL, so no browser or CDN cache can serve a stale script, style or image."""
    digest = hashlib.sha256()
    for path in sorted(ADMIN_STATIC.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(ADMIN_STATIC).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


ASSET_VERSION = _asset_version()
ADMIN_ASSETS = f"/admin/assets/{ASSET_VERSION}"
ADMIN_INDEX = (ADMIN_STATIC / "index.html").read_text(encoding="utf-8").replace("__ASSETS__", f"assets/{ASSET_VERSION}")

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


def _encode(payload: Any) -> tuple[bytes, str]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return body, '"%s"' % hashlib.sha256(body).hexdigest()[:32]


def _cached(content: Content, key: Any, build):
    """One variant of an answer (body and ETag, or a resolved policy), built once per content
    version. Bounded: keys come partly from the request (channel, host), so a flood of made-up
    values is answered without being kept."""
    cached = content.responses.get(key)
    if cached is None:
        cached = build()
        if len(content.responses) < MAX_CACHED_VARIANTS:
            content.responses[key] = cached
    return cached


def _revalidated(request: Request, body: bytes, etag: str, media_type: str = "application/json; charset=utf-8") -> Response:
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
        body = content.raw_catalog.encode("utf-8")
        return _revalidated(request, body, '"%s"' % hashlib.sha256(body).hexdigest()[:32])
    # Image paths in the catalog are relative to the site root; give clients the absolute base
    # (behind the proxy this is https://<public host>/).
    base = PUBLIC_URL or str(request.base_url)
    body, etag = _cached(content, ("config", base), lambda: _encode({**content.catalog, "assetsBaseUrl": content.catalog.get("assetsBaseUrl", base)}))
    return _revalidated(request, body, etag)


@app.get("/api/v1/app/version")
def get_app_version(request: Request, platform: Platform = "android", channel: Channel = "direct", appVersion: AppVersion = None) -> Response:
    content = store.get()
    if content.forced_status:
        return Response(status_code=content.forced_status)
    policy = _cached(content, ("policy", channel), lambda: resolve_release(content.release, channel))
    status = update_status(appVersion, policy) if appVersion is not None else None
    body, etag = _cached(content, ("version", channel, status), lambda: _encode({**policy, "update": status} if status else policy))
    return _revalidated(request, body, etag)


class ReportCount(BaseModel):
    event: str = Field(max_length=40)
    dims: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=2)
    n: int = Field(ge=0, le=1_000_000)


class ReportDay(BaseModel):
    day: str = Field(max_length=10)
    # No item limits here: the 64 KB body cap bounds the work, and the stats store keeps what
    # fits instead of refusing the whole report (which the app would retry forever).
    counts: list[ReportCount]


class UsageReport(BaseModel):
    """What the app uploads: daily totals for one build — no identifier of any kind."""
    model_config = ConfigDict(extra="ignore")

    platform: str = Field(pattern=r"^[a-z]{1,16}$")
    channel: str = Field(pattern=CHANNEL_PATTERN.pattern)
    appVersion: int = Field(ge=0, le=1_000_000_000)
    days: list[ReportDay]


def _bucketed_version(content: Content, version: int) -> int:
    """Versions far above the newest release are forged or broken: counted as 0 ("other")."""
    return version if 0 < version <= content.highest_version + VERSION_MARGIN else 0


async def _read_body(request: Request, limit: int) -> bytes | None:
    """The request body, or None once it grows past [limit] bytes."""
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            return None
    return bytes(body)


@app.post("/api/v1/events", status_code=204)
async def post_events(request: Request) -> Response:
    content = store.get()
    if content.forced_status:
        return Response(status_code=content.forced_status)
    body = await _read_body(request, MAX_EVENTS_BYTES)
    if body is None:
        return Response(status_code=413)
    try:
        report = UsageReport.model_validate_json(body)
    except ValidationError:
        return Response(status_code=400)
    request.state.stats_channel = report.channel
    request.state.stats_version = report.appVersion
    request.app.state.stats.add_report(
        report.model_dump(),
        services=content.service_ids,
        categories=content.category_ids,
        channels=content.channels,
        max_version=content.highest_version + VERSION_MARGIN,
    )
    return Response(status_code=204)


class FeedbackIn(BaseModel):
    """A feedback message: its kind, the text and the build that sent it — nothing about the user."""
    model_config = ConfigDict(extra="ignore")

    platform: str = Field(pattern=r"^[a-z]{1,16}$")
    channel: str = Field(pattern=CHANNEL_PATTERN.pattern)
    appVersion: int = Field(ge=0, le=1_000_000_000)
    osVersion: int = Field(default=0, ge=0, le=1000)
    kind: Literal["problem", "idea", "other"] = "other"
    # Raw; the length is checked again once normalized (app/feedback.py).
    text: str = Field(max_length=4000)
    challenge: str = Field(max_length=200)
    nonce: str = Field(pattern=r"^\d{1,20}$")


def _feedback_enabled(content: Content) -> bool:
    return content.catalog.get("features", {}).get("feedback", True) is not False


@app.get("/api/v1/feedback/challenge")
def get_feedback_challenge(request: Request, platform: Platform = "android", channel: Channel = "direct", appVersion: AppVersion = None) -> Response:
    content = store.get()
    if content.forced_status:
        return Response(status_code=content.forced_status)
    if not _feedback_enabled(content):
        return JSONResponse({"detail": "disabled"}, status_code=403)
    # One per message: never cached, by anyone.
    return JSONResponse(request.app.state.feedback.challenge(), headers={"Cache-Control": "no-store"})


@app.post("/api/v1/feedback", status_code=202)
async def post_feedback(request: Request) -> Response:
    content = store.get()
    if content.forced_status:
        return Response(status_code=content.forced_status)
    if not _feedback_enabled(content):
        return JSONResponse({"detail": "disabled"}, status_code=403)
    body = await _read_body(request, MAX_FEEDBACK_BYTES)
    if body is None:
        return Response(status_code=413)
    try:
        sent = FeedbackIn.model_validate_json(body)
    except ValidationError:
        return Response(status_code=400)
    channel = sent.channel if sent.channel in content.channels else "other"
    version = _bucketed_version(content, sent.appVersion)
    request.state.stats_channel = channel
    request.state.stats_version = version
    message = Message(sent.kind, sent.text, sent.challenge, sent.nonce, channel, version, sent.osVersion)
    try:
        await run_in_threadpool(request.app.state.feedback.submit, message, client_address(request))
    except Refused as refused:
        headers = {"Retry-After": str(refused.retry_after)} if refused.retry_after else None
        return JSONResponse({"detail": refused.reason}, status_code=refused.status, headers=headers)
    return Response(status_code=202)


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    store.get()
    return {"status": "ok"}


@app.middleware("http")
async def headers_and_counts(request: Request, call_next):
    path = request.url.path
    # JSON to the dashboard API is small; only image uploads are big. Refused before parsing,
    # so an unauthenticated 6 MB body can't balloon the process.
    if path.startswith("/admin/api/") and not path.startswith("/admin/api/images/"):
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_ADMIN_JSON_BYTES:
            return Response(status_code=413)
    endpoint = API_ENDPOINTS.get(path)
    try:
        response = await call_next(request)
    except Exception:
        if endpoint is not None:
            _count(request, endpoint, 500)  # a crash still shows up as a server error
        raise
    if endpoint is not None:
        _count(request, endpoint, response.status_code)
    if response.status_code == 200 and path.startswith(("/logos/", "/icons/")):
        # Images keep their name until they change (uploads are named by their content).
        response.headers["Cache-Control"] = f"public, max-age={IMAGE_MAX_AGE}"
    elif path == "/admin" or path.startswith("/admin/"):
        response.headers.update(ADMIN_HEADERS)
        if path.startswith(ADMIN_ASSETS + "/") and response.status_code == 200:
            # Versioned by content: safe to keep forever.
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            # The page and the API: never cached, not by the browser, not by the CDN.
            response.headers["Cache-Control"] = "no-store"
    return response


def _count(request: Request, endpoint: str, status: int) -> None:
    content = store.get()
    channel = getattr(request.state, "stats_channel", None) or request.query_params.get("channel") or "direct"
    try:
        version = int(getattr(request.state, "stats_version", None) or request.query_params.get("appVersion") or 0)
    except ValueError:
        version = 0
    request.app.state.stats.count_api_call(endpoint, status, channel if channel in content.channels else "other", _bucketed_version(content, version))


@app.get("/admin", include_in_schema=False)
def admin_redirect() -> RedirectResponse:
    return RedirectResponse("/admin/")


@app.get("/admin/", include_in_schema=False)
def admin_page() -> HTMLResponse:
    return HTMLResponse(ADMIN_INDEX)


for folder in ("logos", "icons"):
    if (PUBLIC_DIR / folder).is_dir():
        app.mount(f"/{folder}", StaticFiles(directory=PUBLIC_DIR / folder), name=folder)
app.mount(ADMIN_ASSETS, StaticFiles(directory=ADMIN_STATIC), name="admin-assets")
# Local QA pages for the "lab" scenario; not shipped in the production image.
if "lab" in SCENARIOS and (PUBLIC_DIR / "lab").is_dir():
    app.mount("/lab", StaticFiles(directory=PUBLIC_DIR / "lab", html=True), name="lab")
