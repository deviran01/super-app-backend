import hashlib
import json
import time

import pytest

import app.feedback as feedback
from app.feedback import leading_zero_bits, normalize

QUERY = {"platform": "android", "channel": "bazaar", "appVersion": 1}


def solve(challenge: str, difficulty: int) -> str:
    nonce = 0
    while leading_zero_bits(hashlib.sha256(f"{challenge}:{nonce}".encode()).digest()) < difficulty:
        nonce += 1
    return str(nonce)


def send(client, text="The map doesn't load after I sign in.", kind="problem", challenge=None, nonce=None, **extra):
    if challenge is None:
        issued = client.get("/api/v1/feedback/challenge", params=QUERY)
        assert issued.status_code == 200
        assert issued.headers["cache-control"] == "no-store"
        challenge = issued.json()["challenge"]
        nonce = solve(challenge, issued.json()["difficulty"])
    body = {"platform": "android", "channel": "bazaar", "appVersion": 1, "osVersion": 35, "kind": kind, "text": text, "challenge": challenge, "nonce": nonce, **extra}
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


def test_nothing_identifying_is_stored(client, admin, feedback_store):
    assert send(client).status_code == 202
    with feedback_store._db() as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(feedback)")]
    assert not {"address", "ip", "device", "user", "contact"} & set(columns)
    assert "testclient" not in json.dumps(inbox(admin))


def test_each_challenge_works_once_and_must_be_solved(client):
    issued = client.get("/api/v1/feedback/challenge", params=QUERY).json()
    nonce = solve(issued["challenge"], issued["difficulty"])
    assert send(client, challenge=issued["challenge"], nonce=nonce).status_code == 202
    assert send(client, text="Another message, same challenge", challenge=issued["challenge"], nonce=nonce).json() == {"detail": "challenge"}

    fresh = client.get("/api/v1/feedback/challenge", params=QUERY).json()
    wrong = next(str(n) for n in range(10_000) if leading_zero_bits(hashlib.sha256(f"{fresh['challenge']}:{n}".encode()).digest()) < fresh["difficulty"])
    assert send(client, challenge=fresh["challenge"], nonce=wrong).status_code == 409


def test_forged_and_expired_challenges_are_refused(client, feedback_store, monkeypatch):
    issued = client.get("/api/v1/feedback/challenge", params=QUERY).json()["challenge"]
    v, stamp, difficulty, rand, sig = issued.split(".")
    easier = f"{v}.{stamp}.0.{rand}.{sig}"  # signature no longer matches
    assert send(client, challenge=easier, nonce="0").status_code == 409
    assert send(client, challenge="v1.1.0.x.y", nonce="0").status_code == 409

    old = client.get("/api/v1/feedback/challenge", params=QUERY).json()
    nonce = solve(old["challenge"], old["difficulty"])
    later = time.time() + feedback.CHALLENGE_SECONDS + 5
    monkeypatch.setattr(feedback.time, "time", lambda: later)
    assert send(client, challenge=old["challenge"], nonce=nonce).status_code == 409


@pytest.mark.parametrize("text", ["short", "x" * 1001, " ‮‮   hi   ⁦ "])
def test_too_short_or_too_long_text_is_refused(client, text):
    assert send(client, text=text).status_code == 400


def test_malformed_and_oversized_bodies_are_refused(client):
    assert client.post("/api/v1/feedback", content=b"{").status_code == 400
    assert send(client, kind="praise").status_code == 400
    challenge = client.get("/api/v1/feedback/challenge", params=QUERY).json()["challenge"]
    assert send(client, challenge=challenge, nonce="12a").status_code == 400
    assert client.post("/api/v1/feedback", content=b"x" * (9 * 1024)).status_code == 413
    assert client.get("/api/v1/feedback").status_code == 405


def test_text_is_cleaned_of_invisible_and_direction_tricks():
    assert normalize("‮abc‬ d\x00e​f  \n\n\n\ng") == "abc def\n\ng"
    assert normalize("می‌خواهم") == "می‌خواهم"  # ZWNJ is Persian spelling


@pytest.mark.parametrize("text, reason", [
    ("Buy now https://a.example http://b.example www.c.example", "links"),
    ("Join t.me/spamchannel and @spammer_bot and promo.xyz today", "links"),
    ("Great app!!!!!!!!!!!!!!!!!!!!!!!!!", "repeated"),
    ("$$$ 1234567890 %%% ### 0987654321", "symbols"),
])
def test_spam_goes_to_the_spam_folder_without_telling_the_sender(client, admin, text, reason):
    assert send(client, text=text).status_code == 202
    assert inbox(admin)["counts"]["inbox"] == 0
    spam = inbox(admin, "spam")["items"]
    assert [(item["status"], item["spamReason"]) for item in spam] == [("spam", reason)]


def test_an_ordinary_persian_message_with_one_link_is_not_spam(client, admin):
    assert send(client, text="سلام، لطفاً دیجی‌کالا را هم اضافه کنید: digikala.com ممنون 🙏").status_code == 202
    assert inbox(admin)["counts"] == {"unread": 1, "inbox": 1, "archived": 0, "spam": 0}


def test_the_same_text_again_counts_as_a_repeat(client, admin):
    assert send(client, text="The app crashes on Snapp").status_code == 202
    assert send(client, text="the app CRASHES on snapp!!").status_code == 202
    items = inbox(admin)["items"]
    assert len(items) == 1 and items[0]["repeats"] == 1


def test_one_address_can_only_send_a_few(client, monkeypatch):
    monkeypatch.setattr(feedback, "ADDRESS_LIMITS", ((600, 2),))
    assert send(client, text="First message here").status_code == 202
    assert send(client, text="Second message here").status_code == 202
    refused = send(client, text="Third message here")
    assert refused.status_code == 429 and refused.json() == {"detail": "rate"}
    assert 0 < int(refused.headers["retry-after"]) <= 600


def test_everyone_together_is_capped_too(client, monkeypatch):
    monkeypatch.setattr(feedback, "GLOBAL_LIMITS", ((3600, 1),))
    assert send(client, text="First message here").status_code == 202
    assert send(client, text="Second message here").status_code == 429


def test_difficulty_rises_with_volume():
    assert feedback.difficulty_for(0) == feedback.BASE_DIFFICULTY
    assert feedback.difficulty_for(10_000) == feedback.BASE_DIFFICULTY + len(feedback.DIFFICULTY_STEPS)


def test_storage_is_bounded_and_keeps_unread_messages(client, admin, monkeypatch):
    monkeypatch.setattr(feedback, "MAX_STORED", 2)
    assert send(client, text="Spam spam https://a.io https://b.io https://c.io").status_code == 202
    assert send(client, text="A real message to keep").status_code == 202
    assert send(client, text="Another real message").status_code == 202  # the spam made room
    assert inbox(admin, "spam")["counts"]["spam"] == 0
    full = send(client, text="No room for this one")
    assert full.status_code == 429 and full.json() == {"detail": "full"}


def test_the_feature_flag_turns_it_off(client, data_dir):
    catalog = json.loads((data_dir / "catalog.json").read_text())
    catalog["features"]["feedback"] = False
    (data_dir / "catalog.json").write_text(json.dumps(catalog))
    assert client.get("/api/v1/feedback/challenge", params=QUERY).json() == {"detail": "disabled"}
    assert client.post("/api/v1/feedback", json={}).status_code == 403


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
    for n in range(5):
        assert send(client, text=f"Message number {'one two three four five'.split()[n]}").status_code == 202
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
