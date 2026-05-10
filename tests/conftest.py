"""
Shared fixtures for bot tests.
Each test gets a fresh in-memory SQLite database to avoid cross-test contamination.
"""
from __future__ import annotations

import os
import sys
import pytest

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Override env vars BEFORE importing any project modules
os.environ.setdefault("TELEGRAM_TOKEN", "fake-token")
os.environ.setdefault("OWNER_CHAT_ID", "111")
os.environ.setdefault("AI_PROVIDER", "anthropic")
os.environ.setdefault("ANTHROPIC_API_KEY", "fake-key")
os.environ.setdefault("BOT_OWNER_NAME", "TestUser")
os.environ.setdefault("BOT_LANGUAGE", "English")
os.environ.setdefault("USER_TIMEZONE", "UTC")


@pytest.fixture
def tmp_db(tmp_path):
    """Provide a temporary DB path and patch config.DB_PATH to use it."""
    db_path = str(tmp_path / "test_agent.db")
    import config
    original = config.DB_PATH
    config.DB_PATH = db_path

    # Also patch memory module's reference
    import memory
    memory.DB_PATH = db_path

    yield db_path

    config.DB_PATH = original
    memory.DB_PATH = original


@pytest.fixture
async def db(tmp_db):
    """Initialize the DB schema and return the path. Use this for async tests."""
    import memory
    await memory.init_db()
    return tmp_db
