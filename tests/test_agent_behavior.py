"""
Tests for agent behavior: thinking stripping, correction detection, model selection.
These tests avoid importing the full agent/tools chain to prevent needing live API keys.
Instead, we test the pure functions directly by extracting them or importing carefully.
"""
from __future__ import annotations

import re
import sys
import pytest


# ── Helper: import agent module with mocked heavy deps ──

def _get_agent_module():
    """Import agent.py while mocking heavy dependencies that need API keys."""
    from unittest.mock import MagicMock

    # Pre-mock modules that fail without API keys
    if "tools" not in sys.modules:
        sys.modules["tools"] = MagicMock()

    # Mock ai_client at module level before agent imports it
    mock_client = MagicMock()
    mock_client.format_tools.return_value = []
    if "ai_client" not in sys.modules:
        mock_ai = MagicMock()
        mock_ai.get_client.return_value = mock_client
        sys.modules["ai_client"] = mock_ai

    import agent
    return agent


# Import once for all tests
_agent = _get_agent_module()


# ── Thinking/reasoning leak stripping ──

def test_strip_thinking_clean_text():
    """Clean text without reasoning is returned unchanged."""
    text = "הנה התשובה שלך"
    assert _agent._strip_thinking(text) == text


def test_strip_thinking_removes_leaked_reasoning():
    """Leaked reasoning at the start is stripped."""
    text = (
        "I need to check the user's calendar first.\n"
        "Let me search for relevant information.\n"
        "Based on the search results:\n"
        "\n"
        "הנה מה שמצאתי:"
    )
    result = _agent._strip_thinking(text)
    assert "I need to" not in result
    assert "הנה מה שמצאתי:" in result


def test_strip_thinking_preserves_text_without_markers():
    """Text that starts without reasoning markers is untouched."""
    text = "Sure! Here's a summary of the latest news:\n1. Item one\n2. Item two"
    assert _agent._strip_thinking(text) == text


def test_strip_thinking_handles_empty():
    """Empty/None input is handled gracefully."""
    assert _agent._strip_thinking("") == ""
    assert _agent._strip_thinking(None) is None


def test_strip_thinking_handles_only_reasoning():
    """If the entire text is reasoning, return original (fallback)."""
    text = "I need to analyze this.\nLet me think about it.\nBased on the data available."
    result = _agent._strip_thinking(text)
    assert len(result) > 0


# ── Correction detection ──

def test_correction_patterns_english():
    """English correction phrases are detected."""
    assert _agent._is_correction("No, that's wrong, I meant the other one") is True
    assert _agent._is_correction("You misunderstood me") is True
    assert _agent._is_correction("I don't want that") is True
    assert _agent._is_correction("Stop doing that") is True
    assert _agent._is_correction("I prefer shorter answers") is True
    assert _agent._is_correction("Next time, please don't include links") is True
    assert _agent._is_correction("Wrong!") is True


def test_correction_patterns_hebrew():
    """Hebrew correction phrases are detected."""
    assert _agent._is_correction("לא התכוונתי לזה") is True
    assert _agent._is_correction("זה לא נכון") is True
    assert _agent._is_correction("טעות, תנסה שוב") is True
    assert _agent._is_correction("תפסיק לעשות את זה") is True
    assert _agent._is_correction("אל תעשה את זה") is True


def test_correction_patterns_false_positives():
    """Normal messages should NOT be detected as corrections."""
    assert _agent._is_correction("What's the weather today?") is False
    assert _agent._is_correction("Tell me a joke") is False
    assert _agent._is_correction("Schedule a meeting for tomorrow") is False
    assert _agent._is_correction("Good morning!") is False
    assert _agent._is_correction("Thanks, that's helpful") is False


# ── Model selection ──

def _patch_models(model, model_pro):
    """Patch MODEL and MODEL_PRO on both config and agent modules."""
    import config
    originals = (config.MODEL, config.MODEL_PRO, _agent.MODEL, _agent.MODEL_PRO)
    config.MODEL = model
    config.MODEL_PRO = model_pro
    _agent.MODEL = model
    _agent.MODEL_PRO = model_pro
    return originals


def _restore_models(originals):
    import config
    config.MODEL, config.MODEL_PRO, _agent.MODEL, _agent.MODEL_PRO = originals


def test_should_use_pro_long_message():
    """Long messages should escalate to Pro model."""
    orig = _patch_models("claude-haiku-4-5-20251001", "claude-sonnet-4-5")
    try:
        assert _agent._should_use_pro("x" * 600) is True
    finally:
        _restore_models(orig)


def test_should_use_pro_complex_patterns():
    """Complex task keywords trigger Pro model."""
    orig = _patch_models("claude-haiku-4-5-20251001", "claude-sonnet-4-5")
    try:
        assert _agent._should_use_pro("compare these two restaurants") is True
        assert _agent._should_use_pro("analyze my spending patterns") is True
        assert _agent._should_use_pro("write me a detailed plan") is True
        assert _agent._should_use_pro("debug this code please") is True
        assert _agent._should_use_pro("research the best laptops") is True
    finally:
        _restore_models(orig)


def test_should_use_pro_simple_messages():
    """Simple messages stay on the base model."""
    orig = _patch_models("claude-haiku-4-5-20251001", "claude-sonnet-4-5")
    try:
        assert _agent._should_use_pro("hi") is False
        assert _agent._should_use_pro("what time is it") is False
        assert _agent._should_use_pro("set a reminder for 5pm") is False
    finally:
        _restore_models(orig)


def test_should_use_pro_tool_escalation():
    """After 3+ tool calls, should escalate to Pro."""
    orig = _patch_models("claude-haiku-4-5-20251001", "claude-sonnet-4-5")
    try:
        assert _agent._should_use_pro("simple question", tool_count_so_far=2) is False
        assert _agent._should_use_pro("simple question", tool_count_so_far=3) is True
    finally:
        _restore_models(orig)


def test_should_use_pro_same_model_returns_false():
    """When MODEL == MODEL_PRO, always returns False."""
    orig = _patch_models("claude-sonnet-4-5", "claude-sonnet-4-5")
    try:
        assert _agent._should_use_pro("analyze this complex thing") is False
        assert _agent._should_use_pro("x" * 1000) is False
    finally:
        _restore_models(orig)


# ── Tool registry (requires full tools import) ──
# These use pytest.importorskip to gracefully skip if deps are missing

def _try_import_tools():
    """Try importing tools; return None if deps are missing."""
    try:
        # Clear mock if it was set
        if "tools" in sys.modules and hasattr(sys.modules["tools"], "_mock_name"):
            del sys.modules["tools"]
        import tools
        # Check if it's a real module, not our mock
        if hasattr(tools, "ALL_TOOLS"):
            return tools
    except (ImportError, ValueError):
        pass
    return None


_tools = _try_import_tools()


@pytest.mark.skipif(_tools is None, reason="Full tool dependencies not available")
def test_all_tools_have_unique_names():
    """Every tool must have a unique name."""
    names = [t["name"] for t in _tools.ALL_TOOLS]
    assert len(names) == len(set(names)), f"Duplicate tool names: {[n for n in names if names.count(n) > 1]}"


@pytest.mark.skipif(_tools is None, reason="Full tool dependencies not available")
def test_all_tools_have_required_fields():
    """Every tool must have name, description, and input_schema."""
    for tool in _tools.ALL_TOOLS:
        assert "name" in tool, f"Tool missing 'name': {tool}"
        assert "description" in tool, f"Tool {tool.get('name')} missing 'description'"
        assert "input_schema" in tool, f"Tool {tool.get('name')} missing 'input_schema'"
        assert tool["input_schema"]["type"] == "object", f"Tool {tool['name']} input_schema type must be 'object'"


@pytest.mark.skipif(_tools is None, reason="Full tool dependencies not available")
def test_all_tools_have_executors():
    """Every registered tool name has a matching executor function."""
    for tool in _tools.ALL_TOOLS:
        assert tool["name"] in _tools._EXECUTORS, f"Tool {tool['name']} has no executor registered"


@pytest.mark.skipif(_tools is None, reason="Full tool dependencies not available")
def test_execute_unknown_tool_returns_error():
    """Executing a non-existent tool returns a JSON error."""
    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        _tools.execute_tool("nonexistent_tool", {}, 111)
    )
    assert "error" in result.lower() or "Unknown" in result
