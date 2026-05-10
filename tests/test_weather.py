"""Tests for the weather tool's IMS+Open-Meteo layered logic."""
from __future__ import annotations

import json
import pytest


def _load_module():
    """Load tools/weather.py without triggering tools/__init__ side effects."""
    import importlib.util, os
    path = os.path.join(os.path.dirname(__file__), "..", "tools", "weather.py")
    spec = importlib.util.spec_from_file_location("weather_tool", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_ims_lid_lookup_english_and_hebrew():
    m = _load_module()
    assert m._ims_lid_for("Hod Hasharon") == 24
    assert m._ims_lid_for("hod hasharon") == 24
    assert m._ims_lid_for("הוד השרון") == 24
    assert m._ims_lid_for("Tel Aviv") == 2
    assert m._ims_lid_for("תל אביב") == 2
    assert m._ims_lid_for("Jerusalem") == 1
    # Unknown city must return None so non-Israeli cities skip the IMS path.
    assert m._ims_lid_for("London") is None
    assert m._ims_lid_for("New York") is None


def test_english_alias_for_lid_returns_ascii():
    m = _load_module()
    alias = m._english_alias_for_lid(24)
    assert alias is not None
    assert alias.isascii()
    assert "hod" in alias.lower()


def test_english_alias_for_unknown_lid():
    m = _load_module()
    assert m._english_alias_for_lid(99999) is None


@pytest.mark.asyncio
async def test_ims_current_parses_wrapped_response(monkeypatch):
    """IMS responds with {"data": {"<lid>": {...}}, "method": ...}; the parser
    must handle both wrapped and flat shapes."""
    m = _load_module()

    captured_url = []

    class FakeResp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, headers=None):
            captured_url.append(url)
            return FakeResp({
                "data": {
                    "24": {
                        "temperature": "26.2",
                        "feels_like": "24.5",
                        "relative_humidity": "40",
                        "wind_speed": 12,  # m/s — must be converted to km/h
                        "rain": "0.00",
                        "u_v_index": "3",
                        "rain_chance": "0",
                        "due_point_Temp": "-999",  # sentinel — must be filtered out
                        "forecast_time": "2026-04-25 16:40:00",
                    }
                },
                "method": "now_analysis",
            })

    monkeypatch.setattr(m.httpx, "AsyncClient", FakeClient)
    out = await m._ims_current(24)
    assert out is not None
    assert captured_url[0].endswith("/now_analysis/24")
    assert out["temperature_c"] == 26.2
    assert out["feels_like_c"] == 24.5
    assert out["humidity_pct"] == 40
    assert out["wind_kmh"] == pytest.approx(12 * 3.6, rel=0.01)
    assert out["uv_index"] == 3
    assert out["rain_chance_pct"] == 0
    assert out["forecast_time"] == "2026-04-25 16:40:00"


@pytest.mark.asyncio
async def test_ims_current_returns_none_on_http_failure(monkeypatch):
    m = _load_module()

    class FakeClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass
        async def get(self, *a, **k):
            raise m.httpx.TransportError("connection refused")

    monkeypatch.setattr(m.httpx, "AsyncClient", FakeClient)
    out = await m._ims_current(24)
    assert out is None  # silent fallback — not a raised exception


@pytest.mark.asyncio
async def test_ims_current_filters_negative_999_sentinel(monkeypatch):
    """IMS uses -999 to mean 'no data'. Parser must convert it to None."""
    m = _load_module()

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"data": {"24": {
            "temperature": "-999", "feels_like": "20.0",
            "relative_humidity": "-999", "wind_speed": "-999",
            "rain": "-999", "u_v_index": "-999", "rain_chance": "-999",
        }}}

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, *a, **k): return FakeResp()

    monkeypatch.setattr(m.httpx, "AsyncClient", FakeClient)
    out = await m._ims_current(24)
    assert out["temperature_c"] is None
    assert out["humidity_pct"] is None
    assert out["wind_kmh"] is None
    assert out["uv_index"] is None
    # Non-sentinel value passes through.
    assert out["feels_like_c"] == 20.0


@pytest.mark.asyncio
async def test_get_weather_overrides_with_ims_for_israeli_city(monkeypatch):
    """For an Israeli city, IMS should override Open-Meteo current readings,
    but Open-Meteo still supplies the daily forecast."""
    m = _load_module()

    async def fake_geocode(city):
        return {"name": "Hod HaSharon", "country": "Israel",
                "lat": 32.15, "lon": 34.89, "timezone": "Asia/Jerusalem"}

    async def fake_open_meteo(url, params):
        return {
            "current": {"temperature_2m": 99.0, "apparent_temperature": 99.0,
                        "relative_humidity_2m": 99, "wind_speed_10m": 99,
                        "precipitation": 0, "weather_code": 1},
            "daily": {
                "time": ["2026-04-25", "2026-04-26"],
                "temperature_2m_max": [27, 28],
                "temperature_2m_min": [18, 19],
                "precipitation_sum": [0, 0],
                "wind_speed_10m_max": [15, 12],
                "weather_code": [1, 2],
            },
        }

    async def fake_ims(lid):
        return {"temperature_c": 26.2, "feels_like_c": 24.5,
                "humidity_pct": 40, "wind_kmh": 43.2,
                "precipitation_mm": 0.0, "uv_index": 3, "rain_chance_pct": 0,
                "forecast_time": "2026-04-25 16:40:00"}

    monkeypatch.setattr(m, "_geocode", fake_geocode)
    monkeypatch.setattr(m, "_http_get_json", fake_open_meteo)
    monkeypatch.setattr(m, "_ims_current", fake_ims)

    out = await m.execute_weather_tool("get_weather", {"city": "Hod Hasharon"}, 0)
    d = json.loads(out)
    assert d["current"]["source"] == "ims"
    assert d["current"]["temperature_c"] == 26.2  # IMS won
    assert d["current"]["humidity_pct"] == 40
    assert d["current"]["uv_index"] == 3
    assert d["current"]["observed_at"] == "2026-04-25 16:40:00"
    # WMO condition stays from Open-Meteo (IMS uses different codes).
    assert d["current"]["condition"] == "Mainly clear"
    # Forecast still comes from Open-Meteo.
    assert d["forecast_source"] == "open-meteo"
    assert len(d["forecast"]) == 2


@pytest.mark.asyncio
async def test_get_weather_uses_only_open_meteo_for_non_israeli(monkeypatch):
    m = _load_module()

    async def fake_geocode(city):
        return {"name": "London", "country": "United Kingdom",
                "lat": 51.5, "lon": -0.12, "timezone": "Europe/London"}

    async def fake_open_meteo(url, params):
        return {
            "current": {"temperature_2m": 17.9, "apparent_temperature": 17.0,
                        "relative_humidity_2m": 60, "wind_speed_10m": 10,
                        "precipitation": 0, "weather_code": 3},
            "daily": {"time": [], "temperature_2m_max": [],
                      "temperature_2m_min": [], "precipitation_sum": [],
                      "wind_speed_10m_max": [], "weather_code": []},
        }

    ims_called = []

    async def fake_ims(lid):
        ims_called.append(lid)
        return None

    monkeypatch.setattr(m, "_geocode", fake_geocode)
    monkeypatch.setattr(m, "_http_get_json", fake_open_meteo)
    monkeypatch.setattr(m, "_ims_current", fake_ims)

    out = await m.execute_weather_tool("get_weather", {"city": "London"}, 0)
    d = json.loads(out)
    # No IMS call should ever fire for a city not in IMS_CITY_IDS.
    assert ims_called == []
    assert d["current"]["source"] == "open-meteo"
    assert d["current"]["temperature_c"] == 17.9


@pytest.mark.asyncio
async def test_get_weather_falls_back_when_ims_fails(monkeypatch):
    """If IMS times out for an Israeli city, Open-Meteo current must still
    serve the response — never error out."""
    m = _load_module()

    async def fake_geocode(city):
        return {"name": "Hod HaSharon", "country": "Israel",
                "lat": 32.15, "lon": 34.89, "timezone": "Asia/Jerusalem"}

    async def fake_open_meteo(url, params):
        return {
            "current": {"temperature_2m": 24.1, "apparent_temperature": 24.3,
                        "relative_humidity_2m": 55, "wind_speed_10m": 9,
                        "precipitation": 0, "weather_code": 0},
            "daily": {"time": [], "temperature_2m_max": [],
                      "temperature_2m_min": [], "precipitation_sum": [],
                      "wind_speed_10m_max": [], "weather_code": []},
        }

    async def fake_ims(lid):
        return None  # simulate IMS timeout/failure

    monkeypatch.setattr(m, "_geocode", fake_geocode)
    monkeypatch.setattr(m, "_http_get_json", fake_open_meteo)
    monkeypatch.setattr(m, "_ims_current", fake_ims)

    out = await m.execute_weather_tool("get_weather", {"city": "Hod Hasharon"}, 0)
    d = json.loads(out)
    assert d["current"]["source"] == "open-meteo"
    assert d["current"]["temperature_c"] == 24.1


@pytest.mark.asyncio
async def test_hebrew_city_falls_back_to_english_alias_for_geocoding(monkeypatch):
    """Open-Meteo's geocoder is shaky on Hebrew; when geocoding the original
    string fails for an Israeli lid we know, retry with an English alias."""
    m = _load_module()

    geocode_calls = []

    async def fake_geocode(city):
        geocode_calls.append(city)
        if not city.isascii():  # Hebrew → fail
            return None
        return {"name": "Hod HaSharon", "country": "Israel",
                "lat": 32.15, "lon": 34.89, "timezone": "Asia/Jerusalem"}

    async def fake_open_meteo(url, params):
        return {"current": {}, "daily": {"time": [], "temperature_2m_max": [],
                "temperature_2m_min": [], "precipitation_sum": [],
                "wind_speed_10m_max": [], "weather_code": []}}

    async def fake_ims(lid):
        return {"temperature_c": 26.2, "feels_like_c": 24.5,
                "humidity_pct": 40, "wind_kmh": 43.2,
                "precipitation_mm": 0.0, "uv_index": 3, "rain_chance_pct": 0,
                "forecast_time": "2026-04-25 16:40:00"}

    monkeypatch.setattr(m, "_geocode", fake_geocode)
    monkeypatch.setattr(m, "_http_get_json", fake_open_meteo)
    monkeypatch.setattr(m, "_ims_current", fake_ims)

    out = await m.execute_weather_tool("get_weather", {"city": "הוד השרון"}, 0)
    d = json.loads(out)
    # Two geocode attempts: the Hebrew original, then an English alias.
    assert len(geocode_calls) == 2
    assert not geocode_calls[0].isascii()
    assert geocode_calls[1].isascii()
    assert d["current"]["source"] == "ims"
    assert d["current"]["temperature_c"] == 26.2
