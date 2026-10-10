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


def test_the_bundled_pack_fits_the_catalog():
    catalog = standard(json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8")))
    release = json.loads((ROOT / "data" / "release.json").read_text(encoding="utf-8"))
    for pack in packs.bundled().values():
        merged = packs.merge({"catalog": catalog, "release": release}, pack)
        Draft.model_validate(merged)  # the dashboard would accept it
        assert len(merged["catalog"]["services"]) == len(catalog["services"]) + len(pack["services"]), "an id is taken"
        for service in pack["services"]:
            assert re.match(r"^https://[a-z0-9.-]+/", service["url"]), service["id"]
            assert service["pack"] == pack["id"] and service["enabled"]
        # Images ship with public/: a missing logo shows a monogram, a broken path a failed request.
        for item in pack["services"] + pack["categories"]:
            image = item.get("logo") or item.get("icon")
            assert image is None or (ROOT / "public" / image).is_file(), image
