"""
Tests for heartbeat and pulse systems — DB layer and logic checks.
"""
import pytest
import time

CHAT_ID = 111


@pytest.fixture
async def heartbeat_db(tmp_db):
    """Initialize heartbeat and pulse tables."""
    import memory
    await memory.init_db()

    import heartbeat
    original_hb_db = heartbeat.DB_PATH
    heartbeat.DB_PATH = tmp_db
    await heartbeat._ensure_heartbeat_table()

    import pulse
    original_pulse_db = pulse.DB_PATH
    pulse.DB_PATH = tmp_db
    await pulse._ensure_pulse_table()

    yield tmp_db

    heartbeat.DB_PATH = original_hb_db
    pulse.DB_PATH = original_pulse_db


# ── Heartbeat tests ──

@pytest.mark.asyncio
async def test_heartbeat_last_run_default_zero(heartbeat_db):
    """First call to _last_run_time returns 0 (never ran)."""
    from heartbeat import _last_run_time
    last = await _last_run_time(CHAT_ID, "inbox_check")
    assert last == 0


@pytest.mark.asyncio
async def test_heartbeat_record_and_retrieve(heartbeat_db):
    """Recording a heartbeat updates _last_run_time."""
    from heartbeat import _record_heartbeat, _last_run_time

    before = time.time()
    await _record_heartbeat(CHAT_ID, "calendar_check", "HEARTBEAT_OK")
    last = await _last_run_time(CHAT_ID, "calendar_check")

    assert last >= before
    assert last <= time.time()


@pytest.mark.asyncio
async def test_heartbeat_isolated_between_users(heartbeat_db):
    """Heartbeat logs for one user don't affect another."""
    from heartbeat import _record_heartbeat, _last_run_time

    await _record_heartbeat(111, "inbox_check", "New email from boss")
    await _record_heartbeat(222, "inbox_check", "HEARTBEAT_OK")

    last_111 = await _last_run_time(111, "inbox_check")
    last_222 = await _last_run_time(222, "inbox_check")

    # Both should have ran, but independently
    assert last_111 > 0
    assert last_222 > 0


@pytest.mark.asyncio
async def test_heartbeat_different_orders_independent(heartbeat_db):
    """Different standing orders have independent last-run times."""
    from heartbeat import _record_heartbeat, _last_run_time

    await _record_heartbeat(CHAT_ID, "inbox_check", "OK")
    # Don't record calendar_check

    inbox_last = await _last_run_time(CHAT_ID, "inbox_check")
    calendar_last = await _last_run_time(CHAT_ID, "calendar_check")

    assert inbox_last > 0
    assert calendar_last == 0


# ── Pulse tests ──

@pytest.mark.asyncio
async def test_pulse_cooldown_respected(heartbeat_db):
    """should_pulse returns False if last pulse was recent."""
    from pulse import should_pulse, _record_pulse
    from memory import save_message

    # Need a recent message so "active conversation" check doesn't block for wrong reason
    await save_message(CHAT_ID, "user", "test")

    # Record a recent pulse
    await _record_pulse(CHAT_ID, "Test pulse", 0.8)

    # Should be blocked by cooldown
    result = await should_pulse(CHAT_ID)
    assert result is False


@pytest.mark.asyncio
async def test_pulse_active_conversation_blocks(heartbeat_db):
    """should_pulse returns False during an active conversation."""
    from pulse import should_pulse
    from memory import save_message

    # Save a message just now — simulates active conversation
    await save_message(CHAT_ID, "user", "I'm chatting right now")

    result = await should_pulse(CHAT_ID)
    assert result is False


@pytest.mark.asyncio
async def test_pulse_suppression(heartbeat_db):
    """Suppressed topics are correctly recorded and retrieved."""
    from pulse import suppress_topic, _get_suppressed_topics

    await suppress_topic(CHAT_ID, "fitness_reminder")

    suppressed = await _get_suppressed_topics(CHAT_ID)
    assert "fitness_reminder" in suppressed


@pytest.mark.asyncio
async def test_pulse_suppression_escalation(heartbeat_db):
    """Declining the same topic multiple times escalates cooldown."""
    from pulse import suppress_topic, _get_suppressed_topics
    import aiosqlite

    await suppress_topic(CHAT_ID, "morning_greeting")
    await suppress_topic(CHAT_ID, "morning_greeting")  # 2nd decline
    await suppress_topic(CHAT_ID, "morning_greeting")  # 3rd decline

    # Check the decline count in DB
    async with aiosqlite.connect(heartbeat_db) as conn:
        cursor = await conn.execute(
            "SELECT decline_count, cooldown_until FROM pulse_suppression WHERE chat_id = ? AND topic = ?",
            (CHAT_ID, "morning_greeting"),
        )
        row = await cursor.fetchone()

    assert row is not None
    count, cooldown_until = row
    assert count == 3
    # 3 declines = 30-day cooldown
    assert cooldown_until > time.time() + 29 * 86400


@pytest.mark.asyncio
async def test_pulse_suppression_isolated(heartbeat_db):
    """Suppressed topics are per-user."""
    from pulse import suppress_topic, _get_suppressed_topics

    await suppress_topic(111, "weather_tips")
    await suppress_topic(222, "fitness_reminder")

    suppressed_111 = await _get_suppressed_topics(111)
    suppressed_222 = await _get_suppressed_topics(222)

    assert "weather_tips" in suppressed_111
    assert "weather_tips" not in suppressed_222
    assert "fitness_reminder" in suppressed_222
    assert "fitness_reminder" not in suppressed_111
