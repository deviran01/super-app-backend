import io
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.main as main
from app.admin.auth import COOKIE, AdminAccounts
from app.admin.store import AdminStore
from app.content import ContentStore

ROOT = Path(__file__).resolve().parent.parent
HEADERS = {"X-Superapp-Admin": "1"}
# Session cookies are Secure (and __Host-): like production, talk HTTPS.
BASE = "https://testserver"
PASSWORD = "correct horse battery"


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    data, public = tmp_path / "data", tmp_path / "public"
    data.mkdir()
    for name in ("catalog.json", "release.json"):
        shutil.copy(ROOT / "data" / name, data / name)
    (public / "logos").mkdir(parents=True)
    monkeypatch.setattr(main, "store", ContentStore(data))
    main.app.state.admin_store = AdminStore(data)
    main.app.state.admin_accounts = AdminAccounts(data / "admin")
    main.app.state.public_dir = public
    main.app.state.admin_accounts.create("ali", PASSWORD, created_by="test")
    return data, public


@pytest.fixture
def admin(env) -> TestClient:
    client = TestClient(main.app, base_url=BASE, headers=HEADERS)
    assert client.post("/admin/api/session", json={"username": "ali", "password": PASSWORD}).status_code == 200
    return client


def state(client):
    return client.get("/admin/api/state").json()


def save(client, mutate):
    current = state(client)
    draft = current["draft"]
    mutate(draft)
    return client.put("/admin/api/draft", json={"revision": current["revision"], **draft})


def png(color=(200, 30, 30, 255), size=(300, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", size, color).save(out, "PNG")
    return out.getvalue()


def test_everything_needs_a_session(env):
    client = TestClient(main.app, base_url=BASE, headers=HEADERS)
    for method, path in (("get", "/admin/api/state"), ("put", "/admin/api/draft"), ("post", "/admin/api/publish"), ("get", "/admin/api/admins")):
        assert getattr(client, method)(path).status_code == 401
    assert client.get("/admin/").status_code == 200  # the sign-in page itself is public
    assert client.get("/admin/").headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in client.get("/admin/").headers["content-security-policy"]


def test_dashboard_assets_are_versioned_by_content(env):
    client = TestClient(main.app, base_url=BASE)
    page = client.get("/admin/").text
    assert f"assets/{main.ASSET_VERSION}/js/main.js" in page and "__ASSETS__" not in page
    script = client.get(f"/admin/assets/{main.ASSET_VERSION}/js/main.js")
    assert script.status_code == 200 and "immutable" in script.headers["cache-control"]
    assert client.get("/admin/js/main.js").status_code == 404  # no unversioned copies to go stale


def test_session_cookie_is_locked_down(env):
    client = TestClient(main.app, base_url=BASE)
    response = client.post("/admin/api/session", json={"username": "ali", "password": PASSWORD})
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and COOKIE in cookie


def test_changes_need_the_csrf_header(admin):
    current = state(admin)
    bare = TestClient(main.app, base_url=BASE, cookies=admin.cookies)
    response = bare.put("/admin/api/draft", json={"revision": current["revision"], **current["draft"]})
    assert response.status_code == 403


def test_wrong_passwords_lock_the_account(env):
    client = TestClient(main.app, base_url=BASE, headers=HEADERS)
    for _ in range(5):
        assert client.post("/admin/api/session", json={"username": "ali", "password": "nope-nope-nope"}).status_code == 401
    assert client.post("/admin/api/session", json={"username": "ali", "password": PASSWORD}).status_code == 429


def test_draft_edits_do_not_reach_the_app_until_published(admin):
    response = save(admin, lambda d: d["catalog"]["services"][0].update(enabled=False))
    assert response.status_code == 200 and response.json()["dirty"]
    app = TestClient(main.app)
    snapp = lambda: next(s for s in app.get("/api/v1/config").json()["services"] if s["id"] == "snapp")
    assert snapp()["enabled"] is True

    current = state(admin)
    published = admin.post("/admin/api/publish", json={"revision": current["revision"], "note": "Snapp off"})
    assert published.status_code == 200 and not published.json()["dirty"]
    assert snapp()["enabled"] is False
    history = admin.get("/admin/api/history").json()
    assert history[0]["publishedBy"] == "ali" and history[0]["note"] == "Snapp off"


def test_invalid_drafts_are_refused_with_the_field(admin):
    response = save(admin, lambda d: d["catalog"]["services"][2].update(url="http://insecure.example"))
    assert response.status_code == 422
    assert response.json()["detail"]["problems"][0]["path"] == "catalog.services[2].url"

    response = save(admin, lambda d: d["catalog"]["services"][0].update(categoryId="nowhere"))
    assert response.status_code == 422 and "unknown category" in json.dumps(response.json())


def test_concurrent_edits_conflict_instead_of_overwriting(admin):
    stale = state(admin)
    assert save(admin, lambda d: d["release"]["default"].update(latestVersion=2)).status_code == 200
    response = admin.put("/admin/api/draft", json={"revision": stale["revision"], **stale["draft"]})
    assert response.status_code == 409


def test_release_rules_publish_to_the_version_endpoint(admin):
    save(admin, lambda d: d["release"]["channels"]["bazaar"].update(minimumSupportedVersion=5, latestVersion=5))
    admin.post("/admin/api/publish", json={"revision": state(admin)["revision"]})
    answer = TestClient(main.app).get("/api/v1/app/version", params={"channel": "bazaar", "appVersion": 3}).json()
    assert answer["update"] == "REQUIRED" and answer["updateUrl"] == "https://cafebazaar.ir/app/io.celin.super.app"


def test_restore_loads_an_old_version_into_the_draft(admin):
    first = admin.get("/admin/api/history").json()[-1]["id"]
    save(admin, lambda d: d["catalog"]["services"].pop())
    admin.post("/admin/api/publish", json={"revision": state(admin)["revision"]})
    restored = admin.post(f"/admin/api/history/{first}/restore").json()
    assert restored["dirty"] and len(restored["draft"]["catalog"]["services"]) == 29
    assert admin.post("/admin/api/history/..%2F..%2Fadmins/restore").status_code in (404, 405)
    with pytest.raises(KeyError):
        main.app.state.admin_store.restore("../admins", "ali")


def test_uploaded_logos_are_normalized_and_named_by_content(admin, env):
    _, public = env
    response = admin.post("/admin/api/images/logo?name=snapp", content=png(), headers={"Content-Type": "image/png"})
    path = response.json()["path"]
    assert path.startswith("logos/snapp-") and path.endswith(".png")
    image = Image.open(public / path)
    assert image.size == (256, 256) and image.mode == "RGB"
    assert admin.post("/admin/api/images/logo?name=snapp", content=b"not an image").status_code == 422
    assert admin.post("/admin/api/images/logo?name=../x", content=png()).status_code == 422

    icon = admin.post("/admin/api/images/icon?name=transport", content=png((0, 0, 0, 255), (64, 64))).json()["path"]
    glyph = Image.open(public / icon)
    assert glyph.size == (128, 128) and glyph.mode == "LA"


def test_admin_accounts(admin):
    assert admin.post("/admin/api/admins", json={"username": "sara", "password": "short"}).status_code == 422
    assert admin.post("/admin/api/admins", json={"username": "sara", "password": "long enough pass"}).status_code == 200
    assert {a["username"] for a in admin.get("/admin/api/admins").json()} == {"ali", "sara"}
    assert admin.delete("/admin/api/admins/ali").status_code == 422  # not yourself
    assert admin.delete("/admin/api/admins/sara").status_code == 200


def test_signing_out_ends_the_session(admin):
    cookies = dict(admin.cookies)
    assert admin.delete("/admin/api/session").status_code == 200
    assert TestClient(main.app, base_url=BASE, cookies=cookies).get("/admin/api/state").status_code == 401


def test_password_change_keeps_this_session_and_ends_others(admin):
    other = TestClient(main.app, base_url=BASE, cookies=dict(admin.cookies))
    response = admin.post("/admin/api/password", json={"current": PASSWORD, "new": "a brand new secret"})
    assert response.status_code == 200
    assert admin.get("/admin/api/state").status_code == 200
    assert other.get("/admin/api/state").status_code == 401


def test_large_json_is_refused_before_sign_in(env):
    client = TestClient(main.app, base_url=BASE, headers=HEADERS)
    big = b"[" + b"[]," * 100_000 + b"[]]"
    assert client.post("/admin/api/session", content=big, headers={"Content-Type": "application/json"}).status_code == 413


def test_a_crafted_cookie_is_just_signed_out(env):
    # Browsers can send non-ASCII cookie bytes; the signature check must not crash on them.
    assert main.app.state.admin_accounts.resolve("e30.\udce9") is None
    assert main.app.state.admin_accounts.resolve("e30.é") is None


def test_huge_images_are_refused_before_decoding(admin):
    out = io.BytesIO()
    Image.new("L", (5000, 4000)).save(out, "PNG")  # 20 MP, tiny file
    response = admin.post("/admin/api/images/logo?name=snapp", content=out.getvalue(), headers={"Content-Type": "image/png"})
    assert response.status_code == 422 and "2048×2048" in response.json()["detail"]


def test_discard_refuses_a_draft_that_changed_meanwhile(admin):
    stale = state(admin)["revision"]
    assert save(admin, lambda d: d["catalog"]["services"][0].update(enabled=False)).status_code == 200
    assert admin.post("/admin/api/draft/discard", json={"revision": stale}).status_code == 409
    assert admin.post("/admin/api/draft/discard", json={"revision": state(admin)["revision"]}).status_code == 200


def test_a_recreated_account_does_not_revive_old_sessions(env, admin):
    accounts = main.app.state.admin_accounts
    accounts.create("second", PASSWORD, created_by="ali")
    old = accounts.issue("second")
    accounts.delete("second", by="ali")
    accounts.create("second", PASSWORD, created_by="ali")
    assert accounts.resolve(old) is None


def test_only_the_two_uploads_take_big_bodies(env):
    # FastAPI parses a JSON body before it checks the session: a big one to any other admin
    # route is refused unread, signed in or not.
    client = TestClient(main.app, base_url=BASE, headers=HEADERS)
    big = b"[" + b"{}," * 100_000 + b"{}]"
    assert client.post("/admin/api/images/logo/from-store", content=big, headers={"Content-Type": "application/json"}).status_code == 413
    assert client.post("/admin/api/images/logo?name=snapp", content=big).status_code == 401  # read only after sign-in


def test_oversized_uploads_and_huge_pictures_are_refused(admin):
    too_big = b"\x89PNG" + b"0" * (6 * 1024 * 1024)
    assert admin.post("/admin/api/images/logo?name=snapp", content=too_big).status_code == 413
    huge = png(size=(2100, 2100))  # 4.4 MP: over the limit, refused before decoding
    response = admin.post("/admin/api/images/icon?name=transport", content=huge, headers={"Content-Type": "image/png"})
    assert response.status_code == 422 and "2048×2048" in response.json()["detail"]
    assert admin.post("/admin/api/images/logo?name=snapp", content=png(size=(2048, 2048))).status_code == 200
