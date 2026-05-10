import json
import logging
import time
import aiosqlite
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from config import USER_TIMEZONE, DB_PATH

logger = logging.getLogger(__name__)

# Mutable container so set_app works across imports
_state = {"app": None}

# Track active timers: {job_name: {"label": str, "started_at": float, "duration_seconds": int}}
_active_timers = {}

# User timezone
USER_TZ = ZoneInfo(USER_TIMEZONE)

# PTB v20+ uses 0=Sunday, 1=Monday, ..., 6=Saturday
DAY_MAP = {
    "sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
    "thursday": 4, "friday": 5, "saturday": 6,
}
# Reverse map for display
DAY_NAMES = {v: k.capitalize() for k, v in DAY_MAP.items()}


# ── Persistence layer ──

async def _ensure_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                job_name TEXT NOT NULL UNIQUE,
                job_type TEXT NOT NULL,
                message TEXT NOT NULL,
                hour INTEGER,
                minute INTEGER,
                days TEXT,
                fire_at TEXT,
                created_at REAL NOT NULL
            )
        """)
        # Migration: add last_run_date column if it doesn't exist.
        # Pre-populate with today's date so the catch-up logic doesn't
        # spuriously re-fire jobs that already ran today.
        cur = await db.execute("PRAGMA table_info(scheduled_jobs)")
        cols = [row[1] for row in await cur.fetchall()]
        if "last_run_date" not in cols:
            await db.execute("ALTER TABLE scheduled_jobs ADD COLUMN last_run_date TEXT")
            today_iso = datetime.now(USER_TZ).strftime("%Y-%m-%d")
            await db.execute(
                "UPDATE scheduled_jobs SET last_run_date = ? WHERE last_run_date IS NULL",
                (today_iso,)
            )
        await db.commit()


async def _record_last_run(job_name: str, iso_date: str):
    """Record that a daily job ran on the given date (YYYY-MM-DD)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE scheduled_jobs SET last_run_date = ? WHERE job_name = ?",
            (iso_date, job_name),
        )
        await db.commit()


async def _save_job(chat_id, job_name, job_type, message, hour=None, minute=None, days=None, fire_at=None):
    """Persist a job to the database."""
    await _ensure_table()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM scheduled_jobs WHERE job_name = ?", (job_name,))
        await db.execute(
            "INSERT INTO scheduled_jobs (chat_id, job_name, job_type, message, hour, minute, days, fire_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (chat_id, job_name, job_type, message, hour, minute,
             json.dumps(days) if days else None,
             fire_at, time.time()),
        )
        await db.commit()


async def _delete_job(job_name):
    """Remove a job from the database."""
    await _ensure_table()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM scheduled_jobs WHERE job_name = ?", (job_name,))
        await db.commit()


async def _load_all_jobs():
    """Load all persisted jobs from the database."""
    await _ensure_table()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM scheduled_jobs")
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def restore_jobs():
    """Restore persisted jobs to the PTB job queue after restart."""
    app = _state["app"]
    if app is None:
        return

    job_queue = app.job_queue
    jobs = await _load_all_jobs()
    restored = 0

    for job in jobs:
        try:
            job_type = job["job_type"]
            job_name = job["job_name"]
            chat_id = job["chat_id"]
            message = job["message"]

            if job_type == "daily":
                hour = job["hour"]
                minute = job["minute"] or 0
                days = json.loads(job["days"]) if job["days"] else list(range(7))

                from datetime import time as dt_time
                run_time = dt_time(hour=hour, minute=minute, tzinfo=USER_TZ)
                days_tuple = tuple(days)

                job_queue.run_daily(
                    _send_daily,
                    time=run_time,
                    days=days_tuple,
                    chat_id=chat_id,
                    name=job_name,
                    data={"message": message, "days": [DAY_NAMES.get(d, str(d)) for d in days_tuple]},
                )
                restored += 1

            elif job_type == "scheduled":
                fire_at_str = job["fire_at"]
                target_local = datetime.strptime(fire_at_str, "%Y-%m-%d %H:%M")
                target_aware = target_local.replace(tzinfo=USER_TZ)
                now = datetime.now(USER_TZ)

                if target_aware <= now:
                    # Already past — delete from DB
                    await _delete_job(job_name)
                    continue

                delay = target_aware - now
                job_queue.run_once(
                    _send_scheduled,
                    when=delay,
                    chat_id=chat_id,
                    name=job_name,
                    data={"message": message},
                )
                restored += 1

            elif job_type == "reminder":
                fire_at_str = job["fire_at"]
                fire_ts = float(fire_at_str)
                now_ts = time.time()

                if fire_ts <= now_ts:
                    await _delete_job(job_name)
                    continue

                delay_secs = fire_ts - now_ts
                job_queue.run_once(
                    _send_reminder,
                    when=timedelta(seconds=delay_secs),
                    chat_id=chat_id,
                    name=job_name,
                    data={"message": message},
                )
                restored += 1

        except Exception as e:
            logger.error(f"Failed to restore job '{job.get('job_name')}': {e}")

    if restored:
        logger.info(f"Restored {restored} scheduled jobs from database")

    await _catch_up_missed_daily_jobs()


async def _catch_up_missed_daily_jobs():
    """For each daily job: if today is a configured day, today's fire time is
    already past but within the catch-up window, and the job hasn't recorded
    a run today, schedule a one-shot catch-up fire shortly. Handles deploy
    or short outage windows that overlap a fire time."""
    CATCHUP_WINDOW = timedelta(hours=2)

    app = _state["app"]
    if app is None:
        return
    job_queue = app.job_queue

    now = _now_local()
    today_iso = now.strftime("%Y-%m-%d")
    today_idx = (now.weekday() + 1) % 7  # Mon=0..Sun=6 → Sun=0..Sat=6

    await _ensure_table()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT job_name, chat_id, message, hour, minute, days, last_run_date "
            "FROM scheduled_jobs WHERE job_type='daily'"
        ) as cur:
            rows = await cur.fetchall()

    for row in rows:
        if row["last_run_date"] == today_iso:
            continue
        days = json.loads(row["days"]) if row["days"] else list(range(7))
        if today_idx not in days:
            continue
        hour = row["hour"]
        minute = row["minute"] or 0
        fire_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if fire_time > now:
            continue  # hasn't fired yet today — normal scheduler will handle it
        if (now - fire_time) > CATCHUP_WINDOW:
            continue  # too long ago, not worth firing

        delay = timedelta(seconds=30)
        job_queue.run_once(
            _send_daily,
            when=delay,
            chat_id=row["chat_id"],
            name=f"{row['job_name']}_catchup",
            data={
                "message": row["message"],
                "days": [DAY_NAMES.get(d, str(d)) for d in days],
            },
        )
        missed_by = now - fire_time
        logger.info(
            f"Catch-up: scheduling missed daily job '{row['job_name']}' "
            f"({hour:02d}:{minute:02d}, missed by {missed_by})"
        )


# ── App setup ──

def set_app(app):
    _state["app"] = app


def _now_local():
    return datetime.now(USER_TZ)


async def get_schedule_brief() -> str:
    """Return a short listing of today's and tomorrow's scheduled daily messages.
    Reads from the scheduled_jobs table so the agent can see the full schedule
    without calling list_scheduled_jobs."""
    now = _now_local()
    # weekday(): Mon=0..Sun=6 → PTB encoding: Sun=0..Sat=6
    today_idx = (now.weekday() + 1) % 7
    tomorrow_idx = (today_idx + 1) % 7
    today_name = now.strftime("%A")
    tomorrow_name = (now + timedelta(days=1)).strftime("%A")

    today_items = []
    tomorrow_items = []
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT job_name, hour, minute, days FROM scheduled_jobs "
                "WHERE job_type='daily' ORDER BY hour, minute"
            ) as cur:
                async for row in cur:
                    days = json.loads(row["days"]) if row["days"] else list(range(7))
                    t = f"{row['hour']:02d}:{row['minute']:02d}"
                    if today_idx in days:
                        today_items.append(f"{t} {row['job_name']}")
                    if tomorrow_idx in days:
                        tomorrow_items.append(f"{t} {row['job_name']}")
    except Exception as e:
        logger.warning(f"get_schedule_brief failed: {e}")
        return ""

    lines = []
    lines.append(
        f"Today ({today_name}): " + (", ".join(today_items) if today_items else "no scheduled messages")
    )
    lines.append(
        f"Tomorrow ({tomorrow_name}): " + (", ".join(tomorrow_items) if tomorrow_items else "no scheduled messages")
    )
    return "\n".join(lines)


# ── Tool definitions ──

SCHEDULER_TOOLS = [
    {
        "name": "set_reminder",
        "description": "Set a reminder that will send a message to the user after a delay. Examples: 'remind me in 30 minutes to call mom', 'remind me in 2 hours to check the oven'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The reminder message to send",
                },
                "delay_minutes": {
                    "type": "integer",
                    "description": "How many minutes from now to send the reminder",
                },
            },
            "required": ["message", "delay_minutes"],
        },
    },
    {
        "name": "set_timer",
        "description": "Set a countdown timer. When it goes off, the user gets a notification. Examples: 'set a 25 minute timer', 'start a 2 hour timer for cooking', 'set a 90 second timer'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "description": "A label for the timer (e.g. 'cooking', 'pomodoro', 'break'). Defaults to 'timer'.",
                },
                "hours": {
                    "type": "integer",
                    "description": "Hours for the timer. Default 0.",
                },
                "minutes": {
                    "type": "integer",
                    "description": "Minutes for the timer. Default 0.",
                },
                "seconds": {
                    "type": "integer",
                    "description": "Seconds for the timer. Default 0.",
                },
            },
        },
    },
    {
        "name": "check_timer",
        "description": "Check how much time is remaining on active timers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "description": "Label of a specific timer to check. If omitted, shows all active timers.",
                },
            },
        },
    },
    {
        "name": "cancel_timer",
        "description": "Cancel an active timer by its label.",
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "description": "Label of the timer to cancel.",
                },
            },
            "required": ["label"],
        },
    },
    {
        "name": "set_daily_message",
        "description": f"Schedule a recurring message at a specific hour in {USER_TIMEZONE} timezone. Supports choosing specific weekdays using the 'days' parameter (e.g. days=['sunday','monday','wednesday']). If 'days' is omitted it runs every day. Use this for weekly gym reminders, weekday-only digests, weekend messages, etc. Examples: 'remind me every Sunday and Tuesday at 9am to go to the gym', 'send me a morning briefing every weekday at 7am'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message or prompt to send. This will be processed by the AI agent, so you can use prompts like 'Give me a morning briefing' or 'Summarize today's tasks'.",
                },
                "hour": {
                    "type": "integer",
                    "description": f"Hour in {USER_TIMEZONE} timezone (0-23) to send the message. E.g. 7 = 7:00 AM, 14 = 2:00 PM, 20 = 8:00 PM.",
                },
                "minute": {
                    "type": "integer",
                    "description": "Minute (0-59). Default 0.",
                },
                "name": {
                    "type": "string",
                    "description": "A short name for this scheduled job (e.g. 'morning_digest', 'evening_recap')",
                },
                "days": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of days to run on. E.g. ['sunday', 'monday']. If omitted, runs every day. Valid values: monday, tuesday, wednesday, thursday, friday, saturday, sunday.",
                },
            },
            "required": ["message", "hour", "name"],
        },
    },
    {
        "name": "schedule_message",
        "description": f"Schedule a one-time message at a specific date and time ({USER_TIMEZONE} timezone). Use for things like 'remind me on April 20 at 3pm to buy flowers' or 'send me a message next Monday at 10am'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message or prompt to send. Will be processed by the AI agent.",
                },
                "datetime_str": {
                    "type": "string",
                    "description": f"Date and time in {USER_TIMEZONE} timezone. Format: 'YYYY-MM-DD HH:MM'. E.g. '2026-04-20 15:00'.",
                },
                "name": {
                    "type": "string",
                    "description": "A short name for this scheduled job.",
                },
            },
            "required": ["message", "datetime_str", "name"],
        },
    },
    {
        "name": "list_scheduled_jobs",
        "description": "List all currently scheduled jobs (reminders, daily messages, and one-time scheduled messages).",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "cancel_scheduled_job",
        "description": "Cancel a scheduled job by its name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The name of the job to cancel",
                },
            },
            "required": ["name"],
        },
    },
]


# ── Callbacks ──

async def _send_reminder(context):
    """Callback for one-time reminders."""
    chat_id = context.job.chat_id
    message = context.job.data["message"]
    await context.bot.send_message(chat_id=chat_id, text=f"Reminder: {message}")
    # Clean up from DB
    await _delete_job(context.job.name)


async def _timer_done(context):
    """Callback when a timer completes."""
    chat_id = context.job.chat_id
    label = context.job.data["label"]
    duration = context.job.data["duration_seconds"]

    # Clean up tracking
    job_name = f"timer_{label}"
    _active_timers.pop(job_name, None)

    # Format duration nicely
    parts = []
    if duration >= 3600:
        parts.append(f"{duration // 3600}h")
    if (duration % 3600) >= 60:
        parts.append(f"{(duration % 3600) // 60}m")
    if duration % 60:
        parts.append(f"{duration % 60}s")
    dur_str = " ".join(parts) if parts else "0s"

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Timer \"{label}\" is done! ({dur_str})",
    )


def _should_skip(response: str) -> bool:
    if not response:
        return True
    stripped = response.strip()
    return stripped == "[SKIP]" or stripped.upper().startswith("[SKIP]")


async def _send_daily(context):
    """Callback for daily scheduled messages. Runs through the AI agent."""
    from agent import run_agent
    chat_id = context.job.chat_id
    prompt = context.job.data["message"]

    # Guard: refuse to send if today (in user's TZ) isn't in the configured days.
    # Protects against scheduler misfires firing on the wrong calendar day.
    allowed_days = context.job.data.get("days") or []
    now = _now_local()
    today_name = now.strftime("%A")
    today_iso = now.strftime("%Y-%m-%d")
    if allowed_days and today_name not in allowed_days:
        logger.warning(
            f"Daily job '{context.job.name}' fired on {today_name} but configured for {allowed_days} — skipping"
        )
        return

    # A catch-up job runs under name "<original>_catchup" — record against the original.
    job_name = context.job.name
    db_job_name = job_name[:-len("_catchup")] if job_name.endswith("_catchup") else job_name

    try:
        response = await run_agent(chat_id, prompt, skip_active_memory=True, skip_history=True)
        if _should_skip(response):
            logger.info(f"Daily job '{context.job.name}' returned SKIP — no message sent")
            await _record_last_run(db_job_name, today_iso)
            return
        while response:
            chunk = response[:4000]
            response = response[4000:]
            await context.bot.send_message(chat_id=chat_id, text=chunk)
        await _record_last_run(db_job_name, today_iso)
    except Exception as e:
        logger.error(f"Daily job '{context.job.name}' failed: {e}")
        from error_log import log_error
        await log_error(chat_id, "scheduled_job_error", f"Daily job '{context.job.name}' failed",
                       str(e), extra={"job_name": context.job.name, "prompt": prompt[:200]})
        await context.bot.send_message(chat_id=chat_id, text=f"Scheduled job error: {e}")


async def _send_scheduled(context):
    """Callback for one-time scheduled messages. Runs through the AI agent."""
    from agent import run_agent
    chat_id = context.job.chat_id
    prompt = context.job.data["message"]

    try:
        response = await run_agent(chat_id, prompt, skip_active_memory=True, skip_history=True)
        if _should_skip(response):
            logger.info(f"Scheduled job '{context.job.name}' returned SKIP — no message sent")
            await _delete_job(context.job.name)
            return
        while response:
            chunk = response[:4000]
            response = response[4000:]
            await context.bot.send_message(chat_id=chat_id, text=chunk)
    except Exception as e:
        logger.error(f"Scheduled job '{context.job.name}' failed: {e}")
        from error_log import log_error
        await log_error(chat_id, "scheduled_job_error", f"Scheduled job '{context.job.name}' failed",
                       str(e), extra={"job_name": context.job.name, "prompt": prompt[:200]})
        await context.bot.send_message(chat_id=chat_id, text=f"Scheduled job error: {e}")

    # Clean up one-time job from DB
    await _delete_job(context.job.name)


# ── Tool execution ──

async def execute_scheduler_tool(name: str, input_data: dict, chat_id: int) -> str:
    app = _state["app"]
    if app is None:
        return json.dumps({"error": "Scheduler not initialized"})

    job_queue = app.job_queue

    if name == "set_reminder":
        message = input_data["message"]
        delay = input_data["delay_minutes"]
        job_name = f"reminder_{datetime.now(timezone.utc).timestamp()}"

        fire_ts = time.time() + delay * 60

        job_queue.run_once(
            _send_reminder,
            when=timedelta(minutes=delay),
            chat_id=chat_id,
            name=job_name,
            data={"message": message},
        )

        # Persist to DB
        await _save_job(chat_id, job_name, "reminder", message, fire_at=str(fire_ts))

        trigger_time = _now_local() + timedelta(minutes=delay)
        return json.dumps({
            "status": "scheduled",
            "name": job_name,
            "will_fire_at": trigger_time.strftime(f"%Y-%m-%d %H:%M ({USER_TIMEZONE})"),
            "delay_minutes": delay,
        })

    elif name == "set_timer":
        label = input_data.get("label", "timer").strip()
        hours = input_data.get("hours", 0)
        minutes = input_data.get("minutes", 0)
        seconds = input_data.get("seconds", 0)
        total_seconds = hours * 3600 + minutes * 60 + seconds

        if total_seconds <= 0:
            return json.dumps({"error": "Timer duration must be greater than 0"})

        job_name = f"timer_{label}"

        # Cancel existing timer with same label
        existing = job_queue.get_jobs_by_name(job_name)
        for job in existing:
            job.schedule_removal()
        _active_timers.pop(job_name, None)

        job_queue.run_once(
            _timer_done,
            when=timedelta(seconds=total_seconds),
            chat_id=chat_id,
            name=job_name,
            data={"label": label, "duration_seconds": total_seconds},
        )

        _active_timers[job_name] = {
            "label": label,
            "started_at": time.time(),
            "duration_seconds": total_seconds,
        }

        # Timers are not persisted (short-lived)

        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds:
            parts.append(f"{seconds}s")

        return json.dumps({
            "status": "timer_started",
            "label": label,
            "duration": " ".join(parts) if parts else "0s",
            "duration_seconds": total_seconds,
        })

    elif name == "check_timer":
        label = input_data.get("label")

        if label:
            job_name = f"timer_{label.strip()}"
            info = _active_timers.get(job_name)
            if not info:
                return json.dumps({"error": f"No active timer with label '{label}'"})
            elapsed = time.time() - info["started_at"]
            remaining = max(0, info["duration_seconds"] - elapsed)
            mins, secs = divmod(int(remaining), 60)
            hrs, mins = divmod(mins, 60)
            parts = []
            if hrs:
                parts.append(f"{hrs}h")
            if mins:
                parts.append(f"{mins}m")
            parts.append(f"{secs}s")
            return json.dumps({
                "label": info["label"],
                "remaining": " ".join(parts),
                "remaining_seconds": int(remaining),
            })
        else:
            timers = []
            now = time.time()
            for jn, info in list(_active_timers.items()):
                elapsed = now - info["started_at"]
                remaining = max(0, info["duration_seconds"] - elapsed)
                if remaining <= 0:
                    _active_timers.pop(jn, None)
                    continue
                mins, secs = divmod(int(remaining), 60)
                hrs, mins = divmod(mins, 60)
                parts = []
                if hrs:
                    parts.append(f"{hrs}h")
                if mins:
                    parts.append(f"{mins}m")
                parts.append(f"{secs}s")
                timers.append({"label": info["label"], "remaining": " ".join(parts)})
            return json.dumps({"active_timers": timers, "count": len(timers)})

    elif name == "cancel_timer":
        label = input_data["label"].strip()
        job_name = f"timer_{label}"
        existing = job_queue.get_jobs_by_name(job_name)
        if not existing and job_name not in _active_timers:
            return json.dumps({"error": f"No active timer with label '{label}'"})
        for job in existing:
            job.schedule_removal()
        _active_timers.pop(job_name, None)
        return json.dumps({"status": "cancelled", "label": label})

    elif name == "set_daily_message":
        message = input_data["message"]
        hour = input_data["hour"]
        minute = input_data.get("minute", 0)
        job_name = input_data["name"]

        # Remove existing job with same name
        existing = job_queue.get_jobs_by_name(job_name)
        for job in existing:
            job.schedule_removal()

        from datetime import time as dt_time
        run_time = dt_time(hour=hour, minute=minute, tzinfo=USER_TZ)

        day_names = input_data.get("days")
        if day_names:
            days_tuple = tuple(DAY_MAP[d.lower()] for d in day_names if d.lower() in DAY_MAP)
        else:
            days_tuple = tuple(range(7))

        job_queue.run_daily(
            _send_daily,
            time=run_time,
            days=days_tuple,
            chat_id=chat_id,
            name=job_name,
            data={"message": message, "days": [DAY_NAMES.get(d, str(d)) for d in days_tuple]},
        )

        # Persist to DB
        await _save_job(chat_id, job_name, "daily", message,
                       hour=hour, minute=minute, days=list(days_tuple))

        day_label = ", ".join(d.capitalize() for d in day_names) if day_names else "Every day"
        return json.dumps({
            "status": "scheduled",
            "name": job_name,
            "runs_at_local": f"{hour:02d}:{minute:02d}",
            "days": day_label,
        })

    elif name == "schedule_message":
        message = input_data["message"]
        datetime_str = input_data["datetime_str"]
        job_name = input_data["name"]

        # Remove existing job with same name
        existing = job_queue.get_jobs_by_name(job_name)
        for job in existing:
            job.schedule_removal()

        target_local = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
        target_aware = target_local.replace(tzinfo=USER_TZ)

        now = _now_local()
        if target_aware <= now:
            return json.dumps({"error": f"Target time {datetime_str} is in the past. Current time: {now.strftime('%Y-%m-%d %H:%M')}"})

        delay = target_aware - now

        job_queue.run_once(
            _send_scheduled,
            when=delay,
            chat_id=chat_id,
            name=job_name,
            data={"message": message},
        )

        # Persist to DB
        await _save_job(chat_id, job_name, "scheduled", message, fire_at=datetime_str)

        return json.dumps({
            "status": "scheduled",
            "name": job_name,
            "will_fire_at": target_aware.strftime(f"%Y-%m-%d %H:%M ({USER_TIMEZONE})"),
            "delay_minutes": int(delay.total_seconds() / 60),
        })

    elif name == "list_scheduled_jobs":
        jobs = job_queue.jobs()
        job_list = []
        system_job_names = {"daily_summary_generator", "proactive_pulse", "heartbeat"}
        for job in jobs:
            # Only show jobs belonging to this chat (skip system jobs and other users' jobs)
            if job.chat_id != chat_id:
                continue

            next_run_utc = job.next_t
            if next_run_utc:
                next_run_local = next_run_utc.astimezone(USER_TZ)
                next_run_str = next_run_local.strftime("%Y-%m-%d %H:%M (%A)")
            else:
                next_run_str = "unknown"

            info = {
                "name": job.name,
                "next_run_local": next_run_str,
            }
            if job.name in system_job_names:
                info["type"] = "system"
            if job.data:
                info["message"] = job.data.get("message", "")
                if "days" in job.data:
                    info["days"] = job.data["days"]
            job_list.append(info)
        return json.dumps({"jobs": job_list, "timezone": USER_TIMEZONE})

    elif name == "cancel_scheduled_job":
        job_name = input_data["name"]
        existing = job_queue.get_jobs_by_name(job_name)
        if not existing:
            return json.dumps({"error": f"No job found with name: {job_name}"})
        for job in existing:
            job.schedule_removal()
        # Remove from DB too
        await _delete_job(job_name)
        return json.dumps({"status": "cancelled", "name": job_name})

    return json.dumps({"error": f"Unknown scheduler tool: {name}"})
