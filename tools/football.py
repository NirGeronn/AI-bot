"""Football (soccer) games via the 365scores public web endpoint."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta

import httpx

from config import USER_TIMEZONE, BOT_LANGUAGE

logger = logging.getLogger(__name__)

FOOTBALL_TOOLS = [
    {
        "name": "get_football_games",
        "description": (
            "Get football (soccer) games for a given date from 365scores. "
            "Returns kickoff time, teams, competition, status, and score (if started/finished). "
            "Use this for daily football briefings, checking who plays today/tomorrow, or live scores. "
            "Combine with set_daily_message for recurring football updates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": (
                        "Date in YYYY-MM-DD format. Defaults to today in the user's timezone. "
                        "Use 'tomorrow' or 'yesterday' as shortcuts."
                    ),
                },
                "competition": {
                    "type": "string",
                    "description": (
                        "Optional substring filter on competition name (case-insensitive). "
                        "Examples: 'Premier League', 'Champions', 'ליגת העל', 'La Liga'."
                    ),
                },
                "country": {
                    "type": "string",
                    "description": "Optional substring filter on country name (e.g. 'Israel', 'England', 'Spain').",
                },
                "top_only": {
                    "type": "boolean",
                    "description": (
                        "If true, return only games from major competitions: top-5 European leagues, "
                        "UEFA club tournaments, and the Israeli Premier League. Default false."
                    ),
                },
                "language": {
                    "type": "string",
                    "enum": ["en", "he"],
                    "description": "Language for team and competition names. Defaults to Hebrew if the bot speaks Hebrew, else English.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of games to return (default 40).",
                },
            },
            "required": [],
        },
    },
]

# 365scores competition IDs for the "top_only" filter.
TOP_COMPETITION_IDS = {
    7,     # England — Premier League
    11,    # Spain — La Liga
    17,    # Italy — Serie A
    25,    # Germany — Bundesliga
    35,    # France — Ligue 1
    42,    # Israel — Premier League (ליגת העל)
    57,    # Netherlands — Eredivisie
    73,    # Portugal — Liga Portugal
    572,   # UEFA Champions League
    573,   # UEFA Europa League
    5930,  # UEFA Conference League
}

_LANG_MAP = {"en": 1, "he": 2}


def _resolve_date(date_str: str | None, tz_name: str) -> datetime:
    """Resolve a date string (or 'today'/'tomorrow'/'yesterday'/None) to a datetime in the user's tz."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    now = datetime.now(tz)
    if not date_str or date_str.lower() == "today":
        return now
    if date_str.lower() == "tomorrow":
        return now + timedelta(days=1)
    if date_str.lower() == "yesterday":
        return now - timedelta(days=1)
    # Try YYYY-MM-DD
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return d.replace(tzinfo=tz)
    except ValueError:
        pass
    # Try DD/MM/YYYY
    try:
        d = datetime.strptime(date_str, "%d/%m/%Y")
        return d.replace(tzinfo=tz)
    except ValueError:
        pass
    raise ValueError(f"Unrecognized date format: {date_str!r}")


async def _fetch_games(date_ddmmyyyy: str, lang_id: int, tz_name: str) -> dict:
    url = "https://webws.365scores.com/web/games/"
    params = {
        "appTypeId": 5,
        "langId": lang_id,
        "timezoneName": tz_name,
        "userCountryId": 6,
        "sports": 1,
        "startDate": date_ddmmyyyy,
        "endDate": date_ddmmyyyy,
    }
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as e:
            last_err = e
            logger.warning(f"365scores fetch attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
    raise last_err if last_err else RuntimeError("365scores fetch failed")


def _format_kickoff(start_time_iso: str, tz_name: str) -> str:
    """Convert ISO start time to a short HH:MM string in the user's timezone."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    try:
        dt = datetime.fromisoformat(start_time_iso)
        return dt.astimezone(tz).strftime("%H:%M")
    except Exception:
        return start_time_iso


async def execute_football_tool(name: str, input_data: dict, chat_id: int) -> str:
    if name != "get_football_games":
        return json.dumps({"error": f"Unknown football tool: {name}"})

    lang = input_data.get("language") or ("he" if BOT_LANGUAGE.lower().startswith("he") else "en")
    lang_id = _LANG_MAP.get(lang, 2)
    limit = int(input_data.get("limit") or 40)
    comp_filter = (input_data.get("competition") or "").strip().lower()
    country_filter = (input_data.get("country") or "").strip().lower()
    top_only = bool(input_data.get("top_only"))

    try:
        target = _resolve_date(input_data.get("date"), USER_TIMEZONE)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    date_ddmmyyyy = target.strftime("%d/%m/%Y")

    try:
        data = await _fetch_games(date_ddmmyyyy, lang_id, USER_TIMEZONE)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        return json.dumps({"error": f"365scores fetch failed: {msg}"})

    countries = {
        c["id"]: {"name": c.get("name", ""), "slug": c.get("nameForURL", "")}
        for c in data.get("countries", [])
    }
    competitions = {c["id"]: c for c in data.get("competitions", [])}

    out_games = []
    for g in data.get("games", []):
        comp = competitions.get(g.get("competitionId"), {})
        comp_name = g.get("competitionDisplayName") or comp.get("name", "")
        country_info = countries.get(comp.get("countryId"), {"name": "", "slug": ""})
        country_name = country_info["name"]
        country_slug = country_info["slug"]

        if top_only and g.get("competitionId") not in TOP_COMPETITION_IDS:
            continue
        if comp_filter and comp_filter not in comp_name.lower():
            continue
        if country_filter and country_filter not in country_name.lower() and country_filter not in country_slug.lower():
            continue

        home = g.get("homeCompetitor", {}) or {}
        away = g.get("awayCompetitor", {}) or {}
        status_group = g.get("statusGroup")  # 2=scheduled, 3=live, 4=finished
        is_live = status_group == 3
        is_finished = status_group == 4
        has_score = is_live or is_finished

        out_games.append({
            "kickoff": _format_kickoff(g.get("startTime", ""), USER_TIMEZONE),
            "home": home.get("name", ""),
            "away": away.get("name", ""),
            "score": (
                f"{int(home.get('score', 0))}-{int(away.get('score', 0))}"
                if has_score and home.get("score", -1) >= 0 and away.get("score", -1) >= 0
                else None
            ),
            "status": g.get("statusText") or g.get("shortStatusText") or "",
            "is_live": is_live,
            "competition": comp_name,
            "country": country_name,
        })

    # Sort: live first, then scheduled (by kickoff), then finished
    def sort_key(x):
        if x["is_live"]:
            return (0, x["kickoff"])
        if "Sched" in (x["status"] or "") or "מתוכנן" in (x["status"] or ""):
            return (1, x["kickoff"])
        return (2, x["kickoff"])

    out_games.sort(key=sort_key)
    truncated = len(out_games) > limit
    out_games = out_games[:limit]

    return json.dumps({
        "date": target.strftime("%Y-%m-%d"),
        "timezone": USER_TIMEZONE,
        "language": lang,
        "count": len(out_games),
        "truncated": truncated,
        "games": out_games,
    }, ensure_ascii=False)
