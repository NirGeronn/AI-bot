"""
Heartbeat System - Periodic proactive checks.

Each standing order does its data fetch directly (Gmail/Calendar/Todo APIs)
WITHOUT invoking the LLM. The LLM is only called when there's actually
something to summarize for the user. Idle ticks cost ~0 tokens.
"""
import json
import time
import logging
import aiosqlite
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from config import DB_PATH, USER_TIMEZONE

logger = logging.getLogger(__name__)


async def _ensure_heartbeat_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS heartbeat_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                order_name TEXT NOT NULL,
                result TEXT,
                ran_at REAL NOT NULL
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_hb_chat_order ON heartbeat_log(chat_id, order_name)"
        )
        await db.commit()


async def _last_run_time(chat_id: int, order_name: str) -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT MAX(ran_at) FROM heartbeat_log WHERE chat_id = ? AND order_name = ?",
            (chat_id, order_name),
        )
        row = await cursor.fetchone()
    return row[0] if row and row[0] else 0


async def _record_heartbeat(chat_id: int, order_name: str, result: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO heartbeat_log (chat_id, order_name, result, ran_at) VALUES (?, ?, ?, ?)",
            (chat_id, order_name, result[:500], time.time()),
        )
        # Keep profile_question history long-term so we don't repeat questions;
        # other orders only need short retention.
        cutoff = time.time() - 7 * 86400
        await db.execute(
            "DELETE FROM heartbeat_log WHERE ran_at < ? AND order_name != 'profile_question'",
            (cutoff,),
        )
        await db.commit()


async def _seen_email_ids(chat_id: int) -> set[str]:
    """Email IDs already reported to the user, so we don't re-alert."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT result FROM heartbeat_log WHERE chat_id = ? AND order_name = 'inbox_check' "
            "AND ran_at >= ? ORDER BY ran_at DESC LIMIT 50",
            (chat_id, time.time() - 7 * 86400),
        )
        rows = await cursor.fetchall()
    seen = set()
    for (result,) in rows:
        if not result:
            continue
        try:
            payload = json.loads(result)
            for eid in payload.get("ids", []):
                seen.add(eid)
        except (json.JSONDecodeError, TypeError):
            continue
    return seen


# ---------- Cheap data fetches (no LLM) ----------

def _check_inbox_raw(max_results: int = 10) -> list[dict]:
    """Pull recent unread inbox emails directly via Gmail API. No LLM."""
    from tools.gmail import _get_gmail_service, _parse_headers
    service = _get_gmail_service()
    results = service.users().messages().list(
        userId="me", q="in:inbox is:unread", maxResults=max_results
    ).execute()
    emails = []
    for msg in results.get("messages", []):
        detail = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = _parse_headers(detail.get("payload", {}).get("headers", []),
                                 {"from", "subject", "date"})
        emails.append({
            "id": msg["id"],
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "snippet": detail.get("snippet", "")[:200],
        })
    return emails


def _check_calendar_raw(hours_ahead: int = 2) -> list[dict]:
    """Pull upcoming events directly via Calendar API. No LLM."""
    from config import CALENDAR_PROVIDER
    if CALENDAR_PROVIDER == "icloud":
        from tools.icloud_calendar import list_icloud_events
        events = list_icloud_events(days_ahead=1, max_results=10)
    else:
        from tools.calendar import _get_calendar_service, _format_event
        service = _get_calendar_service()
        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(hours=hours_ahead)).isoformat() + "Z"
        result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = [_format_event(e) for e in result.get("items", [])]

    # Filter to events starting within the window
    cutoff = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    upcoming = []
    for e in events:
        start_str = e.get("start", "") or ""
        try:
            start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=ZoneInfo(USER_TIMEZONE))
            if start <= cutoff:
                upcoming.append(e)
        except (ValueError, TypeError):
            upcoming.append(e)
    return upcoming


async def _check_todos_raw(chat_id: int) -> list[dict]:
    """Pull open todos directly from DB. No LLM."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT list_name, item FROM todo_items WHERE chat_id = ? AND completed = 0 "
            "ORDER BY created_at ASC LIMIT 50",
            (chat_id,),
        )
        rows = await cursor.fetchall()
    return [{"list": r[0], "item": r[1]} for r in rows]


# ---------- Formatting (no LLM unless we hit the threshold) ----------

def _format_inbox_brief(emails: list[dict], lang: str) -> str:
    if not emails:
        return ""
    if lang.lower().startswith("hebrew"):
        header = f"📧 {len(emails)} מיילים חדשים:"
    else:
        header = f"📧 {len(emails)} new emails:"
    lines = [header]
    for e in emails[:5]:
        sender = e["from"].split("<")[0].strip() or e["from"]
        subj = e["subject"] or "(no subject)"
        lines.append(f"• {sender}: {subj[:80]}")
    return "\n".join(lines)


def _format_calendar_brief(events: list[dict], lang: str) -> str:
    if not events:
        return ""
    if lang.lower().startswith("hebrew"):
        header = "📅 אירועים קרובים:"
    else:
        header = "📅 Upcoming:"
    lines = [header]
    for e in events[:3]:
        title = e.get("summary") or e.get("title") or "(untitled)"
        start = e.get("start", "")
        try:
            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            local = dt.astimezone(ZoneInfo(USER_TIMEZONE))
            time_str = local.strftime("%H:%M")
        except (ValueError, TypeError, AttributeError):
            time_str = start[-8:-3] if len(start) >= 8 else start
        lines.append(f"• {time_str} — {title}")
    return "\n".join(lines)


def _format_todos_brief(todos: list[dict], lang: str) -> str:
    if not todos:
        return ""
    if lang.lower().startswith("hebrew"):
        header = f"📝 {len(todos)} משימות פתוחות:"
    else:
        header = f"📝 {len(todos)} open todos:"
    lines = [header]
    for t in todos[:5]:
        lines.append(f"• [{t['list']}] {t['item'][:80]}")
    return "\n".join(lines)


# ---------- Main heartbeat loop ----------

STANDING_ORDERS = [
    {"name": "calendar_check",   "interval_seconds": 86400, "active_hours": (8, 22)},
    {"name": "todo_review",      "interval_seconds": 86400, "active_hours": (8, 21)},
    {"name": "profile_question", "interval_seconds": 86400, "active_hours": (10, 12)},
]


def _current_local_hour() -> int:
    return datetime.now(ZoneInfo(USER_TIMEZONE)).hour


async def run_heartbeat(chat_id: int) -> list[dict]:
    """Run all due standing orders. Cheap path — no LLM unless there's something
    actually new to report."""
    from config import BOT_LANGUAGE
    await _ensure_heartbeat_table()

    now = time.time()
    current_hour = _current_local_hour()
    results = []
    lang = BOT_LANGUAGE

    for order in STANDING_ORDERS:
        start_h, end_h = order["active_hours"]
        if not (start_h <= current_hour < end_h):
            continue
        last_run = await _last_run_time(chat_id, order["name"])
        if now - last_run < order["interval_seconds"]:
            continue

        name = order["name"]
        logger.info(f"Heartbeat: running '{name}' (cheap path)")

        try:
            if name == "inbox_check":
                emails = _check_inbox_raw(max_results=10)
                seen = await _seen_email_ids(chat_id)
                fresh = [e for e in emails if e["id"] not in seen]
                payload = {"ids": [e["id"] for e in emails]}  # remember all seen ids
                await _record_heartbeat(chat_id, name, json.dumps(payload))
                if fresh:
                    msg = _format_inbox_brief(fresh, lang)
                    if msg:
                        results.append({"name": name, "message": msg})
                        logger.info(f"Heartbeat: inbox -> {len(fresh)} new")

            elif name == "calendar_check":
                events = _check_calendar_raw(hours_ahead=2)
                await _record_heartbeat(chat_id, name, f"{len(events)} upcoming")
                if events:
                    msg = _format_calendar_brief(events, lang)
                    if msg:
                        results.append({"name": name, "message": msg})
                        logger.info(f"Heartbeat: calendar -> {len(events)} upcoming")

            elif name == "todo_review":
                todos = await _check_todos_raw(chat_id)
                await _record_heartbeat(chat_id, name, f"{len(todos)} open")
                # Only nag if there are several open items — avoids constant noise
                if len(todos) >= 5:
                    msg = _format_todos_brief(todos, lang)
                    if msg:
                        results.append({"name": name, "message": msg})
                        logger.info(f"Heartbeat: todos -> {len(todos)} open")

            elif name == "profile_question":
                from profile_builder import generate_profile_question
                question = await generate_profile_question(chat_id)
                # Always record so daily cooldown applies even when we skip
                await _record_heartbeat(chat_id, name, question or "(skipped)")
                if question:
                    results.append({"name": name, "message": question})
                    logger.info(f"Heartbeat: profile_question -> {question[:80]}")

        except Exception as e:
            logger.error(f"Heartbeat: '{name}' failed: {e}")
            await _record_heartbeat(chat_id, name, f"ERROR: {e}")

    return results
