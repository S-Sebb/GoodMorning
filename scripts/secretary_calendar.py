#!/usr/bin/env python3
"""Secretary calendar commands: SQLite storage, conversational edits, reviewed imports.

Reads never fetch providers. --sync-betterbird and --import-json stage imports;
--pending / --show / --approve perform review. See docs/calendar-pipeline.md.
Config: CLI > environment > JSON config > defaults. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from calendar_store import CalendarStore, encode, endpoints, normalize
from calendar_recurrence import expand, occurrence_id, recurrence_zone


@dataclass
class Event:
    subject: str
    start: datetime
    end: datetime
    location: str = ""
    online: str = ""
    organizer: str = ""
    notes: str = ""
    source: str = ""
    prep: str = field(default="", compare=False)
    external_id: str = ""
    occurrence_id: str = ""
    status: str = "confirmed"
    all_day: bool = False
    event_id: str = ""
    pending_change: bool = False


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


def _tb_time(value, tz):
    """Thunderbird stores PRTime microseconds UTC; accept ms/s too."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"bad timestamp {value!r}")
    if v > 1e15:
        secs = v / 1e6
    elif v > 1e12:
        secs = v / 1e3
    else:
        secs = float(v)
    return datetime.fromtimestamp(secs, tz=timezone.utc).astimezone(tz)


def find_betterbird_db(path_arg: str | None, secretary_dir: str) -> str | None:
    """Accept a .sqlite file, a calendar-data dir, or a profile dir.
    Falls back to a secretary copy, then OS-default profile locations."""
    if path_arg and os.path.isfile(path_arg):
        return path_arg
    if path_arg and not os.path.isdir(path_arg):
        return None
    search_dirs = [path_arg] if path_arg else [secretary_dir]
    for d in search_dirs:
        for name in ("cache.sqlite", "local.sqlite"):
            direct = os.path.join(d, name)
            if os.path.isfile(direct):
                return direct
        cal_data = os.path.join(d, "calendar-data")
        if os.path.isdir(cal_data):
            for name in ("cache.sqlite", "local.sqlite"):
                p = os.path.join(cal_data, name)
                if os.path.isfile(p):
                    return p
    if not path_arg:
        auto = default_profile_dbs()
        if auto:
            return auto[0]
    return None


def default_profile_dbs() -> list[str]:
    """OS-default Thunderbird/Betterbird calendar caches. First hit wins;
    pass --betterbird-path to pick a specific profile."""
    home = os.path.expanduser("~")
    bases: list[str] = []
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            bases.append(os.path.join(appdata, "Thunderbird", "Profiles"))
    elif sys.platform == "darwin":
        bases.append(os.path.join(home, "Library", "Thunderbird", "Profiles"))
    else:
        bases += [os.path.join(home, ".thunderbird"),
                  os.path.join(home, ".betterbird"),
                  os.path.join(home, ".var", "app", "eu.betterbird.Betterbird",
                               ".thunderbird"),
                  os.path.join(home, ".var", "app", "org.mozilla.Thunderbird",
                               ".thunderbird")]
    found: list[str] = []
    for base in bases:
        if not os.path.isdir(base):
            continue
        try:
            entries = sorted(os.listdir(base))
        except OSError:
            continue
        for ent in entries:
            for name in ("cache.sqlite", "local.sqlite"):
                p = os.path.join(base, ent, "calendar-data", name)
                if os.path.isfile(p):
                    found.append(p)
    return found


def read_calendar_names(db_path: str) -> dict:
    """Map cal_id -> display name via prefs.js above the db (best effort)."""
    names: dict[str, str] = {}
    d = os.path.dirname(os.path.abspath(db_path))
    prefs = ""
    for _ in range(3):
        cand = os.path.join(d, "prefs.js")
        if os.path.isfile(cand):
            prefs = cand
            break
        d = os.path.dirname(d)
    if not prefs:
        return names
    try:
        with open(prefs, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return names
    for m in re.finditer(
            r'user_pref\("calendar\.registry\.([^\"]+)\.name",\s*"((?:[^"\\]|\\.)*)"\)',
            text):
        try:
            names[m.group(1)] = json.loads('"' + m.group(2) + '"')
        except ValueError:
            names[m.group(1)] = m.group(2)
    return names


def parse_betterbird(db_path: str, start: datetime, end: datetime, tz) -> list[Event]:
    """Read Betterbird/Thunderbird calendar cache (Owl Exchange included)
    with stdlib sqlite3. Times are PRTime microseconds UTC.

    Require a consistent SQLite backup; locked sources remain unresolved."""
    import shutil
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="bb-cal-")
    snapshot = os.path.join(tmpdir, "cache.sqlite")
    try:
        if _copy_live_db(db_path, snapshot):
            return _parse_betterbird_snapshot(snapshot, db_path, start, end, tz)
        raise ValueError("calendar_busy: close Betterbird and retry after confirmation; nothing imported")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _copy_live_db(db_path: str, dest: str) -> bool:
    """A verified file copy is not proof of a consistent live SQLite snapshot."""
    from contextlib import closing
    import sqlite3
    import time
    deadline = time.monotonic() + 2
    def check_deadline(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError("source snapshot timed out")
    try:
        with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True,
                                     timeout=1)) as src, closing(sqlite3.connect(dest)) as target:
            src.backup(target, pages=256, progress=check_deadline, sleep=0.05)
            if target.execute("PRAGMA integrity_check").fetchone()[0] == "ok":
                return True
    except (OSError, sqlite3.Error, TimeoutError):
        pass
    return False


def probe_betterbird(db_path):
    """Read compatibility metadata only, before opening secretary storage."""
    from contextlib import closing
    try:
        with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=0.1)) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "cal_events" not in tables:
                return {"status": "pending", "reason": "unsupported_cache_schema"}
            columns = {r[1] for r in con.execute("PRAGMA table_info(cal_events)")}
            if not {"id", "title", "event_start", "event_end"} <= columns:
                return {"status": "pending", "reason": "unsupported_cache_schema"}
            recurrence = bool("flags" in columns and con.execute("SELECT 1 FROM cal_events WHERE flags & 16 != 0 LIMIT 1").fetchone())
            if "cal_recurrence" in tables:
                recurrence = recurrence or bool(con.execute("SELECT 1 FROM cal_recurrence LIMIT 1").fetchone())
            ids = [r[0] for r in con.execute("SELECT DISTINCT cal_id FROM cal_events LIMIT 21")] if "cal_id" in columns else []
            supported = not recurrence or ("cal_recurrence" in tables and
                {"item_id", "icalString"} <= {r[1] for r in con.execute("PRAGMA table_info(cal_recurrence)")})
            return {"status": "verified" if supported else "pending", "has_recurrence": recurrence,
                     "calendar_ids": ids[:20], "truncated": len(ids) > 20,
                     **({"reason": "unsupported_recurrence_schema", "next": "Use a current cache or expanded export; do not fix code during setup."} if not supported else {})}
    except sqlite3.OperationalError:
        return {"status": "pending", "reason": "calendar_unavailable_or_busy",
                "next": "Check the selected cache; if locked, close Betterbird before an authorized retry."}


def _parse_betterbird_snapshot(db_path: str, orig_path: str,
                               start: datetime, end: datetime, tz) -> list[Event]:
    import sqlite3
    start_us = int(start.astimezone(timezone.utc).timestamp() * 1e6)
    end_us = int(end.astimezone(timezone.utc).timestamp() * 1e6)
    con = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "cal_events" not in tables:
            raise ValueError(f"{db_path} has no cal_events table; not a calendar cache")
        cols = {r[1] for r in con.execute("PRAGMA table_info(cal_events)")}
        rules = {}
        if "cal_recurrence" in tables:
            rcols = {r[1] for r in con.execute("PRAGMA table_info(cal_recurrence)")}
            if con.execute("SELECT 1 FROM cal_recurrence LIMIT 1").fetchone():
                if not {"item_id", "icalString"} <= rcols:
                    raise ValueError("unsupported Betterbird recurrence schema; nothing imported")
                calendar_col = "cal_id" if "cal_id" in rcols else "''"
                for item, calendar_id, rule in con.execute(f"SELECT item_id, {calendar_col}, icalString FROM cal_recurrence"):
                    rules.setdefault((item, calendar_id), []).append(rule)
        sel = ["id", "title", "event_start", "event_end"]
        if "cal_id" in cols:
            sel.append("cal_id")
        if "location" in cols:
            sel.append("location")
        if "ical_status" in cols:
            sel.append("ical_status")
        for name in ("recurrence_id", "flags", "event_start_tz"):
            if name in cols:
                sel.append(name)
        recurring = []
        if "flags" in cols:
            recurring.append("flags & 16 != 0")
        if "recurrence_id" in cols:
            recurring.append("recurrence_id IS NOT NULL AND recurrence_id != 0")
        if rules:
            # Masters can start years before the requested window.
            recurring.append("id IN (SELECT item_id FROM cal_recurrence)")
        extra = " OR " + " OR ".join(recurring) if recurring else ""
        rows = con.execute(
            f"SELECT {', '.join(sel)} FROM cal_events "
            "WHERE (event_start <= ? AND event_end >= ?) "
            "OR (event_start <= ? AND event_end >= ?) "
            "OR (event_start <= ? AND event_end >= ?)" + extra,
            # Floating date values are stored as UTC-like wall times. Widen
            # the fetch, then apply exact timezone-aware overlap below.
            (end_us + 86400000000, start_us - 86400000000,
             (end_us + 86400000000) // 1000, (start_us - 86400000000) // 1000,
             (end_us + 86400000000) // 1000000, (start_us - 86400000000) // 1000000)).fetchall()
        def item_key(values, columns):
            return (values[columns.index("item_id")],
                    values[columns.index("cal_id")] if "cal_id" in columns else "",
                    str(values[columns.index("recurrence_id")] or "") if "recurrence_id" in columns else "")

        props: dict[tuple, dict[str, str]] = {}
        if "cal_properties" in tables:
            pcols = {r[1] for r in con.execute("PRAGMA table_info(cal_properties)")}
            keycol = "key" if "key" in pcols else "name"
            idcol = "item_id" if "item_id" in pcols else "id"
            if idcol in pcols and keycol in pcols and "value" in pcols:
                psel = ["item_id", *[c for c in ("cal_id", "recurrence_id") if c in pcols]]
                sqlsel = [f"{idcol} AS item_id", *psel[1:], keycol, "value"]
                for row in con.execute(f"SELECT {', '.join(sqlsel)} FROM cal_properties "
                                       f"WHERE UPPER({keycol}) IN ('LOCATION','DESCRIPTION','STATUS')"):
                    props.setdefault(item_key(row, psel), {})[row[-2].upper()] = row[-1] or ""
        attendees: dict[tuple, list[str]] = {}
        if "cal_attendees" in tables:
            att_cols = {r[1] for r in con.execute("PRAGMA table_info(cal_attendees)")}
            who = ("attendee_email" if "attendee_email" in att_cols
                   else "email" if "email" in att_cols else None)
            idcol = ("item_id" if "item_id" in att_cols
                     else "event_id" if "event_id" in att_cols else None)
            if who and idcol:
                asel = ["item_id", *[c for c in ("cal_id", "recurrence_id") if c in att_cols]]
                sqlsel = [f"{idcol} AS item_id", *asel[1:], who]
                for row in con.execute(f"SELECT {', '.join(sqlsel)} FROM cal_attendees"):
                    if row[-1]:
                        attendees.setdefault(item_key(row, asel), []).append(row[-1])
    finally:
        con.close()
    events: list[Event] = []
    masters = {}
    exceptions = {}
    idx = {name: i for i, name in enumerate(sel)}
    for row in rows:
        eid = row[idx["id"]]
        status = row[idx["ical_status"]] if "ical_status" in idx else ""
        try:
            s = _tb_time(row[idx["event_start"]], tz)
            e = _tb_time(row[idx["event_end"]], tz)
            flags = int(row[idx["flags"]] or 0) if "flags" in idx else 0
            all_day = bool(flags & 8)
            floating = "event_start_tz" in idx and row[idx["event_start_tz"]] == "floating"
            if floating or all_day:
                s = _tb_time(row[idx["event_start"]], timezone.utc).replace(tzinfo=tz)
                e = _tb_time(row[idx["event_end"]], timezone.utc).replace(tzinfo=tz)
            elif flags & 16 or (eid, row[idx["cal_id"]] if "cal_id" in idx else "") in rules:
                zone = recurrence_zone(row[idx["event_start_tz"]] if "event_start_tz" in idx else "UTC", tz)
                s, e = s.astimezone(zone), e.astimezone(zone)
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError(f"bad Betterbird row {eid!r}: {exc}; nothing imported") from exc
        if e <= s:
            raise ValueError(f"nonpositive duration for Betterbird row {eid!r}; nothing imported")
        cal_id = row[idx["cal_id"]] if "cal_id" in idx else ""
        occurrence = str(row[idx["recurrence_id"]] or "") if "recurrence_id" in idx else ""
        def lookup(mapping):
            # Older schema versions may omit calendar/occurrence columns.
            return next((mapping[key] for key in ((eid, cal_id, occurrence), (eid, cal_id, ""),
                                                   (eid, "", occurrence), (eid, "", ""))
                         if key in mapping), {})
        prop = lookup(props)
        status = status or prop.get("STATUS", "")
        loc = (row[idx["location"]] if "location" in idx and row[idx["location"]]
               else prop.get("LOCATION", ""))
        people = lookup(attendees)
        notes = prop.get("DESCRIPTION", "")
        if people:
            notes = (notes + f" | attendees: {', '.join(people)}").strip(" |")
        ev = Event(
            subject=row[idx["title"]] or "(no title)", start=s, end=e,
            location=(loc or ""), organizer="",
            notes=notes, source="betterbird", external_id=f"{cal_id}:{eid}",
            occurrence_id=occurrence,
            status="cancelled" if (status or "").upper() == "CANCELLED" else "confirmed",
            all_day=all_day)
        key = (eid, cal_id)
        if occurrence:
            exceptions.setdefault(key, {})[occurrence] = ev
        elif flags & 16 or key in rules or (eid, "") in rules:
            masters[key] = (ev, floating or all_day)
        elif e > start and s < end:
            events.append(ev)
    for key, (master, floating) in masters.items():
        properties = rules.get(key, rules.get((key[0], ""), []))
        if not properties:
            raise ValueError("cache contains recurrence rules without stored definitions; nothing imported")
        duration = (master.end - master.start if master.all_day or floating else
                    master.end.astimezone(timezone.utc) - master.start.astimezone(timezone.utc))
        overrides = exceptions.pop(key, {})
        for stamp, excluded in expand(properties, master.start, end, master.all_day, floating):
            identity = occurrence_id(stamp, floating)
            finish = (stamp + duration if master.all_day or floating else
                      (stamp.astimezone(timezone.utc) + duration).astimezone(stamp.tzinfo))
            override = overrides.pop(identity, None)
            original_in_window = finish > start and stamp < end
            if override is not None:
                if original_in_window or (override.end > start and override.start < end):
                    events.append(replace(override, status="cancelled") if excluded else override)
            elif original_in_window:
                events.append(replace(master, start=stamp, end=finish, occurrence_id=identity,
                                      status="cancelled" if excluded else master.status))
        events.extend(ev for ev in overrides.values() if ev.end > start and ev.start < end)
    for overrides in exceptions.values():
        events.extend(ev for ev in overrides.values() if ev.end > start and ev.start < end)
    if len(events) > 10000:
        raise ValueError("Betterbird import exceeds occurrence limit; nothing imported")
    return sorted(events, key=lambda ev: (ev.start, ev.external_id, ev.occurrence_id))


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


def migrate_markdown(store: CalendarStore, path: str, tz, actor: str) -> dict:
    """All-or-nothing migration, with stable line identities and no source edits."""
    items = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip() or line.lstrip().startswith("#") or line.strip() == "```text" or line.strip() == "```":
                continue
            try:
                data = custom_event(line, tz)
            except ValueError as exc:
                raise ValueError(f"{path}:{lineno}: {exc}; nothing migrated") from exc
            # Content identity makes retries safe, even if the file is relocated.
            items.append((data, None))
    before = store.stats()["total"]
    ids = store.add_many(items, actor)
    return {"read": len(items), "added": store.stats()["total"] - before, "ids": ids}


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
            pending = "; source change awaiting review" if ev.pending_change else ""
            # Keep displayed fields on one line. Review treats source text as data.
            one_line = lambda value: " ".join(value.split())
            lines.append(f"  {span} {one_line(ev.subject)} @ {one_line(where)} "
                         f"[{one_line(ev.source)}; {ev.event_id}]{pending} — {one_line(ev.prep)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stored calendar and conversational import/review commands.")
    ap.add_argument("--days", type=int, default=3, help="days ahead (default 3)")
    ap.add_argument("--source", default="auto", help="stored source filter; auto means all sources")
    ap.add_argument("--timezone", default=None, help="IANA tz, else system local")
    ap.add_argument("--config", default=None, help="JSON config file path")
    ap.add_argument("--secretary-dir", default=None)
    ap.add_argument("--db", default=None, help="SQLite path; default secretary/calendar.sqlite")
    ap.add_argument("--betterbird-path", default=None,
                    help="cache.sqlite file, calendar-data dir, or profile dir")
    ap.add_argument("--no-custom", action="store_true")
    ap.add_argument("--json", action="store_true", help="compact JSON output")
    ap.add_argument("--details", action="store_true", help="include notes and organizer in schedule JSON")
    ap.add_argument("--limit", type=int, help="page size, 1..500 (schedule 100; pending/history 20)")
    ap.add_argument("--offset", type=int, default=0, help="page offset")
    ap.add_argument("--from", dest="from_date", help="window start date YYYY-MM-DD")
    ap.add_argument("--actor", default="secretary", help="session/user label recorded in history")
    ap.add_argument("--expect-revision", type=int, help="required for edits/reviews; get it with --show")
    ap.add_argument("--event-json", help="event object or patch, supplied by the secretary")
    actions = ap.add_mutually_exclusive_group()
    actions.add_argument("--probe-betterbird", action="store_true", help="Read authorized cache compatibility metadata only; no calendar storage or import")
    actions.add_argument("--init", action="store_true", help="create/validate empty calendar storage")
    actions.add_argument("--add", nargs="?", const="", metavar="EVENT",
                    help="add custom event using --event-json, or shorthand: "
                    "'YYYY-MM-DD HH:MM-HH:MM | Title | Place | Notes'")
    actions.add_argument("--update", metavar="ID", help="edit approved event using --event-json")
    actions.add_argument("--cancel", metavar="ID", help="cancel an event without deleting its history")
    actions.add_argument("--approve", metavar="ID", help="approve current import, optionally simplified")
    actions.add_argument("--reject", metavar="ID", help="reject current import revision")
    actions.add_argument("--show", metavar="ID", help="read original and approved event details")
    actions.add_argument("--history", metavar="ID", help="read event history")
    actions.add_argument("--pending", action="store_true", help="compact review queue")
    actions.add_argument("--stats", action="store_true", help="small calendar summary")
    actions.add_argument("--sync-betterbird", action="store_true", help="stage cache events in the date window")
    actions.add_argument("--import-json", metavar="PATH", help="secretary's normalized import batch; - for stdin")
    actions.add_argument("--migrate-md", metavar="PATH", help="explicit one-time Markdown migration, source untouched")
    args = ap.parse_args(argv)
    cfg = load_config_file(args.config)
    secretary_dir = resolve("secretary_dir", args.secretary_dir, cfg,
                            "SECRETARY_DIR", "secretary")
    bb_arg = (args.betterbird_path or os.environ.get("BETTERBIRD_PATH", "").strip()
              or str(cfg.get("betterbird_path", "")).strip() or None)
    db_path = resolve("calendar_db", args.db, cfg, "CALENDAR_DB_PATH",
                      os.path.join(secretary_dir, "calendar.sqlite"))
    tzname = args.timezone or os.environ.get("CALENDAR_TIMEZONE") or cfg.get("timezone")
    store = None
    try:
        if args.limit is None:
            args.limit = 20 if args.pending or args.history else 100
        if not 1 <= args.days <= 30 or not 1 <= args.limit <= 500 or args.offset < 0:
            raise ValueError("--days must be 1..30, --limit 1..500, --offset nonnegative")
        if not args.actor.strip():
            raise ValueError("--actor must not be empty")
        patch = json.loads(args.event_json) if args.event_json is not None else None
        if args.event_json is not None and not isinstance(patch, dict):
            raise ValueError("--event-json must contain an object")
        if patch is not None and not (args.add is not None or args.update or args.approve):
            raise ValueError("--event-json requires --add, --update, or --approve")
        tz = local_tz(tzname if isinstance(tzname, str) and tzname.strip() else None)
        now = datetime.now(tz)
        day_start = (datetime.fromisoformat(args.from_date).replace(tzinfo=tz)
                     if args.from_date else now.replace(hour=0, minute=0, second=0, microsecond=0))
        if args.from_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.from_date):
            raise ValueError("--from must be YYYY-MM-DD")
        window_end = day_start + timedelta(days=args.days)
        if args.probe_betterbird:
            selected = find_betterbird_db(bb_arg, secretary_dir)
            result = probe_betterbird(selected) if selected else {"status": "pending", "reason": "cache_not_found"}
            print(encode(result))
            return 0 if result["status"] == "verified" else 1
        store = CalendarStore(db_path)
        result = None
        if args.init:
            result = {"database": db_path, **store.stats()}
        elif args.add is not None:
            if args.add and patch is not None:
                raise ValueError("choose shorthand or --event-json, not both")
            data = patch if patch is not None else custom_event(args.add, tz)
            result = {"id": store.add(data, args.actor)}
        elif args.update or args.cancel or args.approve or args.reject:
            if args.expect_revision is None:
                raise ValueError("--expect-revision required; read --show ID first")
            if args.update and patch is None:
                raise ValueError("--update requires --event-json")
            action, event_id = next((a, getattr(args, a)) for a in ("update", "cancel", "approve", "reject")
                                    if getattr(args, a))
            changed = store.change(event_id, action, args.expect_revision, patch, args.actor)
            result = {k: changed[k] for k in ("id", "revision", "review")}
        elif args.show:
            result = store.get(args.show)
        elif args.history:
            result = store.history(args.history, args.limit, args.offset)
        elif args.pending:
            result = store.pending(args.limit, args.offset)
            if args.offset + len(result) < store.stats()["pending"]:
                eprint(f"note: more imports await review; continue with --offset {args.offset + len(result)}")
        elif args.stats:
            result = store.stats()
        elif args.migrate_md:
            result = migrate_markdown(store, args.migrate_md, tz, args.actor)
        elif args.import_json:
            text = sys.stdin.read() if args.import_json == "-" else Path(args.import_json).read_text(encoding="utf-8")
            batch = json.loads(text)
            if not isinstance(batch, dict) or set(batch) != {"source", "events"}:
                raise ValueError("import needs exactly source and events")
            result = store.stage(batch["source"], batch["events"], args.actor)
        elif args.sync_betterbird:
            db = find_betterbird_db(bb_arg, secretary_dir)
            if not db:
                raise ValueError("Betterbird cache not found; pass --betterbird-path")
            batch = []
            for ev in parse_betterbird(db, day_start, window_end, tz):
                data = {"external_id": ev.external_id, "occurrence_id": ev.occurrence_id,
                        "subject": ev.subject, "start": ev.start.isoformat(), "end": ev.end.isoformat(),
                        "location": ev.location, "organizer": ev.organizer, "notes": ev.notes,
                        "status": ev.status}
                if ev.all_day:
                    if not tzname:
                        raise ValueError("Betterbird all-day imports require --timezone with an IANA zone")
                    data.update(all_day=True, timezone=tzname,
                                start=ev.start.date().isoformat(), end=ev.end.date().isoformat())
                batch.append(data)
            result = store.stage("betterbird", batch, args.actor)
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
                       source=row["source"], all_day=row["all_day"], event_id=row["id"],
                       pending_change=row.get("pending_change", False))
            ev.prep = prep_warning(ev, now)
            row["prep"] = ev.prep
            events.append(ev)
        if args.json:
            print(encode(rows))
        else:
            print(format_text(events, args.days, tz))
        pending = store.stats()["pending"]
        if pending:
            eprint(f"note: {pending} import(s) await review; use --pending, --show ID, --approve ID")
        if len(rows) == args.limit:
            eprint(f"note: page limit reached; continue with --offset {args.offset + args.limit}")
        if os.path.isfile(os.path.join(secretary_dir, "custom_schedule.md")):
            eprint("note: legacy Markdown is not read; migrate once with --migrate-md PATH")
        return 0
    except (ValueError, KeyError, TypeError, OverflowError, OSError, sqlite3.Error) as exc:
        eprint(f"ERROR: {exc}")
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
