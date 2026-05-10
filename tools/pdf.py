"""PDF reading tool — pulls text out of PDFs from local paths or URLs."""
from __future__ import annotations

import io
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_MAX_TEXT_CHARS = 60000  # truncate very long PDFs to keep prompt sane

PDF_TOOLS = [
    {
        "name": "read_pdf",
        "description": (
            "Extract text from a PDF file. Accepts a local file path on the bot host "
            "or an http(s) URL pointing to a PDF. Returns plain text (truncated to "
            f"{_MAX_TEXT_CHARS} chars). For scanned/image PDFs, reports that no text "
            "could be extracted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Local path or http(s) URL to a PDF",
                },
                "max_chars": {
                    "type": "integer",
                    "description": f"Optional cap on returned text length (default {_MAX_TEXT_CHARS})",
                },
            },
            "required": ["source"],
        },
    },
]


async def _fetch_bytes(source: str) -> bytes:
    if source.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(source)
            r.raise_for_status()
            return r.content
    if not os.path.isfile(source):
        raise FileNotFoundError(f"No such file: {source}")
    with open(source, "rb") as f:
        return f.read()


def _extract_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader  # type: ignore

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for i, page in enumerate(reader.pages):
        try:
            pages.append(page.extract_text() or "")
        except Exception as e:
            logger.warning(f"PDF page {i} extract failed: {e}")
    return "\n\n".join(p for p in pages if p.strip())


async def execute_pdf_tool(name: str, input_data: dict, chat_id: int) -> str:
    if name != "read_pdf":
        return json.dumps({"error": f"Unknown tool: {name}"})
    source = input_data.get("source", "")
    max_chars = input_data.get("max_chars") or _MAX_TEXT_CHARS
    if not source:
        return json.dumps({"error": "source is required"})
    try:
        data = await _fetch_bytes(source)
    except Exception as e:
        return json.dumps({"error": f"fetch failed: {e}"})
    try:
        text = _extract_text(data)
    except Exception as e:
        return json.dumps({"error": f"PDF parse failed: {e}"})
    if not text.strip():
        return json.dumps({
            "ok": False,
            "reason": "no_extractable_text",
            "hint": "PDF likely scanned/image-based; OCR not configured.",
        })
    truncated = len(text) > max_chars
    return json.dumps({
        "ok": True,
        "chars": len(text),
        "truncated": truncated,
        "text": text[:max_chars],
    })
