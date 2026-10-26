#!/usr/bin/env python3
"""Compact setup preflight; fetching requires explicit --verify selections.

Never initializes profile, calendar, state, reports, or delivery flags. Optional
weather verification may write its cache only under the selected runtime.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

from .calendar.public_holidays import regions as holiday_countries
from .runtime_files import profile_fields, secretary_path, normalize_secretary_name, normalize_user_name
from .news.news import load_sources, SOURCES_FILE
from .paths import ROOT



def profile_status(runtime, fields, website_language=None):
    """Local readiness only; never contacts providers or initializes storage."""
    if website_language is not None:
        from .web.language import reply_language
        fields={**fields,'secretary_language':reply_language(website_language)}
    required = ["secretary_language", "city", "timezone", "news_country"]
    missing = [key for key in required if not fields.get(key)]
    if fields.get("timezone"):
        ZoneInfo(fields["timezone"])
    countries = list(dict.fromkeys(code.strip() for code in [fields.get("news_country", "").upper(),
                     *fields.get("news_additional_countries", "").upper().replace(";", ",").split(",")] if code.strip()))
    if len(countries) > 20 or any(len(code) != 2 or not code.isascii() or not code.isalpha() for code in countries):
        raise ValueError("invalid countries")
    secretary_name = normalize_secretary_name(fields.get("secretary_name", ""))
    user_name = normalize_user_name(fields.get("user_name", ""))
    try:  # Optional: a bad line shows no holidays but never blocks setup.
        holidays = holiday_countries(fields.get("holiday_countries")) or ("declined" if fields.get("holiday_countries") else None)
    except ValueError:
        holidays = "invalid"
    return {"profile_ready": not missing, "missing_fields": missing, "countries": countries,
            "secretary_language": fields.get("secretary_language") or None,
            "secretary_name": secretary_name or None, "user_name": user_name or None,
            "holiday_countries": holidays,
            "language_status": "website" if website_language is not None else "confirmed" if fields.get("secretary_language") else "missing"}


def run_check(command, deadline, env=None):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return {"status": "pending", "reason": "deadline_exhausted"}
    try:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, start_new_session=True)
        try:
            output, _ = child.communicate(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.communicate()
            return {"status": "pending", "reason": "timeout"}
        try:
            data = json.loads(output)
        except (ValueError, TypeError):
            return {"status": "pending", "reason": "invalid_check_output"}
        if not isinstance(data, dict):
            return {"status": "pending", "reason": "invalid_check_output"}
        if child.returncode:
            return {"status": "pending", "reason": data.get("reason", data.get("error", "check_failed")), "result": data}
        if data.get("ok") is False or data.get("status") == "pending":
            return {"status": "pending", "reason": data.get("reason", "check_failed"), "result": data}
        return {"status": "verified", "result": data}
    except OSError:
        return {"status": "pending", "reason": "check_unavailable"}


def run_checks(commands, budget, env=None):
    deadline = time.monotonic() + budget
    def check(item):
        name, command = item
        result = run_check(command, deadline, env)
        if name == "weather" and result["status"] == "verified":
            data = result["result"]
            if (data.get("warnings") or data.get("cache_state") == "stale"
                    or not data.get("country") or (data.get("aqi") or {}).get("us_aqi") is None):
                result = {"status": "pending", "reason": "partial_or_unverified_weather", "result": data}
        return name, result
    with ThreadPoolExecutor(max_workers=min(4, len(commands) or 1)) as pool:
        return dict(pool.map(check, commands.items()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secretary-dir")
    parser.add_argument('--website-language',choices=('en','zh-CN'),help='Use the selected website language without changing local preferences')
    parser.add_argument("--verify", nargs="+", choices=("weather", "news", "projects"), default=[])
    parser.add_argument("--budget", type=float, default=20, help="Total elapsed budget for all selected checks (default 20 seconds)")
    args = parser.parse_args(argv)
    if not math.isfinite(args.budget) or not 0 < args.budget <= 120:
        parser.error("--budget must be finite and in (0, 120]")
    runtime = secretary_path(args.secretary_dir)
    try:
        fields = profile_fields(runtime)
        local = profile_status(runtime, fields, args.website_language)
        missing, countries = local["missing_fields"], local["countries"]
        commands, checks = {}, {}
        py = sys.executable
        cache = runtime / "cache"
        if "weather" in args.verify:
            if fields.get("city"):
                commands["weather"] = [py, "scripts/goodmorning.py", "weather", "--profile", str(runtime / "profile.md"),
                    "--city", fields["city"], "--cache-dir", str(cache), "--aqi-source", "open-meteo", "--timeout", "3", "--json"]
            else:
                checks["weather"] = {"status": "pending", "reason": "missing_city"}
        if "news" in args.verify:
            if not countries or not fields.get("timezone"):
                checks["news"] = {"status": "pending", "reason": "missing_country_or_timezone"}
            try:
                sources = load_sources(fields.get("news_sources_path") or SOURCES_FILE)
            except (OSError, ValueError, TypeError):
                sources = None
            for country in countries if fields.get("timezone") else []:
                if sources is None or not sources.get("countries", {}).get(country):
                    checks["news:" + country] = {"status": "pending", "reason": "missing_or_invalid_country_feed_configuration"}
                    continue
                command = [py, "scripts/goodmorning.py", "news", "--verify-sources", "--country", country,
                    "--timezone", fields["timezone"], "--no-cache", "--timeout", "3", "--format", "json"]
                if fields.get("news_sources_path"):
                    command += ["--sources", fields["news_sources_path"]]
                commands["news:" + country] = command
        if "projects" in args.verify:
            registry = runtime / "projects.json"
            if registry.is_file():
                commands["projects"] = ["node", "scripts/projects.mjs", "status", "--all", "--registry", str(registry), "--timeout", "5"]
            else:
                checks["projects"] = {"status": "pending", "reason": "no_authorized_registry"}
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", SECRETARY_DIR=str(runtime),
                   CALENDAR_DB_PATH=str(runtime / "calendar.sqlite"), GM_CACHE_DIR=str(cache))
        checks.update(run_checks(commands, args.budget, env))
        result = {**local, "checks": checks, "budget_seconds": args.budget,
                  "verification_complete": bool(checks) and all(row["status"] == "verified" for row in checks.values())}
        print(json.dumps(result, separators=(",", ":")))
        return 0 if not missing and all(row["status"] == "verified" for row in checks.values()) else 1
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"profile_ready": False, "error": "invalid_or_unavailable_setup_data",
                          "next": "Inspect selected profile/configuration; do not overwrite existing records."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
