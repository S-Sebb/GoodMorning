"""Reproducible synthetic comparison; not a provider-speed or accuracy test."""

import contextlib
import io
import json
import os
import tempfile
from support import TEMP_ROOT
import time
from unittest.mock import patch

from test_weather import NOW, forecast, model, w


def main():
    calls = []
    def provider(url, **kwargs):
        calls.append(url)
        time.sleep(0.04)  # Equal artificial latency for every source.
        if "geocoding" in url:
            return {"results": [{"name": "London", "latitude": 51.5, "longitude": -0.12}]}
        if "air-quality" in url:
            return model()
        data = forecast(weather_code=[61], precipitation_probability_max=[90], rain_sum=[2])
        data["current"]["weather_code"] = 3
        return data

    with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, patch.dict(os.environ, {}, clear=True), patch.object(w.time, "time", return_value=NOW), patch.object(w, "http_get_json", side_effect=provider):
        # Reconstruct the previous serial fetch order and normalized output.
        start = time.perf_counter()
        location = w.openmeteo_geocode("London")
        data = w.fetch_openmeteo("London", location["latitude"], location["longitude"])
        aqi = w.fetch_aqi_openmeteo(location["latitude"], location["longitude"])
        baseline_seconds = time.perf_counter() - start
        old = {key: data[key] for key in ("city", "temp_c", "temp_min_c", "temp_max_c", "rain", "precip_prob_pct", "condition", "provider")}
        old["aqi"] = {key: aqi[key] for key in ("us_aqi", "eu_aqi", "pm25", "o3", "level", "source")}
        old["advice"] = "rain yes, take umbrella; cool, bring a jacket. air clean."
        old_json = json.dumps(old, ensure_ascii=False, indent=2)
        old_text = ("London: overcast, 12C (min 9/max 17C), rain: yes [open-meteo]\n"
                    "AQI (US): 27 good (PM2.5 3.8, EU 21) [model]\n" + old["advice"])
        measurements = {"old_serial": {"http_calls": len(calls), "seconds": round(baseline_seconds, 4)}}
        outputs = {}
        for name, flags in (("cold", []), ("warm", []), ("json", ["--json"])):
            calls.clear()
            stream = io.StringIO()
            start = time.perf_counter()
            with contextlib.redirect_stdout(stream):
                code = w.main(["--city", "London", "--profile", directory + "/missing", "--cache-dir", directory, *flags])
            assert code == 0
            text = stream.getvalue().strip()
            outputs[name] = text
            measurements[name] = {"http_calls": len(calls), "seconds": round(time.perf_counter() - start, 4)}
        sizes = {name: {"chars": len(text), "tokens_est_chars_div_4": round(len(text) / 4)}
                 for name, text in (("old_json", old_json), ("old_text", old_text),
                                    ("new_brief", outputs["cold"]), ("new_json", outputs["json"]))}
        print(json.dumps({"method": "synthetic, 40ms per HTTP call; token counts are estimates",
                          "runs": measurements, "output_sizes": sizes,
                          "brief_vs_old_json_reduction_pct": round(100 * (1 - len(outputs["cold"]) / len(old_json)), 1)}, indent=2))


if __name__ == "__main__":
    main()
