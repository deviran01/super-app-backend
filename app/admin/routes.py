"""Admin API (/admin/api): sign-in, the draft, publishing, history, images, accounts, usage statistics and feedback."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ValidationError

from .auth import COOKIE, SECURE_COOKIES, SESSION_SECONDS, AdminAccounts, client_address, require_admin
from .images import MAX_UPLOAD_BYTES, ImageError, fetch_store_icon, icon_png, logo_png, save
from .schema import ID_RE, Draft, problems
from .store import AdminStore, Conflict, DraftState

router = APIRouter(prefix="/admin/api")


def store(request: Request) -> AdminStore:
    return request.app.state.admin_store


def accounts(request: Request) -> AdminAccounts:
    return request.app.state.admin_accounts


def _state_json(state: DraftState) -> dict[str, Any]:
    return {
        "draft": state.draft,
        "live": state.live,
        "revision": state.revision,
        "dirty": state.dirty,
        "updatedBy": state.updated_by,
        "updatedAt": state.updated_at,
        "published": state.live_meta,
    }


# --- session ----------------------------------------------------------------------------


class Credentials(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


@router.post("/session")
def sign_in(body: Credentials, request: Request, response: Response) -> dict[str, str]:
    accounts_ = accounts(request)
    try:
        ok = accounts_.verify(body.username, body.password, client_address(request))
    except PermissionError as locked:
        raise HTTPException(status_code=429, detail=f"Too many attempts. Try again in {locked.args[0] // 60 + 1} minutes.")
    if not ok:
        raise HTTPException(status_code=401, detail="Wrong username or password")
    username = body.username.strip().lower()
    response.set_cookie(
        COOKIE,
        accounts_.issue(username),
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="strict",
        path="/",
    )
    return {"username": username}


@router.get("/session")
def current(username: str = Depends(require_admin)) -> dict[str, str]:
    return {"username": username}


@router.delete("/session")
def sign_out(request: Request, response: Response, username: str = Depends(require_admin)) -> dict[str, bool]:
    accounts(request).end_sessions(username)
    response.delete_cookie(COOKIE, path="/", secure=SECURE_COOKIES, httponly=True, samesite="strict")
    return {"ok": True}


# --- draft and publishing -----------------------------------------------------------------


@router.get("/state")
def get_state(request: Request, _: str = Depends(require_admin)) -> dict[str, Any]:
    return _state_json(store(request).state())


class SaveDraft(BaseModel):
    revision: int
    catalog: dict[str, Any]
    release: dict[str, Any]


@router.put("/draft")
def save_draft(body: SaveDraft, request: Request, username: str = Depends(require_admin)) -> dict[str, Any]:
    try:
        draft = Draft.model_validate({"catalog": body.catalog, "release": body.release})
    except ValidationError as error:
        raise HTTPException(status_code=422, detail={"message": "Some fields need attention", "problems": problems(error)})
    try:
        return _state_json(store(request).save_draft(draft, body.revision, username))
    except Conflict as conflict:
        raise HTTPException(status_code=409, detail=f"Someone else saved meanwhile ({conflict}). Reload to see their changes.")


class BaseRevision(BaseModel):
    # Optional for older dashboards; when sent, a draft that changed meanwhile isn't replaced.
    revision: int | None = None


CONFLICT = "Another admin changed the draft meanwhile. It has been reloaded; check it and try again."


@router.post("/draft/discard")
def discard(request: Request, body: BaseRevision | None = None, _: str = Depends(require_admin)) -> dict[str, Any]:
    try:
        return _state_json(store(request).discard(body.revision if body else None))
    except Conflict:
        raise HTTPException(status_code=409, detail=CONFLICT)


class Publish(BaseModel):
    revision: int
    note: str = Field(default="", max_length=200)


@router.post("/publish")
def publish(body: Publish, request: Request, username: str = Depends(require_admin)) -> dict[str, Any]:
    try:
        return _state_json(store(request).publish(body.revision, username, body.note.strip()))
    except Conflict as conflict:
        raise HTTPException(status_code=409, detail=f"The draft changed ({conflict}). Review it and publish again.")
    except ValidationError as error:
        raise HTTPException(status_code=422, detail={"message": "The draft can't be published", "problems": problems(error)})


@router.get("/history")
def history(request: Request, _: str = Depends(require_admin)) -> list[dict[str, Any]]:
    return store(request).history()


@router.get("/history/{entry_id}")
def history_entry(entry_id: str, request: Request, _: str = Depends(require_admin)) -> dict[str, Any]:
    try:
        entry = store(request).entry(entry_id)
    except KeyError:
        entry = None
    if entry is None:
        raise HTTPException(status_code=404, detail="No such version")
    return entry


@router.post("/history/{entry_id}/restore")
def restore(entry_id: str, request: Request, body: BaseRevision | None = None, username: str = Depends(require_admin)) -> dict[str, Any]:
    try:
        return _state_json(store(request).restore(entry_id, username, body.revision if body else None))
    except KeyError:
        raise HTTPException(status_code=404, detail="No such version")
    except Conflict:
        raise HTTPException(status_code=409, detail=CONFLICT)


# --- images -------------------------------------------------------------------------------


def _name(value: str) -> str:
    if not ID_RE.match(value):
        raise HTTPException(status_code=422, detail="Set a valid id first")
    return value


async def _body(request: Request) -> bytes:
    # nginx caps uploads too; this keeps a direct request from buffering more than one image.
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"The image is larger than {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    if not data:
        raise HTTPException(status_code=422, detail="Choose an image")
    return bytes(data)


@router.post("/images/logo")
async def upload_logo(request: Request, name: str = Query(), _: str = Depends(require_admin)) -> dict[str, str]:
    return await _upload(request, name, "logos", logo_png)


@router.post("/images/icon")
async def upload_icon(request: Request, name: str = Query(), _: str = Depends(require_admin)) -> dict[str, str]:
    return await _upload(request, name, "icons/categories", icon_png)


async def _upload(request: Request, name: str, folder: str, convert) -> dict[str, str]:
    name = _name(name)
    data = await _body(request)
    try:
        # Decoding and resizing take a while: off the event loop, so the API keeps answering.
        png = await run_in_threadpool(convert, data)
    except ImageError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"path": save(request.app.state.public_dir, folder, name, png)}


class StoreIcon(BaseModel):
    name: str
    package: str = Field(max_length=150)


@router.post("/images/logo/from-store")
def logo_from_store(body: StoreIcon, request: Request, _: str = Depends(require_admin)) -> dict[str, str]:
    try:
        png = logo_png(fetch_store_icon(body.package.strip()))
        return {"path": save(request.app.state.public_dir, "logos", _name(body.name), png)}
    except ImageError as error:
        raise HTTPException(status_code=422, detail=str(error))


# --- statistics and feedback -----------------------------------------------------------------


@router.get("/stats")
def stats(
    request: Request,
    days: int = Query(30, ge=1, le=90),
    channel: str | None = Query(None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$"),
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    return request.app.state.stats.summary(days, channel)


@router.get("/feedback")
def feedback_page(
    request: Request,
    folder: Literal["inbox", "archived", "spam"] = "inbox",
    before: int | None = Query(None, ge=1),
    limit: int = Query(30, ge=1, le=100),
    _: str = Depends(require_admin),
) -> dict[str, Any]:
    return request.app.state.feedback.page(folder, before, limit)


@router.get("/feedback/counts")
def feedback_counts(request: Request, _: str = Depends(require_admin)) -> dict[str, int]:
    return request.app.state.feedback.counts()


class FeedbackStatus(BaseModel):
    status: Literal["new", "read", "archived", "spam"]


@router.patch("/feedback/{item_id}")
def set_feedback_status(item_id: int, body: FeedbackStatus, request: Request, _: str = Depends(require_admin)) -> dict[str, Any]:
    item = request.app.state.feedback.set_status(item_id, body.status)
    if item is None:
        raise HTTPException(status_code=404, detail="No such message")
    return item


@router.delete("/feedback/{item_id}")
def delete_feedback(item_id: int, request: Request, _: str = Depends(require_admin)) -> dict[str, bool]:
    if not request.app.state.feedback.delete(item_id):
        raise HTTPException(status_code=404, detail="No such message")
    return {"ok": True}


@router.post("/feedback/read-all")
def read_all_feedback(request: Request, _: str = Depends(require_admin)) -> dict[str, int]:
    return {"updated": request.app.state.feedback.mark_all_read()}


@router.post("/feedback/empty-spam")
def empty_spam(request: Request, _: str = Depends(require_admin)) -> dict[str, int]:
    return {"deleted": request.app.state.feedback.empty_spam()}


# --- accounts -----------------------------------------------------------------------------


@router.get("/admins")
def list_admins(request: Request, _: str = Depends(require_admin)) -> list[dict[str, Any]]:
    return [{"username": a.username, "createdAt": a.created_at, "createdBy": a.created_by} for a in accounts(request).list()]


@router.post("/admins")
def add_admin(body: Credentials, request: Request, username: str = Depends(require_admin)) -> dict[str, Any]:
    try:
        admin = accounts(request).create(body.username, body.password, created_by=username)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"username": admin.username, "createdAt": admin.created_at, "createdBy": admin.created_by}


@router.delete("/admins/{target}")
def remove_admin(target: str, request: Request, username: str = Depends(require_admin)) -> dict[str, bool]:
    try:
        accounts(request).delete(target, by=username)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except KeyError:
        raise HTTPException(status_code=404, detail="No such admin")
    return {"ok": True}


class PasswordChange(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)


@router.post("/password")
def change_password(body: PasswordChange, request: Request, response: Response, username: str = Depends(require_admin)) -> dict[str, bool]:
    accounts_ = accounts(request)
    try:
        if not accounts_.verify(username, body.current, client_address(request)):
            raise HTTPException(status_code=422, detail="Your current password is wrong")
        accounts_.set_password(username, body.new)
    except PermissionError:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    # Every other session ended; keep this one.
    response.set_cookie(COOKIE, accounts_.issue(username), max_age=SESSION_SECONDS, httponly=True, secure=SECURE_COOKIES, samesite="strict", path="/")
    return {"ok": True}
