import json

import pytest

import app.feedback as feedback
from app.feedback import normalize

QUERY = {"platform": "android", "channel": "bazaar", "appVersion": 1}


def send(client, text="The map doesn't load after I sign in.", kind="problem", **extra):
    body = {"platform": "android", "channel": "bazaar", "appVersion": 1, "osVersion": 35, "kind": kind, "text": text, **extra}
    return client.post("/api/v1/feedback", json=body)


def inbox(admin, folder="inbox"):
    response = admin.get("/admin/api/feedback", params={"folder": folder})
    assert response.status_code == 200
    return response.json()


def test_a_message_reaches_the_dashboard_inbox(client, admin):
    assert send(client, "  Please add   Torob.\r\n\r\n\r\n\r\nThanks!  ", kind="idea").status_code == 202
    page = inbox(admin)
    assert page["counts"] == {"unread": 1, "inbox": 1, "archived": 0, "spam": 0}
    item = page["items"][0]
    assert item["text"] == "Please add Torob.\n\nThanks!"
    assert (item["kind"], item["status"], item["channel"], item["appVersion"], item["osVersion"]) == ("idea", "new", "bazaar", 1, 35)


@pytest.mark.parametrize("text", ["ok", "سلام", "تست", "!!!", "https://a.example https://b.example https://c.example", "x" * 1000])
def test_any_message_is_taken_as_it_is(client, admin, text):
    assert send(client, text=text).status_code == 202
    assert inbox(admin)["counts"]["inbox"] == 1


def test_older_apps_still_sending_a_challenge_are_fine(client):
    assert send(client, challenge="v1.x", nonce="123").status_code == 202


def test_nothing_identifying_is_stored(client, admin, feedback_store):
    assert send(client).status_code == 202
    with feedback_store._db() as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(feedback)")]
    assert not {"address", "ip", "device", "user", "contact"} & set(columns)
    assert "testclient" not in json.dumps(inbox(admin))


@pytest.mark.parametrize("text", ["", "   ", " ‮⁦ ", "x" * 1001])
def test_empty_or_too_long_text_is_refused(client, text):
    assert send(client, text=text).status_code == 400


def test_malformed_and_oversized_bodies_are_refused(client):
    assert client.post("/api/v1/feedback", content=b"{").status_code == 400
    assert send(client, kind="praise").status_code == 400
    assert client.post("/api/v1/feedback", content=b"x" * (9 * 1024)).status_code == 413
    assert client.get("/api/v1/feedback").status_code == 405
    assert client.get("/api/v1/feedback/challenge").status_code == 404


def test_text_is_cleaned_of_invisible_and_direction_tricks():
    assert normalize("‮abc‬ d\x00e​f  \n\n\n\ng") == "abc def\n\ng"
    assert normalize("می‌خواهم") == "می‌خواهم"  # ZWNJ is Persian spelling


def test_the_same_text_again_counts_as_a_repeat(client, admin):
    assert send(client, text="The app crashes on Snapp").status_code == 202
    assert send(client, text="the app CRASHES on snapp!!").status_code == 202
    items = inbox(admin)["items"]
    assert len(items) == 1 and items[0]["repeats"] == 1


def test_a_flood_from_one_address_is_cut_off(client, monkeypatch):
    monkeypatch.setattr(feedback, "ADDRESS_LIMITS", ((60, 2),))
    assert send(client, text="First message").status_code == 202
    assert send(client, text="Second message").status_code == 202
    refused = send(client, text="Third message")
    assert refused.status_code == 429 and refused.json() == {"detail": "rate"}
    assert 0 < int(refused.headers["retry-after"]) <= 60


def test_a_flood_from_everyone_together_is_cut_off_too(client, monkeypatch):
    monkeypatch.setattr(feedback, "GLOBAL_LIMITS", ((3600, 1),))
    assert send(client, text="First message").status_code == 202
    assert send(client, text="Second message").status_code == 429


def test_storage_is_bounded_and_keeps_unread_messages(client, admin, monkeypatch):
    monkeypatch.setattr(feedback, "MAX_STORED", 2)
    assert send(client, text="Junk to throw away").status_code == 202
    junk = inbox(admin)["items"][0]["id"]
    assert admin.patch(f"/admin/api/feedback/{junk}", json={"status": "spam"}).status_code == 200
    assert send(client, text="A real message to keep").status_code == 202
    assert send(client, text="Another real message").status_code == 202  # the spam made room
    assert inbox(admin, "spam")["counts"]["spam"] == 0
    full = send(client, text="No room for this one")
    assert full.status_code == 429 and full.json() == {"detail": "full"}


def test_the_feature_flag_turns_it_off(client, data_dir):
    catalog = json.loads((data_dir / "catalog.json").read_text())
    catalog["features"]["feedback"] = False
    (data_dir / "catalog.json").write_text(json.dumps(catalog))
    assert send(client).json() == {"detail": "disabled"}


def test_admins_triage_messages(client, admin):
    for text in ("First message here", "Second message here", "Third message here"):
        assert send(client, text=text).status_code == 202
    first, second, third = sorted(item["id"] for item in inbox(admin)["items"])
    assert admin.patch(f"/admin/api/feedback/{first}", json={"status": "archived"}).json()["status"] == "archived"
    assert admin.patch(f"/admin/api/feedback/{second}", json={"status": "spam"}).status_code == 200
    assert admin.post("/admin/api/feedback/read-all").json() == {"updated": 1}
    assert admin.get("/admin/api/feedback/counts").json() == {"unread": 0, "inbox": 1, "archived": 1, "spam": 1}
    assert admin.post("/admin/api/feedback/empty-spam").json() == {"deleted": 1}
    assert admin.delete(f"/admin/api/feedback/{third}").json() == {"ok": True}
    assert admin.delete(f"/admin/api/feedback/{third}").status_code == 404
    assert admin.patch(f"/admin/api/feedback/{first}", json={"status": "deleted"}).status_code == 422


def test_pages_go_newest_first(client, admin):
    for word in "one two three four five".split():
        assert send(client, text=f"Message number {word}").status_code == 202
    first = admin.get("/admin/api/feedback", params={"limit": 2}).json()
    second = admin.get("/admin/api/feedback", params={"limit": 2, "before": first["next"]}).json()
    last = admin.get("/admin/api/feedback", params={"limit": 2, "before": second["next"]}).json()
    ids = [i["id"] for page in (first, second, last) for i in page["items"]]
    assert ids == sorted(ids, reverse=True) and len(ids) == 5 and last["next"] is None


def test_the_dashboard_needs_a_signed_in_admin(client, admin):
    assert client.get("/admin/api/feedback").status_code == 401
    assert client.post("/admin/api/feedback/empty-spam").status_code == 401
    admin.headers.pop("X-Superapp-Admin")
    assert admin.post("/admin/api/feedback/read-all").status_code == 403


def test_feedback_calls_are_counted(client, admin):
    assert send(client).status_code == 202
    api = admin.get("/admin/api/stats", params={"days": 1}).json()["api"]
    assert {"endpoint": "feedback", "status": "2xx", "n": 1} in api
