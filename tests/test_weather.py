"""Weather contract, caching, failure, and output tests; no real credentials."""

import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from support import TEMP_ROOT
import threading
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from goodmorning import weather as w

NOW = datetime(2026, 10, 9, 9, tzinfo=timezone.utc).timestamp()


def forecast(**daily):
    return {"timezone": "Europe/London",
            "current": {"time": "2026-10-09T10:00", "temperature_2m": 12, "weather_code": 0},
            "daily": {"time": ["2026-10-09"], "temperature_2m_min": [9],
                      "temperature_2m_max": [17], "weather_code": [0],
                      "precipitation_probability_max": [10], "rain_sum": [0],
                      "showers_sum": [0], "snowfall_sum": [0], **daily}}


def hourly(wet=(21, 22, 23, 27)):
    """Two synthetic local days; rain at 03:00 (already past by 10:00) and from 21:00."""
    times = [f"2026-10-{9 + h // 24:02d}T{h % 24:02d}:00" for h in range(48)]
    return {"time": times, "temperature_2m": [8 + (h % 24) / 4 for h in range(48)],
            "precipitation_probability": [100 if h == 3 else 80 if h in wet else 5 for h in range(48)]}


def model():
    return {"timezone": "Europe/London", "current": {"time": "2026-10-09T10:00",
            "us_aqi": 27, "european_aqi": 21, "pm2_5": 3.8, "ozone": 54}}


def station():
    return {"status": "ok", "data": {"aqi": 60, "time": {"iso": "2026-10-09T09:00:00+00:00"},
            "iaqi": {"pm25": {"v": 60}}, "city": {"name": "Test station", "url": "https://example.org/station"},
            "attributions": [{"name": "Test EPA", "url": "https://example.org"}]}}


class WeatherTests(unittest.TestCase):
    def test_runtime_flag_selects_profile_and_private_cache(self):
        runtime=Path(self.tmp.name)/'runtime';runtime.mkdir()
        (runtime/'profile.md').write_text('city: London, GB\n')
        output=io.StringIO()
        with patch.object(w,'http_get_json',side_effect=self.provider),contextlib.redirect_stdout(output):
            self.assertEqual(w.main(['--secretary-dir',str(runtime),'--json']),0)
        self.assertEqual(json.loads(output.getvalue())['city'],'London')
        self.assertEqual(json.loads(output.getvalue())['country'],'GB')
        self.assertTrue(list((runtime/'cache/weather').glob('*.json')))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.tmp.cleanup)
        clock_patch = patch.object(w.time, "time", return_value=NOW)
        self.clock = clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.calls = []

    def provider(self, url, **kwargs):
        self.calls.append(url)
        if "geocoding" in url:
            return {"results": [{"latitude": 51.5, "longitude": -0.12, "name": "London", "country_code": "GB"}]}
        if "air-quality" in url:
            return model()
        if "waqi" in url:
            return station()
        return forecast()

    def run_cli(self, *args, provider=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(w, "http_get_json", side_effect=provider or self.provider), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = w.main(["--cache-dir", self.tmp.name, "--profile", self.tmp.name + "/missing", *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cold_warm_refresh_and_no_cache(self):
        for flags, count in (([], 3), ([], 0), (["--refresh"], 3), (["--no-cache"], 3)):
            self.calls.clear()
            code, text, _ = self.run_cli("--city", "London, GB", "--json", *flags)
            self.assertEqual(code, 0)
            self.assertEqual(len(self.calls), count)
            out = json.loads(text)
            self.assertEqual(out["aqi"]["us_aqi"], 27)
            self.assertEqual(out["country"], "GB")
            self.assertEqual(out["cache_state"], "cached" if count == 0 else "live")

    def test_independent_expiry(self):
        self.run_cli("--city", "London")
        self.clock.return_value = NOW + w.WEATHER_TTL + 1
        self.calls.clear()
        self.run_cli("--city", "London")
        self.assertEqual(len(self.calls), 1)
        self.assertIn("api.open-meteo.com/v1/forecast", self.calls[0])

    def test_coordinates_bypass_lookup_and_environment_label(self):
        os.environ["GM_CITY"] = "Wrong city"
        code, text, _ = self.run_cli("--lat", "51.5", "--lon", "-0.12", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(json.loads(text)["city"], "51.5,-0.12")

    def test_coordinate_label_not_cached(self):
        self.run_cli("--lat", "51.5", "--lon", "-0.12", "--city", "First")
        _, text, _ = self.run_cli("--lat", "51.5", "--lon", "-0.12", "--city", "Second", "--json")
        self.assertEqual(json.loads(text)["city"], "Second")

    def test_invalid_inputs_do_not_fetch(self):
        for args in (("--lat", "50"), ("--lon", "0"), ("--lat", "nan", "--lon", "0"),
                     ("--lat", "91", "--lon", "0"), ("--timeout", "0"), ("--timeout", "inf"),
                     ("--aqi-source", "waqi"), ()):
            code, text, _ = self.run_cli(*args, "--json")
            self.assertEqual(code, 1)
            self.assertIn("error", json.loads(text))
        self.assertEqual(self.calls, [])

    def test_profile_and_environment_precedence(self):
        profile = Path(self.tmp.name) / "profile.md"
        profile.write_text("city: 'Paris, FR'\nregion: global\n")
        os.environ["GM_CITY"] = "Berlin, DE"
        self.run_cli("--profile", str(profile), "--city", "London, GB")
        self.assertIn("name=London&", self.calls[0])
        self.assertEqual(w.parse_profile(profile), ("Paris, FR", "global"))
        profile.write_text("city:\nregion: global\n")
        self.assertEqual(w.parse_profile(profile), ("", "global"))

    def test_qualified_city_filters_country_instead_of_using_first_match(self):
        candidates = {"results": [
            {"name": "London", "latitude": 42.98, "longitude": -81.25, "country_code": "CA", "country": "Canada", "admin1": "Ontario"},
            {"name": "London", "latitude": 51.5, "longitude": -0.12, "country_code": "GB", "country": "United Kingdom", "admin1": "England"},
            {"name": "City of London", "latitude": 51.51, "longitude": -0.09, "country_code": "GB", "country": "United Kingdom", "admin1": "England"}]}
        with patch.object(w, "http_get_json", return_value=candidates) as fetch:
            result = w.openmeteo_geocode("London, England, United Kingdom")
        self.assertEqual(result["country"], "GB")
        self.assertIn("name=London&", fetch.call_args.args[0])

    def test_ambiguous_city_is_not_silently_resolved(self):
        candidates = {"results": [
            {"name": "London", "latitude": 42.98, "longitude": -81.25, "country_code": "CA"},
            {"name": "London", "latitude": 51.5, "longitude": -0.12, "country_code": "GB"}]}
        with patch.object(w, "http_get_json", return_value=candidates), self.assertRaisesRegex(w.WeatherError, "ambiguous"):
            w.openmeteo_geocode("London")

    def test_geocode_language_order_matches_script(self):
        self.assertEqual(w._geocode_languages("上海")[0], "zh")
        self.assertEqual(w._geocode_languages("Москва")[0], "ru")
        self.assertEqual(w._geocode_languages("London")[0], "en")
        self.assertEqual(w._geocode_languages("Shanghai, CN")[-1], "zh")

    def test_cjk_city_resolves_when_english_index_has_no_match(self):
        shanghai = {"results": [
            {"name": "上海", "latitude": 31.22, "longitude": 121.45,
             "country_code": "CN", "country": "中国", "admin1": "上海市"}]}
        def provider(url, **kwargs):
            self.calls.append(url)
            if "language=en" in url:
                return {}
            return shanghai
        with patch.object(w, "http_get_json", side_effect=provider):
            result = w.openmeteo_geocode("上海, 上海市, CN")
        self.assertEqual(result["country"], "CN")
        self.assertEqual(result["latitude"], 31.22)
        self.assertIn("language=zh", self.calls[0])

    def test_ascii_city_falls_back_to_second_language(self):
        hit = {"results": [
            {"name": "Testville", "latitude": 1.0, "longitude": 2.0, "country_code": "GB"}]}
        def provider(url, **kwargs):
            self.calls.append(url)
            return {} if "language=en" in url else hit
        with patch.object(w, "http_get_json", side_effect=provider):
            result = w.openmeteo_geocode("Testville")
        self.assertEqual(result["latitude"], 1.0)
        self.assertEqual(len(self.calls), 2)

    def test_qualifier_mismatch_tries_next_language(self):
        english = {"results": [
            {"name": "London", "latitude": 51.5, "longitude": -0.12,
             "country_code": "GB", "country": "United Kingdom", "admin1": "England"}]}
        chinese = {"results": [
            {"name": "倫敦", "latitude": 51.5, "longitude": -0.12,
             "country_code": "GB", "country": "英国", "admin1": "英格兰"}]}
        def provider(url, **kwargs):
            return chinese if "language=zh" in url else english
        with patch.object(w, "http_get_json", side_effect=provider):
            result = w.openmeteo_geocode("London, 英格兰, GB")
        self.assertEqual(result["country"], "GB")

    def test_unknown_city_fails_after_every_language_index(self):
        for city in ("不存在的城市", "NoSuchCityXYZ"):
            with patch.object(w, "http_get_json", return_value={}) as fetch, self.assertRaises(w.WeatherError):
                w.openmeteo_geocode(city)
            self.assertEqual(fetch.call_count, len(w._geocode_languages(city)))

    def test_afternoon_rain_despite_clear_current_conditions(self):
        for change in ({"weather_code": [61], "precipitation_probability_max": [30]},
                       {"rain_sum": [2], "precipitation_probability_max": [None]},
                       {"precipitation_probability_max": [80]}):
            with patch.object(w, "http_get_json", return_value=forecast(**change)):
                out = w.fetch_openmeteo("Test", 0, 0)
            self.assertEqual(out["condition"], "clear")
            self.assertEqual(out["rain"], "yes")

    def test_rain_code_with_low_probability_is_not_rain(self):
        for change in ({"weather_code": [61], "precipitation_probability_max": [5]},
                       {"weather_code": [51], "rain_sum": [0.4], "precipitation_probability_max": [0]}):
            with patch.object(w, "http_get_json", return_value=forecast(**change)):
                out = w.fetch_openmeteo("Test", 0, 0)
            self.assertEqual(out["rain"], "no")
            self.assertNotIn("umbrella", out["advice"])

    def test_daily_snow_is_not_rain(self):
        with patch.object(w, "http_get_json", return_value=forecast(weather_code=[73], snowfall_sum=[3], precipitation_probability_max=[90])):
            out = w.fetch_openmeteo("Test", 0, 0)
        self.assertEqual(out["rain"], "no")
        self.assertTrue(out["snow"])

    def test_missing_rain_facts_are_unknown(self):
        with patch.object(w, "http_get_json", return_value=forecast(weather_code=[None], rain_sum=[None], showers_sum=[None], precipitation_probability_max=[None])):
            out = w.fetch_openmeteo("Test", 0, 0)
        self.assertEqual(out["rain"], "unknown")

    def test_bad_weather_schema_and_old_day_fail_cleanly(self):
        for data in ({}, {"current": []}, forecast(time=["2026-10-08"]),
                     forecast(rain_sum=["bad"]), forecast(weather_code="bad"),
                     forecast(precipitation_probability_max=[101])):
            code, text, _ = self.run_cli("--city", "Test", "--no-cache", "--json",
                                       provider=lambda url, **kw: self.provider(url, **kw) if "geocoding" in url else data)
            self.assertEqual(code, 1)
            self.assertIn("error", json.loads(text))

    def test_malformed_and_old_current_timestamps_rejected(self):
        for stamp in (123, "bad", "2026-10-09T00:00"):
            data = forecast()
            data["current"]["time"] = stamp
            with patch.object(w, "http_get_json", return_value=data), self.assertRaises(w.WeatherError):
                w.fetch_openmeteo("Test", 0, 0)

    def test_valid_json_with_bad_cache_schema_is_refetched(self):
        cache = w.Cache(Path(self.tmp.name) / "weather")
        cache.directory.mkdir()
        cache.write("geocode:test", {"version": 1, "fetched_at": NOW, "data": {}})
        code, _, _ = self.run_cli("--city", "Test")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls), 3)

    def test_aqi_mode_changes_do_not_reuse_wrong_source(self):
        os.environ["WAQI_TOKEN"] = "fake-test-token"
        self.run_cli("--city", "Test", "--aqi-source", "off")
        for source, expected in (("open-meteo", "open-meteo/cams-model"), ("waqi", "waqi-station")):
            _, text, _ = self.run_cli("--city", "Test", "--aqi-source", source, "--json")
            self.assertEqual(json.loads(text)["aqi"]["source"], expected)

    def test_forecast_cache_does_not_hide_model_failure(self):
        self.run_cli("--city", "Test", "--aqi-source", "off")
        def provider(url, **kwargs):
            raise w.WeatherError("HTTP 503")
        code, text, _ = self.run_cli("--city", "Test", provider=provider)
        self.assertEqual(code, 0)
        self.assertIn("AQI unavailable", text)

    def test_aqi_failure_visible_without_failing_weather(self):
        def provider(url, **kwargs):
            if "air-quality" in url:
                raise w.WeatherError("HTTP 429")
            return self.provider(url, **kwargs)
        code, text, _ = self.run_cli("--city", "Test", provider=provider)
        self.assertEqual(code, 0)
        self.assertIn("AQI unavailable", text)
        self.assertIn("HTTP 429", text)

    def test_model_failure_uses_station_and_preserves_error(self):
        os.environ["WAQI_TOKEN"] = "fake-test-token"
        def provider(url, **kwargs):
            if "air-quality" in url:
                raise w.WeatherError("HTTP 503")
            return self.provider(url, **kwargs)
        code, text, _ = self.run_cli("--city", "Test", "--json", provider=provider)
        out = json.loads(text)
        self.assertEqual(code, 0)
        self.assertEqual(out["aqi"]["source"], "waqi-station")
        self.assertIn("error", out["aqi"]["model"])

    def test_station_indexes_attribution_and_live_only(self):
        os.environ["WAQI_TOKEN"] = "fake-test-token"
        for _ in range(2):
            code, text, _ = self.run_cli("--city", "Test", "--json")
            st = json.loads(text)["aqi"]["station"]
            self.assertEqual(code, 0)
            self.assertEqual(st["pm25_subindex"], 60)
            self.assertNotIn("pm25", st)
            self.assertEqual(st["attributions"][0]["name"], "Test EPA")
        self.assertEqual(sum("waqi" in url for url in self.calls), 2)
        for path in Path(self.tmp.name).rglob("*.json"):
            self.assertNotIn("fake-test-token", path.read_text())
            self.assertNotIn("Test station", path.read_text())

    def test_station_failure_kept_with_healthy_model(self):
        os.environ["WAQI_TOKEN"] = "fake-test-token"
        def provider(url, **kwargs):
            if "waqi" in url:
                return {"status": "error", "data": "fake-test-token must not leak"}
            return self.provider(url, **kwargs)
        _, text, _ = self.run_cli("--city", "Test", "--json", provider=provider)
        self.assertIn("error", json.loads(text)["aqi"]["station"])
        self.assertNotIn("fake-test-token", text)

    def test_old_station_observation_rejected(self):
        data = station()
        data["data"]["time"]["iso"] = "2026-10-08T09:00:00+00:00"
        with patch.object(w, "http_get_json", return_value=data), self.assertRaisesRegex(w.WeatherError, "older than"):
            w.fetch_aqi_waqi(lat=0, lon=0, token="fake")

    def test_aqi_off_skips_all_air_requests(self):
        os.environ["WAQI_TOKEN"] = "fake"
        code, text, _ = self.run_cli("--city", "Test", "--aqi-source", "off", "--json")
        self.assertEqual(code, 0)
        self.assertIsNone(json.loads(text)["aqi"])
        self.assertEqual(len(self.calls), 2)

    def test_sources_execute_concurrently(self):
        barrier = threading.Barrier(2)
        def provider(url, **kwargs):
            if "geocoding" not in url:
                barrier.wait(timeout=2)
            return self.provider(url, **kwargs)
        self.assertEqual(self.run_cli("--city", "Test", provider=provider)[0], 0)

    def test_stale_fallback_expires_and_never_crosses_local_midnight(self):
        self.run_cli("--city", "Test")
        def offline(url, **kwargs):
            raise w.WeatherError("network unavailable or timed out")
        self.clock.return_value = NOW + 3601
        code, text, _ = self.run_cli("--city", "Test", provider=offline)
        self.assertEqual(code, 0)
        self.assertIn("STALE", text)
        self.clock.return_value = NOW + w.STALE_LIMIT + 1
        self.assertEqual(self.run_cli("--city", "Test", provider=offline)[0], 1)
        # Less than six hours old, but the local calendar day has changed.
        cache = w.Cache(Path(self.tmp.name) / "midnight")
        self.clock.return_value = datetime(2026, 10, 9, 22, 30, tzinfo=timezone.utc).timestamp()
        cache.get("test", lambda: {"date": "2026-10-09", "timezone": "Europe/London"}, 1800, w.STALE_LIMIT, True)
        self.clock.return_value += 3600
        with self.assertRaises(w.WeatherError):
            cache.get("test", lambda: offline(""), 1800, w.STALE_LIMIT, True)

    def test_refresh_with_providers_down_returns_usable_cache_as_stale(self):
        self.run_cli("--city", "Test", "--aqi-source", "off")
        def offline(url, **kwargs):
            raise w.WeatherError("network unavailable or timed out")
        code, text, _ = self.run_cli("--city", "Test", "--aqi-source", "off", "--refresh", "--json", provider=offline)
        out = json.loads(text)
        self.assertEqual(code, 0)
        self.assertEqual(out["cache_state"], "stale")
        self.assertEqual(out["fetched_at"], w.utc_time(NOW))
        self.assertEqual(out["temp_c"], 12)

    def test_corrupt_cache_and_write_failure_are_best_effort(self):
        cache = w.Cache(self.tmp.name)
        cache.path("x").write_text("{broken")
        self.assertEqual(cache.get("x", lambda: {"value": 1}, 60)["value"], 1)
        with patch.object(w.os, "replace", side_effect=OSError("disk full")):
            self.assertEqual(cache.get("y", lambda: {"value": 2}, 60)["value"], 2)
        self.assertEqual(len(list(Path(self.tmp.name).glob("*"))), 1)

    def test_cache_does_not_write_errors_or_future_clock_entries(self):
        cache = w.Cache(self.tmp.name)
        with self.assertRaises(w.WeatherError):
            cache.get("x", lambda: (_ for _ in ()).throw(w.WeatherError("fail")), 60)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
        cache.get("x", lambda: {"value": 1}, 60)
        self.clock.return_value = NOW - 1
        self.assertEqual(cache.get("x", lambda: {"value": 2}, 60)["value"], 2)

    def test_http_retry_policy_and_url_secret_redaction(self):
        url = "https://example.org/?token=fake-test-token"
        for status, attempts in ((429, 1), (401, 1), (503, 2)):
            with patch.object(w.urllib.request, "urlopen", side_effect=urllib.error.HTTPError(url, status, "bad", {}, None)) as request, patch.object(w.time, "sleep"):
                with self.assertRaises(w.WeatherError) as error:
                    w.http_get_json(url)
                self.assertEqual(request.call_count, attempts)
                self.assertNotIn("fake-test-token", str(error.exception))

    def test_network_retry_and_invalid_json(self):
        with patch.object(w.urllib.request, "urlopen", side_effect=urllib.error.URLError("secret URL")) as request, patch.object(w.time, "sleep"):
            with self.assertRaisesRegex(w.WeatherError, "network"):
                w.http_get_json("https://example.org")
            self.assertEqual(request.call_count, 2)
        with patch.object(w.urllib.request, "urlopen", return_value=contextlib.nullcontext(io.StringIO("not JSON"))) as request:
            with self.assertRaisesRegex(w.WeatherError, "JSON"):
                w.http_get_json("https://example.org")
            self.assertEqual(request.call_count, 1)

    def test_http_payload_is_bounded(self):
        with patch.object(w.urllib.request, "urlopen", return_value=contextlib.nullcontext(io.BytesIO(b"x" * (w.MAX_RESPONSE_BYTES + 1)))):
            with self.assertRaisesRegex(w.WeatherError, "too large"):
                w.http_get_json("https://example.org")

    def frame_output(self, now=NOW):
        data = forecast()
        data["hourly"] = hourly()
        data["daily"].update(sunrise=["2026-10-09T07:30", "2026-10-10T07:32"], sunset=["2026-10-09T18:00", "2026-10-10T17:58"])
        with patch.object(w, "http_get_json", return_value=data):
            out = w.fetch_openmeteo("Test", 51.5, -0.12)
        out.update(latitude=51.5, longitude=-0.12)
        air = {"source": "open-meteo/cams-model", "hourly": {"time": data["hourly"]["time"], "us_aqi": [30] * 48}}
        return out, w.forecast_frame(out, air, now=now)

    def test_frame_judges_rain_from_the_hours_ahead_not_the_whole_day(self):
        out, frame = self.frame_output()  # 10:00 in London: the 03:00 rain has passed.
        self.assertEqual((frame["start"], frame["past"]), ("2026-10-09T06:00", 4))
        self.assertEqual(frame["sun"], [["sunrise", 1.5], ["sunset", 12.0]])
        self.assertEqual(frame["night"], [[0, 1.5], [12.0, 18]])
        self.assertTrue(frame["links"]["forecast"].endswith("#api_response"))
        w.apply_frame(out, frame)
        self.assertEqual(out["ahead"]["rain_from"], "21:00")
        self.assertEqual(out["precip_prob_pct"], 80)
        self.assertEqual(out["advice"], "umbrella for after 21:00; cool, bring a jacket.")
        out.update(cache_state="live", aqi=None, aqi_source="off", warnings=[])
        self.assertIn("10:00–24:00: 10.5..13.8C, dry until 21:00, then rain likely (rain chance up to 80%)", w.brief(out))

    def test_late_frame_runs_to_noon_and_dry_hours_mean_no_umbrella(self):
        out, frame = self.frame_output(datetime(2026, 10, 9, 22, tzinfo=timezone.utc).timestamp())
        self.assertEqual((frame["start"], frame["past"]), ("2026-10-09T18:00", 5))
        self.assertEqual(frame["night"], [[0, 13.53]])
        w.apply_frame(out, frame)
        self.assertEqual((out["ahead"]["rain_from"], out["ahead"]["rain_until"]), ("23:00", "00:00"))
        frame["hours"] = [[10, 5, 30]] * 18
        w.apply_frame(out, frame)
        self.assertEqual(out["rain"], "no")
        self.assertNotIn("umbrella", out["advice"])

    def test_missing_hourly_data_keeps_the_daily_judgement(self):
        with patch.object(w, "http_get_json", return_value=forecast(precipitation_probability_max=[80])):
            out = w.fetch_openmeteo("Test", 0, 0)
        self.assertIsNone(w.forecast_frame(out, None, now=NOW))
        self.assertEqual(out["rain"], "yes")
        code, text, _ = self.run_cli("--city", "Test", "--json")
        self.assertNotIn("frame", json.loads(text))
        self.assertNotIn("hourly", json.loads(text))

    def test_widget_reads_the_account_city_and_returns_only_the_frame(self):
        runtime = Path(self.tmp.name) / "runtime"
        runtime.mkdir()
        def provider(url, **kwargs):
            data = self.provider(url, **kwargs)
            if "api.open-meteo.com/v1/forecast" in url:
                data["hourly"] = hourly()
                data["daily"].update(sunrise=["2026-10-09T07:30", "2026-10-10T07:32"], sunset=["2026-10-09T18:00", "2026-10-10T17:58"])
            return data
        with patch.object(w, "http_get_json", side_effect=provider):
            self.assertEqual(w.widget(runtime), {"error": "Forecast unavailable"})  # No city saved yet.
            (runtime / "profile.md").write_text("city: London, GB\n")
            result = w.widget(runtime)
        self.assertEqual(set(result), {"city", "frame"})
        self.assertEqual((result["city"], result["frame"]["start"]), ("London", "2026-10-09T06:00"))

    def test_aqi_thresholds_and_missing_model_value(self):
        for value, level in ((50, "good"), (51, "moderate"), (101, "unhealthy for sensitive groups"),
                             (151, "unhealthy"), (201, "very unhealthy"), (301, "hazardous")):
            self.assertEqual(w.aqi_level(value), level)
        data = model()
        data["current"]["us_aqi"] = None
        with patch.object(w, "http_get_json", return_value=data), self.assertRaises(w.WeatherError):
            w.fetch_aqi_openmeteo(0, 0)


if __name__ == "__main__":
    unittest.main()
