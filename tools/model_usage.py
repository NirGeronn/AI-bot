"""Model usage tool — surfaces aggregated token/cost stats from the local usage table."""
from __future__ import annotations

import json
import logging
import time

import aiosqlite

from config import DB_PATH, PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M

logger = logging.getLogger(__name__)

MODEL_USAGE_TOOLS = [
    {
        "name": "get_model_usage",
        "description": (
            "Get aggregated LLM token usage and approximate USD cost for the bot itself. "
            "Useful when the user asks how much the bot cost them, how many tokens were "
            "used today/this week, or wants a per-model breakdown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Window in days to look back (default 7, max 90)",
                },
                "group_by": {
                    "type": "string",
                    "enum": ["day", "model", "total"],
                    "description": "Aggregation: by day, by model, or single total (default total)",
                },
            },
            "required": [],
        },
    },
]


async def _has_usage_table() -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='usage'")
        return await cur.fetchone() is not None


async def _columns() -> set[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("PRAGMA table_info(usage)")
        rows = await cur.fetchall()
        return {row[1] for row in rows}


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000) * PRICE_INPUT_PER_M + (output_tokens / 1_000_000) * PRICE_OUTPUT_PER_M


async def execute_model_usage_tool(name: str, input_data: dict, chat_id: int) -> str:
    if name != "get_model_usage":
        return json.dumps({"error": f"Unknown tool: {name}"})
    days = int(input_data.get("days") or 7)
    days = max(1, min(days, 90))
    group_by = (input_data.get("group_by") or "total").lower()

    if not await _has_usage_table():
        return json.dumps({"error": "usage table not found", "hint": "no LLM calls have been logged yet"})

    cols = await _columns()
    cutoff = time.time() - days * 86400

    ts_col = "timestamp" if "timestamp" in cols else ("ts" if "ts" in cols else None)
    in_col = next((c for c in ("input_tokens", "prompt_tokens", "in_tokens") if c in cols), None)
    out_col = next((c for c in ("output_tokens", "completion_tokens", "out_tokens") if c in cols), None)
    model_col = "model" if "model" in cols else None

    if not (ts_col and in_col and out_col):
        return json.dumps({
            "error": "usage table schema unrecognized",
            "columns": sorted(cols),
        })

    select_extra = f", {model_col}" if (group_by == "model" and model_col) else ""
    where_clause = f"WHERE {ts_col} >= ?"

    if group_by == "day":
        sql = (
            f"SELECT DATE({ts_col},'unixepoch','localtime') AS day, "
            f"SUM({in_col}) AS input_tok, SUM({out_col}) AS output_tok, COUNT(*) AS calls "
            f"FROM usage {where_clause} GROUP BY day ORDER BY day"
        )
    elif group_by == "model" and model_col:
        sql = (
            f"SELECT {model_col} AS model, SUM({in_col}) AS input_tok, "
            f"SUM({out_col}) AS output_tok, COUNT(*) AS calls "
            f"FROM usage {where_clause} GROUP BY {model_col} ORDER BY input_tok DESC"
        )
    else:
        sql = (
            f"SELECT SUM({in_col}) AS input_tok, SUM({out_col}) AS output_tok, "
            f"COUNT(*) AS calls FROM usage {where_clause}"
        )

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, (cutoff,))
        rows = await cur.fetchall()

    breakdown = []
    grand_in = grand_out = grand_calls = 0
    for r in rows:
        i = r["input_tok"] or 0
        o = r["output_tok"] or 0
        c = r["calls"] or 0
        grand_in += i
        grand_out += o
        grand_calls += c
        item = {
            "input_tokens": i,
            "output_tokens": o,
            "calls": c,
            "estimated_usd": round(_estimate_cost(i, o), 4),
        }
        if "day" in r.keys():
            item["day"] = r["day"]
        if model_col and "model" in r.keys():
            item["model"] = r["model"]
        breakdown.append(item)

    return json.dumps({
        "window_days": days,
        "group_by": group_by,
        "total": {
            "input_tokens": grand_in,
            "output_tokens": grand_out,
            "calls": grand_calls,
            "estimated_usd": round(_estimate_cost(grand_in, grand_out), 4),
        },
        "breakdown": breakdown,
        "note": "Pricing uses configured PRICE_INPUT_PER_M / PRICE_OUTPUT_PER_M; approximate.",
    })
