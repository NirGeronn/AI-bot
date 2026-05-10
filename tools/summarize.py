"""Summarize tool — uses the configured LLM to compress long text into bullets/TL;DR."""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_MAX_INPUT_CHARS = 80000

SUMMARIZE_TOOLS = [
    {
        "name": "summarize_text",
        "description": (
            "Summarize a long block of text using the LLM. Use for inputs longer than "
            "~5K chars (articles, transcripts, threads). For shorter inputs, summarize "
            "directly without this tool. Returns a structured summary in the requested style."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The long text to summarize",
                },
                "style": {
                    "type": "string",
                    "enum": ["bullets", "tldr", "headline_bullets_bottomline"],
                    "description": "Output style (default 'bullets')",
                },
                "language": {
                    "type": "string",
                    "description": "Output language (default: match input). Examples: 'Hebrew', 'English'.",
                },
                "max_bullets": {
                    "type": "integer",
                    "description": "Max number of bullets when style is 'bullets' (default 7)",
                },
            },
            "required": ["text"],
        },
    },
]


def _build_prompt(text: str, style: str, language: str | None, max_bullets: int) -> str:
    lang = f"Output language: {language}." if language else "Match the language of the input text."
    if style == "tldr":
        instr = "Produce a single-paragraph TL;DR (3-4 sentences max), faithful to the source."
    elif style == "headline_bullets_bottomline":
        instr = (
            "Produce: (1) a one-line headline, (2) up to 6 bullets covering the key points, "
            "(3) a one-line bottom-line / takeaway. No preamble."
        )
    else:
        instr = f"Produce up to {max_bullets} concise bullets covering the key points. No preamble."
    return (
        f"{instr}\n{lang}\n"
        f"Do NOT invent facts not present in the source.\n\n"
        f"--- SOURCE ---\n{text}\n--- END ---"
    )


async def execute_summarize_tool(name: str, input_data: dict, chat_id: int) -> str:
    if name != "summarize_text":
        return json.dumps({"error": f"Unknown tool: {name}"})
    text = input_data.get("text", "")
    if not text:
        return json.dumps({"error": "text is required"})
    style = (input_data.get("style") or "bullets").lower()
    language = input_data.get("language")
    max_bullets = int(input_data.get("max_bullets") or 7)

    truncated = False
    if len(text) > _MAX_INPUT_CHARS:
        text = text[:_MAX_INPUT_CHARS]
        truncated = True

    prompt = _build_prompt(text, style, language, max_bullets)

    try:
        from ai_client import get_client
        client = get_client()
        messages = client.build_messages(
            system_prompt="You are a concise, faithful summarizer.",
            history=[],
            user_content=prompt,
        )
        response = await client.chat(messages, tools=None, max_tokens=1024, temperature=0.2)
        summary = (response.text or "").strip()
    except Exception as e:
        logger.error(f"summarize LLM call failed: {e}")
        return json.dumps({"error": f"LLM call failed: {e}"})

    return json.dumps({
        "ok": True,
        "style": style,
        "truncated_input": truncated,
        "summary": summary,
    })
