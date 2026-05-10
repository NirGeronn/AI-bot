"""
Proactive Pulse System — autonomous smart outreach.
Periodically checks context (calendar, memories, recent conversations) and
sends a proactive message if confident it's useful. Learns from declines.
"""
from __future__ import annotations

import json
import time
import logging
import aiosqlite
from config import DB_PATH, MODEL, BOT_OWNER_NAME, BOT_LANGUAGE, USER_TIMEZONE

logger = logging.getLogger(__name__)

# Pulse configuration
PULSE_CONFIDENCE_THRESHOLD = 0.7
PULSE_COOLDOWN_SECONDS = 4 * 3600  # 4 hours between pulses
ACTIVE_CONVERSATION_GRACE_SECONDS = 120  # Don't interrupt active chats


async def _ensure_pulse_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS pulse_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                confidence REAL NOT NULL,
                reaction TEXT DEFAULT NULL,
                sent_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pulse_suppression (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                topic TEXT NOT NULL,
                cooldown_until REAL NOT NULL,
                decline_count INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pulse_log_chat ON pulse_log(chat_id);
            CREATE INDEX IF NOT EXISTS idx_pulse_supp_chat ON pulse_suppression(chat_id);
        """)
        await db.commit()


async def _last_message_time(chat_id: int) -> float:
    """Get timestamp of the last conversation message."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT MAX(timestamp) FROM conversations WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
    return row[0] if row and row[0] else 0


async def _last_pulse_time(chat_id: int) -> float:
    """Get timestamp of the last pulse sent."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT MAX(sent_at) FROM pulse_log WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
    return row[0] if row and row[0] else 0


async def _get_suppressed_topics(chat_id: int) -> list[str]:
    """Get topics the user has declined (still in cooldown)."""
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT topic FROM pulse_suppression WHERE chat_id = ? AND cooldown_until > ?",
            (chat_id, now),
        )
        rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def _record_pulse(chat_id: int, message: str, confidence: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO pulse_log (chat_id, message, confidence, sent_at) VALUES (?, ?, ?, ?)",
            (chat_id, message, confidence, time.time()),
        )
        await db.commit()


async def suppress_topic(chat_id: int, topic: str):
    """Record a topic decline with escalating cooldown (24h -> 7d -> 30d)."""
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        # Check existing decline count
        cursor = await db.execute(
            "SELECT decline_count FROM pulse_suppression WHERE chat_id = ? AND topic = ?",
            (chat_id, topic),
        )
        row = await cursor.fetchone()

        if row:
            count = row[0] + 1
            # Escalating cooldowns
            if count >= 3:
                cooldown = 30 * 86400  # 30 days
            elif count >= 2:
                cooldown = 7 * 86400  # 7 days
            else:
                cooldown = 86400  # 24 hours

            await db.execute(
                "UPDATE pulse_suppression SET cooldown_until = ?, decline_count = ? WHERE chat_id = ? AND topic = ?",
                (now + cooldown, count, chat_id, topic),
            )
        else:
            await db.execute(
                "INSERT INTO pulse_suppression (chat_id, topic, cooldown_until, decline_count, created_at) VALUES (?, ?, ?, 1, ?)",
                (chat_id, topic, now + 86400, now),
            )
        await db.commit()


async def should_pulse(chat_id: int) -> bool:
    """Check if conditions are right for a proactive pulse."""
    now = time.time()

    # Don't interrupt active conversations
    last_msg = await _last_message_time(chat_id)
    if now - last_msg < ACTIVE_CONVERSATION_GRACE_SECONDS:
        return False

    # Respect cooldown between pulses
    last_pulse = await _last_pulse_time(chat_id)
    if now - last_pulse < PULSE_COOLDOWN_SECONDS:
        return False

    return True


def _gather_action_signals() -> dict:
    """Pull cheap signals from inbox/calendar/todos without LLM. Failures are
    swallowed — pulse should still work if any one source is unavailable."""
    inbox, events, todos = [], [], []
    try:
        from heartbeat import _check_calendar_raw
        events = _check_calendar_raw(hours_ahead=24)
    except Exception as e:
        logger.warning(f"pulse: calendar fetch failed: {e}")
    return {"inbox": inbox, "events": events}


async def generate_pulse(chat_id: int) -> dict | None:
    """
    Generate a proactive pulse message by analyzing current context.
    Returns {"message": str, "confidence": float, "topic": str} or None.
    """
    from ai_client import get_client
    from memory import get_all_memories, get_recent_daily_summaries, record_usage
    from heartbeat import _check_todos_raw

    await _ensure_pulse_table()

    if not await should_pulse(chat_id):
        return None

    # Gather context
    memories = await get_all_memories(chat_id)
    summaries = await get_recent_daily_summaries(chat_id, days=3)
    suppressed = await _get_suppressed_topics(chat_id)
    signals = _gather_action_signals()
    todos = await _check_todos_raw(chat_id)

    mem_text = "\n".join(f"- {m['key']}: {m['value']}" for m in memories[:30]) if memories else "(no memories)"
    sum_text = "\n".join(f"- {s['date']}: {s['summary']}" for s in summaries) if summaries else "(no recent summaries)"
    supp_text = ", ".join(suppressed) if suppressed else "(none)"

    inbox_text = "\n".join(
        f"- from {(e.get('from') or '').split('<')[0].strip() or '?'}: {e.get('subject','')[:80]} — {e.get('snippet','')[:120]}"
        for e in signals["inbox"][:5]
    ) or "(no unread emails)"
    events_text = "\n".join(
        f"- {e.get('start','?')} — {e.get('summary') or e.get('title') or '(untitled)'}"
        for e in signals["events"][:5]
    ) or "(no upcoming events in next 24h)"
    todos_text = "\n".join(f"- [{t['list']}] {t['item'][:80]}" for t in todos[:5]) or "(no open todos)"

    # Get current time context
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now_local = datetime.now(ZoneInfo(USER_TIMEZONE))
    time_context = now_local.strftime(f"%A, %Y-%m-%d %H:%M {USER_TIMEZONE}")

    client = get_client()

    system_prompt = (
        f"You are the proactive intelligence module of a personal AI assistant for {BOT_OWNER_NAME}. "
        f"Your job is to decide if there's something specific you can DO for {BOT_OWNER_NAME} right now and propose it as a yes/no action.\n\n"
        "Strongly prefer ACTION PROPOSALS over generic check-ins. Examples of good proposals:\n"
        "- 'Email from El Al about Sunday's flight — want me to add it to your calendar?'\n"
        "- 'You have a 14:00 meeting and no agenda yet — want me to draft one?'\n"
        "- '5 open shopping items that haven't moved in a week — want me to clean the list?'\n"
        "Bad (generic check-ins to AVOID): 'How's your day going?', 'Did you finish your todos?'\n\n"
        "Rules:\n"
        "- Only suggest if there's a CONCRETE thing you'd do once the user agrees\n"
        "- The message must end with a yes/no question the user can act on\n"
        "- Set confidence 0.0-1.0 (only send if >= 0.7); 0 if nothing actionable\n"
        "- Keep it to 1-2 sentences\n"
        "- Do NOT repeat suppressed topics\n"
        f"- Write in {BOT_LANGUAGE}\n\n"
        "Return ONLY valid JSON: {\"message\": \"...\", \"confidence\": 0.X, \"topic\": \"short_topic_key\"}"
    )

    user_content = (
        f"Current time: {time_context}\n\n"
        f"Unread inbox (top 5):\n{inbox_text}\n\n"
        f"Upcoming calendar (next 24h):\n{events_text}\n\n"
        f"Open todos (top 5):\n{todos_text}\n\n"
        f"User memories:\n{mem_text}\n\n"
        f"Recent daily summaries:\n{sum_text}\n\n"
        f"Suppressed topics (DO NOT suggest these):\n{supp_text}"
    )

    messages = client.build_messages(system_prompt, [], user_content)
    response = await client.chat(messages, max_tokens=400, temperature=0.4)

    if response.input_tokens or response.cache_creation_input_tokens or response.cache_read_input_tokens:
        await record_usage(
            chat_id, response.input_tokens, response.output_tokens, MODEL,
            cache_creation_tokens=response.cache_creation_input_tokens,
            cache_read_tokens=response.cache_read_input_tokens,
        )

    text = response.text or ""

    try:
        # Parse JSON from response (handle markdown code blocks)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        logger.warning(f"Pulse: failed to parse LLM response: {text[:200]}")
        return None

    confidence = result.get("confidence", 0)
    if confidence < PULSE_CONFIDENCE_THRESHOLD:
        logger.info(f"Pulse: below threshold ({confidence:.2f}), skipping")
        return None

    message = result.get("message", "")
    topic = result.get("topic", "unknown")

    if not message:
        return None

    # Record the pulse
    await _record_pulse(chat_id, message, confidence)

    logger.info(f"Pulse: sending ({confidence:.2f}) topic={topic}: {message[:80]}")
    return {"message": message, "confidence": confidence, "topic": topic}
