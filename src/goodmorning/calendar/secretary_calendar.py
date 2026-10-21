#!/usr/bin/env python3
"""Secretary calendar commands: SQLite storage, conversational edits, imports.

Reads never fetch providers. --sync-ics and --import-json apply imports to the schedule.
See docs/calendar-pipeline.md.
Config: CLI > environment > JSON config > defaults. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from .calendar_store import CalendarStore, encode, endpoints, normalize


@dataclass
class Event:
    subject: str
    start: datetime
    end: datetime
    location: str = ""
    online: str = ""
    source: str = ""
    prep: str = field(default="", compare=False)
    all_day: bool = False
    event_id: str = ""


def eprint(*a: object) -> None:
    print(*a, file=sys.stderr)


def load_config_file(path: str | None) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        eprint(f"WARN: ignoring bad config {path}: {exc}")
        return {}


def resolve(name: str, args_val: str | None, cfg: dict, env: str,
            default: str) -> str:
    if args_val:
        return args_val
    if env in os.environ and os.environ[env].strip():
        return os.environ[env].strip()
    if name in cfg and str(cfg[name]).strip():
        return str(cfg[name]).strip()
    return default


def local_tz(name: str | None):
    """Return ZoneInfo for name, else system local tz."""
    if not name:
        name = os.environ.get("TZ")
        system_path = str(Path("/etc/localtime").resolve())
        if not name and "/zoneinfo/" in system_path:
            name = system_path.split("/zoneinfo/", 1)[1]
    if name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"bad timezone {name!r}") from exc
    return datetime.now().astimezone().tzinfo


_CUSTOM_LINE = re.compile(
    r"^\s*[-*]\s*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})(?:\s*-\s*(\d{1,2}:\d{2}))?\s*\|\s*([^|]+)(?:\|\s*([^|]*))?(?:\|\s*(.*))?\s*$"
)

def custom_event(text: str, tz) -> dict:
    """Legacy shorthand is input only, never the storage format."""
    line = text.strip()
    if not line.startswith(("-", "*")):
        line = "- " + line
    m = _CUSTOM_LINE.match(line)
    if not m:
        raise ValueError("use YYYY-MM-DD HH:MM-HH:MM | Title | Place | Notes")
    d, s_t, e_t, title, place, notes = m.groups()
    day = datetime.strptime(d, "%Y-%m-%d").date()
    sh, sm = map(int, s_t.split(":"))
    s = datetime(day.year, day.month, day.day, sh, sm, tzinfo=tz)
    if e_t:
        eh, em = map(int, e_t.split(":"))
        e = datetime(day.year, day.month, day.day, eh, em, tzinfo=tz)
    else:
        e = s + timedelta(hours=1)
    # Reject nonexistent/ambiguous wall times rather than silently choosing a fold.
    for stamp in (s, e):
        back = stamp.astimezone(timezone.utc).astimezone(tz)
        if back.replace(tzinfo=None) != stamp.replace(tzinfo=None) or \
                stamp.replace(fold=0).utcoffset() != stamp.replace(fold=1).utcoffset():
            raise ValueError("ambiguous or nonexistent local time; use --event-json with explicit offsets")
    return normalize({"subject": title.strip(), "start": s.isoformat(), "end": e.isoformat(),
                      "location": (place or "").strip(), "notes": (notes or "").strip()})


def prep_warning(ev: Event, now: datetime) -> str:
    hints: list[str] = []
    subj = ev.subject.lower()
    loc = ev.location.strip()
    if ev.online:
        hints.append("join link ready, test mic/camera")
    if loc:
        hints.append(f"allow travel, confirm {loc}")
    if any(k in subj for k in ("slide", "present", "talk", "deadline", "due")):
        hints.append("materials due: send night before")
    if any(k in subj for k in ("ta ", "ta:", "teach", "tutorial", "lab", "rsm", "lecture")):
        hints.append("bring teaching materials")
    if "interview" in subj:
        hints.append("prep docs + questions")
    delta = ev.start - now
    if timedelta(0) <= delta <= timedelta(hours=24):
        hints.append("soon: pack tonight")
    elif delta < timedelta(0) and ev.end > now:
        hints.append("now: join if not there")
    if not hints:
        hints.append("no special prep")
    return "; ".join(hints)


def format_text(events: list[Event], days: int, tz) -> str:
    if not events:
        return "No events in the next %d day(s)." % days
    by_day: dict[str, list[Event]] = {}
    for ev in events:
        by_day.setdefault(ev.start.strftime("%a %Y-%m-%d"), []).append(ev)
    lines: list[str] = []
    for day in sorted(by_day, key=lambda d: d[4:]):  # sort by date, not weekday name
        day_evs = by_day[day]
        lines.append(f"{day} ({len(day_evs)} event(s))")
        for ev in day_evs:
            where = ev.location or (("online: " + ev.online[:60]) if ev.online else "no place listed")
            span = (("all day" if ev.end.date() - ev.start.date() == timedelta(days=1)
                     else f"all day through {(ev.end - timedelta(days=1)):%Y-%m-%d}") if ev.all_day else
                    f"{ev.start.strftime('%H:%M')}-{ev.end.strftime('%H:%M')}"
                    if ev.start.date() == ev.end.date() else
                    f"{ev.start:%m-%d %H:%M}–{ev.end:%m-%d %H:%M}")
            # Keep displayed fields on one line. Review treats source text as data.
            one_line = lambda value: " ".join(value.split())
            lines.append(f"  {span} {one_line(ev.subject)} @ {one_line(where)} "
                         f"[{one_line(ev.source)}; {ev.event_id}] — {one_line(ev.prep)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stored calendar, conversational edits and imports.")
    ap.add_argument("--days", type=int, default=3, help="days ahead (default 3)")
    ap.add_argument("--source", default="auto", help="stored source filter; auto means all sources")
    ap.add_argument("--timezone", default=None, help="IANA tz, else system local")
    ap.add_argument("--config", default=None, help="JSON config file path")
    ap.add_argument("--secretary-dir", default=None)
    ap.add_argument("--db", default=None, help="SQLite path; default secretary/calendar.sqlite")
    ap.add_argument("--no-custom", action="store_true")
    ap.add_argument("--json", action="store_true", help="compact JSON output")
    ap.add_argument("--details", action="store_true", help="include notes and organizer in schedule JSON")
    ap.add_argument("--limit", type=int, help="page size, 1..500 (schedule 100; history 20)")
    ap.add_argument("--offset", type=int, default=0, help="page offset")
    ap.add_argument("--from", dest="from_date", help="window start date YYYY-MM-DD")
    ap.add_argument("--actor", default="secretary", help="session/user label recorded in history")
    ap.add_argument("--expect-revision", type=int, help="required for edits; get it with --show")
    ap.add_argument("--event-json", help="event object or patch, supplied by the secretary")
    ap.add_argument("--ics-url", help="published calendar link for --sync-ics; saved after a successful sync")
    actions = ap.add_mutually_exclusive_group()
    actions.add_argument("--init", action="store_true", help="create/validate empty calendar storage")
    actions.add_argument("--add", nargs="?", const="", metavar="EVENT",
                    help="add custom event using --event-json, or shorthand: "
                    "'YYYY-MM-DD HH:MM-HH:MM | Title | Place | Notes'")
    actions.add_argument("--update", metavar="ID", help="edit approved event using --event-json")
    actions.add_argument("--cancel", metavar="ID", help="cancel an event without deleting its history")
    actions.add_argument("--show", metavar="ID", help="read original and approved event details")
    actions.add_argument("--history", metavar="ID", help="read event history")
    actions.add_argument("--stats", action="store_true", help="small calendar summary")
    actions.add_argument("--import-json", metavar="PATH", help="secretary's normalized import batch; - for stdin")
    actions.add_argument("--sync-ics", action="store_true", help="apply the saved (or --ics-url) published calendar feed")
    args = ap.parse_args(argv)
    cfg = load_config_file(args.config)
    from goodmorning.runtime_files import secretary_path, profile_fields, calendar_config, calendar_path
    secretary_dir = str(secretary_path(resolve("secretary_dir", args.secretary_dir, cfg,
                                              "SECRETARY_DIR", str(secretary_path()))))
    store = None
    try:
        if not args.config:
            cfg = calendar_config(secretary_dir)
        db_path = str(calendar_path(secretary_dir, args.db, cfg))
        tzname = args.timezone or os.environ.get("CALENDAR_TIMEZONE") or cfg.get("timezone") or profile_fields(secretary_dir).get("timezone")
        if args.limit is None:
            args.limit = 20 if args.history else 100
        if not 1 <= args.days <= 30 or not 1 <= args.limit <= 500 or args.offset < 0:
            raise ValueError("--days must be 1..30, --limit 1..500, --offset nonnegative")
        if not args.actor.strip():
            raise ValueError("--actor must not be empty")
        patch = json.loads(args.event_json) if args.event_json is not None else None
        if args.event_json is not None and not isinstance(patch, dict):
            raise ValueError("--event-json must contain an object")
        if patch is not None and not (args.add is not None or args.update):
            raise ValueError("--event-json requires --add or --update")
        if args.ics_url and not args.sync_ics:
            raise ValueError("--ics-url requires --sync-ics")
        tz = local_tz(tzname if isinstance(tzname, str) and tzname.strip() else None)
        now = datetime.now(tz)
        day_start = (datetime.fromisoformat(args.from_date).replace(tzinfo=tz)
                     if args.from_date else now.replace(hour=0, minute=0, second=0, microsecond=0))
        if args.from_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.from_date):
            raise ValueError("--from must be YYYY-MM-DD")
        window_end = day_start + timedelta(days=args.days)
        writes = args.init or args.add is not None or any((args.update, args.cancel, args.import_json, args.sync_ics))
        store = CalendarStore(db_path, readonly=not writes)
        result = None
        if args.init:
            result = {"database": db_path, **store.stats()}
        elif args.add is not None:
            if args.add and patch is not None:
                raise ValueError("choose shorthand or --event-json, not both")
            data = patch if patch is not None else custom_event(args.add, tz)
            result = {"id": store.add(data, args.actor)}
        elif args.update or args.cancel:
            if args.expect_revision is None:
                raise ValueError("--expect-revision required; read --show ID first")
            if args.update and patch is None:
                raise ValueError("--update requires --event-json")
            action, event_id = ("update", args.update) if args.update else ("cancel", args.cancel)
            changed = store.change(event_id, action, args.expect_revision, patch, args.actor)
            result = {k: changed[k] for k in ("id", "revision")}
        elif args.show:
            result = store.get(args.show)
        elif args.history:
            result = store.history(args.history, args.limit, args.offset)
        elif args.stats:
            result = store.stats()
        elif args.import_json:
            text = sys.stdin.read() if args.import_json == "-" else Path(args.import_json).read_text(encoding="utf-8")
            batch = json.loads(text)
            if not isinstance(batch, dict) or set(batch) != {"source", "events"}:
                raise ValueError("import needs exactly source and events")
            result = store.import_events(batch["source"], batch["events"], args.actor)
        elif args.sync_ics:
            from .calendar_ics import FEED_DAYS, fetch, sync
            url = args.ics_url or cfg.get("ics_url")
            if not url:
                raise ValueError("no saved calendar feed; pass --ics-url with the published calendar link")
            source = args.source if args.source != "auto" else cfg.get("ics_source") or "ics"
            result = sync(store, source, fetch(url), day_start, day_start + timedelta(days=FEED_DAYS), tz, tzname, args.actor)
            if args.ics_url and (args.ics_url, source) != (cfg.get("ics_url"), cfg.get("ics_source")):
                from goodmorning.runtime_files import atomic_text
                atomic_text(Path(secretary_dir) / "calendar.config.json",
                            json.dumps({**calendar_config(secretary_dir), "ics_url": args.ics_url, "ics_source": source}, indent=2) + "\n")
        if result is not None:
            print(encode(result))
            return 0
        rows = store.query(day_start, window_end, args.source, args.no_custom,
                           args.limit, args.offset, args.details)
        events = []
        for row in rows:
            s, e = endpoints(row)
            ev = Event(subject=row["subject"], start=s if row["all_day"] else s.astimezone(tz),
                       end=e if row["all_day"] else e.astimezone(tz),
                       location=row.get("location", ""), online=row.get("online", ""),
                       source=row["source"], all_day=row["all_day"], event_id=row["id"])
            ev.prep = prep_warning(ev, now)
            row["prep"] = ev.prep
            events.append(ev)
        if args.json:
            print(encode(rows))
        else:
            print(format_text(events, args.days, tz))
        if len(rows) == args.limit:
            eprint(f"note: page limit reached; continue with --offset {args.offset + args.limit}")
        return 0
    except (ValueError, KeyError, TypeError, OverflowError, OSError, sqlite3.Error) as exc:
        eprint(f"ERROR: {exc}")
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
