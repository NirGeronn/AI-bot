from __future__ import annotations

import asyncio
import json
import logging
import httpx

logger = logging.getLogger(__name__)

WEATHER_TOOLS = [
    {
        "name": "get_weather",
        "description": "Get current weather and 7-day forecast for a city. Returns temperature, humidity, wind, rain, and daily forecast. Use this when the user asks about weather anywhere.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name, e.g. 'Tel Aviv', 'London', 'New York'",
                },
            },
            "required": ["city"],
        },
    },
]

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Rime fog", 51: "Light drizzle", 53: "Moderate drizzle",
    55: "Dense drizzle", 61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

# IMS (Israel Meteorological Service) location IDs.
# Maps lowercased English/Hebrew city aliases → IMS lid.
# Used as the primary source for current conditions in Israeli cities (real
# station-quality data, hourly updates). Open-Meteo is the fallback and the
# forecast source.
IMS_CITY_IDS = {
    "jerusalem": 1, "ירושלים": 1,
    "tel aviv": 2, "tel-aviv": 2, "tel aviv-yafo": 2, "תל אביב": 2, "תל-אביב": 2,
    "haifa": 3, "חיפה": 3,
    "rishon lezion": 4, "ראשון לציון": 4,
    "petah tikva": 5, "petach tikva": 5, "פתח תקווה": 5,
    "ashdod": 6, "אשדוד": 6,
    "netanya": 7, "נתניה": 7,
    "beer sheva": 8, "be'er sheva": 8, "beersheba": 8, "באר שבע": 8,
    "bnei brak": 9, "בני ברק": 9,
    "holon": 10, "חולון": 10,
    "ramat gan": 11, "רמת גן": 11,
    "ashkelon": 12, "אשקלון": 12,
    "rehovot": 13, "רחובות": 13,
    "bat yam": 14, "בת ים": 14,
    "beit shemesh": 15, "בית שמש": 15,
    "kfar saba": 16, "kfar sava": 16, "כפר סבא": 16,
    "herzliya": 17, "הרצליה": 17,
    "hadera": 18, "חדרה": 18,
    "modiin": 19, "modi'in": 19, "מודיעין": 19,
    "ramla": 20, "רמלה": 20,
    "raanana": 21, "ra'anana": 21, "רעננה": 21,
    "hod hasharon": 24, "הוד השרון": 24,
    "givatayim": 25, "גבעתיים": 25,
    "eilat": 31, "אילת": 31,
    "rosh haayin": 32, "רֹאש הָעַיִן": 32, "ראש העין": 32,
    "ramat hasharon": 37, "רמת השרון": 37,
    "tiberias": 40, "טבריה": 40,
    "tzfat": 50, "safed": 50, "צפת": 50,
}


async def _ims_current(lid: int) -> dict | None:
    """Fetch current conditions from IMS for an Israeli city. Returns None on failure."""
    url = f"https://ims.gov.il/en/now_analysis/{lid}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"IMS fetch failed for lid={lid}: {type(e).__name__}: {e}")
        return None

    # Response shape: {"data": {"<lid>": {...}}, "method": "..."}
    # Some endpoints return flat {"<lid>": {...}} — handle both.
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    entry = (inner or {}).get(str(lid)) or {}
    if not entry:
        return None

    def _f(key):
        v = entry.get(key)
        try:
            f = float(v)
            return f if f != -999 else None
        except (TypeError, ValueError):
            return None

    return {
        "temperature_c": _f("temperature"),
        "feels_like_c": _f("feels_like"),
        "humidity_pct": _f("relative_humidity"),
        "wind_kmh": (_f("wind_speed") * 3.6) if _f("wind_speed") is not None else None,
        "precipitation_mm": _f("rain"),
        "uv_index": _f("u_v_index"),
        "rain_chance_pct": _f("rain_chance"),
        "forecast_time": entry.get("forecast_time"),
    }


def _ims_lid_for(city: str) -> int | None:
    """Return IMS location id for an Israeli city, or None if not in our mapping."""
    return IMS_CITY_IDS.get(city.strip().lower())


def _english_alias_for_lid(lid: int) -> str | None:
    """Return the first ASCII alias mapped to this IMS lid (for Open-Meteo geocoding)."""
    for alias, alid in IMS_CITY_IDS.items():
        if alid == lid and alias.isascii():
            return alias
    return None


async def _http_get_json(url: str, params: dict, timeout: float = 10.0, retries: int = 2) -> dict:
    """GET a JSON endpoint with retry on transient failures."""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as e:
            last_err = e
            logger.warning(
                f"weather HTTP {type(e).__name__} on {url} attempt {attempt + 1}: {e}"
            )
            if attempt < retries:
                await asyncio.sleep(0.5 * (attempt + 1))
    raise last_err if last_err else RuntimeError(f"Failed to fetch {url}")


async def _geocode(city: str) -> dict | None:
    """Convert city name to coordinates using Open-Meteo geocoding."""
    data = await _http_get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": city, "count": 1, "language": "en"},
    )
    results = data.get("results")
    if not results:
        return None
    r = results[0]
    return {
        "name": r.get("name", city),
        "country": r.get("country", ""),
        "lat": r["latitude"],
        "lon": r["longitude"],
        "timezone": r.get("timezone", "auto"),
    }


async def execute_weather_tool(name: str, input_data: dict, chat_id: int) -> str:
    if name == "get_weather":
        city = input_data["city"]
        lid = _ims_lid_for(city)

        try:
            location = await _geocode(city)
        except Exception as e:
            logger.warning(f"Geocoding failed for {city!r}: {type(e).__name__}: {e}")
            location = None

        # If geocoding failed for an Israeli city we know, retry with an English
        # alias so we can still get a forecast — Open-Meteo's geocoder is shaky
        # on Hebrew strings.
        if not location and lid is not None:
            english = _english_alias_for_lid(lid)
            if english:
                try:
                    location = await _geocode(english)
                except Exception:
                    location = None

        # Last resort: synthesize a minimal location so we can still serve
        # IMS current conditions (no forecast in this branch).
        if not location and lid is not None:
            location = {"name": city, "country": "Israel",
                        "lat": None, "lon": None, "timezone": "Asia/Jerusalem"}

        if not location:
            return json.dumps({"error": f"City not found: {city}"})

        # Open-Meteo forecast — only when we have coordinates.
        data: dict = {}
        forecast_error: str | None = None
        if location["lat"] is not None and location["lon"] is not None:
            try:
                data = await _http_get_json(
                    "https://api.open-meteo.com/v1/forecast",
                    {
                        "latitude": location["lat"],
                        "longitude": location["lon"],
                        "timezone": location["timezone"],
                        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
                        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
                        "forecast_days": 7,
                    },
                )
            except Exception as e:
                forecast_error = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                logger.warning(f"Open-Meteo forecast failed for {location['name']}: {forecast_error}")

        current = data.get("current", {})
        daily = data.get("daily", {})

        current_block = {
            "temperature_c": current.get("temperature_2m"),
            "feels_like_c": current.get("apparent_temperature"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "wind_kmh": current.get("wind_speed_10m"),
            "precipitation_mm": current.get("precipitation"),
            "condition": WMO_CODES.get(current.get("weather_code", -1), "Unknown"),
            "source": "open-meteo" if data else None,
        }

        # If this is an Israeli city we know, try IMS for real station-quality
        # current conditions. IMS overrides Open-Meteo current; Open-Meteo
        # remains the source for the daily forecast.
        if lid is not None:
            ims = await _ims_current(lid)
            if ims:
                # Keep Open-Meteo's WMO `condition` (IMS uses internal codes we don't map),
                # but override the numeric current readings with IMS station data.
                for k in ("temperature_c", "feels_like_c", "humidity_pct",
                          "wind_kmh", "precipitation_mm"):
                    if ims.get(k) is not None:
                        current_block[k] = ims[k]
                if ims.get("uv_index") is not None:
                    current_block["uv_index"] = ims["uv_index"]
                if ims.get("rain_chance_pct") is not None:
                    current_block["rain_chance_pct"] = ims["rain_chance_pct"]
                current_block["source"] = "ims"
                if ims.get("forecast_time"):
                    current_block["observed_at"] = ims["forecast_time"]

        if current_block["source"] is None:
            return json.dumps({
                "error": (
                    f"Weather fetch failed for {city}. "
                    f"IMS unavailable and Open-Meteo {forecast_error or 'has no coordinates'}."
                )
            })

        result = {
            "location": f"{location['name']}, {location['country']}",
            "current": current_block,
            "forecast": [],
            "forecast_source": "open-meteo" if data else None,
        }

        dates = daily.get("time", [])
        for i, date in enumerate(dates):
            result["forecast"].append({
                "date": date,
                "high_c": daily["temperature_2m_max"][i],
                "low_c": daily["temperature_2m_min"][i],
                "precipitation_mm": daily["precipitation_sum"][i],
                "wind_kmh": daily["wind_speed_10m_max"][i],
                "condition": WMO_CODES.get(daily["weather_code"][i], "Unknown"),
            })

        return json.dumps(result)

    return json.dumps({"error": f"Unknown weather tool: {name}"})
