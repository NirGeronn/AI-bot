"""
Morning News Digest — Personalized daily briefing.
Searches for news based on user interests (from memories/profile) and
generates a concise digest sent each morning.
"""
from __future__ import annotations
import json
import logging
import time
import aiosqlite
from config import DB_PATH, MODEL, BOT_OWNER_NAME, BOT_LANGUAGE, USER_TIMEZONE

logger = logging.getLogger(__name__)

# Default topics if no user interests are found
DEFAULT_TOPICS = ["technology", "AI", "world news"]


async def _get_user_interests(chat_id: int) -> list[str]:
    """Extract user interests from memories and profile."""
    from memory import get_all_memories, get_owner_profile

    interests = set()

    # Check memories for interest-related keys
    memories = await get_all_memories(chat_id)
    interest_keywords = {"interest", "hobby", "likes", "favorite", "passion", "work", "job", "field"}
    for m in memories:
        key_lower = m["key"].lower()
        if any(kw in key_lower for kw in interest_keywords):
            interests.add(m["value"])

    # Check owner profile for clues
    profile = await get_owner_profile(chat_id)
    if profile:
        # The LLM will use the profile to personalize the digest
        pass

    return list(interests) if interests else DEFAULT_TOPICS


async def _search_news(topics: list[str]) -> list[dict]:
    """Search for recent news on given topics."""
    from tools.web import _search_ddg
    all_results = []
    seen_urls = set()

    for topic in topics[:5]:  # Max 5 topics
        try:
            query = f"{topic} news today"
            results = _search_ddg(query, max_results=5)
            for r in results:
                url = r.get("url", "")
                if url not in seen_urls:
                    seen_urls.add(url)
                    r["topic"] = topic
                    all_results.append(r)
        except Exception as e:
            logger.warning(f"News search failed for topic '{topic}': {e}")

    return all_results[:15]  # Cap at 15 results total


async def _last_digest_time(chat_id: int) -> float:
    """Get timestamp of last digest sent."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS news_digest_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    digest TEXT NOT NULL,
                    sent_at REAL NOT NULL
                )
            """)
            await db.commit()
            cursor = await db.execute(
                "SELECT MAX(sent_at) FROM news_digest_log WHERE chat_id = ?",
                (chat_id,),
            )
            row = await cursor.fetchone()
        return row[0] if row and row[0] else 0
    except Exception:
        return 0


async def _record_digest(chat_id: int, digest: str):
    """Record that a digest was sent."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO news_digest_log (chat_id, digest, sent_at) VALUES (?, ?, ?)",
            (chat_id, digest[:1000], time.time()),
        )
        # Keep last 30 digests
        await db.execute("""
            DELETE FROM news_digest_log WHERE chat_id = ? AND id NOT IN (
                SELECT id FROM news_digest_log WHERE chat_id = ? ORDER BY sent_at DESC LIMIT 30
            )
        """, (chat_id, chat_id))
        await db.commit()


async def generate_news_digest(chat_id: int) -> str | None:
    """
    Generate a personalized morning news digest.
    Returns the digest text or None if already sent today.
    """
    from ai_client import get_client
    from memory import get_owner_profile, record_usage

    # Check if already sent today (within last 20 hours)
    last_sent = await _last_digest_time(chat_id)
    if time.time() - last_sent < 20 * 3600:
        logger.info("News digest: already sent today, skipping")
        return None

    # Get user interests
    interests = await _get_user_interests(chat_id)
    profile = await get_owner_profile(chat_id) or ""

    # Search for news
    news_results = await _search_news(interests)
    if not news_results:
        logger.warning("News digest: no search results found")
        return None

    # Format search results for the LLM
    news_text = ""
    for i, r in enumerate(news_results, 1):
        news_text += f"{i}. [{r.get('topic', '')}] {r['title']}\n   {r['snippet']}\n\n"

    client = get_client()

    system_prompt = (
        f"You are creating a personalized morning news briefing for {BOT_OWNER_NAME}. "
        f"Write in {BOT_LANGUAGE}. Keep it concise and easy to scan.\n\n"
        "Rules:\n"
        "- Start with a short friendly morning greeting\n"
        "- Group news by topic/category\n"
        "- Use bullet points, max 2 lines per item\n"
        "- Highlight the most important/relevant items first\n"
        "- Keep the entire digest under 15 bullet points\n"
        "- Use *bold* for emphasis (Telegram formatting)\n"
        "- End with a brief weather hint or motivational note\n"
        "- Skip irrelevant or low-quality results\n"
        "- Do NOT use markdown headers (no #, ##, ###)\n"
    )

    user_content = (
        f"Owner profile:\n{profile}\n\n"
        f"Their interests: {', '.join(interests)}\n\n"
        f"Today's news search results:\n{news_text}\n\n"
        "Create a concise, personalized morning briefing from these results."
    )

    messages = client.build_messages(system_prompt, [], user_content)
    response = await client.chat(messages, max_tokens=1500, temperature=0.4)

    if response.input_tokens or response.cache_creation_input_tokens or response.cache_read_input_tokens:
        await record_usage(
            chat_id, response.input_tokens, response.output_tokens, MODEL,
            cache_creation_tokens=response.cache_creation_input_tokens,
            cache_read_tokens=response.cache_read_input_tokens,
        )

    digest = (response.text or "").strip()
    if not digest:
        return None

    await _record_digest(chat_id, digest)
    logger.info(f"News digest generated for chat {chat_id}: {len(digest)} chars")

    return digest
