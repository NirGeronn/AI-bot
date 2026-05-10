"""
Tests for active memory: search term extraction and context retrieval.
"""
import pytest

CHAT_ID = 111


def test_extract_search_terms_filters_stop_words():
    """Stop words are removed from search terms."""
    from active_memory import extract_search_terms

    terms = extract_search_terms("What is the weather in Tel Aviv?")
    assert "what" not in terms
    assert "the" not in terms
    assert "weather" in terms


def test_extract_search_terms_hebrew_stop_words():
    """Hebrew stop words are also filtered."""
    from active_memory import extract_search_terms

    terms = extract_search_terms("מה את חושבת על פיצה")
    assert "את" not in terms
    assert "מה" not in terms
    assert "פיצה" in terms


def test_extract_search_terms_short_words_filtered():
    """Words with 2 or fewer characters are filtered."""
    from active_memory import extract_search_terms

    terms = extract_search_terms("I am ok at it")
    assert "am" not in terms
    assert "ok" not in terms
    assert "at" not in terms


def test_extract_search_terms_bigrams():
    """Bigrams of non-stop-words are included."""
    from active_memory import extract_search_terms

    terms = extract_search_terms("machine learning algorithms")
    assert "machine learning" in terms or "learning algorithms" in terms


def test_extract_search_terms_limit():
    """Max 8 terms are returned."""
    from active_memory import extract_search_terms

    terms = extract_search_terms(
        "quantum computing artificial intelligence neural networks deep learning "
        "reinforcement supervised unsupervised transfer federated continual meta"
    )
    assert len(terms) <= 8


def test_extract_search_terms_empty_input():
    """Empty input returns no terms."""
    from active_memory import extract_search_terms

    assert extract_search_terms("") == []
    assert extract_search_terms("   ") == []


def test_extract_search_terms_all_stop_words():
    """Input of only stop words returns empty."""
    from active_memory import extract_search_terms

    terms = extract_search_terms("what is the and or but")
    assert len(terms) == 0


@pytest.mark.asyncio
async def test_search_relevant_context_finds_memories(db):
    """Active memory finds relevant stored memories."""
    from memory import store_memory
    from active_memory import search_relevant_context

    await store_memory(CHAT_ID, "favorite_restaurant", "Miznon in Tel Aviv")
    await store_memory(CHAT_ID, "birthday", "March 15")

    context = await search_relevant_context(CHAT_ID, "Where should we eat in Tel Aviv?")
    assert context is not None
    assert "Miznon" in context


@pytest.mark.asyncio
async def test_search_relevant_context_skips_bot_diary(db):
    """Active memory search excludes the __bot_diary__ entry."""
    from memory import store_memory, save_bot_diary
    from active_memory import search_relevant_context

    await save_bot_diary(CHAT_ID, "Always be concise when user asks quick questions")
    await store_memory(CHAT_ID, "preference", "concise answers")

    context = await search_relevant_context(CHAT_ID, "Can you be more concise?")
    if context:
        assert "__bot_diary__" not in context


@pytest.mark.asyncio
async def test_search_relevant_context_no_match(db):
    """Returns None when no relevant context is found."""
    from active_memory import search_relevant_context

    context = await search_relevant_context(CHAT_ID, "random unrelated query")
    assert context is None


@pytest.mark.asyncio
async def test_search_relevant_context_finds_summaries(db):
    """Active memory finds relevant daily summaries."""
    from memory import save_daily_summary
    from active_memory import search_relevant_context

    await save_daily_summary(CHAT_ID, "2026-04-18", "Discussed trip to Paris and flight options", 10)
    await save_daily_summary(CHAT_ID, "2026-04-17", "Worked on coding project", 8)

    context = await search_relevant_context(CHAT_ID, "What were those Paris flight options?")
    assert context is not None
    assert "Paris" in context or "flight" in context
