import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.admin.auth import AdminAccounts
from app.content import ContentStore
from app.stats import StatsStore, today

ROOT = Path(__file__).resolve().parent.parent
QUERY = {"platform": "android", "channel": "bazaar", "appVersion": 1}
HEADERS = {"X-Superapp-Admin": "1"}
PASSWORD = "correct horse battery"


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    for name in ("catalog.json", "release.json"):
        shutil.copy(ROOT / "data" / name, data / name)
    monkeypatch.setattr(main, "store", ContentStore(data))
    return data


@pytest.fixture
def client(data_dir) -> TestClient:
    return TestClient(main.app)


@pytest.fixture
def admin(data_dir) -> TestClient:
    main.app.state.admin_accounts = AdminAccounts(data_dir / "admin")
    main.app.state.admin_accounts.create("ali", PASSWORD, created_by="test")
    client = TestClient(main.app, base_url="https://testserver", headers=HEADERS)
    assert client.post("/admin/api/session", json={"username": "ali", "password": PASSWORD}).status_code == 200
    return client


def report(*counts, day=None, channel="bazaar", version=1):
    return {
        "platform": "android",
        "channel": channel,
        "appVersion": version,
        "days": [{"day": day or today().isoformat(), "counts": [{"event": e, "dims": list(d), "n": n} for e, d, n in counts]}],
    }


def test_the_app_reports_daily_totals_that_the_dashboard_sums_up(client, stats):
    for _ in range(2):
        assert client.post("/api/v1/events", json=report(
            ("app_opened", (), 3), ("active_day", (), 1), ("first_open", (), 1),
            ("service_opened", ("snapp", "home"), 4), ("service_opened", ("digikala", "search"), 1),
            ("favorite_added", ("snapp",), 1), ("category_opened", ("transport",), 2),
            ("search_used", ("none",), 1), ("search_used", ("found",), 3),
            ("service_load_failed", ("snapp", "timeout"), 2), ("update_clicked", (), 1),
        )).status_code == 204

    summary = stats.summary(7)
    totals = summary["totals"]
    assert totals["activeToday"] == 2 and totals["installs"] == 2 and totals["appOpens"] == 6
    assert totals["serviceOpens"] == 10 and totals["searches"] == 8 and totals["searchesWithoutResults"] == 2
    assert totals["loadFailures"] == 4 and totals["updateClicks"] == 2
    snapp = next(s for s in summary["services"] if s["id"] == "snapp")
    assert snapp["opens"] == 8 and snapp["favoritesAdded"] == 2 and snapp["failures"] == 4
    assert summary["services"][0]["id"] == "snapp"
    assert {"source": "home", "n": 8} in summary["sources"]
    assert summary["categories"] == [{"id": "transport", "n": 4}]
    assert summary["failures"] == [{"service": "snapp", "error": "timeout", "n": 4}]
    assert summary["daily"][-1]["activeUsers"] == 2 and len(summary["daily"]) == 7


def test_only_known_events_ids_and_values_are_kept_and_counts_are_capped(client, stats):
    yesterday = (today() - timedelta(days=1)).isoformat()
    body = report(
        ("active_day", (), 50),                         # one per install per day
        ("service_opened", ("not-a-service", "home"), 5),
        ("service_opened", ("snapp", "https://x"), 5),  # never a URL
        ("search_used", ("pizza",), 1),                 # never a query
        ("something_new", (), 9),
        ("app_opened", ("extra",), 1),                  # wrong number of dimensions
        channel="custom-build", version=999_999,
    )
    body["days"].append({"day": "2001-01-01", "counts": [{"event": "app_opened", "dims": [], "n": 1}]})
    body["days"].append({"day": yesterday, "counts": [{"event": "app_opened", "dims": [], "n": 1}]})
    assert client.post("/api/v1/events", json=body).status_code == 204

    summary = stats.summary(30)
    assert summary["totals"]["activeToday"] == 1
    assert summary["totals"]["serviceOpens"] == 0 and summary["totals"]["searches"] == 0
    assert summary["totals"]["appOpens"] == 1  # yesterday's; 2001 is outside the window
    # The report itself is an API call, counted under the same unknown channel.
    assert summary["channels"] == [{"channel": "other", "apiCalls": 1, "activeUsers": 1, "installs": 0}]
    assert summary["versions"][0]["version"] == 0  # unknown versions are bucketed


def test_reports_are_validated(client):
    assert client.post("/api/v1/events", content=b"{not json", headers={"Content-Type": "application/json"}).status_code == 400
    assert client.post("/api/v1/events", json={**report(), "appVersion": -1}).status_code == 400
    too_big = report(*[("app_opened", (), 1)] * 400)
    too_big["days"] *= 8
    too_big["padding"] = "x" * 70_000
    assert client.post("/api/v1/events", json=too_big).status_code == 413
    assert client.get("/api/v1/events").status_code == 405


def test_every_api_call_is_counted_by_endpoint_status_channel_and_version(client, stats):
    first = client.get("/api/v1/config", params=QUERY)
    client.get("/api/v1/config", params=QUERY, headers={"If-None-Match": first.headers["etag"]})
    client.get("/api/v1/app/version", params={**QUERY, "channel": "myket"})
    client.get("/api/v1/app/version", params={**QUERY, "appVersion": "abc"})  # 422
    client.post("/api/v1/events", json=report(channel="myket", version=2))

    summary = stats.summary(1)
    assert summary["totals"]["apiCalls"] == 5
    assert summary["totals"]["apiNotModified"] == 1 and summary["totals"]["apiErrors"] == 1
    calls = {(row["endpoint"], row["status"]): row["n"] for row in summary["api"]}
    assert calls == {("config", "2xx"): 1, ("config", "304"): 1, ("version", "2xx"): 1, ("version", "4xx"): 1, ("events", "2xx"): 1}
    channels = {row["channel"]: row["apiCalls"] for row in summary["channels"]}
    assert channels == {"bazaar": 3, "myket": 2}
    assert {row["version"]: row["apiCalls"] for row in summary["versions"]} == {1: 3, 0: 1, 2: 1}
    assert stats.summary(1, channel="myket")["totals"]["apiCalls"] == 2
    # Nothing else about the caller is kept.
    assert summary["daily"][-1]["apiCalls"] == 5


def test_counts_survive_a_restart(client, stats, tmp_path):
    client.post("/api/v1/events", json=report(("app_opened", (), 2)))
    stats.flush()
    reopened = StatsStore(tmp_path / "stats" / "stats.db")
    assert reopened.summary(1)["totals"]["appOpens"] == 2


def test_down_scenario_refuses_reports(data_dir, monkeypatch):
    monkeypatch.setattr(main, "store", ContentStore(data_dir, ["down"]))
    assert TestClient(main.app).post("/api/v1/events", json=report()).status_code == 503


def test_the_dashboard_reads_statistics_signed_in_only(client, admin):
    client.post("/api/v1/events", json=report(("active_day", (), 1)))
    assert TestClient(main.app, base_url="https://testserver", headers=HEADERS).get("/admin/api/stats").status_code == 401
    response = admin.get("/admin/api/stats", params={"days": 7, "channel": "bazaar"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["totals"]["activeToday"] == 1
    assert admin.get("/admin/api/stats", params={"days": 0}).status_code == 422


def test_one_report_counts_one_install_however_it_repeats_itself(client, stats):
    body = report(*[("active_day", (), 1)] * 50, ("first_open", (), 3))
    body["days"] += [dict(body["days"][0]) for _ in range(5)]  # the same day again
    assert client.post("/api/v1/events", json=body).status_code == 204
    totals = stats.summary(1)["totals"]
    assert totals["activeToday"] == 1 and totals["installs"] == 1


def test_app_events_are_stored_without_the_version_except_users_and_installs(client, stats, tmp_path):
    import sqlite3

    client.post("/api/v1/events", json=report(("active_day", (), 1), ("service_opened", ("snapp", "home"), 2), version=1))
    stats.flush()
    rows = dict(sqlite3.connect(tmp_path / "stats" / "stats.db").execute("SELECT event, version FROM counts WHERE source = 'app'").fetchall())
    assert rows == {"active_day": 1, "service_opened": 0}


def test_a_long_report_is_trimmed_not_refused(client, stats):
    many = report(*[("service_opened", ("snapp", source), 1) for source in ("home", "search")] * 300)
    assert client.post("/api/v1/events", json=many).status_code == 204
    assert stats.summary(1)["totals"]["serviceOpens"] == 600


def test_a_missing_data_file_keeps_the_last_content(client, data_dir):
    assert client.get("/api/v1/config", params=QUERY).status_code == 200
    (data_dir / "catalog.json").unlink()
    assert client.get("/api/v1/config", params=QUERY).status_code == 200
