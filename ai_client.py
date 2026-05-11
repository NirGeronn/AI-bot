"""
Unified AI client supporting Anthropic and OpenAI.
Provides a consistent interface so agent.py doesn't need provider-specific code.
Includes retry with exponential backoff for resilience.
"""
from __future__ import annotations
import json
import asyncio
import logging
from dataclasses import dataclass, field
from config import AI_PROVIDER, AI_API_KEY, MODEL

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds
RETRY_MAX_DELAY = 15.0


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class AIResponse:
    text: str | None
    tool_calls: list[ToolCall]
    finish_reason: str  # "stop" or "tool_calls"
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


async def _retry_with_backoff(func, *args, **kwargs):
    """Execute an async function with exponential backoff retry."""
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                logger.warning(f"API call failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}, retrying in {delay:.1f}s")
                await asyncio.sleep(delay)
            else:
                logger.error(f"API call failed after {MAX_RETRIES} attempts: {e}")
    raise last_err


def _to_openai_tools(anthropic_tools: list[dict]) -> list[dict]:
    """Convert Anthropic-style tool schemas to OpenAI function calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for tool in anthropic_tools
    ]


class AnthropicClient:
    def __init__(self):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=AI_API_KEY)
        self._call_counter = 0

    def format_tools(self, tools: list[dict]) -> list[dict]:
        # Tool schemas are already in Anthropic format (name, description, input_schema)
        return tools

    def build_messages(self, system_prompt: str, history: list[dict], user_content) -> dict:
        """Build Anthropic message structure. Returns dict with 'system' and 'messages'."""
        messages = []

        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                continue
            elif role == "assistant":
                parts = []
                if content:
                    parts.append({"type": "text", "text": content})
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        func = tc.get("function", {})
                        try:
                            args = json.loads(func.get("arguments", "{}"))
                        except json.JSONDecodeError:
                            args = {}
                        parts.append({
                            "type": "tool_use",
                            "id": tc.get("id", f"tc_{self._call_counter}"),
                            "name": func.get("name", ""),
                            "input": args,
                        })
                if parts:
                    messages.append({"role": "assistant", "content": parts})
            elif role == "tool":
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": content,
                }
                # Merge into last user message if it has tool_results, else create new
                if messages and messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], list) and messages[-1]["content"] and messages[-1]["content"][0].get("type") == "tool_result":
                    messages[-1]["content"].append(tool_result)
                else:
                    messages.append({"role": "user", "content": [tool_result]})
            else:
                if isinstance(content, list):
                    parts = []
                    for item in content:
                        if item.get("type") == "text":
                            parts.append({"type": "text", "text": item["text"]})
                        elif item.get("type") == "image_url":
                            url = item["image_url"]["url"]
                            if url.startswith("data:"):
                                header, b64 = url.split(",", 1)
                                mime = header.split(":")[1].split(";")[0]
                                parts.append({
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": mime,
                                        "data": b64,
                                    },
                                })
                    messages.append({"role": "user", "content": parts})
                else:
                    messages.append({"role": "user", "content": content or ""})

        # Add current user message
        if isinstance(user_content, list):
            parts = []
            for item in user_content:
                if item.get("type") == "text":
                    parts.append({"type": "text", "text": item["text"]})
                elif item.get("type") == "image_url":
                    url = item["image_url"]["url"]
                    if url.startswith("data:"):
                        header, b64 = url.split(",", 1)
                        mime = header.split(":")[1].split(";")[0]
                        parts.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime,
                                "data": b64,
                            },
                        })
            messages.append({"role": "user", "content": parts})
        else:
            messages.append({"role": "user", "content": user_content})

        # Ensure messages alternate roles (Anthropic requirement)
        merged = []
        for msg in messages:
            if merged and merged[-1]["role"] == msg["role"]:
                # Merge consecutive same-role messages
                prev = merged[-1]
                prev_content = prev["content"] if isinstance(prev["content"], list) else [{"type": "text", "text": prev["content"]}]
                new_content = msg["content"] if isinstance(msg["content"], list) else [{"type": "text", "text": msg["content"]}]
                merged[-1]["content"] = prev_content + new_content
            else:
                merged.append(msg)

        # Anthropic requires first message to be from user
        if merged and merged[0]["role"] != "user":
            merged.insert(0, {"role": "user", "content": "(continuing conversation)"})

        return {"system": system_prompt, "messages": merged}

    def make_user_image_content(self, text: str, image_data: dict) -> list[dict]:
        """Build multimodal user content (in OpenAI format, converted later in build_messages)."""
        return [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{image_data['media_type']};base64,{image_data['base64']}",
                },
            },
            {"type": "text", "text": text},
        ]

    async def chat(self, messages, tools=None, max_tokens: int = 4096, temperature: float = 0.1, model_override: str = None) -> AIResponse:
        use_model = model_override or MODEL

        system_prompt = messages["system"]
        msg_list = messages["messages"]

        # Wrap system prompt into a single cached block so the prefix (skills,
        # memories, etc.) hits the cache across calls. Use 1h TTL because the
        # bot's heartbeat runs every 1-2 hours; the default 5m would expire.
        if isinstance(system_prompt, str):
            system_param = [{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }] if system_prompt else None
        else:
            system_param = system_prompt

        # Also mark the last tool with cache_control so the tool schemas
        # (largest static payload after the system prompt) get cached too.
        tools_param = tools
        if tools:
            tools_param = [dict(t) for t in tools]
            tools_param[-1] = {
                **tools_param[-1],
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }

        async def _call():
            kwargs = {
                "model": use_model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": msg_list,
            }
            if system_param:
                kwargs["system"] = system_param
            if tools_param:
                kwargs["tools"] = tools_param
            return await self.client.messages.create(**kwargs)

        response = await _retry_with_backoff(_call)

        if response.usage:
            cw = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            cr = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            if cw or cr:
                logger.info(
                    f"cache: write={cw} read={cr} fresh_input={response.usage.input_tokens}"
                )

        text = None
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                text = (text or "") + block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=dict(block.input) if block.input else {},
                ))

        return AIResponse(
            text=text,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if response.stop_reason == "tool_use" else "stop",
            input_tokens=response.usage.input_tokens if response.usage else 0,
            output_tokens=response.usage.output_tokens if response.usage else 0,
            cache_creation_input_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        )

    def append_assistant_msg(self, messages: dict, response: AIResponse):
        """Append assistant response to messages for multi-turn."""
        content = []
        if response.text:
            content.append({"type": "text", "text": response.text})
        for tc in response.tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.arguments,
            })
        if content:
            messages["messages"].append({"role": "assistant", "content": content})

    def append_tool_result(self, messages: dict, tool_call_id: str, tool_name: str, result: str):
        """Append tool result to messages."""
        tool_result = {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": result,
        }
        # Merge into last user message if it already has tool_results
        last = messages["messages"][-1] if messages["messages"] else None
        if (last and last["role"] == "user" and isinstance(last["content"], list)
                and last["content"] and last["content"][0].get("type") == "tool_result"):
            last["content"].append(tool_result)
        else:
            messages["messages"].append({"role": "user", "content": [tool_result]})


class OpenAIClient:
    def __init__(self):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=AI_API_KEY)

    def format_tools(self, tools: list[dict]) -> list[dict]:
        return _to_openai_tools(tools)

    def build_messages(self, system_prompt: str, history: list[dict], user_content) -> list[dict]:
        """Build OpenAI message array."""
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        if isinstance(user_content, list):
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": user_content})
        return messages

    def make_user_image_content(self, text: str, image_data: dict) -> list[dict]:
        """Build multimodal user content with image."""
        return [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{image_data['media_type']};base64,{image_data['base64']}",
                },
            },
            {"type": "text", "text": text},
        ]

    async def chat(self, messages: list, tools=None, max_tokens: int = 4096, temperature: float = 0.1, model_override: str = None) -> AIResponse:
        use_model = model_override or MODEL

        # Newer OpenAI models (e.g. gpt-5.x, o1, o3) only accept the default
        # temperature. Omit the param when the model name signals that family.
        omit_temperature = (
            use_model.startswith(("gpt-5", "o1", "o3", "o4"))
        )

        async def _call():
            kwargs = {
                "model": use_model,
                "max_completion_tokens": max_tokens,
                "messages": messages,
                "tools": tools if tools else None,
            }
            if not omit_temperature:
                kwargs["temperature"] = temperature
            return await self.client.chat.completions.create(**kwargs)

        response = await _retry_with_backoff(_call)

        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        return AIResponse(
            text=message.content,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if message.tool_calls else "stop",
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
        )

    def append_assistant_msg(self, messages: list, response: AIResponse):
        """Append assistant response to message list for multi-turn."""
        msg = {"role": "assistant", "content": response.text or ""}
        if response.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in response.tool_calls
            ]
        messages.append(msg)

    def append_tool_result(self, messages: list, tool_call_id: str, tool_name: str, result: str):
        """Append tool result to message list."""
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result,
        })


def get_client():
    """Get the AI client based on AI_PROVIDER config."""
    if AI_PROVIDER == "anthropic":
        return AnthropicClient()
    return OpenAIClient()
