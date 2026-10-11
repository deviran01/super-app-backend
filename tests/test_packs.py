"""Packs: sets of services switched on and off together from the dashboard. The app only
ever sees the switched-on ones, without the pack bookkeeping."""
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
from app.admin import packs
from app.admin.schema import Draft
from app.content import ContentStore, served_catalog

ROOT = Path(__file__).resolve().parent.parent
QUERY = {"platform": "android", "channel": "bazaar", "appVersion": 1}
PACK = {"id": "outage", "title": {"en": "Outage"}, "active": False}


def standard(catalog):
    """The catalog without packs (data/catalog.json, pulled from the server, may hold the
    bundled one, switched off)."""
    catalog = json.loads(json.dumps(catalog))
    catalog.pop("packs", None)
    for key in ("categories", "services", "compareGroups"):
        catalog[key] = [item for item in catalog.get(key, []) if "pack" not in item]
    return catalog


def with_pack(catalog, active=False):
    """The catalog plus a small pack: its own category and service, a service in a catalog
    category, and a compare group mixing both."""
    catalog = json.loads(json.dumps(catalog))
    catalog["packs"] = [{**PACK, "active": active}]
    catalog["categories"].append({"id": "news", "pack": "outage", "title": {"en": "News"}, "order": 99})
    catalog["services"] += [
        {"id": "isna", "pack": "outage", "name": {"en": "ISNA"}, "categoryId": "news", "url": "https://www.isna.ir/"},
        {"id": "okala", "pack": "outage", "name": {"en": "Okala"}, "categoryId": "food", "url": "https://www.okala.com/"},
    ]
    catalog["compareGroups"] += [
        {"id": "groceries", "pack": "outage", "serviceIds": ["snappfood", "okala"]},
        {"id": "food-plus", "serviceIds": ["snappfood", "tapsifood", "okala"]},
    ]
    return catalog


def config(data_dir: Path, catalog, monkeypatch):
    (data_dir / "catalog.json").write_text(json.dumps(catalog))
    monkeypatch.setattr(main, "store", ContentStore(data_dir))
    return TestClient(main.app).get("/api/v1/config", params=QUERY).json()


def ids(items):
    return {item["id"] for item in items}


def test_a_switched_off_pack_is_not_served(data_dir, monkeypatch):
    original = standard(json.loads((data_dir / "catalog.json").read_text()))
    body = config(data_dir, with_pack(original), monkeypatch)
    assert ids(body["services"]) == ids(original["services"])
    assert ids(body["categories"]) == ids(original["categories"])
    groups = {g["id"]: g["serviceIds"] for g in body["compareGroups"]}
    assert "groceries" not in groups and groups["food-plus"] == ["snappfood", "tapsifood"]
    assert "packs" not in body and '"pack"' not in json.dumps(body)
    # Reports about the pack still count: it may have been switched off minutes ago.
    assert {"isna", "okala"} <= main.store.get().service_ids and "news" in main.store.get().category_ids


def test_a_switched_on_pack_is_served_without_its_bookkeeping(data_dir, monkeypatch):
    original = standard(json.loads((data_dir / "catalog.json").read_text()))
    body = config(data_dir, with_pack(original, active=True), monkeypatch)
    assert {"isna", "okala"} <= ids(body["services"]) and "news" in ids(body["categories"])
    groups = {g["id"]: g["serviceIds"] for g in body["compareGroups"]}
    assert groups["groceries"] == ["snappfood", "okala"] and groups["food-plus"] == ["snappfood", "tapsifood", "okala"]
    assert "packs" not in body and '"pack"' not in json.dumps(body)


def test_a_catalog_without_packs_is_served_as_it_is(data_dir):
    catalog = standard(json.loads((data_dir / "catalog.json").read_text()))
    assert served_catalog(catalog) is catalog
    assert "packs" not in served_catalog({**catalog, "packs": []})


def state(client):
    return client.get("/admin/api/state").json()


def publish(client):
    response = client.post("/admin/api/publish", json={"revision": state(client)["revision"], "note": "test"})
    assert response.status_code == 200, response.text


def test_the_bundled_pack_goes_live_only_when_switched_on(admin, data_dir):
    (data_dir / "catalog.json").write_text(json.dumps(standard(json.loads((data_dir / "catalog.json").read_text()))))
    app = TestClient(main.app)
    before = ids(app.get("/api/v1/config", params=QUERY).json()["services"])
    bundled = packs.bundled()["iran-access"]

    listed = {p["id"]: p for p in admin.get("/admin/api/packs").json()}["iran-access"]
    assert not listed["added"] and listed["new_services"] == len(bundled["services"])

    added = admin.post("/admin/api/packs/iran-access/add", json={"revision": state(admin)["revision"]})
    assert added.status_code == 200, added.text
    draft = added.json()["draft"]["catalog"]
    assert draft["packs"] == [{"id": "iran-access", "title": bundled["title"], "description": bundled["description"], "active": False}]
    assert ids(bundled["services"]) <= ids(draft["services"])
    # Switched off: publishing it changes nothing for users.
    publish(admin)
    assert ids(app.get("/api/v1/config", params=QUERY).json()["services"]) == before

    current = state(admin)
    current["draft"]["catalog"]["packs"][0]["active"] = True
    assert admin.put("/admin/api/draft", json={"revision": current["revision"], **current["draft"]}).status_code == 200
    publish(admin)
    served = app.get("/api/v1/config", params=QUERY).json()
    assert ids(served["services"]) == before | ids(bundled["services"])
    assert '"pack"' not in json.dumps(served)

    # Adding again brings nothing new and keeps the switch as it is.
    listed = {p["id"]: p for p in admin.get("/admin/api/packs").json()}["iran-access"]
    assert listed["added"] and listed["new_services"] == listed["new_categories"] == 0
    again = admin.post("/admin/api/packs/iran-access/add").json()["draft"]["catalog"]
    assert again["packs"][0]["active"] is True and len(again["services"]) == len(draft["services"])


def test_adding_a_pack_keeps_edits_and_refuses_stale_drafts(admin):
    stale = state(admin)["revision"]
    current = state(admin)
    current["draft"]["catalog"]["services"][0]["enabled"] = False
    assert admin.put("/admin/api/draft", json={"revision": current["revision"], **current["draft"]}).status_code == 200
    assert admin.post("/admin/api/packs/iran-access/add", json={"revision": stale}).status_code == 409
    added = admin.post("/admin/api/packs/iran-access/add", json={"revision": state(admin)["revision"]}).json()
    assert added["draft"]["catalog"]["services"][0]["enabled"] is False
    assert admin.post("/admin/api/packs/nope/add").status_code == 404
    # Like every other admin route: signed in, and changes need the CSRF header.
    assert TestClient(main.app, base_url="https://testserver").get("/admin/api/packs").status_code == 401
    bare = TestClient(main.app, base_url="https://testserver", cookies=dict(admin.cookies))
    assert bare.post("/admin/api/packs/iran-access/add").status_code == 403


def save(client, mutate):
    current = state(client)
    mutate(current["draft"]["catalog"])
    return client.put("/admin/api/draft", json={"revision": current["revision"], **current["draft"]})


def test_pack_rules(admin):
    def add_pack(catalog):
        catalog["packs"] = [*catalog.get("packs", []), PACK]
        catalog["categories"].append({"id": "news", "pack": "outage", "title": {"en": "News"}})

    # A pack's category leaves with the pack, so everything in it must be in the pack.
    response = save(admin, lambda c: (add_pack(c), c["services"][0].update(categoryId="news")))
    assert response.status_code == 422 and "must be in that pack too" in response.text
    response = save(admin, lambda c: c["services"][0].update(pack="missing"))
    assert response.status_code == 422 and "unknown pack" in response.text
    # Switching off every enabled service would leave the app with nothing.
    response = save(admin, lambda c: (add_pack(c), [s.update(pack="outage") for s in c["services"]]))
    assert response.status_code == 422 and "outside switched-off packs" in response.text


def test_the_bundled_packs_fit_the_catalog():
    catalog = standard(json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8")))
    release = json.loads((ROOT / "data" / "release.json").read_text(encoding="utf-8"))
    document = {"catalog": catalog, "release": release}
    for pack in packs.bundled().values():
        before = len(document["catalog"]["services"])
        document = packs.merge(document, pack)
        Draft.model_validate(document)  # the dashboard would accept it, with the packs before it
        assert len(document["catalog"]["services"]) == before + len(pack["services"]), "an id is taken"
        for service in pack["services"]:
            assert re.match(r"^https://[a-z0-9.-]+/", service["url"]), service["id"]
            assert service["pack"] == pack["id"] and service["enabled"]
        # Images ship with public/: a missing logo shows a monogram, a broken path a failed request.
        for item in pack["services"] + pack["categories"]:
            image = item.get("logo") or item.get("icon")
            assert image is None or (ROOT / "public" / image).is_file(), image


def test_the_app_mode_switch_publishes_only_itself(admin, data_dir):
    (data_dir / "catalog.json").write_text(json.dumps(standard(json.loads((data_dir / "catalog.json").read_text()))))
    app = TestClient(main.app)
    served = lambda: {s["id"]: s for s in app.get("/api/v1/config", params=QUERY).json()["services"]}
    switch = lambda active: admin.post("/admin/api/packs/iran-access/switch", json={"active": active})
    admin.post("/admin/api/packs/iran-access/add")
    assert switch(True).status_code == 404  # only in the draft: publish it first
    publish(admin)
    before = served()

    # An unrelated edit waits in the draft; a form is open on the draft as it is now.
    current = state(admin)
    current["draft"]["catalog"]["services"][0]["enabled"] = False
    assert admin.put("/admin/api/draft", json={"revision": current["revision"], **current["draft"]}).status_code == 200
    opened = state(admin)

    on = switch(True)
    assert on.status_code == 200
    after = served()
    assert len(after) == len(before) + len(packs.bundled()["iran-access"]["services"])
    assert after["snapp"]["enabled"] is True  # the draft's edit stays unpublished
    draft = on.json()["draft"]["catalog"]
    assert draft["packs"][0]["active"] is True and draft["services"][0]["enabled"] is False and on.json()["dirty"]
    assert admin.get("/admin/api/history").json()[0]["note"].startswith("Switched on")
    # A form opened before the switch can't save over it.
    stale = admin.put("/admin/api/draft", json={"revision": opened["revision"], **opened["draft"]})
    assert stale.status_code == 409

    assert switch(False).status_code == 200
    assert served().keys() == before.keys()
    assert switch(False).status_code == 200  # already off: nothing to publish
    assert admin.get("/admin/api/history").json()[0]["note"].startswith("Switched off")
    assert admin.post("/admin/api/packs/nope/switch", json={"active": True}).status_code == 404


ALONE = {"id": "web", "title": {"en": "Web only"}, "active": False, "exclusive": True}


def with_exclusive_pack(catalog, active=False, extra_active=False):
    """with_pack() plus a pack that replaces the catalog: its own category and two services,
    and a compare group mixing one of them with a catalog service."""
    catalog = with_pack(catalog, active=extra_active)
    catalog["packs"].append({**ALONE, "active": active})
    catalog["categories"].append({"id": "web-news", "pack": "web", "title": {"en": "News"}, "order": 100})
    catalog["services"] += [
        {"id": "web-isna", "pack": "web", "name": {"en": "ISNA"}, "categoryId": "web-news", "url": "https://www.isna.ir/"},
        {"id": "web-alef", "pack": "web", "name": {"en": "Alef"}, "categoryId": "web-news", "url": "https://www.alef.ir/"},
    ]
    catalog["compareGroups"] += [
        {"id": "web-headlines", "pack": "web", "serviceIds": ["web-isna", "web-alef"]},
        {"id": "web-mixed", "pack": "web", "serviceIds": ["web-isna", "snappfood"]},
    ]
    return catalog


def test_a_pack_that_replaces_the_catalog_is_served_alone(data_dir, monkeypatch):
    original = standard(json.loads((data_dir / "catalog.json").read_text()))
    off = config(data_dir, with_exclusive_pack(original), monkeypatch)
    assert ids(off["services"]) == ids(original["services"])
    # On, even with another pack on too: only its own entries, without the bookkeeping.
    body = config(data_dir, with_exclusive_pack(original, active=True, extra_active=True), monkeypatch)
    assert ids(body["services"]) == {"web-isna", "web-alef"}
    assert ids(body["categories"]) == {"web-news"}
    assert [g["id"] for g in body["compareGroups"]] == ["web-headlines"]
    assert "packs" not in body and '"pack"' not in json.dumps(body)
    # Reports about the catalog's services still count while it's on.
    assert "snappfood" in main.store.get().service_ids


def test_rules_for_a_pack_that_replaces_the_catalog(admin):
    def add(catalog, active=False):
        catalog["packs"] = [*catalog.get("packs", []), {**ALONE, "active": active}]
        catalog["categories"].append({"id": "web-news", "pack": "web", "title": {"en": "News"}})

    # Its services can't sit in the catalog's categories: those are hidden while it's on.
    response = save(admin, lambda c: (add(c), c["services"].append(
        {"id": "web-isna", "pack": "web", "name": {"en": "ISNA"}, "categoryId": c["services"][0]["categoryId"], "url": "https://www.isna.ir/"})))
    assert response.status_code == 422 and "replaces the catalog, so its category must be in that pack too" in response.text
    # Switched on without an enabled service, the app would get nothing.
    response = save(admin, lambda c: add(c, active=True))
    assert response.status_code == 422 and "needs an enabled service" in response.text


def test_the_app_mode_picks_one_pack_and_a_replacing_pack_is_on_alone(admin, data_dir):
    catalog = with_exclusive_pack(standard(json.loads((data_dir / "catalog.json").read_text())))
    (data_dir / "catalog.json").write_text(json.dumps(catalog))
    app = TestClient(main.app)
    served = lambda: ids(app.get("/api/v1/config", params=QUERY).json()["services"])
    mode = lambda pack: admin.post("/admin/api/mode", json={"pack": pack})
    switch = lambda pack, active: admin.post(f"/admin/api/packs/{pack}/switch", json={"active": active})
    live = lambda: {p["id"]: p["active"] for p in state(admin)["live"]["catalog"]["packs"]}
    base = served()

    assert mode("outage").status_code == 200 and live() == {"outage": True, "web": False}
    assert served() == base | {"isna", "okala"}
    assert admin.get("/admin/api/history").json()[0]["note"] == "App mode: Outage"
    assert mode("web").status_code == 200 and live() == {"outage": False, "web": True}
    assert served() == {"web-isna", "web-alef"}
    assert admin.get("/admin/api/history").json()[0]["summary"]["enabled"] == 2
    assert mode(None).status_code == 200 and live() == {"outage": False, "web": False}
    assert served() == base

    # The single switch keeps a replacing pack alone: on, it switches the others off...
    assert switch("outage", True).status_code == 200
    assert switch("web", True).status_code == 200 and live() == {"outage": False, "web": True}
    # ...and switching another pack on switches it off.
    assert switch("outage", True).status_code == 200 and live() == {"outage": True, "web": False}

    assert mode("nope").status_code == 404
    signed_out = TestClient(main.app, base_url="https://testserver")
    assert signed_out.post("/admin/api/mode", json={"pack": None}).status_code == 401
