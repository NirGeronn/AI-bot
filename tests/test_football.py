"""Tests for the football tool (tools/football.py)."""
from __future__ import annotations

import json
import pytest


@pytest.fixture
def sample_365scores():
    """Mimics the shape of a 365scores /web/games/ response — a few games
    spanning scheduled/live/finished, English + Hebrew, top-league + small."""
    return {
        "lastUpdateId": 1,
        "ttl": 5,
        "summary": {},
        "sports": [{"id": 1, "name": "Soccer"}],
        "countries": [
            {"id": 1, "name": "England", "nameForURL": "england"},
            {"id": 6, "name": "Israel", "nameForURL": "israel"},
            {"id": 109, "name": "Colombia", "nameForURL": "colombia"},
        ],
        "competitions": [
            {"id": 7, "countryId": 1, "name": "Premier League"},
            {"id": 42, "countryId": 6, "name": "Premier League"},
            {"id": 620, "countryId": 109, "name": "Liga Apertura"},
        ],
        "games": [
            {
                "id": 100, "competitionId": 7,
                "competitionDisplayName": "Premier League",
                "startTime": "2026-04-25T16:30:00+03:00",
                "statusGroup": 2, "statusText": "Scheduled", "shortStatusText": "Sched.",
                "homeCompetitor": {"name": "Fulham", "score": -1},
                "awayCompetitor": {"name": "Aston Villa", "score": -1},
            },
            {
                "id": 101, "competitionId": 42,
                "competitionDisplayName": "Israeli Premier League",
                "startTime": "2026-04-25T20:30:00+03:00",
                "statusGroup": 3, "statusText": "1st Half", "shortStatusText": "Live",
                "homeCompetitor": {"name": "Hapoel Tel Aviv", "score": 1},
                "awayCompetitor": {"name": "Maccabi Haifa", "score": 0},
            },
            {
                "id": 102, "competitionId": 620,
                "competitionDisplayName": "Liga Apertura",
                "startTime": "2026-04-25T00:00:00+03:00",
                "statusGroup": 4, "statusText": "Ended", "shortStatusText": "Ended",
                "homeCompetitor": {"name": "Cucuta Deportivo", "score": 1},
                "awayCompetitor": {"name": "Junior FC", "score": 1},
            },
        ],
    }


def _load_module():
    """Load tools/football.py without triggering tools/__init__ side effects."""
    import importlib.util, os
    path = os.path.join(os.path.dirname(__file__), "..", "tools", "football.py")
    spec = importlib.util.spec_from_file_location("football_tool", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_tool_schema_shape():
    m = _load_module()
    assert len(m.FOOTBALL_TOOLS) == 1
    t = m.FOOTBALL_TOOLS[0]
    assert t["name"] == "get_football_games"
    props = t["input_schema"]["properties"]
    for field in ["date", "competition", "country", "top_only", "language", "limit"]:
        assert field in props, f"missing input field: {field}"
    # No required fields — every call should be valid with no args.
    assert t["input_schema"].get("required", []) == []


def test_top_competition_ids_are_well_known():
    m = _load_module()
    # Sanity: top set must include the major European leagues + Israeli top flight.
    must_have = {7, 11, 17, 25, 35, 42}
    assert must_have.issubset(m.TOP_COMPETITION_IDS)


def test_resolve_date_today_tomorrow_yesterday():
    m = _load_module()
    today = m._resolve_date(None, "Asia/Jerusalem")
    tomorrow = m._resolve_date("tomorrow", "Asia/Jerusalem")
    yesterday = m._resolve_date("yesterday", "Asia/Jerusalem")
    # Use total_seconds to avoid timedelta.days truncation when the calls
    # are microseconds apart.
    one_day_s = 24 * 60 * 60
    assert abs((tomorrow - today).total_seconds() - one_day_s) < 1
    assert abs((today - yesterday).total_seconds() - one_day_s) < 1


def test_resolve_date_explicit_formats():
    m = _load_module()
    a = m._resolve_date("2026-04-25", "Asia/Jerusalem")
    b = m._resolve_date("25/04/2026", "Asia/Jerusalem")
    assert a.year == b.year == 2026
    assert a.month == b.month == 4
    assert a.day == b.day == 25


def test_resolve_date_rejects_garbage():
    m = _load_module()
    with pytest.raises(ValueError):
        m._resolve_date("not-a-date", "Asia/Jerusalem")


@pytest.mark.asyncio
async def test_full_response_shape(monkeypatch, sample_365scores):
    m = _load_module()

    async def fake_fetch(date_ddmmyyyy, lang_id, tz_name):
        return sample_365scores

    monkeypatch.setattr(m, "_fetch_games", fake_fetch)
    out = await m.execute_football_tool("get_football_games", {"language": "en"}, 0)
    d = json.loads(out)
    assert d["count"] == 3
    assert d["language"] == "en"
    # Live games sort first.
    assert d["games"][0]["is_live"] is True
    assert d["games"][0]["home"] == "Hapoel Tel Aviv"
    # Finished games carry a score; scheduled ones don't.
    finished = next(g for g in d["games"] if g["status"] == "Ended")
    assert finished["score"] == "1-1"
    scheduled = next(g for g in d["games"] if g["status"] == "Scheduled")
    assert scheduled["score"] is None


@pytest.mark.asyncio
async def test_top_only_filter(monkeypatch, sample_365scores):
    m = _load_module()
    async def fake_fetch(*a, **k): return sample_365scores
    monkeypatch.setattr(m, "_fetch_games", fake_fetch)

    out = await m.execute_football_tool(
        "get_football_games", {"top_only": True, "language": "en"}, 0
    )
    d = json.loads(out)
    # Liga Apertura (countryId=109, compId=620) must be filtered out;
    # English + Israeli Premier League must remain.
    comps = {g["competition"] for g in d["games"]}
    assert "Premier League" in comps
    assert "Israeli Premier League" in comps
    assert "Liga Apertura" not in comps


@pytest.mark.asyncio
async def test_country_filter_uses_slug(monkeypatch, sample_365scores):
    """Country filter must work even when API returns Hebrew country names —
    we match against `nameForURL` (slug) too."""
    m = _load_module()
    async def fake_fetch(*a, **k): return sample_365scores
    monkeypatch.setattr(m, "_fetch_games", fake_fetch)

    out = await m.execute_football_tool(
        "get_football_games", {"country": "israel", "language": "en"}, 0
    )
    d = json.loads(out)
    assert d["count"] == 1
    assert d["games"][0]["home"] == "Hapoel Tel Aviv"


@pytest.mark.asyncio
async def test_competition_substring_filter(monkeypatch, sample_365scores):
    m = _load_module()
    async def fake_fetch(*a, **k): return sample_365scores
    monkeypatch.setattr(m, "_fetch_games", fake_fetch)

    out = await m.execute_football_tool(
        "get_football_games", {"competition": "premier", "language": "en"}, 0
    )
    d = json.loads(out)
    # Both Premier Leagues should match (substring is case-insensitive).
    assert d["count"] == 2


@pytest.mark.asyncio
async def test_fetch_failure_returns_error(monkeypatch):
    m = _load_module()

    async def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(m, "_fetch_games", boom)
    out = await m.execute_football_tool("get_football_games", {}, 0)
    d = json.loads(out)
    assert "error" in d
    assert "365scores fetch failed" in d["error"]


@pytest.mark.asyncio
async def test_unknown_tool_name():
    m = _load_module()
    out = await m.execute_football_tool("get_basketball_games", {}, 0)
    d = json.loads(out)
    assert "error" in d
