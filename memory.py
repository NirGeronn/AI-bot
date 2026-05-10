from __future__ import annotations

import json
import time
import aiosqlite
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                model TEXT NOT NULL,
                timestamp REAL NOT NULL,
                cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
                cache_read_tokens INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS daily_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                summary TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS owner_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                profile TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_conv_chat ON conversations(chat_id);
            CREATE INDEX IF NOT EXISTS idx_mem_chat ON memories(chat_id);
            CREATE INDEX IF NOT EXISTS idx_usage_chat ON usage(chat_id);
        """)
        # Migration: add cache columns to existing usage tables
        for col in ("cache_creation_tokens", "cache_read_tokens"):
            try:
                await db.execute(f"ALTER TABLE usage ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass
        await db.executescript("""
            CREATE INDEX IF NOT EXISTS idx_daily_chat_date ON daily_summaries(chat_id, date);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_owner_chat ON owner_profile(chat_id);
        """)
        await db.commit()


async def save_message(chat_id: int, role: str, content):
    if not isinstance(content, str):
        content = json.dumps(content, default=str)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO conversations (chat_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (chat_id, role, content, time.time()),
        )
        await db.commit()


async def load_history(chat_id: int, limit: int = 40) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT role, content FROM conversations WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        )
        rows = await cursor.fetchall()

    messages = []
    for role, content in reversed(rows):
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            parsed = content

        # Normalize content to string for OpenAI compatibility
        if isinstance(parsed, list):
            # Anthropic-style content blocks: extract text
            text_parts = []
            for block in parsed:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            parsed = " ".join(text_parts) if text_parts else str(parsed)
        elif not isinstance(parsed, str):
            parsed = str(parsed)

        messages.append({"role": role, "content": parsed})
    return messages


async def clear_history(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM conversations WHERE chat_id = ?", (chat_id,))
        await db.commit()


async def store_memory(chat_id: int, key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM memories WHERE chat_id = ? AND key = ?", (chat_id, key)
        )
        await db.execute(
            "INSERT INTO memories (chat_id, key, value, timestamp) VALUES (?, ?, ?, ?)",
            (chat_id, key, value, time.time()),
        )
        await db.commit()


async def recall_memories(chat_id: int, query: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT key, value FROM memories WHERE chat_id = ? AND (key LIKE ? OR value LIKE ?)",
            (chat_id, f"%{query}%", f"%{query}%"),
        )
        rows = await cursor.fetchall()
    return [{"key": k, "value": v} for k, v in rows]


async def get_all_memories(chat_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT key, value FROM memories WHERE chat_id = ? ORDER BY timestamp DESC",
            (chat_id,),
        )
        rows = await cursor.fetchall()
    return [{"key": k, "value": v} for k, v in rows]


async def delete_memory(chat_id: int, key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM memories WHERE chat_id = ? AND key = ?", (chat_id, key)
        )
        await db.commit()


async def record_usage(
    chat_id: int,
    input_tokens: int,
    output_tokens: int,
    model: str,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO usage (chat_id, input_tokens, output_tokens, model, timestamp, "
            "cache_creation_tokens, cache_read_tokens) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chat_id, input_tokens, output_tokens, model, time.time(),
             cache_creation_tokens, cache_read_tokens),
        )
        await db.commit()


async def get_usage_cost_since(chat_id: int, since_timestamp: float) -> float:
    """Calculate estimated cost since a given timestamp.
    Anthropic cache pricing: writes are 1.25x base input, reads are 0.1x base input.
    """
    from config import PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M
    price_in, price_out = PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), "
            "COALESCE(SUM(cache_creation_tokens),0), COALESCE(SUM(cache_read_tokens),0) "
            "FROM usage WHERE chat_id = ? AND timestamp >= ?",
            (chat_id, since_timestamp),
        )
        total_in, total_out, cache_w, cache_r = await cursor.fetchone()
    return (
        total_in * price_in
        + total_out * price_out
        + cache_w * price_in * 1.25
        + cache_r * price_in * 0.1
    ) / 1_000_000


async def get_today_conversations(chat_id: int) -> list[dict]:
    """Get all conversations from today (UTC) for daily summary generation."""
    now = time.time()
    today_start = now - (now % 86400)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT role, content FROM conversations WHERE chat_id = ? AND timestamp >= ? ORDER BY id ASC",
            (chat_id, today_start),
        )
        rows = await cursor.fetchall()

    messages = []
    for role, content in rows:
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            parsed = content
        if isinstance(parsed, list):
            text_parts = []
            for block in parsed:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            parsed = " ".join(text_parts) if text_parts else str(parsed)
        elif not isinstance(parsed, str):
            parsed = str(parsed)
        messages.append({"role": role, "content": parsed})
    return messages


async def save_daily_summary(chat_id: int, date: str, summary: str, message_count: int):
    """Save a daily summary. Replaces existing summary for the same date."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM daily_summaries WHERE chat_id = ? AND date = ?",
            (chat_id, date),
        )
        await db.execute(
            "INSERT INTO daily_summaries (chat_id, date, summary, message_count, created_at) VALUES (?, ?, ?, ?, ?)",
            (chat_id, date, summary, message_count, time.time()),
        )
        await db.commit()


async def get_recent_daily_summaries(chat_id: int, days: int = 7) -> list[dict]:
    """Get the most recent daily summaries."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT date, summary FROM daily_summaries WHERE chat_id = ? ORDER BY date DESC LIMIT ?",
            (chat_id, days),
        )
        rows = await cursor.fetchall()
    return [{"date": d, "summary": s} for d, s in rows]


async def get_last_summary_date(chat_id: int) -> str | None:
    """Get the date of the most recent daily summary."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT date FROM daily_summaries WHERE chat_id = ? ORDER BY date DESC LIMIT 1",
            (chat_id,),
        )
        row = await cursor.fetchone()
    return row[0] if row else None


async def get_conversations_for_date(chat_id: int, date_str: str) -> list[dict]:
    """Get conversations for a specific date (YYYY-MM-DD, UTC)."""
    from datetime import datetime
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    start_ts = dt.timestamp()
    end_ts = start_ts + 86400

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT role, content FROM conversations WHERE chat_id = ? AND timestamp >= ? AND timestamp < ? ORDER BY id ASC",
            (chat_id, start_ts, end_ts),
        )
        rows = await cursor.fetchall()

    messages = []
    for role, content in rows:
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            parsed = content
        if isinstance(parsed, list):
            text_parts = [b.get("text", "") for b in parsed if isinstance(b, dict) and b.get("type") == "text"]
            parsed = " ".join(text_parts) if text_parts else str(parsed)
        elif not isinstance(parsed, str):
            parsed = str(parsed)
        messages.append({"role": role, "content": parsed})
    return messages


async def save_owner_profile(chat_id: int, profile: str):
    """Save or update the owner profile."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO owner_profile (chat_id, profile, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET profile = ?, updated_at = ?""",
            (chat_id, profile, time.time(), profile, time.time()),
        )
        await db.commit()


async def get_owner_profile(chat_id: int) -> str | None:
    """Get the owner profile."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT profile FROM owner_profile WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
    return row[0] if row else None


async def save_bot_diary(chat_id: int, diary: str):
    """Save/update the bot's self-model diary."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Use a single row per chat_id, upsert
        cursor = await db.execute(
            "SELECT id FROM memories WHERE chat_id = ? AND key = '__bot_diary__'",
            (chat_id,),
        )
        row = await cursor.fetchone()
        if row:
            await db.execute(
                "UPDATE memories SET value = ?, timestamp = ? WHERE chat_id = ? AND key = '__bot_diary__'",
                (diary, time.time(), chat_id),
            )
        else:
            await db.execute(
                "INSERT INTO memories (chat_id, key, value, timestamp) VALUES (?, '__bot_diary__', ?, ?)",
                (chat_id, diary, time.time()),
            )
        await db.commit()


async def get_bot_diary(chat_id: int) -> str | None:
    """Get the bot's self-model diary."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT value FROM memories WHERE chat_id = ? AND key = '__bot_diary__'",
            (chat_id,),
        )
        row = await cursor.fetchone()
    return row[0] if row else None


async def get_usage_stats(chat_id: int) -> dict:
    """Get usage statistics: total, today, and last 30 days. Includes cache tokens."""
    now = time.time()
    today_start = now - (now % 86400)  # start of UTC day
    month_start = now - 30 * 86400

    cols = ("COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), "
            "COALESCE(SUM(cache_creation_tokens),0), COALESCE(SUM(cache_read_tokens),0), "
            "COUNT(*)")

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"SELECT {cols} FROM usage WHERE chat_id = ?", (chat_id,),
        )
        total_in, total_out, total_cw, total_cr, total_requests = await cursor.fetchone()

        cursor = await db.execute(
            f"SELECT {cols} FROM usage WHERE chat_id = ? AND timestamp >= ?",
            (chat_id, today_start),
        )
        today_in, today_out, today_cw, today_cr, today_requests = await cursor.fetchone()

        cursor = await db.execute(
            f"SELECT {cols} FROM usage WHERE chat_id = ? AND timestamp >= ?",
            (chat_id, month_start),
        )
        month_in, month_out, month_cw, month_cr, month_requests = await cursor.fetchone()

    def _bucket(in_t, out_t, cw, cr, req):
        return {
            "input_tokens": in_t, "output_tokens": out_t,
            "cache_creation_tokens": cw, "cache_read_tokens": cr,
            "requests": req,
        }

    return {
        "total": _bucket(total_in, total_out, total_cw, total_cr, total_requests),
        "today": _bucket(today_in, today_out, today_cw, today_cr, today_requests),
        "last_30_days": _bucket(month_in, month_out, month_cw, month_cr, month_requests),
    }
