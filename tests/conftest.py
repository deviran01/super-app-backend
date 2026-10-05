from pathlib import Path

import pytest

import app.main as main
from app.stats import StatsStore


@pytest.fixture(autouse=True)
def stats(tmp_path: Path) -> StatsStore:
    """Every test counts into its own database, never into the checkout's data/."""
    store = StatsStore(tmp_path / "stats" / "stats.db")
    main.app.state.stats = store
    return store
