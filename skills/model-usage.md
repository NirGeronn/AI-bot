---
name: model-usage
description: Report on the bot's own LLM token usage and cost over time
---

## Model Usage

Use the **get_model_usage** tool when the user asks about cost, token usage, "how much did the bot spend", "how many tokens did I use today", or wants a breakdown by model/day.

When to use:
- "כמה עלית לי היום" / "how much have I spent" / "show me my usage" / "tokens this week".

Behavior:
- Tool returns aggregated stats from the local `usage` table: total input/output tokens, cache hits, estimated USD cost, broken down by day or model.
- Default range is the last 7 days; the user can ask for "today", "this month", or a specific number of days.
- Pricing is approximate (uses configured per-1M token rates from env). Note this when the user asks for exact figures.
