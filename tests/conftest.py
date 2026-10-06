import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.feedback as feedback
import app.main as main
from app.admin.auth import AdminAccounts
from app.content import ContentStore
from app.feedback import FeedbackStore
from app.stats import StatsStore

ROOT = Path(__file__).resolve().parent.parent
HEADERS = {"X-Superapp-Admin": "1"}
PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def stats(tmp_path: Path) -> StatsStore:
    """Every test counts into its own database, never into the checkout's data/."""
    store = StatsStore(tmp_path / "stats" / "stats.db")
    main.app.state.stats = store
    return store


@pytest.fixture(autouse=True)
def feedback_store(tmp_path: Path, monkeypatch) -> FeedbackStore:
    """Feedback too, with an easy proof of work so tests stay fast."""
    monkeypatch.setattr(feedback, "BASE_DIFFICULTY", 8)
    store = FeedbackStore(tmp_path / "feedback" / "feedback.db", secret=b"test-secret")
    main.app.state.feedback = store
    return store


# The checkout's content in a temporary data/, the public API and a signed-in admin
# (test_api.py and test_admin.py define their own).


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
