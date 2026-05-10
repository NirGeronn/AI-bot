from __future__ import annotations

import json
import logging
import re
from config import MODEL, MODEL_PRO, MAX_TOKENS, MAX_HISTORY
from ai_client import get_client
from skills_loader import get_base_system_prompt
from memory import (
    save_message, load_history, get_all_memories, record_usage,
    get_recent_daily_summaries, get_owner_profile, get_bot_diary,
)
from tools import execute_tool
from tool_router import select_tool_groups, get_formatted_tools
from error_log import log_error

logger = logging.getLogger(__name__)

# Patterns that indicate model reasoning/thinking leaked into output
_REASONING_MARKERS = re.compile(
    r'(?:'
    r'I (?:need to|will|should|have successfully|can see)'
    r'|Let me |Let\'s go through'
    r'|Here\'s (?:the|my) plan'
    r'|Now,? I (?:will|need|should)'
    r'|Based on (?:the|this)'
    r'|User preferences'
    r'|the user(?:\'s| is| wants| asked| specified| preference)'
    r'|Not (?:a major|Maccabi|relevant)'
    r'|THINKING'
    r')',
    re.IGNORECASE,
)


def _describe_api_error(exc: Exception) -> str:
    """Turn a provider API exception into a user-facing explanation."""
    raw = str(exc)
    low = raw.lower()

    inner = re.search(r"'message':\s*['\"]([^'\"]+)['\"]", raw)
    provider_msg = inner.group(1) if inner else None

    if "usage limit" in low or "monthly limit" in low:
        detail = provider_msg or "Usage limit reached on the LLM provider."
        return f"⚠️ LLM provider usage limit reached.\n\n{detail}\n\nRaise the cap in the provider console or wait for the reset."
    if "credit balance" in low or "insufficient" in low or "insufficient_quota" in low or "billing" in low:
        return f"⚠️ Low credit on LLM provider.\n\n{provider_msg or raw[:300]}\n\nTop up the account."
    if "invalid x-api-key" in low or "invalid_api_key" in low or "authentication" in low or "401" in raw[:20]:
        return f"⚠️ LLM provider rejected the API key (auth failure).\n\n{provider_msg or raw[:300]}"
    if "permission" in low and ("denied" in low or "not allowed" in low):
        return f"⚠️ LLM provider permission error.\n\n{provider_msg or raw[:300]}"
    if "rate_limit" in low or "rate limit" in low or "429" in raw[:20]:
        return f"⚠️ Rate-limited by LLM provider — too many requests.\n\n{provider_msg or raw[:300]}"
    if "overloaded" in low or "529" in raw[:20]:
        return "⚠️ LLM provider is overloaded (529). Try again shortly."
    if "internal server" in low or "500" in raw[:20] or "503" in raw[:20] or "502" in raw[:20] or "bad gateway" in low:
        return f"⚠️ LLM provider server error.\n\n{provider_msg or raw[:300]}"
    if "timeout" in low or "timed out" in low:
        return "⚠️ Timeout reaching the LLM provider (network slow or provider hung)."
    if "connection" in low or "dns" in low or "unreachable" in low or "getaddrinfo" in low:
        return "⚠️ Network / connectivity problem reaching the LLM provider (could be GCP networking, DNS, or provider outage)."
    if "context" in low and ("length" in low or "window" in low or "too long" in low or "too many tokens" in low):
        return f"⚠️ Context too large for the model.\n\n{provider_msg or raw[:300]}"
    if provider_msg:
        return f"⚠️ LLM provider error: {provider_msg}"
    return f"⚠️ LLM call failed: {raw[:400]}"


def _strip_thinking(text: str) -> str:
    """Remove leaked thinking/reasoning blocks from response text."""
    if not text:
        return text

    # Check if the text starts with reasoning content
    first_lines = text[:500]
    if not _REASONING_MARKERS.search(first_lines):
        return text  # No reasoning detected at the start

    # Strategy: find where the actual response begins after the reasoning block.
    # The actual response is typically the last coherent section after reasoning,
    # often starting after a line like "Now, I will format..." or after a blank line
    # followed by non-reasoning content (e.g. Hebrew text for Hebrew bot).
    lines = text.split('\n')
    best_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # If this line still looks like reasoning, move the candidate start forward
        if _REASONING_MARKERS.search(stripped):
            best_start = i + 1
        # Lines that are just bullet analysis like "* Football Games:" with reasoning after
        elif stripped.startswith('*') and i < len(lines) - 1 and _REASONING_MARKERS.search(lines[min(i+1, len(lines)-1)]):
            best_start = i + 1

    if best_start > 0 and best_start < len(lines):
        cleaned = '\n'.join(lines[best_start:]).strip()
        if cleaned:
            return cleaned

    return text

client = get_client()

# Keywords/patterns that suggest a complex task needing Pro model
_COMPLEX_PATTERNS = [
    r'\b(compare|analyze|summarize|explain in detail|deep dive|pros and cons)\b',
    r'\b(write me a|draft|compose|create a plan|strategy)\b',
    r'\b(research|investigate|find out everything)\b',
    r'\b(code|debug|fix this|refactor|implement)\b',
]
_COMPLEX_RE = re.compile('|'.join(_COMPLEX_PATTERNS), re.IGNORECASE)


def _should_use_pro(user_text: str, tool_count_so_far: int = 0) -> bool:
    """Decide if we should escalate to Pro model for this request."""
    if MODEL_PRO == MODEL:
        return False
    # Long messages often indicate complex requests
    if len(user_text) > 500:
        return True
    # Pattern-based detection
    if _COMPLEX_RE.search(user_text):
        return True
    # If we've already used 3+ tools, escalate for the remaining reasoning
    if tool_count_so_far >= 3:
        return True
    return False

# Human-friendly tool status messages
TOOL_STATUS = {
    "web_search": "Searching the web...",
    "web_research": "Researching (this may take a moment)...",
    "browse_url": "Reading webpage...",
    "gmail_check_inbox": "Checking inbox...",
    "gmail_search": "Searching emails...",
    "gmail_read_email": "Reading email...",
    "gmail_send": "Sending email...",
    "calendar_list_events": "Checking calendar...",
    "calendar_create_event": "Creating event...",
    "calendar_delete_event": "Deleting event...",
    "get_weather": "Checking weather...",
    "github_trending": "Fetching GitHub trends...",
    "speed_test": "Running speed test...",
    "check_breach": "Checking breach databases...",
    "is_it_down": "Pinging website...",
    "todo_add": "Updating todo list...",
    "remember": "Saving to memory...",
    "browser_navigate": "Opening in browser...",
    "browser_click": "Clicking...",
    "browser_type": "Typing...",
    "browser_screenshot": "Taking screenshot...",
}


async def _build_system_prompt(chat_id: int, memories: list[dict]) -> str:
    """Build the static, cacheable portion of the system prompt.

    Excludes dynamic content (timestamp, mood, active memory) which would
    bust the prompt cache on every call. Those go into the user message via
    _build_dynamic_preamble.
    """
    prompt = get_base_system_prompt()

    profile = await get_owner_profile(chat_id)
    if profile:
        prompt += f"\n\nOwner profile:\n{profile}"

    if memories:
        facts = "\n".join(f"- {m['key']}: {m['value']}" for m in memories)
        prompt += f"\n\nYou remember these facts about this user:\n{facts}"

    summaries = await get_recent_daily_summaries(chat_id, days=5)
    if summaries:
        summary_text = "\n".join(f"- {s['date']}: {s['summary']}" for s in summaries)
        prompt += f"\n\nRecent daily summaries (what happened in past days):\n{summary_text}"

    diary = await get_bot_diary(chat_id)
    if diary:
        prompt += f"\n\nYour behavioral principles (learned from past interactions):\n{diary}"

    return prompt


async def _build_dynamic_preamble(active_context: str | None = None) -> str:
    """Per-call dynamic content. Prepended to the user message so it stays
    OUT of the cached system prefix. Timestamp is rounded to the hour so
    consecutive calls within the same hour don't bust the cache."""
    from mood import mood_prompt_section
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from config import USER_TIMEZONE

    now = datetime.now(ZoneInfo(USER_TIMEZONE))
    parts = [
        f"[Current date/time ({USER_TIMEZONE}): "
        f"{now.strftime('%A, %Y-%m-%d %H:00')} (rounded to hour). "
        f"Today is {now.strftime('%A')}.]",
        mood_prompt_section(),
    ]

    try:
        from tools.scheduler import get_schedule_brief
        schedule_brief = await get_schedule_brief()
        if schedule_brief:
            parts.append(f"[Scheduled messages]\n{schedule_brief}")
    except Exception as e:
        logger.warning(f"Schedule brief failed: {e}")

    if active_context:
        parts.append(f"[Active memory — context relevant to the current message]\n{active_context}")
    return "\n\n".join(p for p in parts if p)


async def _load_compacted_history(chat_id: int) -> list[dict]:
    """
    Load conversation history with compaction.
    Recent messages (last 20) are kept in full.
    Older messages (20-60) are summarized into a compact context block.
    """
    all_messages = await load_history(chat_id, limit=60)

    if len(all_messages) <= 20:
        return all_messages

    # Split into old (to compact) and recent (to keep)
    recent = all_messages[-20:]
    old = all_messages[:-20]

    # Compact old messages into a summary
    old_text = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content'][:200]}"
        for m in old
    )

    try:
        summary_prompt = "Summarize this conversation into 3-6 bullet points. Include key topics, decisions, tasks mentioned, and any important context. Be concise."
        summary_messages = client.build_messages(
            summary_prompt, [], old_text
        )
        summary_resp = await client.chat(
            summary_messages, max_tokens=300, temperature=0.2
        )

        if summary_resp.input_tokens or summary_resp.cache_creation_input_tokens or summary_resp.cache_read_input_tokens:
            await record_usage(
                chat_id, summary_resp.input_tokens, summary_resp.output_tokens, MODEL,
                cache_creation_tokens=summary_resp.cache_creation_input_tokens,
                cache_read_tokens=summary_resp.cache_read_input_tokens,
            )

        summary = summary_resp.text or ""

        # Prepend compact summary as a context message
        compacted = [
            {"role": "user", "content": f"[Earlier conversation context]\n{summary}"},
            {"role": "assistant", "content": "Got it, I have the context from our earlier conversation."},
        ]
        return compacted + recent

    except Exception as e:
        logger.warning(f"Compaction failed, falling back to truncation: {e}")
        await log_error(chat_id, "compaction_error", "History compaction failed", str(e))
        return recent


async def run_agent(chat_id: int, user_text: str, image_data: dict | None = None, status_callback=None, tool_groups: list[str] | None = None, skip_active_memory: bool = False, skip_history: bool = False) -> str:
    """
    Run the agent. Optionally pass image_data={"base64": ..., "media_type": ...}
    to include an image in the user message.
    status_callback: async function(text) to send status updates to the user.
    skip_active_memory: when True, don't inject past summaries/memories from
    active_memory. Used by scheduled jobs whose prompts are self-contained
    and where injected summaries tend to drift the model off-task.
    skip_history: when True, run with no prior conversation history. Used by
    scheduled jobs so the agent doesn't pull earlier scheduled prompts
    (e.g. morning_weather) into the current response.
    """
    # Load conversation history with compaction (skipped for scheduled jobs)
    messages = [] if skip_history else await _load_compacted_history(chat_id)
    memories = await get_all_memories(chat_id)

    # Active Memory: search for context relevant to the current message
    active_context = None
    if user_text and not skip_active_memory:
        try:
            from active_memory import search_relevant_context
            active_context = await search_relevant_context(chat_id, user_text)
        except Exception as e:
            logger.warning(f"Active memory search failed: {e}")

    # Static system prompt (cacheable). Dynamic content (timestamp, mood,
    # active memory) goes into the user message instead so the cache prefix
    # stays stable across calls.
    system_prompt = await _build_system_prompt(chat_id, memories)
    preamble = await _build_dynamic_preamble(active_context=active_context)

    # Build user content (text or multimodal). Prepend the dynamic preamble
    # to whatever the user said.
    user_text_with_preamble = f"{preamble}\n\n{user_text}" if user_text else preamble
    if image_data:
        text = user_text_with_preamble if user_text else f"{preamble}\n\nWhat's in this image?"
        user_content = client.make_user_image_content(text, image_data)
    else:
        user_content = user_text_with_preamble

    # Build full message structure
    full_messages = client.build_messages(system_prompt, messages, user_content)

    # Select relevant tools based on message content
    selected_tools = select_tool_groups(user_text, image_data=image_data, explicit_groups=tool_groups)
    formatted_tools = get_formatted_tools(client, selected_tools) if selected_tools else None

    # Always use MODEL_PRO for the agent loop — it handles tools reliably.
    # MODEL is used for internal calls (summaries, compaction, diary).
    current_model = MODEL_PRO

    # Agentic tool loop with error recovery
    max_iterations = 10
    previous_tool_calls = set()
    consecutive_errors = 0
    max_consecutive_errors = 3
    last_response = None
    last_api_err = None
    total_tool_calls = 0

    for iteration in range(max_iterations):
        try:
            response = await client.chat(
                full_messages,
                tools=formatted_tools if formatted_tools else None,
                max_tokens=MAX_TOKENS,
                temperature=0.1,
                model_override=current_model if current_model != MODEL else None,
            )
        except Exception as api_err:
            logger.error(f"API call failed (iteration {iteration}): {api_err}")
            await log_error(chat_id, "api_error", f"API call failed (iteration {iteration})",
                          str(api_err), user_message=user_text)
            last_api_err = api_err
            consecutive_errors += 1
            if consecutive_errors >= max_consecutive_errors:
                return _describe_api_error(last_api_err)
            continue

        last_response = response
        consecutive_errors = 0

        # Track token usage (including cache writes/reads)
        if (response.input_tokens or response.output_tokens
                or response.cache_creation_input_tokens or response.cache_read_input_tokens):
            await record_usage(
                chat_id, response.input_tokens, response.output_tokens, current_model,
                cache_creation_tokens=response.cache_creation_input_tokens,
                cache_read_tokens=response.cache_read_input_tokens,
            )

        # Append assistant message to conversation
        client.append_assistant_msg(full_messages, response)

        if response.finish_reason == "stop":
            break

        # Process tool calls
        if response.tool_calls:
            total_tool_calls += len(response.tool_calls)
            for tc in response.tool_calls:
                tool_name = tc.name
                tool_input = tc.arguments

                # Duplicate detection — prevent infinite loops
                call_sig = f"{tool_name}:{json.dumps(tool_input, sort_keys=True)}"
                if call_sig in previous_tool_calls:
                    logger.warning(f"Duplicate tool call detected: {tool_name}, injecting hint")
                    client.append_tool_result(
                        full_messages, tc.id, tool_name,
                        json.dumps({
                            "error": "DUPLICATE_CALL",
                            "message": f"You already called {tool_name} with the same arguments. "
                                       "Try a different approach or provide your answer with the information you already have.",
                        }),
                    )
                    continue
                previous_tool_calls.add(call_sig)

                logger.info(f"Tool call: {tool_name}({tool_input})")

                # Track tool usage
                try:
                    from habits import track_tool_use
                    await track_tool_use(chat_id, tool_name)
                except Exception:
                    pass

                # Send activity status to user
                if status_callback and tool_name in TOOL_STATUS:
                    try:
                        await status_callback(TOOL_STATUS[tool_name])
                    except Exception:
                        pass

                # Execute with error recovery
                try:
                    result = await execute_tool(tool_name, tool_input, chat_id)
                except Exception as tool_err:
                    logger.error(f"Tool execution error: {tool_name}: {tool_err}")
                    await log_error(chat_id, "tool_error", f"Tool '{tool_name}' crashed",
                                  str(tool_err), user_message=user_text,
                                  extra={"tool": tool_name, "args": tool_input})
                    result = json.dumps({
                        "error": str(tool_err),
                        "hint": "This tool call failed. Consider trying a different approach "
                                "or answering with the information you already have.",
                    })

                logger.info(f"Tool result: {result[:200]}")

                # Check if result contains an error
                try:
                    result_data = json.loads(result)
                    if isinstance(result_data, dict) and "error" in result_data:
                        logger.warning(f"Tool returned error: {result_data['error'][:100]}")
                        await log_error(chat_id, "tool_result_error", f"Tool '{tool_name}' returned error",
                                      result_data["error"][:500], user_message=user_text,
                                      extra={"tool": tool_name, "args": tool_input})
                except (json.JSONDecodeError, TypeError):
                    pass

                client.append_tool_result(full_messages, tc.id, tool_name, result)

    # Extract final text and strip any leaked thinking blocks
    final_text = (last_response.text if last_response else None) or ""
    final_text = _strip_thinking(final_text)

    # Log empty responses
    if not final_text.strip():
        await log_error(chat_id, "empty_response", "Bot returned empty response",
                       f"finish_reason={last_response.finish_reason if last_response else 'no_response'}, "
                       f"iterations={iteration+1 if 'iteration' in dir() else '?'}",
                       user_message=user_text)

    # Persist to DB (with image description for better context in future conversations)
    if image_data:
        save_text = user_text or "[sent an image]"
        # Extract a brief image description from the response for future context
        img_desc = final_text[:200] if final_text else ""
        await save_message(chat_id, "user", f"[Image: {img_desc}] {save_text}")
    else:
        await save_message(chat_id, "user", user_text)
    await save_message(chat_id, "assistant", final_text)

    # Real-time learning: detect corrections and update behavior immediately
    if user_text and _is_correction(user_text):
        try:
            await _learn_from_correction(chat_id, user_text, final_text)
        except Exception as e:
            logger.warning(f"Real-time learning failed: {e}")

    return final_text or "(no response)"


# Correction detection patterns
_CORRECTION_PATTERNS = re.compile(
    r'('
    r'no[,.]?\s+(i meant|that.?s wrong|not what i|incorrect|you got it wrong)'
    r'|that.?s not (right|correct|what i)'
    r'|wrong[,!.]'
    r'|you misunderstood'
    r'|i (didn.?t mean|don.?t want|never said)'
    r'|stop (doing|saying|suggesting)'
    r'|don.?t (ever|always|keep)'
    r'|please don.?t'
    r'|i prefer'
    r'|next time[,.]?\s+(please|don.?t|do)'
    r'|לא התכוונתי'
    r'|זה לא נכון'
    r'|טעות'
    r'|לא ככה'
    r'|תפסיק'
    r'|אל תעשה'
    r'|בפעם הבאה'
    r')',
    re.IGNORECASE
)


def _is_correction(text: str) -> bool:
    """Check if the user's message is a correction or behavioral feedback."""
    return bool(_CORRECTION_PATTERNS.search(text))


async def _learn_from_correction(chat_id: int, user_text: str, bot_response: str):
    """Extract a behavioral lesson from a user correction and update diary immediately."""
    from memory import get_bot_diary, save_bot_diary

    current_diary = await get_bot_diary(chat_id) or ""

    diary_prompt = (
        "The user just corrected the assistant. Extract a brief behavioral principle "
        "(1 line) from this correction. If the correction is trivial or not about behavior, "
        "return NONE. Otherwise return the principle to add.\n\n"
        "Current diary:\n" + (current_diary or "(empty)") + "\n\n"
        "User's correction: " + user_text[:500] + "\n"
        "Bot's response: " + bot_response[:300]
    )

    messages = client.build_messages(diary_prompt, [], "Extract principle or return NONE")
    response = await client.chat(messages, max_tokens=150, temperature=0.2)

    if response.input_tokens or response.cache_creation_input_tokens or response.cache_read_input_tokens:
        await record_usage(
            chat_id, response.input_tokens, response.output_tokens, MODEL,
            cache_creation_tokens=response.cache_creation_input_tokens,
            cache_read_tokens=response.cache_read_input_tokens,
        )

    principle = (response.text or "").strip()
    if principle and "NONE" not in principle.upper() and len(principle) > 5:
        # Append to diary
        if current_diary:
            lines = current_diary.strip().split("\n")
            # Keep max 10 principles
            if len(lines) >= 10:
                lines = lines[-9:]  # drop oldest
            lines.append(principle)
            new_diary = "\n".join(lines)
        else:
            new_diary = principle
        await save_bot_diary(chat_id, new_diary)
        logger.info(f"Real-time learning: added principle for chat {chat_id}: {principle[:80]}")


async def generate_daily_summary(chat_id: int) -> str | None:
    """Generate a summary of today's conversations and save it. Also update owner profile."""
    from memory import (
        get_today_conversations, save_daily_summary,
        get_owner_profile, save_owner_profile, get_all_memories,
    )
    from datetime import datetime, timezone

    conversations = await get_today_conversations(chat_id)
    if len(conversations) < 4:
        return None

    conv_text = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content'][:300]}"
        for m in conversations[:100]
    )

    # Generate daily summary
    summary_prompt = (
        "You are a summarizer. Given today's conversations between a user and their AI assistant, "
        "write a brief summary (2-4 sentences) of the main topics discussed, tasks done, "
        "and any notable events. Be factual and concise."
    )
    summary_messages = client.build_messages(
        summary_prompt, [],
        f"Summarize today's conversations:\n\n{conv_text}",
    )
    summary_resp = await client.chat(summary_messages, max_tokens=500, temperature=0.3)

    if summary_resp.input_tokens or summary_resp.cache_creation_input_tokens or summary_resp.cache_read_input_tokens:
        await record_usage(
            chat_id, summary_resp.input_tokens, summary_resp.output_tokens, MODEL,
            cache_creation_tokens=summary_resp.cache_creation_input_tokens,
            cache_read_tokens=summary_resp.cache_read_input_tokens,
        )

    summary = summary_resp.text or ""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    await save_daily_summary(chat_id, today, summary, len(conversations))

    # Update owner profile
    memories = await get_all_memories(chat_id)
    current_profile = await get_owner_profile(chat_id) or ""

    if memories:
        mem_text = "\n".join(f"- {m['key']}: {m['value']}" for m in memories)
        profile_prompt = (
            "You maintain a concise owner profile for a personal AI assistant. "
            "Given the user's stored memories and today's conversations, "
            "update/write a compact profile (max 10 lines) covering: "
            "name, occupation, key interests, preferences, communication style, "
            "and any important personal details. Keep only confirmed facts. "
            "Write in third person. If the current profile is good and nothing new was learned, "
            "return it unchanged."
        )
        profile_messages = client.build_messages(
            profile_prompt, [],
            f"Current profile:\n{current_profile or '(none yet)'}\n\n"
            f"Stored memories:\n{mem_text}\n\n"
            f"Today's conversations:\n{conv_text[:3000]}",
        )
        profile_resp = await client.chat(profile_messages, max_tokens=600, temperature=0.3)

        if profile_resp.input_tokens or profile_resp.cache_creation_input_tokens or profile_resp.cache_read_input_tokens:
            await record_usage(
                chat_id, profile_resp.input_tokens, profile_resp.output_tokens, MODEL,
                cache_creation_tokens=profile_resp.cache_creation_input_tokens,
                cache_read_tokens=profile_resp.cache_read_input_tokens,
            )

        new_profile = profile_resp.text or ""
        if new_profile.strip():
            await save_owner_profile(chat_id, new_profile.strip())

    # Update bot diary
    from memory import get_bot_diary, save_bot_diary
    current_diary = await get_bot_diary(chat_id) or ""

    try:
        diary_prompt = (
            "You maintain a bot's private diary of behavioral principles and lessons learned. "
            "Given the current diary and today's conversations, update the diary. "
            "Rules:\n"
            "- Keep max 8 behavioral principles (things to do/avoid when interacting with this user)\n"
            "- Each principle should be a concrete, actionable rule\n"
            "- Remove principles that seem wrong or outdated\n"
            "- Add new ones only if clearly confirmed by multiple interactions\n"
            "- Keep it concise — each principle is 1 line\n"
            "- Format: numbered list of principles"
        )
        diary_messages = client.build_messages(
            diary_prompt, [],
            f"Current diary:\n{current_diary or '(empty — first reflection)'}\n\n"
            f"Today's conversations:\n{conv_text[:3000]}",
        )
        diary_resp = await client.chat(diary_messages, max_tokens=400, temperature=0.3)

        if diary_resp.input_tokens or diary_resp.cache_creation_input_tokens or diary_resp.cache_read_input_tokens:
            await record_usage(
                chat_id, diary_resp.input_tokens, diary_resp.output_tokens, MODEL,
                cache_creation_tokens=diary_resp.cache_creation_input_tokens,
                cache_read_tokens=diary_resp.cache_read_input_tokens,
            )

        new_diary = diary_resp.text or ""
        if new_diary.strip():
            await save_bot_diary(chat_id, new_diary.strip())
            logger.info(f"Bot diary updated for chat {chat_id}")
    except Exception as e:
        logger.warning(f"Bot diary update failed: {e}")

    logger.info(f"Daily summary generated for chat {chat_id}: {summary[:100]}")
    return summary
