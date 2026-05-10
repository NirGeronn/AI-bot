"""
Habits tracking — passively tracks user activity patterns.
Stores when the user messages, what tools get used, and topic hints.
Powers better pulse timing and personalization.
"""
import time
import json
import logging
import aiosqlite
from config import DB_PATH

logger = logging.getLogger(__name__)


async def _ensure_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                hour INTEGER NOT NULL,
                weekday INTEGER NOT NULL,
                tool_used TEXT,
                message_length INTEGER NOT NULL DEFAULT 0,
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_habits_chat ON habits(chat_id);
        """)
        await db.commit()


async def track_message(chat_id: int, message_length: int):
    """Track a user message event."""
    from datetime import datetime, timezone, timedelta
    await _ensure_table()

    now = datetime.now(timezone.utc) + timedelta(hours=3)  # Israel time
    hour = now.hour
    weekday = now.weekday()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO habits (chat_id, hour, weekday, message_length, timestamp) VALUES (?, ?, ?, ?, ?)",
            (chat_id, hour, weekday, message_length, time.time()),
        )
        await db.commit()


async def track_tool_use(chat_id: int, tool_name: str):
    """Track a tool usage event."""
    from datetime import datetime, timezone, timedelta
    await _ensure_table()

    now = datetime.now(timezone.utc) + timedelta(hours=3)
    hour = now.hour
    weekday = now.weekday()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO habits (chat_id, hour, weekday, tool_used, timestamp) VALUES (?, ?, ?, ?, ?)",
            (chat_id, hour, weekday, tool_name, time.time()),
        )
        await db.commit()


async def get_activity_summary(chat_id: int) -> dict:
    """Get a summary of user activity patterns."""
    await _ensure_table()

    async with aiosqlite.connect(DB_PATH) as db:
        # Most active hours
        cursor = await db.execute(
            "SELECT hour, COUNT(*) as cnt FROM habits WHERE chat_id = ? AND tool_used IS NULL GROUP BY hour ORDER BY cnt DESC LIMIT 5",
            (chat_id,),
        )
        active_hours = {r[0]: r[1] for r in await cursor.fetchall()}

        # Most active days
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        cursor = await db.execute(
            "SELECT weekday, COUNT(*) as cnt FROM habits WHERE chat_id = ? AND tool_used IS NULL GROUP BY weekday ORDER BY cnt DESC",
            (chat_id,),
        )
        active_days = {day_names[r[0]]: r[1] for r in await cursor.fetchall()}

        # Most used tools
        cursor = await db.execute(
            "SELECT tool_used, COUNT(*) as cnt FROM habits WHERE chat_id = ? AND tool_used IS NOT NULL GROUP BY tool_used ORDER BY cnt DESC LIMIT 10",
            (chat_id,),
        )
        top_tools = {r[0]: r[1] for r in await cursor.fetchall()}

        # Total messages (last 30 days)
        since = time.time() - 30 * 86400
        cursor = await db.execute(
            "SELECT COUNT(*) FROM habits WHERE chat_id = ? AND tool_used IS NULL AND timestamp >= ?",
            (chat_id, since),
        )
        msg_count = (await cursor.fetchone())[0]

    return {
        "active_hours": active_hours,
        "active_days": active_days,
        "top_tools": top_tools,
        "messages_last_30d": msg_count,
    }
