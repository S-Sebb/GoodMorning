#!/usr/bin/env python3
"""Fetch a compact daily weather brief, without an LLM or paid keys.

Open-Meteo weather and CAMS AQI are keyless. WAQI is an optional station
cross-check (WAQI_TOKEN). Explicit coordinates bypass geocoding; otherwise
city comes from --city > GM_CITY/CITY > secretary/profile.md. Use a qualified
city (e.g. London, GB) or coordinates to avoid location ambiguity.

Sources fetch concurrently and cache independently. See docs/weather-pipeline.md
for freshness, failure handling, attribution, and the JSON contract.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TIMEOUT = 8
RAIN_WMO = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 97, 99}
SNOW_WMO = {71, 73, 75, 77, 85, 86}
STORM_WMO = {95, 96, 97, 99}
RAIN_SIGNAL_MIN_PROB = 30
WEATHER_TTL = 1800
AQI_TTL = 3600
STALE_LIMIT = 6 * 3600
GEOCODE_TTL = 30 * 86400
MAX_RESPONSE_BYTES = 256 * 1024
FRAME_HOURS = 18
WET_HOUR_PROB = 50
# The evening's card for tomorrow. Code decides each fact; these English phrases are
# also the page's translation keys, so the agent's read and the card say the same thing.
SKY_TEXT = {
    "dry": "Dry all day",
    "all": {"rain": "Rain likely all day", "snow": "Snow likely all day"},
    "until": {"rain": "Rain likely until about {time}", "snow": "Snow likely until about {time}"},
    "from": {"rain": "Dry until about {time}, then rain", "snow": "Dry until about {time}, then snow"},
    "between": {"rain": "Rain likely about {start}–{end}", "snow": "Snow likely about {start}–{end}"},
    "on-off": {"rain": "Rain on and off from about {time}", "snow": "Snow on and off from about {time}"},
}
COMPARE_TEXT = {"warmer": "A bit warmer than today", "much-warmer": "Much warmer than today",
                "cooler": "A bit cooler than today", "much-cooler": "Much cooler than today"}
ALERT_TEXT = {"storm": "Thunderstorms possible: take care if you're outdoors.",
              "snow": "Snow expected: allow extra time for travel.",
              "ice": "Below freezing at times: watch for icy paths.",
              "heat": "A hot day: drink plenty of water."}
BRING_TEXT = {"winter-coat": "Winter coat, hat and gloves", "warm-coat": "Warm coat", "jacket": "Jacket or warm sweater",
              "light-jacket": "Long sleeves and a light jacket", "short-sleeves": "Short sleeves",
              "light-clothes": "Light, breathable clothes", "layers": "Layers you can take off", "umbrella": "Umbrella",
              "umbrella-after": "Umbrella if you're out after {time}", "waterproof-shoes": "Waterproof shoes",
              "boots": "Boots with grip"}
CLOTHING = ((5, "winter-coat"), (10, "warm-coat"), (16, "jacket"), (22, "light-jacket"), (28, "short-sleeves"),
            (math.inf, "light-clothes"))

WMO_TEXT = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "icy fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "snow showers",
    95: "thunderstorm", 96: "storm with hail", 97: "heavy thunderstorm", 99: "storm with hail",
}
PRECIP_TEXT = {WMO_TEXT[code] for code in RAIN_WMO | SNOW_WMO}


class WeatherError(Exception):
    """A safe, URL-free error suitable for user-facing output."""


def http_get_json(url, headers=None, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "GoodMorning/1.0"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise WeatherError("provider response too large")
            data = json.loads(body)
            if not isinstance(data, dict) or data.get("error"):
                raise WeatherError("invalid provider response")
            return data
        except urllib.error.HTTPError as e:
            e.close()
            if attempt == 0 and e.code in (500, 502, 503, 504):
                time.sleep(0.25)
                continue
            raise WeatherError(f"HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            if attempt == 0:
                time.sleep(0.25)
                continue
            raise WeatherError("network unavailable or timed out") from None
        except (ValueError, UnicodeError):
            raise WeatherError("invalid provider JSON") from None


def number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise WeatherError("invalid numeric provider value")
    return value


def local_day(zone, now=None):
    try:
        return datetime.fromtimestamp(time.time() if now is None else now, ZoneInfo(zone)).date().isoformat()
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise WeatherError("invalid provider timezone") from None


def validate_current_time(value, zone):
    try:
        stamp = datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(zone))
        if not -3600 <= time.time() - stamp.timestamp() <= STALE_LIMIT:
            raise ValueError
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise WeatherError("current data timestamp missing or outside freshness limit") from None


def validate_cached(key, data):
    """Treat valid JSON with a broken normalized schema as a cache miss."""
    kind = key.split(":", 1)[0]
    fields = {
        "geocode": ("latitude", "longitude", "city"),
        "weather": ("date", "timezone", "time", "temp_c", "temp_min_c", "temp_max_c", "rain", "condition", "advice", "provider"),
        "aqi": ("date", "timezone", "time", "us_aqi", "level", "source"),
    }.get(kind, ())
    if any(field not in data for field in fields):
        raise WeatherError("invalid cache schema")
    for field in fields:
        if field in ("latitude", "longitude", "temp_c", "temp_min_c", "temp_max_c", "us_aqi"):
            number(data[field])
        elif not isinstance(data[field], str):
            raise WeatherError("invalid cache schema")
    if kind == "geocode":
        validate_coordinates(data["latitude"], data["longitude"])
    elif kind == "weather":
        number(data.get("precip_prob_pct"))
        if data["rain"] not in ("yes", "no", "unknown"):
            raise WeatherError("invalid cache schema")
    elif kind == "aqi" and (data["us_aqi"] is None or data["us_aqi"] < 0):
        raise WeatherError("invalid cache schema")


class Cache:
    """Versioned, atomic, best-effort disk cache. Never persists credentials."""

    def __init__(self, directory, refresh=False):
        self.directory = Path(directory) if directory else None
        self.refresh = refresh

    def path(self, key):
        return self.directory / (hashlib.sha256(key.encode()).hexdigest() + ".json")

    def read(self, key):
        if self.directory:
            try:
                obj = json.loads(self.path(key).read_text(encoding="utf-8"))
                if (isinstance(obj, dict) and obj.get("version") == 1
                        and isinstance(obj.get("data"), dict)
                        and number(obj.get("fetched_at")) is not None):
                    validate_cached(key, obj["data"])
                    return obj
            except (OSError, ValueError, WeatherError):
                pass
        return None

    def write(self, key, obj):
        if not self.directory:
            return
        tmp = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory,
                                             delete=False) as f:
                tmp = f.name
                json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            os.replace(tmp, self.path(key))
        except (OSError, ValueError):
            pass
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def get(self, key, fetch, ttl, stale_limit=0, daily=False):
        obj = self.read(key)
        now = time.time()
        age = now - obj["fetched_at"] if obj else float("inf")
        usable = obj is not None and age >= 0
        if usable and daily:
            data = obj["data"]
            try:
                usable = data.get("date") == local_day(data.get("timezone"), now)
                if usable and data.get("time") is not None:
                    validate_current_time(data["time"], data["timezone"])
            except WeatherError:
                usable = False
        if usable and age < ttl and not self.refresh:
            state = "cached"
        else:
            try:
                data = fetch()
                obj = {"version": 1, "fetched_at": time.time(), "data": data}
                self.write(key, obj)
                state = "live"
            except WeatherError as e:
                if not usable or age > stale_limit:
                    raise
                return {**obj["data"], "fetched_at": utc_time(obj["fetched_at"]),
                        "cache_state": "stale", "error": str(e)}
        return {**obj["data"], "fetched_at": utc_time(obj["fetched_at"]), "cache_state": state}


def utc_time(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def parse_profile(path):
    """Read city/region from secretary/profile.md. Returns (city, region)."""
    city, region = "", ""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeError):
        return city, region
    m = re.search(r"^city[ \t]*:[ \t]*([^\r\n]*)$", text, re.M | re.I)
    if m:
        city = m.group(1).strip().strip("\"' ")
    m = re.search(r"^region[ \t]*:[ \t]*([^\r\n]*)$", text, re.M | re.I)
    if m:
        region = m.group(1).strip().strip("\"' ").lower()
    return city, region


def find_profile(explicit):
    from .runtime_files import secretary_path
    return str(Path(explicit).expanduser().resolve() if explicit else secretary_path() / "profile.md")


def build_advice(temp_c, rain, snow=False, rain_from=None):
    umbrella = f"umbrella for after {rain_from}" if rain_from else "take umbrella"
    bits = [umbrella] if rain else (["rain forecast unavailable"] if rain is None else [])
    if snow:
        bits.append("snow, wear boots")
    elif rain and temp_c is not None and temp_c < 10:
        bits.append("wet and cold, rain boots help")
    if temp_c is None:
        pass
    elif temp_c < 5:
        bits.append("cold, wear winter coat")
    elif temp_c < 15:
        bits.append("cool, bring a jacket")
    elif temp_c > 28:
        bits.append("hot, stay cool")
    return "; ".join(bits) + "." if bits else ""


def aqi_level(us_aqi):
    if us_aqi is None:
        return "unknown"
    if us_aqi <= 50:
        return "good"
    if us_aqi <= 100:
        return "moderate"
    if us_aqi <= 150:
        return "unhealthy for sensitive groups"
    if us_aqi <= 200:
        return "unhealthy"
    if us_aqi <= 300:
        return "very unhealthy"
    return "hazardous"


def aqi_advice(us_aqi):
    if us_aqi is None:
        return ""
    if us_aqi <= 50:
        return ""
    if us_aqi <= 100:
        return "sensitive people reduce prolonged outdoor exertion."
    if us_aqi <= 150:
        return "sensitive groups limit outdoor time."
    if us_aqi <= 200:
        return "limit outdoor exertion."
    return "avoid outdoor exertion."


def _geocode_languages(city):
    """Order geocoding languages so native-script names are found.

    Open-Meteo matches the query against names in the requested language:
    ``上海`` with ``language=en`` returns no results, while ``language=zh``
    finds it (and ``Москва`` needs ``ru``). English queries work in both,
    so trying ``en`` first preserves current behaviour and a ``zh`` fallback
    fixes Chinese-character cities like Shanghai.
    """
    if re.search(r"[\u4e00-\u9fff\uf900-\ufaff]", city):
        return ["zh", "en"]
    if re.search(r"[\u0400-\u04ff]", city):
        return ["ru", "en", "zh"]
    if re.search(r"[\u3040-\u30ff]", city):
        return ["ja", "zh", "en"]
    if re.search(r"[\uac00-\ud7af]", city):
        return ["ko", "zh", "en"]
    return ["en", "zh"]


def openmeteo_geocode(city, timeout=TIMEOUT):
    parts = [part.strip() for part in city.split(",")]
    if not parts[0] or any(not part for part in parts):
        raise WeatherError("city must have nonempty location components")
    saw_filtered_empty = False
    saw_ambiguous = False
    for lang in _geocode_languages(city):
        q = urllib.parse.urlencode({"name": parts[0], "count": 10, "language": lang, "format": "json"})
        data = http_get_json("https://geocoding-api.open-meteo.com/v1/search?" + q, timeout=timeout)
        res = (data or {}).get("results") or []
        if not res:
            continue
        try:
            if not isinstance(res, list) or not all(isinstance(item, dict) for item in res):
                raise WeatherError("invalid geocoding response")
            if len(parts) > 1:
                country = parts[-1].casefold()
                res = [item for item in res if country in (
                    str(item.get("country_code", "")).casefold(), str(item.get("country", "")).casefold())]
                for region in parts[1:-1]:
                    res = [item for item in res if region.casefold() in (
                        str(item.get("admin1", "")).casefold(), str(item.get("admin2", "")).casefold())]
            exact = [item for item in res if str(item.get("name", "")).casefold() == parts[0].casefold()]
            if exact:
                res = exact
            if not res:
                saw_filtered_empty = True
                continue
            if len({(item.get("latitude"), item.get("longitude")) for item in res}) != 1:
                saw_ambiguous = True
                continue
            location = res[0]
            if not isinstance(location.get("name", city), str):
                raise WeatherError("invalid geocoding name")
            lat, lon = number(location["latitude"]), number(location["longitude"])
            validate_coordinates(lat, lon)
            return {"latitude": lat, "longitude": lon, "city": location.get("name", city),
                    "country": location.get("country_code"), "admin1": location.get("admin1")}
        except (KeyError, TypeError, IndexError, AttributeError):
            raise WeatherError("invalid geocoding response") from None
    if saw_ambiguous:
        raise WeatherError("city is ambiguous; specify country/region or verified coordinates")
    if saw_filtered_empty:
        raise WeatherError("no city matches the confirmed country/region; use verified coordinates")
    if re.search(r"[^\x00-\x7f]", city):
        raise WeatherError("city not found; try English/Pinyin like 'Shanghai, CN' or use --lat/--lon")
    raise WeatherError("city not found; use a qualified city or --lat/--lon")


def fetch_openmeteo(city, lat, lon, timeout=TIMEOUT):
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,weather_code",
        "hourly": "temperature_2m,precipitation_probability",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,rain_sum,showers_sum,snowfall_sum,sunrise,sunset",
        "timezone": "auto", "forecast_days": 2,
    })
    d = http_get_json("https://api.open-meteo.com/v1/forecast?" + q, timeout=timeout)
    cur, daily = d.get("current", {}), d.get("daily", {})
    if not isinstance(cur, dict) or not isinstance(daily, dict) or not cur.get("time"):
        raise WeatherError("missing weather data")
    def first(key):
        values = daily.get(key)
        if values is None or values == []:
            return None
        if not isinstance(values, list):
            raise WeatherError("invalid daily weather data")
        return values[0] if key == "time" else number(values[0])
    day, zone = first("time"), d.get("timezone")
    if day != local_day(zone):
        raise WeatherError("forecast is not for today")
    validate_current_time(cur["time"], zone)
    code, day_code = number(cur.get("weather_code")), first("weather_code")
    temp = number(cur.get("temperature_2m"))
    tmax, tmin = first("temperature_2m_max"), first("temperature_2m_min")
    prob = first("precipitation_probability_max")
    rain_sum, showers, snow_sum = first("rain_sum"), first("showers_sum"), first("snowfall_sum")
    if (prob is not None and not 0 <= prob <= 100) or any(v is not None and v < 0 for v in (rain_sum, showers, snow_sum)):
        raise WeatherError("invalid precipitation data")
    snow = day_code in SNOW_WMO or (snow_sum or 0) > 0
    days = {day: [number(code), number(code) in SNOW_WMO or (number(fall) or 0) > 0] for day, code, fall in
            zip(daily.get("time") or [], daily.get("weather_code") or [], daily.get("snowfall_sum") or [])}
    # The daily code reflects the worst hour, even trace drizzle; a low probability overrides it.
    signal = day_code in RAIN_WMO or (rain_sum or 0) + (showers or 0) > 0.2
    rain = (signal and (prob is None or prob >= RAIN_SIGNAL_MIN_PROB)
            or (prob is not None and prob >= 50 and not snow))
    if not rain and all(v is None for v in (day_code, prob, rain_sum, showers)):
        rain = None
    text = WMO_TEXT.get(code, "unknown")
    return {
        "city": city,
        "date": day, "timezone": zone, "time": cur["time"],
        "temp_c": temp,
        "temp_min_c": tmin,
        "temp_max_c": tmax,
        "rain": "unknown" if rain is None else ("yes" if rain else "no"),
        "snow": snow,
        "days": days,
        "precip_prob_pct": prob,
        "condition": text,
        "daily_condition": WMO_TEXT.get(day_code, "unknown"),
        "advice": build_advice(temp, rain, snow=snow),
        "provider": "open-meteo",
        "aqi": None,
        "hourly": hourly_series(d.get("hourly"), {"temp": "temperature_2m", "prob": "precipitation_probability"}),
        "sun": [[rise, sunset] for rise, sunset in zip(daily.get("sunrise") or [], daily.get("sunset") or [])
                if isinstance(rise, str) and isinstance(sunset, str)],
    }


def hourly_series(hourly, fields):
    """Hourly values keyed by local ISO hour; None when the provider omitted or broke them."""
    if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
        return None
    series = {"time": hourly["time"]}
    for name, key in fields.items():
        values = hourly.get(key)
        if not isinstance(values, list) or len(values) != len(series["time"]):
            return None
        series[name] = [number(value) for value in values]
    return series if all(isinstance(t, str) for t in series["time"]) else None


def fetch_aqi_openmeteo(lat, lon, timeout=TIMEOUT):
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "current": "us_aqi,european_aqi,pm2_5,ozone",
        "hourly": "us_aqi",
        "timezone": "auto", "forecast_days": 2,
    })
    d = http_get_json("https://air-quality-api.open-meteo.com/v1/air-quality?" + q, timeout=timeout)
    cur = d.get("current")
    if not isinstance(cur, dict) or not isinstance(cur.get("time"), str):
        raise WeatherError("missing AQI data")
    us = number(cur.get("us_aqi"))
    if us is None or us < 0:
        raise WeatherError("AQI unavailable")
    if cur["time"][:10] != local_day(d.get("timezone")):
        raise WeatherError("AQI is not for today")
    validate_current_time(cur["time"], d["timezone"])
    return {
        "time": cur["time"], "date": cur["time"][:10], "timezone": d.get("timezone"),
        "us_aqi": us,
        "eu_aqi": number(cur.get("european_aqi")),
        "pm25": number(cur.get("pm2_5")),
        "o3": number(cur.get("ozone")),
        "pollutant_unit": "ug/m3",
        "level": aqi_level(us),
        "source": "open-meteo/cams-model",
        "hourly": hourly_series(d.get("hourly"), {"us_aqi": "us_aqi"}),
    }


def fetch_aqi_waqi(city=None, lat=None, lon=None, token="", timeout=TIMEOUT):
    if lat is not None and lon is not None:
        url = f"https://api.waqi.info/feed/geo:{lat};{lon}/?" + urllib.parse.urlencode({"token": token})
    else:
        url = f"https://api.waqi.info/feed/{urllib.parse.quote(city, safe='')}/?" + urllib.parse.urlencode({"token": token})
    d = http_get_json(url, timeout=timeout)
    if d.get("status") != "ok":
        raise WeatherError("WAQI lookup failed (check token and station coverage)")
    data = d["data"]
    if not isinstance(data, dict):
        raise WeatherError("invalid WAQI data")
    iaqi = data.get("iaqi", {})
    us = data.get("aqi")
    try:
        us = int(us) if us not in (None, "-", "") else None
    except (ValueError, TypeError, OverflowError):
        us = None
    if us is None or us < 0:
        raise WeatherError("station AQI unavailable")
    observed = (data.get("time") or {}).get("iso")
    try:
        stamp = datetime.fromisoformat(observed)
        if stamp.tzinfo is None or not -3600 <= time.time() - stamp.timestamp() <= STALE_LIMIT:
            raise ValueError
    except (ValueError, TypeError):
        raise WeatherError("station observation missing or older than 6 hours") from None
    return {
        "time": observed,
        "us_aqi": us,
        "pm25_subindex": number((iaqi.get("pm25") or {}).get("v")),
        "o3_subindex": number((iaqi.get("o3") or {}).get("v")),
        "dominant": data.get("dominentpol"),
        "station": (data.get("city") or {}).get("name"),
        "url": (data.get("city") or {}).get("url"),
        "attributions": [{"name": str(a.get("name", "")), "url": str(a.get("url", ""))}
                         for a in (data.get("attributions") or []) if isinstance(a, dict)],
        "level": aqi_level(us),
        "source": "waqi-station",
    }


def validate_coordinates(lat, lon):
    if lat is None or lon is None or not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise WeatherError("provide both --lat (-90..90) and --lon (-180..180)")


def forecast_frame(out, aqi, now=None, day=None):
    """The 18 hours a briefing charts: 06:00–24:00, or 18:00 to noon for late briefings.

    A later `day` (ISO date) always covers its 06:00–24:00.

    `past` counts frame hours already gone when the briefing was made; summaries
    use only the hours after it. None when the provider sent no usable hours.
    """
    hourly = out.get("hourly")
    if not hourly:
        return None
    zone = ZoneInfo(out["timezone"])
    now = datetime.fromtimestamp(time.time() if now is None else now, zone)
    if day:
        start = datetime.fromisoformat(day).replace(hour=6, tzinfo=zone)
    else:
        start = now.replace(hour=18 if now.hour >= 18 else 6, minute=0, second=0, microsecond=0)
    try:
        first = hourly["time"].index(start.strftime("%Y-%m-%dT%H:%M"))
    except ValueError:
        return None
    temps, probs = hourly["temp"][first:first + FRAME_HOURS], hourly["prob"][first:first + FRAME_HOURS]
    if len(temps) < FRAME_HOURS or None in temps or None in probs:
        return None
    air = [None] * FRAME_HOURS
    series = (aqi or {}).get("hourly") or ((aqi or {}).get("model") or {}).get("hourly")
    if series and start.strftime("%Y-%m-%dT%H:%M") in series["time"]:
        at = series["time"].index(start.strftime("%Y-%m-%dT%H:%M"))
        values = series["us_aqi"][at:at + FRAME_HOURS]
        if len(values) == FRAME_HOURS and None not in values:
            air = values
    offset = lambda stamp: (datetime.fromisoformat(stamp).replace(tzinfo=zone) - start).total_seconds() / 3600
    sun, light = [], []
    for rise, sunset in out.get("sun") or []:
        rise, sunset = offset(rise), offset(sunset)
        light.append((rise, sunset))
        sun += [["sunrise", round(at, 2)] for at in (rise,) if 0 <= at < FRAME_HOURS]
        sun += [["sunset", round(at, 2)] for at in (sunset,) if 0 <= at < FRAME_HOURS]
    night, cursor = [], 0
    for rise, sunset in sorted(light):
        if rise > cursor and cursor < FRAME_HOURS:
            night.append([round(cursor, 2), round(min(rise, FRAME_HOURS), 2)])
        cursor = max(cursor, sunset)
    if light and cursor < FRAME_HOURS:
        night.append([round(cursor, 2), FRAME_HOURS])
    lat, lon = out["latitude"], out["longitude"]
    station = (aqi or {}).get("url") if (aqi or {}).get("source") == "waqi-station" else None
    return {
        "start": start.strftime("%Y-%m-%dT%H:%M"),
        "past": min(max(int((now - start).total_seconds() // 3600), 0), FRAME_HOURS - 1),
        "hours": [[round(t, 1), round(p), None if a is None else round(a)] for t, p, a in zip(temps, probs, air)],
        "sun": sorted(sun, key=lambda entry: entry[1]),
        "night": [span for span in night if span[1] > span[0]],
        "snow": (out.get("days") or {}).get(day, [None, False])[1] if day else bool(out.get("snow")),
        "links": {
            "forecast": "https://open-meteo.com/en/docs?" + urllib.parse.urlencode({
                "latitude": lat, "longitude": lon, "hourly": "temperature_2m,precipitation_probability",
                "timezone": "auto", "forecast_days": 2}) + "#api_response",
            "air": station if isinstance(station, str) and station.startswith("https://") else
                   "https://open-meteo.com/en/docs/air-quality-api?" + urllib.parse.urlencode({
                       "latitude": lat, "longitude": lon, "hourly": "us_aqi",
                       "timezone": "auto", "forecast_days": 2}) + "#api_response",
        },
    }


def frame_ahead(frame):
    """The hours after the briefing: high/low, rain peak and when it starts or eases."""
    first = datetime.fromisoformat(frame["start"]).hour
    clock = lambda index: "24:00" if first + index == 24 and index == FRAME_HOURS else f"{(first + index) % 24:02d}:00"
    rows = frame["hours"][frame["past"]:]
    wet = [prob >= WET_HOUR_PROB for _, prob, _ in rows]
    first_wet = wet.index(True) if any(wet) else None
    return {
        "from": clock(frame["past"]), "until": clock(FRAME_HOURS),
        "temp_min_c": min(t for t, _, _ in rows), "temp_max_c": max(t for t, _, _ in rows),
        "rain_peak_pct": max(prob for _, prob, _ in rows),
        "rain_from": None if first_wet is None else clock(frame["past"] + first_wet),
        "rain_until": (None if not wet[0] else clock(frame["past"] + wet.index(False)) if False in wet else clock(FRAME_HOURS)),
    }


def apply_frame(out, frame):
    """Judge rain and advice from the hours ahead, not hours that already passed."""
    ahead = frame_ahead(frame)
    rain = ahead["rain_from"] is not None and not out.get("snow")
    later = ahead["rain_from"] if rain and ahead["rain_from"] != ahead["from"] else None
    out.update(frame=frame, ahead=ahead, rain="yes" if rain else "no", precip_prob_pct=ahead["rain_peak_pct"],
               advice=build_advice(out["temp_c"], rain, snow=out.get("snow"), rain_from=later))
    # The current code can show model drizzle in an hour the frame calls dry; the hours ahead are the one precipitation source.
    if ahead["rain_from"] != ahead["from"] and out["condition"] in PRECIP_TEXT:
        out["condition"] = None


def outlook(out, frame, day):
    """The evening card for a later day: [outlook, low, high, icon, sky, compare, alert, bring], decided by code."""
    clock = lambda index: f"{6 + index:02d}:00"
    temps = [t for t, _, _ in frame["hours"]]
    low, high = round(min(temps)), round(max(temps))
    code = (out.get("days") or {}).get(day, [None, False])[0]
    snow = frame["snow"]
    wet = [p >= WET_HOUR_PROB for _, p, _ in frame["hours"]] + [False]
    spans = [(i, wet.index(False, i)) for i in range(FRAME_HOURS) if wet[i] and (i == 0 or not wet[i - 1])]
    kind = "snow" if snow else "rain"
    if not spans:
        sky = ["dry"]
    elif len(spans) > 1:
        sky = ["on-off", kind, clock(spans[0][0])]
    elif spans[0] == (0, FRAME_HOURS):
        sky = ["all", kind]
    elif spans[0][0] == 0:
        sky = ["until", kind, clock(spans[0][1])]
    elif spans[0][1] == FRAME_HOURS:
        sky = ["from", kind, clock(spans[0][0])]
    else:
        sky = ["between", kind, clock(spans[0][0]), clock(spans[0][1])]
    compare = None
    hourly, before = out.get("hourly"), (date.fromisoformat(day) - timedelta(days=1)).isoformat() + "T06:00"
    if hourly and before in hourly["time"]:
        today = hourly["temp"][hourly["time"].index(before):][:FRAME_HOURS]
        if len(today) == FRAME_HOURS and None not in today:
            change = max(temps) - max(today)
            if abs(change) >= 3:
                compare = ("much-" if abs(change) >= 6 else "") + ("warmer" if change > 0 else "cooler")
    # Like a rain code, a storm code with no likely-wet hour is not a storm worth a heads-up.
    alert = ("storm" if code in STORM_WMO and spans else "snow" if snow else "ice" if min(temps) <= 0
             else "heat" if max(temps) >= 30 else None)
    symbol = ("storm" if alert == "storm" else "snow" if snow and spans else "rain" if spans
              else "sun" if code in (0, 1) else "partly" if code == 2 else "cloud")
    bring = [[next(item for limit, item in CLOTHING if high < limit)]]
    if high - low >= 8:
        bring.append(["layers"])
    if snow:
        bring.append(["boots"])
    elif spans:
        bring.append(["umbrella-after", sky[2]] if sky[0] == "from" else ["umbrella"])
        if high < 10:
            bring.append(["waterproof-shoes"])
    return ["outlook", low, high, symbol, sky, compare, alert, bring]


def outlook_text(card, say=lambda words, **values: words.format(**values)):
    """The card's phrases; `say` translates them for the page."""
    _, _, _, _, sky, compare, alert, bring = card
    shape = SKY_TEXT[sky[0]] if sky[0] == "dry" else SKY_TEXT[sky[0]][sky[1]]
    times = dict(zip(("start", "end"), sky[2:])) if sky[0] == "between" else {"time": sky[2]} if len(sky) > 2 else {}
    return {"sky": say(shape, **times), "compare": compare and say(COMPARE_TEXT[compare]),
            "alert": alert and say(ALERT_TEXT[alert]),
            "bring": [say(BRING_TEXT[item[0]], **({"time": item[1]} if len(item) > 1 else {})) for item in bring]}


def brief(out):
    def fmt(value):
        return "?" if value is None else f"{value:g}"
    stale = " STALE" if out["cache_state"] == "stale" else ""
    if out.get("outlook"):
        card, words = out["outlook"], outlook_text(out["outlook"])
        facts = [words["sky"]] + [words[key] for key in ("compare", "alert") if words[key]]
        return (f"{out['city']} tomorrow ({out['day']}, 06:00–24:00 {out['timezone']}){stale}: {card[1]}..{card[2]}C. "
                + ". ".join(fact.rstrip(".") for fact in facts) + ". Get ready tonight: "
                + ", ".join(words["bring"]).lower() + ". [Open-Meteo]")
    probability = out.get("precip_prob_pct")
    rain = out["rain"] + (f" ({fmt(probability)}% precip)" if probability is not None else "")
    line = (f"{out['city']} {out['date']} {out['time'][11:16]} {out['timezone']}{stale}: "
            f"{out['condition']}, {fmt(out['temp_c'])}C "
            f"({fmt(out['temp_min_c'])}..{fmt(out['temp_max_c'])}C); rain {rain}.")
    ahead = out.get("ahead")
    if ahead:
        if ahead["rain_from"] is None:
            wet = "dry"
        elif ahead["rain_from"] == ahead["from"]:
            wet = "rain likely now" + (f", easing by {ahead['rain_until']}" if ahead["rain_until"] != ahead["until"] else "")
        else:
            wet = f"dry until {ahead['rain_from']}, then rain likely"
        line = (f"{out['city']} {out['date']} {out['time'][11:16]} {out['timezone']}{stale}: "
                f"{out['condition'] + ', ' if out['condition'] else ''}{fmt(out['temp_c'])}C; {ahead['from']}–{ahead['until']}: "
                f"{fmt(ahead['temp_min_c'])}..{fmt(ahead['temp_max_c'])}C, {wet} "
                f"(rain chance up to {fmt(ahead['rain_peak_pct'])}%).")
    if out["advice"]:
        line += " " + out["advice"]
    lines = [line + " [Open-Meteo]"]
    aqi = out.get("aqi")
    if aqi and aqi.get("us_aqi") is not None:
        is_model = aqi["source"] == "open-meteo/cams-model"
        source = "Open-Meteo/CAMS model" if is_model else "WAQI station"
        stamp = aqi["time"][11:16] if is_model else aqi["time"]
        line = f"AQI US {fmt(aqi['us_aqi'])} {aqi['level']} [{source}; {stamp}]"
        if aqi.get("cache_state") == "stale":
            line += " STALE"
        station = aqi.get("station") if is_model else aqi
        if isinstance(station, dict) and station.get("us_aqi") is not None:
            agencies = ", ".join(str(a.get("name", "")) for a in station.get("attributions", []) if isinstance(a, dict))
            label = f"{station.get('station') or 'nearby'}; {agencies}"
            if is_model:
                line += f"; WAQI station {fmt(station['us_aqi'])} {station['level']} ({label}; {station['time']})"
            else:
                line += f" ({label})"
        advice = aqi_advice(aqi["us_aqi"])
        if advice:
            line += ". " + advice
        lines.append(line)
    elif out["aqi_source"] != "off":
        lines.append("AQI unavailable.")
    if out.get("warnings"):
        lines.append("Warning: " + "; ".join(out["warnings"]))
    return "\n".join(lines)


def widget(runtime):
    """The phone widgets' forecast: the account's own city and cache, read the way the briefing reads it."""
    try:
        out = read(arguments(["--secretary-dir", str(runtime), "--timeout", "5"]))
    except WeatherError:
        out = {}
    if not out.get("frame"):
        return {"error": "Forecast unavailable"}
    return {"city": out["city"], "frame": out["frame"]}


def arguments(argv=None):
    ap = argparse.ArgumentParser(description="GoodMorning weather + AQI fetch (free sources only)")
    ap.add_argument("--city", default="")
    ap.add_argument("--region", choices=["global", "mainland-china"], default="")
    ap.add_argument("--lat", type=float, default=None)
    ap.add_argument("--lon", type=float, default=None)
    ap.add_argument("--profile", default="")
    ap.add_argument("--secretary-dir", help="Selected runtime; uses its profile.md and cache unless explicitly overridden")
    ap.add_argument("--aqi-source", choices=["auto", "open-meteo", "waqi", "off"], default="auto")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--day", type=lambda value: date.fromisoformat(value).isoformat(),
                    help="The evening card for 06:00–24:00 of a later local day (YYYY-MM-DD); no air quality")
    from .runtime_files import cache_path
    ap.add_argument("--cache-dir")
    ap.add_argument("--refresh", action="store_true", help="Fetch again; retain bounded stale fallback")
    ap.add_argument("--no-cache", action="store_true", help="No disk reads or writes")
    ap.add_argument("--timeout", type=float, default=TIMEOUT, help="Timeout per HTTP attempt in seconds (default: 8)")
    a = ap.parse_args(argv)

    if a.secretary_dir:
        from .runtime_files import secretary_path
        runtime = secretary_path(a.secretary_dir)
        a.profile = a.profile or str(runtime / 'profile.md')
        a.cache_dir = a.cache_dir or str(runtime / 'cache')
    a.cache_dir = a.cache_dir or str(cache_path())
    return a


def read(a):
    """The weather, AQI and forecast frame for parsed arguments; raises WeatherError when weather is unavailable."""
    from .runtime_files import cache_path
    prof_city, _ = parse_profile(find_profile(a.profile or None))
    city = a.city or os.environ.get("GM_CITY") or os.environ.get("CITY") or prof_city
    waqi_tok = os.environ.get("WAQI_TOKEN") or os.environ.get("WAQI_API_TOKEN", "")
    if not math.isfinite(a.timeout) or a.timeout <= 0:
        raise WeatherError("--timeout must be a positive finite number")
    if a.aqi_source == "waqi" and not waqi_tok:
        raise WeatherError("WAQI_TOKEN missing; get a free token at https://aqicn.org/data-platform/token/")
    cache = Cache(None if a.no_cache else cache_path(a.cache_dir) / "weather", a.refresh)
    location = {}
    if a.lat is not None or a.lon is not None:
        validate_coordinates(a.lat, a.lon)
        lat, lon = a.lat, a.lon
        city = a.city or f"{lat:g},{lon:g}"
    else:
        if not city:
            raise WeatherError("no city; pass --city, set GM_CITY, or set city in secretary/profile.md")
        location = cache.get("geocode:v2:" + city.casefold().strip(),
                             lambda: openmeteo_geocode(city, a.timeout), GEOCODE_TTL,
                             stale_limit=365 * 86400)
        lat, lon, city = location["latitude"], location["longitude"], location["city"]
    key = f"{lat},{lon}"
    jobs = {"weather": lambda: cache.get("weather:v2:" + key,
            lambda: fetch_openmeteo(city, lat, lon, a.timeout), WEATHER_TTL, STALE_LIMIT, daily=True)}
    if a.aqi_source in ("auto", "open-meteo") and not a.day:
        jobs["model"] = lambda: cache.get("aqi:" + key,
            lambda: fetch_aqi_openmeteo(lat, lon, a.timeout), AQI_TTL, STALE_LIMIT, daily=True)
    if waqi_tok and a.aqi_source in ("auto", "waqi") and not a.day:
        # WAQI forbids redistribution of cached/archive data. Keep station data live-only.
        jobs["station"] = lambda: fetch_aqi_waqi(lat=lat, lon=lon, token=waqi_tok, timeout=a.timeout)
    results, warnings = {}, []
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {name: pool.submit(fetch) for name, fetch in jobs.items()}
        for name, future in futures.items():
            try:
                results[name] = future.result()
            except (WeatherError, KeyError, TypeError, ValueError, AttributeError) as e:
                message = str(e) if isinstance(e, WeatherError) else "invalid provider response"
                if name == "weather":
                    raise WeatherError("weather unavailable: " + message) from None
                results[name] = {"error": message, "source": "waqi-station" if name == "station" else "open-meteo/cams-model"}
                warnings.append(name + ": " + message)
    out = results["weather"]
    out["city"] = city  # Labels are not part of the coordinate-keyed cache.
    out["latitude"], out["longitude"] = lat, lon
    if location.get("country"):
        out["country"], out["admin1"] = location["country"], location.get("admin1")
    for name in ("weather", "model"):
        if results.get(name, {}).get("cache_state") == "stale":
            warnings.append(name + ": using stale same-day data (" + results[name]["error"] + ")")
    if location.get("cache_state") == "stale":
        warnings.append("geocode: using saved coordinates")
    model, station = results.get("model"), results.get("station")
    if model and model.get("us_aqi") is not None:
        aqi = {**model}
        if station:
            aqi["station"] = station
    elif station and station.get("us_aqi") is not None:
        aqi = {**station}
        if model:
            aqi["model"] = model
    else:
        aqi = model or station
    out.update(aqi=aqi, aqi_source=a.aqi_source, warnings=warnings)
    if a.day:
        frame = forecast_frame(out, None, day=a.day)
        if not frame:
            raise WeatherError(f"no hourly forecast for {a.day}")
        # Today's condition, rain and advice would contradict tomorrow's card.
        keep = ("city", "country", "admin1", "latitude", "longitude", "timezone", "provider", "cache_state", "fetched_at", "warnings")
        return {**{key: out[key] for key in keep if key in out}, "day": a.day, "outlook": outlook(out, frame, a.day)}
    frame = forecast_frame(out, aqi)
    if frame:
        apply_frame(out, frame)
    out.pop("hourly", None)
    for value in (aqi, (aqi or {}).get("model")):
        if isinstance(value, dict):
            value.pop("hourly", None)
    return out


def main(argv=None):
    a = arguments(argv)
    try:
        out = read(a)
        print(json.dumps(out, ensure_ascii=False, separators=(",", ":"), allow_nan=False) if a.json else brief(out))
        return 0
    except WeatherError as e:
        if a.json:
            print(json.dumps({"error": str(e)}, separators=(",", ":")))
        else:
            print("error: " + str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
