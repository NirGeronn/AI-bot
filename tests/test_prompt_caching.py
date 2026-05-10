"""Tests for the prompt-caching wiring in ai_client.AnthropicClient.

We stub the Anthropic SDK and assert: (a) cache_control is always sent on
messages.create, and (b) cache_creation/cache_read fields from the response
flow back into AIResponse so callers (the bot's logger) can verify hit rates."""
from __future__ import annotations

import os
import sys
import types
import pytest


@pytest.fixture
def stubbed_anthropic_module(monkeypatch):
    """Install a minimal fake `anthropic` module so AnthropicClient.__init__'s
    `import anthropic` picks it up. We do NOT touch AI_PROVIDER or reload
    modules — AnthropicClient can be instantiated directly and the fake
    accepts any api_key."""
    captured = {}

    class FakeUsage:
        def __init__(self, input_tokens=10, output_tokens=20,
                     cache_creation_input_tokens=0, cache_read_input_tokens=0):
            self.input_tokens = input_tokens
            self.output_tokens = output_tokens
            self.cache_creation_input_tokens = cache_creation_input_tokens
            self.cache_read_input_tokens = cache_read_input_tokens

    class FakeBlock:
        def __init__(self, text):
            self.type = "text"
            self.text = text

    class FakeResponse:
        def __init__(self, usage):
            self.content = [FakeBlock("hello")]
            self.stop_reason = "end_turn"
            self.usage = usage

    class FakeMessages:
        def __init__(self, response_factory):
            self._response_factory = response_factory

        async def create(self, **kwargs):
            captured["kwargs"] = kwargs
            return self._response_factory()

    class FakeAsyncAnthropic:
        _response = None

        def __init__(self, **kwargs):
            self.messages = FakeMessages(lambda: FakeAsyncAnthropic._response)

    fake_module = types.ModuleType("anthropic")
    fake_module.AsyncAnthropic = FakeAsyncAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    # Other test files (e.g. test_agent_behavior) install a MagicMock under
    # "ai_client" in sys.modules to dodge API-key requirements. Force a real
    # reimport here so we test the actual AnthropicClient.
    sys.modules.pop("ai_client", None)
    import importlib
    import ai_client
    ai_client = importlib.reload(ai_client) if not hasattr(ai_client, "AnthropicClient") else ai_client
    return ai_client, FakeAsyncAnthropic, FakeUsage, FakeResponse, captured


@pytest.mark.asyncio
async def test_cache_control_attached_to_system_block(stubbed_anthropic_module):
    """cache_control belongs INSIDE the system content block (Anthropic API
    contract), not as a top-level kwarg to messages.create."""
    ai_client, FakeAsyncAnthropic, FakeUsage, FakeResponse, captured = stubbed_anthropic_module
    FakeAsyncAnthropic._response = FakeResponse(FakeUsage())

    client = ai_client.AnthropicClient()
    msgs = client.build_messages(
        "You are helpful.",
        history=[],
        user_content="hi",
    )
    await client.chat(msgs, tools=None, max_tokens=100)

    kwargs = captured["kwargs"]
    # No top-level cache_control kwarg (the old broken setup).
    assert "cache_control" not in kwargs

    # System is a list with one cached block carrying the prompt.
    system = kwargs["system"]
    assert isinstance(system, list) and len(system) == 1
    assert system[0]["type"] == "text"
    assert system[0]["text"] == "You are helpful."
    assert system[0]["cache_control"]["type"] == "ephemeral"
    # 1h TTL because heartbeats run hourly; 5m would always expire.
    assert system[0]["cache_control"]["ttl"] == "1h"


@pytest.mark.asyncio
async def test_response_exposes_cache_read_and_write_tokens(stubbed_anthropic_module):
    """When the API reports cache_read_input_tokens, AIResponse must surface it."""
    ai_client, FakeAsyncAnthropic, FakeUsage, FakeResponse, _ = stubbed_anthropic_module

    FakeAsyncAnthropic._response = FakeResponse(
        FakeUsage(
            input_tokens=12,
            output_tokens=34,
            cache_creation_input_tokens=2048,
            cache_read_input_tokens=4096,
        )
    )
    client = ai_client.AnthropicClient()
    msgs = client.build_messages("system", [], "hi")
    resp = await client.chat(msgs, tools=None, max_tokens=100)

    assert resp.input_tokens == 12
    assert resp.output_tokens == 34
    assert resp.cache_creation_input_tokens == 2048
    assert resp.cache_read_input_tokens == 4096


@pytest.mark.asyncio
async def test_response_handles_old_sdk_without_cache_fields(stubbed_anthropic_module):
    """If the SDK's usage object doesn't carry cache_* attributes, AIResponse
    should default them to 0 — never raise AttributeError."""
    ai_client, FakeAsyncAnthropic, _, FakeResponse, _ = stubbed_anthropic_module

    class BareUsage:
        input_tokens = 5
        output_tokens = 10
        # Intentionally no cache_creation_input_tokens / cache_read_input_tokens.

    FakeAsyncAnthropic._response = FakeResponse(BareUsage())
    client = ai_client.AnthropicClient()
    msgs = client.build_messages("system", [], "hi")
    resp = await client.chat(msgs, tools=None, max_tokens=100)

    assert resp.cache_creation_input_tokens == 0
    assert resp.cache_read_input_tokens == 0


@pytest.mark.asyncio
async def test_last_tool_gets_cache_control(stubbed_anthropic_module):
    """The last tool carries cache_control so the entire tool list (the
    largest static payload after the system prompt) gets cached too."""
    ai_client, FakeAsyncAnthropic, FakeUsage, FakeResponse, captured = stubbed_anthropic_module
    FakeAsyncAnthropic._response = FakeResponse(FakeUsage())

    client = ai_client.AnthropicClient()
    msgs = client.build_messages("system", [], "hi")
    tools = [
        {"name": "a", "description": "first", "input_schema": {"type": "object", "properties": {}}},
        {"name": "b", "description": "second", "input_schema": {"type": "object", "properties": {}}},
    ]
    await client.chat(msgs, tools=tools, max_tokens=100)

    sent_tools = captured["kwargs"]["tools"]
    assert sent_tools[0].get("cache_control") is None
    assert sent_tools[-1]["cache_control"]["type"] == "ephemeral"
    assert sent_tools[-1]["cache_control"]["ttl"] == "1h"
    # Verify we didn't mutate the caller's list.
    assert "cache_control" not in tools[-1]


def test_max_history_is_set_to_30():
    """The cost-reduction change today: MAX_HISTORY 100 → 30."""
    import config
    assert config.MAX_HISTORY == 30
