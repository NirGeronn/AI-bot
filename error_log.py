"""
Error logging system — captures failures for later review and debugging.
Stores errors in SQLite so they persist across restarts.
"""
from __future__ import annotations

import time
import json
import logging
import traceback
import aiosqlite
from config import DB_PATH

logger = logging.getLogger(__name__)


async def _ensure_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS error_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                error_type TEXT NOT NULL,
                context TEXT NOT NULL,
                error_message TEXT NOT NULL,
                user_message TEXT,
                extra TEXT,
                timestamp REAL NOT NULL
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_errlog_ts ON error_log(timestamp)"
        )
        await db.commit()


_table_ready = False


async def log_error(
    chat_id: int | None,
    error_type: str,
    context: str,
    error_message: str,
    user_message: str | None = None,
    extra: dict | None = None,
):
    """
    Log an error for later review.

    error_type: api_error, tool_error, tool_result_error, parse_error,
                empty_response, agent_error, heartbeat_error, pulse_error
    context:    short description of what was happening
    error_message: the actual error text
    user_message: the user message that triggered this (if any)
    extra:      any additional data (tool name, args, etc.)
    """
    global _table_ready
    try:
        if not _table_ready:
            await _ensure_table()
            _table_ready = True

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO error_log (chat_id, error_type, context, error_message, user_message, extra, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    chat_id,
                    error_type,
                    context,
                    error_message[:2000],
                    (user_message or "")[:500],
                    json.dumps(extra) if extra else None,
                    time.time(),
                ),
            )
            # Clean old logs (keep last 14 days)
            cutoff = time.time() - 14 * 86400
            await db.execute("DELETE FROM error_log WHERE timestamp < ?", (cutoff,))
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to log error: {e}")


async def cleanup_old_errors(retention_days: int = 14) -> int:
    """Delete error rows older than retention_days. Returns count deleted."""
    try:
        await _ensure_table()
        cutoff = time.time() - retention_days * 86400
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("DELETE FROM error_log WHERE timestamp < ?", (cutoff,))
            await db.commit()
            return cursor.rowcount or 0
    except Exception as e:
        logger.error(f"Failed to cleanup old errors: {e}")
        return 0


async def get_recent_errors(limit: int = 20) -> list[dict]:
    """Get recent errors for review."""
    try:
        await _ensure_table()
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM error_log ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()

        from datetime import datetime, timezone
        errors = []
        for row in rows:
            ts = datetime.fromtimestamp(row["timestamp"], tz=timezone.utc)
            errors.append({
                "id": row["id"],
                "time": ts.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "type": row["error_type"],
                "context": row["context"],
                "error": row["error_message"],
                "user_msg": row["user_message"] or "",
                "extra": json.loads(row["extra"]) if row["extra"] else None,
            })
        return errors
    except Exception as e:
        logger.error(f"Failed to get errors: {e}")
        return []


async def get_error_summary() -> str:
    """Get a formatted summary of recent errors for display."""
    errors = await get_recent_errors(20)
    if not errors:
        return "No errors logged."

    lines = []
    for e in errors:
        extra_str = ""
        if e["extra"]:
            extra_str = f" | {json.dumps(e['extra'])}"
        user_str = f" | user: \"{e['user_msg'][:60]}\"" if e["user_msg"] else ""
        lines.append(
            f"[{e['time']}] {e['type']}: {e['context']}\n"
            f"  error: {e['error'][:200]}{user_str}{extra_str}"
        )
    return "\n\n".join(lines)
