#!/usr/bin/env python3
"""Local workflow preparation and save-first capture; no providers, jobs or hidden setup."""

import argparse
import datetime as dt
import json
from pathlib import Path
import sqlite3
import sys

from .daily import show as daily_show
from .inbox_store import InboxStore, encode, stamp
from goodmorning.runtime_files import secretary_path, cache_path, profile_fields, calendar_path
from goodmorning.setup_check import profile_status
from .state import load_state, rebuild_index, parse_daily, missed_page, today_str
from goodmorning.briefings.briefing_document import source_path

KINDS = ("gm", "gn", "eureka", "todo", "secretary")
PERSONAL = ("secretary_name", "secretary_language", "secretary_tone", "special_needs", "occupations", "expertise_fields",
            "work_days", "work_hours", "sleep_time", "industry", "knowledge_area", "project_scope")


def prepare(directory, kind, today=None, cache=None, *, task_limit=7, website_language=None, replacement=False):
    fields = profile_fields(directory)
    ready = profile_status(directory, fields, website_language)
    if website_language is not None:fields={**fields,'secretary_language':ready['secretary_language']}
    if not ready["profile_ready"]:
        return {"workflow": kind, **ready, "next": "resume secretary setup; do not initialize or fetch automatically"}
    date = today_str(today, fields["timezone"])
    day = dt.date.fromisoformat(date)
    result = {"workflow": kind, "ready": True, "date": date, "timezone": fields["timezone"],
              "profile": {key: fields[key] for key in PERSONAL if fields.get(key)}}
    english = fields["secretary_language"].strip().casefold() == "english"
    if kind in ("gm", "gn"):
        result["title"] = {"gm": "GoodMorning", "gn": "GoodNight"}[kind] + " " + date if english else None
    elif kind == "secretary":
        result["title"] = None
    if kind in ("todo", "eureka"):
        result["capture_date"] = dt.datetime.fromisoformat(stamp(directory)).date().isoformat()
        result["profile"] = {key: fields[key] for key in ("secretary_name", "secretary_language", "secretary_tone") if fields.get(key)}
        return result
    result.update(yesterday=(day - dt.timedelta(days=1)).isoformat(), tomorrow=(day + dt.timedelta(days=1)).isoformat())
    if kind in ("gm", "gn"):
        # Stop on today's source before scanning history or unrelated stores.
        daily_path = Path(directory) / "daily" / (date + ".md")
        if daily_path.parent.is_symlink() or daily_path.is_symlink():
            raise ValueError("unsafe_path: daily records must not be symlinks")
        run = parse_daily(str(daily_path))[kind]
        if run["ran"] and not replacement:
            canonical = source_path(Path(directory), date, kind)
            pointer = run["answer_file"]
            valid = canonical.is_file() and not canonical.is_symlink() and (not pointer or
                (Path(directory) / pointer).resolve() == canonical.resolve())
            return {"workflow": kind, "ready": True, "date": date, "duplicate": True,
                    "original_session": run["session"], "answer_file": "daily/" + canonical.name if valid else None,
                    "next": "stop; no fetch or rename"}
        # Missed-run history needs flags, not snapshot bodies or project/calendar scans.
        state = rebuild_index(str(directory), load_state(str(directory)), date,
                              snapshot_stats=False, scan_context=False)
        missed = missed_page(state, date, 1, 0)
        result.update(missed=missed["rows"], missed_total=missed["total"], warnings=state["warnings"])
        result["daily"] = daily_show(directory, date, limit=task_limit, full_titles=task_limit > 7)
    if Path(directory, "inbox.sqlite").exists():
        store = InboxStore(directory)
        try:
            result["inbox"] = store.list()
            result['document_version'] = store.version
        finally:
            store.close()
    cache = cache_path(cache)
    try:
        calendar = str(calendar_path(directory))
    except (ValueError, OSError, TypeError):
        calendar = None
        result["calendar_configuration"] = {"error": "invalid_or_unavailable", "next": "inspect calendar configuration; profile setup is still saved"}
    result["paths"] = {"runtime": str(directory), "profile": str(Path(directory) / "profile.md"),
                       "cache": str(cache), "calendar_db": calendar,
                       "projects_registry": str(Path(directory) / "projects.json")}
    if kind == "gm":
        result["news"] = {"countries": ready["countries"], "sources": fields.get("news_sources_path") or None,
                          "latest_enabled": fields.get("news_latest", "false").casefold() == "true"}
        result["city"] = fields["city"]
    if kind == "gn":
        result["calendar_source"] = fields.get("calendar_source", "")
    if kind in ('gm', 'gn'):
        from .routing import prepare as item_prepare
        from goodmorning.web import language as ui
        token = ui.CURRENT.set(website_language) if website_language else None
        try:
            result['items'] = item_prepare(directory, date, 'gm' if kind == 'secretary' else kind)
        except (ValueError, OSError, sqlite3.Error) as error:
            result['items'] = {'error': 'items_unavailable', 'next': str(error)}
        finally:
            if token is not None:
                ui.CURRENT.reset(token)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secretary-dir")
    parser.add_argument("--cache-dir")
    parser.add_argument("--website-language",choices=('en','zh-CN'),help='Explicit browser request language; does not rewrite local preferences')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", choices=KINDS)
    action.add_argument("--capture", choices=("eureka", "todo"))
    parser.add_argument("--today")
    parser.add_argument("--session")
    parser.add_argument("--request-key")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--input-file")
    inputs.add_argument("--input-stdin", action="store_true")
    args = parser.parse_args(argv)
    try:
        directory = secretary_path(args.secretary_dir)
        kind = args.prepare or args.capture
        if args.capture and args.today:
            raise ValueError("invalid_input: capture uses the actual local timestamp, not historical dates")
        result = prepare(directory, kind, args.today, args.cache_dir, website_language=args.website_language)
        if args.capture and result.get("ready"):
            if not args.session or not args.request_key or not (args.input_file or args.input_stdin):
                raise ValueError("input_required: capture needs session, stable request key and JSON input")
            if args.input_file:
                with open(args.input_file, encoding="utf-8") as stream:
                    text = stream.read(100001)
            else:
                text = sys.stdin.read(100001)
            if len(text) > 100000:
                raise ValueError("invalid_input: input exceeds 100000 characters")
            payload = json.loads(text)
            if not isinstance(payload, dict) or "kind" in payload:
                raise ValueError("invalid_input: supply raw and optional context/project/summary/questions; kind comes from the workflow")
            payload["kind"] = "todo" if kind == "todo" else "idea"
            store = InboxStore(directory, write=True)
            try:
                receipt = store.mutate("add", payload, args.session, args.request_key, stamp(directory))
            finally:
                store.close()
            summary = " ".join(payload["raw"].split()[:6])[:100]
            fields = result["profile"]
            english = not fields.get("secretary_language") or fields["secretary_language"].casefold() == "english"
            result = {**receipt, "profile": fields, "title": ("Todo " if kind == "todo" else "Eureka ") + summary if english else None,
                      "title_summary": summary}
        print(encode(result))
        return 0 if result.get("ready") or result.get("saved") else 1
    except (ValueError, KeyError, OSError, sqlite3.Error) as error:
        message = str(error) if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError) else "workflow_unavailable: preserve runtime and inspect profile/input/storage"
        print(encode({"error": message.split(":", 1)[0], "next": message}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
