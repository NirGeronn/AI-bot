from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import aiosqlite

from config import DB_PATH

logger = logging.getLogger(__name__)

ANTHROPIC_BILLING_TOOLS = [
    {
        "name": "get_anthropic_credit",
        "description": (
            "Report the user's current Anthropic/Claude credit balance in USD, "
            "based on a locally-stored credit figure minus token spend since that figure was recorded. "
            "Use this when the user asks about their Claude credit, balance, or spend, "
            "and in the daily morning weather message."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

# Per-model Anthropic pricing, USD per 1M tokens (input, output).
# Match by substring against model name; first match wins.
_PRICING = [
    ("opus",    (15.0,  75.0)),
    ("sonnet",  (3.0,   15.0)),
    ("haiku",   (1.0,    5.0)),
]
_DEFAULT_PRICE = (3.0, 15.0)


async def _ensure_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS kv_settings ("
            " key TEXT PRIMARY KEY,"
            " value TEXT NOT NULL,"
            " updated_at REAL NOT NULL)"
        )
        await db.commit()


async def set_credit_balance(usd: float) -> float:
    """Record a fresh credit balance. Returns the stored timestamp (unix)."""
    await _ensure_table()
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO kv_settings (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            ("anthropic_credit_usd", str(usd), now),
        )
        await db.execute(
            "INSERT INTO kv_settings (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            ("anthropic_credit_as_of", str(now), now),
        )
        await db.commit()
    return now


async def get_credit_record() -> tuple[float, float] | None:
    """Return (credit_usd, as_of_timestamp) or None if not set."""
    await _ensure_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT key, value FROM kv_settings WHERE key IN ('anthropic_credit_usd','anthropic_credit_as_of')"
        )
        rows = await cur.fetchall()
    data = {k: v for k, v in rows}
    if "anthropic_credit_usd" not in data or "anthropic_credit_as_of" not in data:
        return None
    try:
        return float(data["anthropic_credit_usd"]), float(data["anthropic_credit_as_of"])
    except ValueError:
        return None


def _price_for_model(model: str) -> tuple[float, float]:
    if not model:
        return _DEFAULT_PRICE
    lower = model.lower()
    for substr, price in _PRICING:
        if substr in lower:
            return price
    return _DEFAULT_PRICE


async def _spend_since(since_ts: float) -> tuple[float, dict]:
    """Total Anthropic spend across all chats since a timestamp, plus per-model breakdown."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT model, SUM(input_tokens), SUM(output_tokens), COUNT(*) "
            "FROM usage WHERE timestamp >= ? GROUP BY model",
            (since_ts,),
        )
        rows = await cur.fetchall()

    total = 0.0
    breakdown = {}
    for model, in_tok, out_tok, calls in rows:
        in_tok = in_tok or 0
        out_tok = out_tok or 0
        p_in, p_out = _price_for_model(model or "")
        cost = (in_tok * p_in + out_tok * p_out) / 1_000_000
        total += cost
        breakdown[model or "(unknown)"] = {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "calls": calls,
            "cost_usd": round(cost, 4),
        }
    return total, breakdown


async def execute_anthropic_billing_tool(name: str, input_data: dict, chat_id: int) -> str:
    if name != "get_anthropic_credit":
        return json.dumps({"error": f"Unknown tool: {name}"})

    record = await get_credit_record()
    if record is None:
        return json.dumps({
            "error": "No credit balance recorded yet. Use /setcredit <usd> in Telegram to set the current balance.",
        })

    credit, as_of = record
    spent, breakdown = await _spend_since(as_of)
    remaining = max(credit - spent, 0.0)

    as_of_iso = datetime.fromtimestamp(as_of, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    return json.dumps({
        "credit_at_last_update_usd": round(credit, 4),
        "as_of_utc": as_of_iso,
        "spent_since_usd": round(spent, 4),
        "remaining_usd": round(remaining, 4),
        "percent_used": round(min(spent / credit * 100, 100.0), 1) if credit > 0 else None,
        "spend_breakdown": breakdown,
        "note": "Based on local token tracking and Anthropic list prices. Update via /setcredit after topping up.",
    })
