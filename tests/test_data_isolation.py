"""
Tests for data isolation between different chat_ids (users/bot instances).
Ensures that one user's data never leaks to another.
"""
import pytest
import time

# Two simulated users
USER_A = 111
USER_B = 222


@pytest.mark.asyncio
async def test_conversation_history_isolated(db):
    """Messages saved for user A must NOT appear in user B's history."""
    from memory import save_message, load_history

    await save_message(USER_A, "user", "Hello from A")
    await save_message(USER_A, "assistant", "Hi A!")
    await save_message(USER_B, "user", "Hello from B")
    await save_message(USER_B, "assistant", "Hi B!")

    history_a = await load_history(USER_A)
    history_b = await load_history(USER_B)

    # Each user sees only their own messages
    assert len(history_a) == 2
    assert len(history_b) == 2
    assert all("A" in m["content"] for m in history_a)
    assert all("B" in m["content"] for m in history_b)


@pytest.mark.asyncio
async def test_memories_isolated(db):
    """Stored memories are scoped per chat_id."""
    from memory import store_memory, get_all_memories, recall_memories

    await store_memory(USER_A, "favorite_food", "pizza")
    await store_memory(USER_B, "favorite_food", "sushi")
    await store_memory(USER_A, "pet", "dog named Rex")

    mems_a = await get_all_memories(USER_A)
    mems_b = await get_all_memories(USER_B)

    assert len(mems_a) == 2
    assert len(mems_b) == 1

    # Recall should only return this user's data
    results_a = await recall_memories(USER_A, "food")
    results_b = await recall_memories(USER_B, "food")
    assert any("pizza" in r["value"] for r in results_a)
    assert not any("pizza" in r["value"] for r in results_b)
    assert any("sushi" in r["value"] for r in results_b)


@pytest.mark.asyncio
async def test_delete_memory_isolated(db):
    """Deleting a memory for one user doesn't affect the other."""
    from memory import store_memory, delete_memory, get_all_memories

    await store_memory(USER_A, "color", "blue")
    await store_memory(USER_B, "color", "red")

    await delete_memory(USER_A, "color")

    mems_a = await get_all_memories(USER_A)
    mems_b = await get_all_memories(USER_B)

    assert len(mems_a) == 0
    assert len(mems_b) == 1
    assert mems_b[0]["value"] == "red"


@pytest.mark.asyncio
async def test_usage_tracking_isolated(db):
    """Usage stats are per-user."""
    from memory import record_usage, get_usage_stats

    await record_usage(USER_A, 1000, 500, "claude-haiku-4-5-20251001")
    await record_usage(USER_A, 2000, 1000, "claude-haiku-4-5-20251001")
    await record_usage(USER_B, 500, 200, "claude-haiku-4-5-20251001")

    stats_a = await get_usage_stats(USER_A)
    stats_b = await get_usage_stats(USER_B)

    assert stats_a["total"]["input_tokens"] == 3000
    assert stats_a["total"]["output_tokens"] == 1500
    assert stats_a["total"]["requests"] == 2

    assert stats_b["total"]["input_tokens"] == 500
    assert stats_b["total"]["output_tokens"] == 200
    assert stats_b["total"]["requests"] == 1


@pytest.mark.asyncio
async def test_daily_summaries_isolated(db):
    """Daily summaries are scoped per chat_id."""
    from memory import save_daily_summary, get_recent_daily_summaries

    await save_daily_summary(USER_A, "2026-04-19", "A talked about work", 10)
    await save_daily_summary(USER_B, "2026-04-19", "B talked about cooking", 5)

    sums_a = await get_recent_daily_summaries(USER_A)
    sums_b = await get_recent_daily_summaries(USER_B)

    assert len(sums_a) == 1
    assert "work" in sums_a[0]["summary"]
    assert len(sums_b) == 1
    assert "cooking" in sums_b[0]["summary"]


@pytest.mark.asyncio
async def test_owner_profile_isolated(db):
    """Owner profiles are scoped per chat_id."""
    from memory import save_owner_profile, get_owner_profile

    await save_owner_profile(USER_A, "Nir is a developer")
    await save_owner_profile(USER_B, "Nehoray is a designer")

    profile_a = await get_owner_profile(USER_A)
    profile_b = await get_owner_profile(USER_B)

    assert "Nir" in profile_a
    assert "Nehoray" in profile_b
    assert "Nehoray" not in profile_a
    assert "Nir" not in profile_b


@pytest.mark.asyncio
async def test_bot_diary_isolated(db):
    """Bot diary (behavioral principles) is per-user."""
    from memory import save_bot_diary, get_bot_diary

    await save_bot_diary(USER_A, "1. Always respond in Hebrew for user A")
    await save_bot_diary(USER_B, "1. User B prefers English")

    diary_a = await get_bot_diary(USER_A)
    diary_b = await get_bot_diary(USER_B)

    assert "Hebrew" in diary_a
    assert "English" in diary_b
    assert "English" not in diary_a
    assert "Hebrew" not in diary_b


@pytest.mark.asyncio
async def test_clear_history_isolated(db):
    """Clearing history for one user doesn't affect the other."""
    from memory import save_message, load_history, clear_history

    await save_message(USER_A, "user", "msg from A")
    await save_message(USER_B, "user", "msg from B")

    await clear_history(USER_A)

    history_a = await load_history(USER_A)
    history_b = await load_history(USER_B)

    assert len(history_a) == 0
    assert len(history_b) == 1


@pytest.mark.asyncio
async def test_usage_cost_isolated(db):
    """Cost calculation is per-user."""
    from memory import record_usage, get_usage_cost_since

    now = time.time()
    await record_usage(USER_A, 10000, 5000, "claude-haiku-4-5-20251001")
    await record_usage(USER_B, 1000, 500, "claude-haiku-4-5-20251001")

    cost_a = await get_usage_cost_since(USER_A, now - 10)
    cost_b = await get_usage_cost_since(USER_B, now - 10)

    assert cost_a > cost_b
    # User B shouldn't be charged for user A's tokens
    assert cost_b < cost_a / 5
