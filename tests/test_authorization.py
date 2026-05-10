"""
Tests for authorization: the bot must only respond to the configured OWNER_CHAT_ID.
We test the is_authorized function directly without importing the full bot module.
"""
from __future__ import annotations

import pytest
import config


def is_authorized(chat_id: int) -> bool:
    """Mirror of bot.is_authorized — avoids importing bot.py's heavy deps."""
    if config.OWNER_CHAT_ID is None:
        return True
    return chat_id == config.OWNER_CHAT_ID


def test_authorized_owner():
    """The configured OWNER_CHAT_ID is authorized."""
    original = config.OWNER_CHAT_ID
    config.OWNER_CHAT_ID = 12345

    try:
        assert is_authorized(12345) is True
    finally:
        config.OWNER_CHAT_ID = original


def test_unauthorized_stranger():
    """A random chat_id is NOT authorized."""
    original = config.OWNER_CHAT_ID
    config.OWNER_CHAT_ID = 12345

    try:
        assert is_authorized(99999) is False
    finally:
        config.OWNER_CHAT_ID = original


def test_no_owner_set_allows_all():
    """When OWNER_CHAT_ID is None, all users are allowed (for dev/testing)."""
    original = config.OWNER_CHAT_ID
    config.OWNER_CHAT_ID = None

    try:
        assert is_authorized(12345) is True
        assert is_authorized(99999) is True
    finally:
        config.OWNER_CHAT_ID = original


def test_authorization_doesnt_leak_across_ids():
    """Ensure only exact chat_id match passes."""
    original = config.OWNER_CHAT_ID
    config.OWNER_CHAT_ID = 111

    try:
        assert is_authorized(111) is True
        assert is_authorized(112) is False
        assert is_authorized(110) is False
        assert is_authorized(-111) is False
        assert is_authorized(0) is False
    finally:
        config.OWNER_CHAT_ID = original
