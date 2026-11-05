"""Every test that touches the database gets its own fresh SQLite file and upload folder."""
import pytest

from core import config, seed


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("VG_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("LLM_PROVIDER", "offline")  # tests never call a paid API
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    seed.ensure_ready(with_history=False)
    return tmp_path
