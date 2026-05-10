"""
Active Memory - Pre-reply memory search inspired by OpenClaw.
Before generating a response, searches memory and daily summaries
for context relevant to the user's current message.
"""
from __future__ import annotations

import re
import logging
from memory import recall_memories, get_recent_daily_summaries

logger = logging.getLogger(__name__)

# Common words to skip when extracting search terms
STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "i", "me", "my", "you", "your", "he", "she", "it", "we", "they",
    "this", "that", "these", "those", "what", "which", "who", "whom",
    "how", "when", "where", "why", "not", "no", "yes", "and", "or",
    "but", "if", "then", "so", "too", "very", "just", "about", "with",
    "for", "from", "to", "of", "in", "on", "at", "by", "up", "out",
    "all", "some", "any", "much", "many", "more", "most", "other",
    "into", "over", "after", "before", "between", "under", "again",
    "please", "tell", "show", "give", "get", "make", "let", "want",
    "know", "think", "say", "go", "come", "see", "look", "find",
    "hey", "hi", "hello", "thanks", "thank", "okay", "ok",
    # Hebrew stop words
    "את", "של", "על", "עם", "לא", "כן", "גם", "או", "אם", "אני",
    "הוא", "היא", "זה", "זו", "מה", "איך", "למה", "מתי", "איפה",
    "יש", "אין", "היה", "הייתה", "לי", "שלי", "שלך",
}


def extract_search_terms(text: str) -> list[str]:
    """Extract meaningful search terms from user message."""
    # Clean and tokenize
    text = text.lower().strip()
    # Split on whitespace and punctuation
    words = re.findall(r'[\w\u0590-\u05FF]+', text)

    # Filter stop words and short words
    terms = [w for w in words if w not in STOP_WORDS and len(w) > 2]

    # Also extract multi-word phrases (bigrams) for better matching
    bigrams = []
    for i in range(len(words) - 1):
        if words[i] not in STOP_WORDS and words[i + 1] not in STOP_WORDS:
            bigrams.append(f"{words[i]} {words[i + 1]}")

    # Return unique terms, single words first then bigrams
    seen = set()
    result = []
    for t in terms + bigrams:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result[:8]  # Limit to avoid too many searches


async def search_relevant_context(chat_id: int, user_message: str) -> str | None:
    """
    Search memories and summaries for context relevant to the user's message.
    Returns a formatted string to inject into the system prompt, or None.
    """
    terms = extract_search_terms(user_message)
    if not terms:
        return None

    # Search memories with each term
    found_memories = {}
    for term in terms[:5]:  # Limit searches
        results = await recall_memories(chat_id, term)
        for r in results:
            key = r["key"]
            if key != "__bot_diary__" and key not in found_memories:
                found_memories[key] = r["value"]

    # Search daily summaries for relevant context
    summaries = await get_recent_daily_summaries(chat_id, days=7)
    relevant_summaries = []
    if summaries:
        terms_lower = set(terms)
        for s in summaries:
            summary_lower = s["summary"].lower()
            if any(t in summary_lower for t in terms_lower):
                relevant_summaries.append(s)

    # Build context string
    parts = []
    if found_memories:
        mem_lines = [f"- {k}: {v}" for k, v in found_memories.items()]
        parts.append(f"Relevant memories:\n" + "\n".join(mem_lines))

    if relevant_summaries:
        sum_lines = [f"- {s['date']}: {s['summary']}" for s in relevant_summaries[:3]]
        parts.append(f"Related past conversations:\n" + "\n".join(sum_lines))

    if not parts:
        return None

    context = "\n\n".join(parts)
    logger.info(f"Active memory found {len(found_memories)} memories, {len(relevant_summaries)} summaries for: {terms[:3]}")
    return context
