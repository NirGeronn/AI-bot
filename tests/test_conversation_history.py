"""
Tests for conversation history: persistence, ordering, compaction, limits, and session management.
"""
import pytest
import json
import time

CHAT_ID = 111


@pytest.mark.asyncio
async def test_messages_persist_and_load_in_order(db):
    """Messages are stored and loaded in chronological order."""
    from memory import save_message, load_history

    await save_message(CHAT_ID, "user", "first")
    await save_message(CHAT_ID, "assistant", "second")
    await save_message(CHAT_ID, "user", "third")

    history = await load_history(CHAT_ID)
    assert len(history) == 3
    assert history[0]["content"] == "first"
    assert history[1]["content"] == "second"
    assert history[2]["content"] == "third"
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_load_history_limit(db):
    """load_history respects the limit parameter."""
    from memory import save_message, load_history

    for i in range(50):
        await save_message(CHAT_ID, "user", f"msg-{i}")

    history_10 = await load_history(CHAT_ID, limit=10)
    history_all = await load_history(CHAT_ID, limit=100)

    assert len(history_10) == 10
    assert len(history_all) == 50
    # The limited history should contain the most RECENT messages
    assert history_10[-1]["content"] == "msg-49"
    assert history_10[0]["content"] == "msg-40"


@pytest.mark.asyncio
async def test_json_content_roundtrip(db):
    """Content stored as JSON is correctly loaded back."""
    from memory import save_message, load_history

    # Anthropic-style content blocks
    content_blocks = [
        {"type": "text", "text": "Hello world"},
        {"type": "text", "text": "How are you?"},
    ]
    await save_message(CHAT_ID, "user", content_blocks)

    history = await load_history(CHAT_ID)
    assert len(history) == 1
    # Should be normalized to a single string
    assert "Hello world" in history[0]["content"]
    assert "How are you?" in history[0]["content"]


@pytest.mark.asyncio
async def test_non_string_content_normalized(db):
    """Non-string content (dict, list, number) is converted to string."""
    from memory import save_message, load_history

    await save_message(CHAT_ID, "assistant", {"key": "value"})

    history = await load_history(CHAT_ID)
    assert len(history) == 1
    assert isinstance(history[0]["content"], str)


@pytest.mark.asyncio
async def test_clear_history_removes_messages(db):
    """clear_history deletes all messages for that chat."""
    from memory import save_message, load_history, clear_history

    await save_message(CHAT_ID, "user", "hello")
    await save_message(CHAT_ID, "assistant", "hi")

    await clear_history(CHAT_ID)
    history = await load_history(CHAT_ID)
    assert len(history) == 0


@pytest.mark.asyncio
async def test_clear_history_preserves_memories(db):
    """clear_history does NOT delete stored memories."""
    from memory import save_message, clear_history, store_memory, get_all_memories

    await save_message(CHAT_ID, "user", "hello")
    await store_memory(CHAT_ID, "name", "Nir")

    await clear_history(CHAT_ID)
    memories = await get_all_memories(CHAT_ID)
    assert len(memories) == 1
    assert memories[0]["value"] == "Nir"


@pytest.mark.asyncio
async def test_clear_history_preserves_usage(db):
    """clear_history does NOT delete usage tracking data."""
    from memory import save_message, clear_history, record_usage, get_usage_stats

    await save_message(CHAT_ID, "user", "hello")
    await record_usage(CHAT_ID, 1000, 500, "claude-haiku-4-5-20251001")

    await clear_history(CHAT_ID)
    stats = await get_usage_stats(CHAT_ID)
    assert stats["total"]["requests"] == 1


@pytest.mark.asyncio
async def test_clear_history_preserves_daily_summaries(db):
    """clear_history does NOT delete daily summaries."""
    from memory import save_message, clear_history, save_daily_summary, get_recent_daily_summaries

    await save_message(CHAT_ID, "user", "hello")
    await save_daily_summary(CHAT_ID, "2026-04-19", "Discussed testing", 5)

    await clear_history(CHAT_ID)
    summaries = await get_recent_daily_summaries(CHAT_ID)
    assert len(summaries) == 1


@pytest.mark.asyncio
async def test_clear_history_preserves_owner_profile(db):
    """clear_history does NOT delete the owner profile."""
    from memory import save_message, clear_history, save_owner_profile, get_owner_profile

    await save_message(CHAT_ID, "user", "hello")
    await save_owner_profile(CHAT_ID, "A developer from Israel")

    await clear_history(CHAT_ID)
    profile = await get_owner_profile(CHAT_ID)
    assert "developer" in profile


@pytest.mark.asyncio
async def test_clear_history_preserves_bot_diary(db):
    """clear_history does NOT delete the bot diary."""
    from memory import save_message, clear_history, save_bot_diary, get_bot_diary

    await save_message(CHAT_ID, "user", "hello")
    await save_bot_diary(CHAT_ID, "1. Be concise")

    await clear_history(CHAT_ID)
    diary = await get_bot_diary(CHAT_ID)
    assert "concise" in diary


@pytest.mark.asyncio
async def test_today_conversations(db):
    """get_today_conversations returns only today's messages."""
    from memory import save_message, get_today_conversations
    import aiosqlite

    # Insert a message with today's timestamp
    await save_message(CHAT_ID, "user", "today's message")

    # Insert an old message directly (yesterday)
    old_ts = time.time() - 2 * 86400
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO conversations (chat_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (CHAT_ID, "user", "old message", old_ts),
        )
        await conn.commit()

    today = await get_today_conversations(CHAT_ID)
    assert len(today) == 1
    assert today[0]["content"] == "today's message"


@pytest.mark.asyncio
async def test_daily_summary_replaces_same_date(db):
    """Saving a daily summary for the same date replaces the previous one."""
    from memory import save_daily_summary, get_recent_daily_summaries

    await save_daily_summary(CHAT_ID, "2026-04-19", "First summary", 5)
    await save_daily_summary(CHAT_ID, "2026-04-19", "Updated summary", 8)

    summaries = await get_recent_daily_summaries(CHAT_ID)
    assert len(summaries) == 1
    assert summaries[0]["summary"] == "Updated summary"


@pytest.mark.asyncio
async def test_owner_profile_upsert(db):
    """Saving owner profile twice updates the existing one (not duplicates)."""
    from memory import save_owner_profile, get_owner_profile

    await save_owner_profile(CHAT_ID, "Version 1")
    await save_owner_profile(CHAT_ID, "Version 2")

    profile = await get_owner_profile(CHAT_ID)
    assert profile == "Version 2"


@pytest.mark.asyncio
async def test_store_memory_upsert(db):
    """Storing a memory with the same key updates the value."""
    from memory import store_memory, get_all_memories

    await store_memory(CHAT_ID, "city", "Tel Aviv")
    await store_memory(CHAT_ID, "city", "Jerusalem")

    memories = await get_all_memories(CHAT_ID)
    city_mems = [m for m in memories if m["key"] == "city"]
    assert len(city_mems) == 1
    assert city_mems[0]["value"] == "Jerusalem"


@pytest.mark.asyncio
async def test_recall_memories_search(db):
    """recall_memories searches both key and value fields."""
    from memory import store_memory, recall_memories

    await store_memory(CHAT_ID, "pet_name", "Rex the dog")
    await store_memory(CHAT_ID, "car", "Toyota Corolla")

    # Search by value content
    results = await recall_memories(CHAT_ID, "dog")
    assert len(results) == 1
    assert results[0]["key"] == "pet_name"

    # Search by key
    results = await recall_memories(CHAT_ID, "car")
    assert len(results) == 1
    assert results[0]["value"] == "Toyota Corolla"

    # No match
    results = await recall_memories(CHAT_ID, "bitcoin")
    assert len(results) == 0


@pytest.mark.asyncio
async def test_bot_diary_upsert(db):
    """Bot diary updates existing entry rather than creating duplicates."""
    from memory import save_bot_diary, get_bot_diary, get_all_memories

    await save_bot_diary(CHAT_ID, "Principle 1")
    await save_bot_diary(CHAT_ID, "Principle 1\nPrinciple 2")

    diary = await get_bot_diary(CHAT_ID)
    assert "Principle 2" in diary

    # Ensure there's only one __bot_diary__ entry
    memories = await get_all_memories(CHAT_ID)
    diary_entries = [m for m in memories if m["key"] == "__bot_diary__"]
    assert len(diary_entries) == 1
