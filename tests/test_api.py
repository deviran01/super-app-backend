import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.content import ContentError, ContentStore

ROOT = Path(__file__).resolve().parent.parent
QUERY = {"platform": "android", "channel": "bazaar", "appVersion": 1}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    for name in ("catalog.json", "release.json"):
        shutil.copy(ROOT / "data" / name, tmp_path / name)
    return tmp_path


@pytest.fixture
def client(data_dir: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(main, "store", ContentStore(data_dir))
    return TestClient(main.app)


def replace_file(path: Path, text: str) -> None:
    """Writes like a deploy does (rsync): a new file renamed over the old one."""
    temp = path.with_suffix(".tmp")
    temp.write_text(text)
    temp.replace(path)


def use_scenarios(monkeypatch, data_dir: Path, *names: str) -> None:
    monkeypatch.setattr(main, "store", ContentStore(data_dir, list(names)))


def test_config_returns_the_catalog_with_an_absolute_image_base(client):
    response = client.get("/api/v1/config", params=QUERY)
    assert response.status_code == 200
    body = response.json()
    assert body["schemaVersion"] == 1 and len(body["services"]) > 20
    assert body["assetsBaseUrl"] == "http://testserver/"
    assert "app" not in body  # the update policy has its own endpoint
    assert response.headers["cache-control"] == "no-cache"


def test_unchanged_documents_revalidate_with_304(client):
    first = client.get("/api/v1/config", params=QUERY)
    again = client.get("/api/v1/config", params=QUERY, headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    weak = client.get("/api/v1/app/version", params=QUERY)
    assert client.get("/api/v1/app/version", params=QUERY, headers={"If-None-Match": "W/" + weak.headers["etag"]}).status_code == 304


def test_each_store_gets_its_own_update_link(client):
    bazaar = client.get("/api/v1/app/version", params=QUERY).json()
    myket = client.get("/api/v1/app/version", params={**QUERY, "channel": "myket"}).json()
    direct = client.get("/api/v1/app/version", params={**QUERY, "channel": "direct"}).json()
    assert bazaar["updateUrl"] == "https://cafebazaar.ir/app/io.celin.super.app"
    assert myket["updateUrl"] == "https://myket.ir/app/io.celin.super.app"
    assert "updateUrl" not in direct
    assert bazaar["update"] == "NONE" and bazaar["minimumSupportedVersion"] == 1


def test_version_policy_per_store(data_dir, monkeypatch):
    release = json.loads((data_dir / "release.json").read_text())
    release["default"].update(minimumSupportedVersion=12, latestVersion=15)
    release["channels"]["bazaar"].update(minimumSupportedVersion=14, latestVersion=16)
    release["channels"]["myket"] = {"updateUrl": "https://myket.ir/app/io.celin.super.app", "forceUpdate": True}
    replace_file(data_dir / "release.json", json.dumps(release))
    client = TestClient(main.app)
    monkeypatch.setattr(main, "store", ContentStore(data_dir))

    def status(channel, version):
        return client.get("/api/v1/app/version", params={"channel": channel, "appVersion": version}).json()["update"]

    assert [status("bazaar", v) for v in (13, 15, 16)] == ["REQUIRED", "OPTIONAL", "NONE"]
    assert [status("direct", v) for v in (11, 12, 15)] == ["REQUIRED", "OPTIONAL", "NONE"]
    assert status("myket", 14) == "REQUIRED"  # forceUpdate raises the minimum to latest (15)


def test_bad_parameters_are_rejected(client):
    assert client.get("/api/v1/app/version", params={"channel": "../../etc"}).status_code == 422
    assert client.get("/api/v1/app/version", params={"appVersion": -1}).status_code == 422
    assert client.post("/api/v1/config").status_code == 405


def test_edited_files_are_served_without_a_restart_and_broken_ones_are_not(client, data_dir):
    release = json.loads((data_dir / "release.json").read_text())
    release["channels"]["bazaar"]["latestVersion"] = 2
    replace_file(data_dir / "release.json", json.dumps(release))
    assert client.get("/api/v1/app/version", params=QUERY).json()["update"] == "OPTIONAL"

    replace_file(data_dir / "release.json", '{"default": ')  # a broken upload
    response = client.get("/api/v1/app/version", params=QUERY)
    assert response.status_code == 200 and response.json()["latestVersion"] == 2


def test_unusable_content_fails_at_startup(data_dir):
    (data_dir / "release.json").write_text('{"default": {"minimumSupportedVersion": "1"}}')
    with pytest.raises(ContentError):
        ContentStore(data_dir)


def test_images_are_served_with_long_caching(client):
    response = client.get("/logos/snapp.png")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=604800"
    assert client.get("/logos/../data/release.json").status_code == 404


def test_qa_scenarios(data_dir, monkeypatch):
    client = TestClient(main.app)
    use_scenarios(monkeypatch, data_dir, "force-update")
    assert client.get("/api/v1/app/version", params=QUERY).json()["update"] == "REQUIRED"
    use_scenarios(monkeypatch, data_dir, "bazaar-ahead")
    assert client.get("/api/v1/app/version", params=QUERY).json()["update"] == "OPTIONAL"
    assert client.get("/api/v1/app/version", params={**QUERY, "channel": "myket"}).json()["update"] == "NONE"
    use_scenarios(monkeypatch, data_dir, "lab", "maintenance")
    services = {s["id"]: s for s in client.get("/api/v1/config").json()["services"]}
    assert "lab" in services and "maintenance" in services["tapsi"]
    use_scenarios(monkeypatch, data_dir, "down")
    assert client.get("/api/v1/config").status_code == 503


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
