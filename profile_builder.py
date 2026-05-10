"""
Profile Builder — generates one casual question per day to fill gaps in
owner_profile. Used by the heartbeat system as a standing order.
"""
from __future__ import annotations

import json
import time
import logging
import aiosqlite
from config import DB_PATH, MODEL, BOT_OWNER_NAME, BOT_LANGUAGE

logger = logging.getLogger(__name__)


async def _recent_questions(chat_id: int, days: int = 21) -> list[str]:
    """Return profile questions asked in the last `days` so we don't repeat them."""
    cutoff = time.time() - days * 86400
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT result FROM heartbeat_log WHERE chat_id = ? AND order_name = 'profile_question' "
            "AND ran_at >= ? ORDER BY ran_at DESC LIMIT 30",
            (chat_id, cutoff),
        )
        rows = await cursor.fetchall()
    return [r[0] for r in rows if r and r[0]]


async def generate_profile_question(chat_id: int) -> str | None:
    """
    Generate one targeted question that fills a gap in the user's profile.
    Returns the question text, or None if there's nothing useful to ask.
    """
    from ai_client import get_client
    from memory import get_all_memories, get_owner_profile, record_usage

    profile = await get_owner_profile(chat_id) or "(no profile yet)"
    memories = await get_all_memories(chat_id)
    # Keep input small — 20 memories is enough signal to spot a profile gap.
    mem_text = "\n".join(f"- {m['key']}: {m['value']}" for m in memories[:20]) if memories else "(no memories)"
    recent = await _recent_questions(chat_id)
    recent_text = "\n".join(f"- {q}" for q in recent) if recent else "(none)"

    system_prompt = (
        f"You build a long-term profile of {BOT_OWNER_NAME} by asking one question at a time. "
        "Pick ONE specific, casual, low-pressure question that would fill a meaningful gap in what we know "
        "about the user — interests, routines, goals, preferences, taste, relationships, work context. "
        "Rules:\n"
        "- Pick ONE question, not several\n"
        "- Keep it short (one sentence) and conversational, not interrogative\n"
        "- Do NOT ask anything similar to the recent questions list\n"
        "- Do NOT ask things already known from the profile or memories\n"
        f"- Write the question in {BOT_LANGUAGE}\n"
        "- If you can't find a meaningful gap, return an empty question\n\n"
        'Return ONLY valid JSON: {"question": "...", "topic": "short_topic_key"} '
        '(empty question if nothing useful to ask).'
    )

    user_content = (
        f"Current profile:\n{profile}\n\n"
        f"Stored memories:\n{mem_text}\n\n"
        f"Recently asked (avoid these):\n{recent_text}"
    )

    client = get_client()
    messages = client.build_messages(system_prompt, [], user_content)
    response = await client.chat(messages, max_tokens=150, temperature=0.6)

    if response.input_tokens or response.cache_creation_input_tokens or response.cache_read_input_tokens:
        await record_usage(
            chat_id, response.input_tokens, response.output_tokens, MODEL,
            cache_creation_tokens=response.cache_creation_input_tokens,
            cache_read_tokens=response.cache_read_input_tokens,
        )

    text = (response.text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        logger.warning(f"profile_builder: failed to parse: {text[:200]}")
        return None

    question = (parsed.get("question") or "").strip()
    if not question:
        return None

    logger.info(f"profile_builder: question topic={parsed.get('topic')} -> {question[:80]}")
    return question
