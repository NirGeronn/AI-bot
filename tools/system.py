import json
import asyncio
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
from config import USER_TIMEZONE
from memory import get_usage_stats, get_usage_cost_since, store_memory, recall_memories
from config import PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M

SYSTEM_TOOLS = [
    {
        "name": "get_current_time",
        "description": "Get the current date and time.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command on the local machine. Use for system tasks, file operations, or running scripts. Be careful with destructive commands.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30)",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "get_usage",
        "description": "Get API token usage statistics (today, last 30 days, all-time) with estimated cost in USD. Also shows remaining credit balance if one was set.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "set_credit_balance",
        "description": "Set the current Anthropic credit balance in USD. Use when the user tells you their balance (e.g. 'I have $50 in credits'). The bot will then track spending and show remaining balance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "balance_usd": {
                    "type": "number",
                    "description": "The current credit balance in USD",
                },
            },
            "required": ["balance_usd"],
        },
    },
    {
        "name": "log_bot_error",
        "description": (
            "Record a bot mistake into the error_log table. You MUST call this tool "
            "whenever the user asks you to log an error — e.g. 'log this', "
            "'add to error log', 'תוסיף לerror log', 'רשום את השגיאה'. "
            "Never claim an error was 'logged' / 'נרשם' without actually calling this tool. "
            "Describe the mistake honestly in your own words."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "error_type": {
                    "type": "string",
                    "description": "Short category, e.g. 'bot_mistake', 'context_loss', 'wrong_answer', 'misread_request'.",
                },
                "description": {
                    "type": "string",
                    "description": "What went wrong, in 1-3 sentences. The bot's own description of its mistake.",
                },
                "user_complaint": {
                    "type": "string",
                    "description": "The user's message that flagged the issue (verbatim or close paraphrase). Optional.",
                },
            },
            "required": ["error_type", "description"],
        },
    },
]


def _calc_cost(input_tokens: int, output_tokens: int,
               cache_creation_tokens: int = 0, cache_read_tokens: int = 0) -> float:
    """Anthropic cache pricing: writes = 1.25x input, reads = 0.1x input."""
    return (
        input_tokens * PRICE_INPUT_PER_M
        + output_tokens * PRICE_OUTPUT_PER_M
        + cache_creation_tokens * PRICE_INPUT_PER_M * 1.25
        + cache_read_tokens * PRICE_INPUT_PER_M * 0.1
    ) / 1_000_000


async def execute_system_tool(name: str, input_data: dict, chat_id: int) -> str:
    if name == "get_current_time":
        now = datetime.now(ZoneInfo(USER_TIMEZONE))
        return json.dumps({
            "datetime": now.isoformat(),
            "formatted": now.strftime("%A, %B %d, %Y at %I:%M %p"),
            "timezone": USER_TIMEZONE,
        })

    elif name == "run_command":
        command = input_data["command"]
        timeout = input_data.get("timeout", 30)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return json.dumps({
                "exit_code": proc.returncode,
                "stdout": stdout.decode()[-2000:],  # limit output size
                "stderr": stderr.decode()[-1000:],
            })
        except asyncio.TimeoutError:
            proc.kill()
            return json.dumps({"error": f"Command timed out after {timeout}s"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    elif name == "get_usage":
        stats = await get_usage_stats(chat_id)
        result = {}
        for period, data in stats.items():
            cw = data.get("cache_creation_tokens", 0)
            cr = data.get("cache_read_tokens", 0)
            cost = _calc_cost(data["input_tokens"], data["output_tokens"], cw, cr)
            result[period] = {
                "input_tokens": data["input_tokens"],
                "output_tokens": data["output_tokens"],
                "cache_creation_tokens": cw,
                "cache_read_tokens": cr,
                "total_tokens": data["input_tokens"] + data["output_tokens"] + cw + cr,
                "requests": data["requests"],
                "estimated_cost_usd": round(cost, 4),
            }

        # Check if a credit balance was set
        balance_memories = await recall_memories(chat_id, "_credit_balance")
        if balance_memories:
            try:
                balance_data = json.loads(balance_memories[0]["value"])
                initial_balance = balance_data["balance_usd"]
                set_at = balance_data["set_at"]
                # Calculate cost since balance was set
                cost_since = await get_usage_cost_since(chat_id, set_at)
                remaining = round(initial_balance - cost_since, 4)
                result["credit_balance"] = {
                    "initial_balance_usd": initial_balance,
                    "spent_since_set_usd": round(cost_since, 4),
                    "estimated_remaining_usd": remaining,
                }
            except (json.JSONDecodeError, KeyError):
                pass

        return json.dumps(result)

    elif name == "set_credit_balance":
        balance = input_data["balance_usd"]
        import time as _time
        balance_data = json.dumps({"balance_usd": balance, "set_at": _time.time()})
        await store_memory(chat_id, "_credit_balance", balance_data)
        return json.dumps({
            "status": "saved",
            "balance_usd": balance,
            "note": "I'll track spending from now and show remaining balance when you ask for usage.",
        })

    elif name == "log_bot_error":
        from error_log import log_error
        err_type = input_data.get("error_type", "bot_mistake")
        description = input_data.get("description", "")
        user_complaint = input_data.get("user_complaint")
        await log_error(
            chat_id,
            err_type,
            "User-reported bot mistake",
            description,
            user_message=user_complaint,
        )
        return json.dumps({"status": "logged", "error_type": err_type})

    return json.dumps({"error": f"Unknown system tool: {name}"})
