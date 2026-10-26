# Weather usage

```bash
python scripts/goodmorning.py weather
python scripts/goodmorning.py weather --city 'London, GB'
python scripts/goodmorning.py weather --lat 51.5 --lon -0.12 --city London
python scripts/goodmorning.py weather --refresh
python scripts/goodmorning.py weather --aqi-source open-meteo --json
python scripts/goodmorning.py weather --no-cache
```

For `/gm`, run once and use the default brief. Preserve warnings, `STALE`,
timestamps, and source labels in the daily weather summary. Use JSON only for
setup verification, code, or troubleshooting; do not read raw provider/cache data.
Later runs cannot reconstruct an earlier morning's forecast.
Those diagnostics are internal records, not a script for the user-facing reply.
Normal messages give weather, practical advice and AQI health level; short source
labels are enough. Do not announce successful retrieval or append a routine
model-versus-station disclaimer. Stale/unavailable data or health warnings remain
visible when they affect the user's decision, once and in concise language.

## Location and sources

- City precedence: `--city`, `GM_CITY`, `CITY`, then `secretary/profile.md`.
  Use `--profile PATH` for another profile. Explicit `--lat` and `--lon` override
  location settings; an explicit city can supply their display label.
- Confirm a country/admin-qualified city or verified coordinates. The first
  geocoder match does not prove an ambiguous name is correct. JSON includes the
  resolved country/admin and coordinates. `--region` does not select a provider.
- Comma-qualified names search the city component and filter returned country
  ISO code/full English name and optional administrative region. Several matching
  coordinates or a country mismatch fail clearly; no arbitrary first result.
  Older first-result geocoding cache entries are not reused.
- Non-ASCII names are searched in their matching language first (for example
  `zh` for `上海`) with an English fallback. A bare native name that matches
  several places still needs a qualifier: `Shanghai, CN` or `上海, 上海市, CN`.
  Unknown non-ASCII names suggest Pinyin/English plus `--lat`/`--lon`.
- Open-Meteo weather and CAMS model AQI need no key. The free Open-Meteo service
  is non-commercial only and has no uptime guarantee.
- Optional WAQI station cross-check: register at
  <https://aqicn.org/data-platform/token/> and provide `WAQI_TOKEN` or
  `WAQI_API_TOKEN` through the environment, never in a profile or source file.
  Select `--aqi-source auto|open-meteo|waqi|off`.
- In `auto`, usable model AQI stays primary; a station can be a fallback after
  model failure. Conflicting readings are not averaged. Both use US AQI, but
  observation times and methods differ. Model AQI is not a local sensor.
- Model `pm25`/`o3` are concentrations (`ug/m3`); WAQI pollutant values are AQI
  subindexes, not concentrations. Preserve station/agency attribution. Check
  WAQI terms before publishing station data; do not redistribute caches/archives.

## Freshness and failures

- Cache: `.cache/goodmorning/weather/`, `$GM_CACHE_DIR/weather/`, or
  `--cache-dir DIR` plus `/weather/`.
- Geocoding is fresh for 30 days; outage fallback lasts up to 365 days with a
  warning. A changed city uses a separate key. Weather is fresh for 30 minutes;
  model AQI for 60 minutes.
- Failed refreshes may use same-local-day weather/model data up to six hours old.
  Yesterday's forecast is never reused as today's. WAQI is live-only; station
  readings need an offset-bearing timestamp within the allowed freshness window.
- `--refresh` bypasses fresh hits but retains bounded outage fallback.
  `--no-cache` disables disk reads/writes, including geocoding fallback.
- Weather unavailable without fallback exits 1 with a short error (`--json`
  returns an error object). Invalid arguments exit 2. Optional AQI failure exits
  0 with visible warnings or a station fallback. AQI `off` does not mean good AQI.
- Network timeout defaults to eight seconds per socket attempt, not a whole-run
  deadline. Network errors and selected server errors get one retry.
- Initialization uses `python scripts/goodmorning.py setup --verify weather --budget 20` after consent
  to enforce an elapsed deadline including DNS and retries. Partial weather/AQI
  results remain pending verification even when weather.py exits zero.

With the provider's hourly forecast, rain, the umbrella advice and the brief's
high/low cover only the hours ahead in an 18-hour frame: 06:00–24:00, or 18:00
to noon the next day for runs after 18:00 local. An hour with at least 50%
precipitation probability is wet; a snow day is not rain. Advice names a later
start ("umbrella for after 21:00"). When the current hour is dry, a current
drizzle, rain, shower or snow condition is dropped (`condition` null), so the
brief never pairs "light drizzle" with "dry until 09:00". JSON adds `ahead` and `frame` (hourly
temperature, rain chance and AQI, sunrise/sunset, night spans, source links).
Browser jobs attach that `frame` to the saved weather block when the section is
published, so its charts and headlines are code-owned.

Without hourly data, `rain yes` is a full-local-day umbrella heuristic: at least 50% precipitation
probability without a snow forecast, or a rain/storm code or more than 0.2 mm
rain/showers when the probability is at least 30% or missing. A rain code with a
lower probability is `no`, so the brief never pairs an umbrella with 0%. Missing
facts can produce `unknown`; snow does not automatically mean rain. This brief is not a severe-weather alert service.

JSON includes location, local date/time/timezone, daily conditions, freshness,
and warnings. `cache_state` is `live`, `cached`, or `stale`; `fetched_at` is fetch
time, not model issuance time. Station times retain their UTC offsets.
