#!/usr/bin/env python3
"""Run-state index for GoodMorning (/gm, /gn, /eureka, /secretary).

What it records:
  - Whether gm/gn ran each day, with session names for jump links.
  - The full verbatim gm/gn agent answers as snapshot files
    (secretary/daily/YYYY-MM-DD.gm.md / .gn.md), plus their size and
    estimated token cost, so later agents can decide BEFORE reading.
  - Per-day pipeline coverage derived from the daily file: did the day get
    a weather / news / schedule / tasks / feedback section?
  - Inbox pressure (pending eureka ideas, oldest date) so /gm and /gn know
    what to remind without reading the whole inbox.
   - Project last-update dates and stored calendar counts, so stale
    projects and calendar drift are visible in one cheap read.

Design rule (token discipline): daily files and the calendar database are sources of truth; state.json
is a derived index. Skills read --check + today's daily file by
default and open .gm.md/.gn.md snapshots ONLY on explicit
need (user asks "what did you say...", audit, dispute). Never bulk-read
snapshots. See docs/state-pipeline.md for usage.

Usage:
  python scripts/state.py --check [--json]
  python scripts/state.py --mark-gm --session NAME [--answer-file P | --answer-stdin] [--force]
  python scripts/state.py --mark-gn --session NAME [--answer-file P | --answer-stdin] [--force]
  python scripts/state.py --rebuild [--json]
  python scripts/state.py --tokens PATH

Config: CLI flags > env (SECRETARY_DIR) > defaults. Stdlib only.
Dates: --today YYYY-MM-DD overrides "today" (tests, backfill).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from calendar_store import read_stats
from runtime_files import atomic_text, profile_fields, runtime_lock
from reply_policy import boilerplate_categories

VERSION = 1
STATE_NAME = "state.json"
# state.json is the cheap always-read (~1-2k tokens). Per-day entries grow
# ~400B/day, so only the newest KEEP_DAYS persist; older history stays in
# secretary/daily/ (source of truth) and is rescanned live by --check /
# --rebuild whenever needed. Never bulk-read snapshots (see answer_cost).
KEEP_DAYS = 14
MAX_ANSWER_CHARS = 1024 * 1024

# Headings recognised (case-insensitive) when deriving per-day coverage
# from secretary/daily/YYYY-MM-DD.md. Keep in sync with
# templates/daily.template.md.
SECTION_KEYS = ("weather", "news", "schedule", "tasks", "feedback")


def eprint(*a: object) -> None:
    print(*a, file=sys.stderr)


def find_secretary_dir(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("SECRETARY_DIR"):
        return os.environ["SECRETARY_DIR"]
    if os.path.isdir(os.path.join(os.getcwd(), "secretary")):
        return os.path.join(os.getcwd(), "secretary")
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "secretary")


def today_str(override: str | None, timezone: str = "") -> str:
    if override:
        try:
            parsed = dt.date.fromisoformat(override)
            if parsed.isoformat() != override:
                raise ValueError
            return override
        except ValueError:
            sys.exit(f"error: --today must be YYYY-MM-DD, got '{override}'")
    return dt.datetime.now(ZoneInfo(timezone) if timezone else None).date().isoformat()


def read_profile_timezone(secretary_dir: str) -> str:
    return profile_fields(secretary_dir).get("timezone", "")


def estimate_tokens(chars: int) -> int:
    """Heuristic token estimate for English prose (~4 chars/token).

    Documented approximation, not a tokenizer: good enough to decide
    whether opening a snapshot is worth it. CJK-heavy text costs more;
    treat the number as a lower bound then.
    """
    return (chars + 3) // 4


def stat_answer(path: str) -> dict | None:
    try:
        chars = size = lines = 0
        digest = hashlib.sha1()
        last = ""
        with open(path, encoding="utf-8", newline="") as f:
            while True:
                text = f.read(65536)
                if not text:
                    break
                chars += len(text)
                data = text.encode("utf-8")
                size += len(data)
                lines += text.count("\n")
                digest.update(data)
                last = text[-1]
    except FileNotFoundError:
        return None
    return {
        "chars": chars, "bytes": size,
        "lines": lines + (1 if last and last != "\n" else 0),
        "tokens_est": estimate_tokens(chars),
        "sha1": digest.hexdigest()[:12],
    }


def blank_run() -> dict:
    return {"ran": False, "session": None, "answer_file": None,
            "chars": 0, "tokens_est": 0, "sha1": None}


def blank_state() -> dict:
    return {"version": VERSION, "updated_at": None, "timezone": "",
            "last_gm_date": None, "last_gn_date": None, "days": {},
            "history_before": None,
            "inbox": {"pending": 0, "oldest_pending_date": None, "total": 0},
            "projects": {}, "custom_schedule": {"events": 0},
            "calendar": {"total": 0, "custom": 0, "imported": 0, "pending": 0}}


def load_state(secretary_dir: str) -> dict:
    path = os.path.join(secretary_dir, STATE_NAME)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("version") == VERSION:
            if not isinstance(data.get("days"), dict) or not all(
                isinstance(day, dict) and all(isinstance(day.get(k), dict) for k in ("gm", "gn"))
                for day in data["days"].values()
            ) or not isinstance(data.get("snapshot_cache", {}), dict):
                eprint("WARN: invalid state index structure; rebuilding from source records.")
                return blank_state()
            return data
        raise ValueError("unsupported state schema; preserve it and check the version")
    except FileNotFoundError:
        return blank_state()
    except (json.JSONDecodeError, UnicodeError):
        eprint("WARN: invalid state index; rebuilding from source records.")
    return blank_state()


def save_state(secretary_dir: str, state: dict) -> None:
    state["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    # Do not truncate the in-memory history before computing checks or costs.
    state = dict(state)
    names = sorted(state.get("days", {}))
    if len(names) > KEEP_DAYS:
        state["history_before"] = names[-KEEP_DAYS]
        # Keep only metadata for the additional days in the 30-day cost window.
        # Agents use --check, never read this implementation cache directly.
        state["snapshot_cache"] = {
            d: {k: {field: run[field] for field in ("chars", "tokens_est", "sha1", "fingerprint")}
                for k, run in state["days"][d].items() if k in ("gm", "gn") and "fingerprint" in run}
            for d in names[:-KEEP_DAYS]
            if any("fingerprint" in state["days"][d][k] for k in ("gm", "gn"))
        }
        state["days"] = {d: state["days"][d] for d in names[-KEEP_DAYS:]}
    else:
        state["history_before"] = None
        state.pop("snapshot_cache", None)
    os.makedirs(secretary_dir, exist_ok=True)
    atomic_text(os.path.join(secretary_dir, STATE_NAME),
                json.dumps(state, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")


# ---- file parsers (source of truth) ----

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
RUN_LINE = re.compile(r"^\s*[-*]\s*(gm|gn)\s*:\s*(yes|no|y|n|true|false|done|ran)?\b(.*)$", re.I)
SESSION_RE = re.compile(r"session\s+([A-Za-z0-9_.:/-]+)", re.I)
ANSWER_RE = re.compile(r"answer\s*:\s*([^\s|)]+)", re.I)
HEADING_RE = re.compile(r"^#{1,4}\s*(.+?)\s*$")


def parse_daily(path: str) -> dict:
    """Extract gm/gn run lines + section coverage from a daily file."""
    day = {"gm": blank_run(), "gn": blank_run(), "has_daily": False,
           "sections": {k: False for k in SECTION_KEYS}}
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return day
    day["has_daily"] = True
    seen = set()
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = RUN_LINE.match(line)
        if m:
            kind = m.group(1).lower()
            if kind in seen:
                raise ValueError("duplicate daily run lines; resolve them before marking")
            seen.add(kind)
            flag = (m.group(2) or "").lower()
            rest = m.group(3) or ""
            ran = flag in ("yes", "y", "true", "done", "ran")
            sm = SESSION_RE.search(rest)
            am = ANSWER_RE.search(rest)
            day[kind]["ran"] = ran
            day[kind]["session"] = sm.group(1) if sm else day[kind]["session"]
            if am:
                day[kind]["answer_file"] = am.group(1).strip()
            continue
        m = HEADING_RE.match(line)
        if m:
            h = m.group(1).lower()
            if "weather" in h:
                day["sections"]["weather"] = True
            elif "news" in h:
                day["sections"]["news"] = True
            elif "schedul" in h or "calendar" in h:
                day["sections"]["schedule"] = True
            elif "must" in h or "todo" in h or "to-do" in h or "task" in h or "nice-to" in h:
                day["sections"]["tasks"] = True
            elif "feedback" in h or "progress" in h:
                day["sections"]["feedback"] = True
    return day


def scan_inbox(secretary_dir: str) -> dict:
    """Tolerant parse of secretary/inbox.md.

    Expected line shape (templates/inbox not yet fixed, so be lenient):
      - YYYY-MM-DD | raw idea | pending | project
    Any line mentioning 'pending' counts as pending; first date-like
    token is its date. Lines mentioning confirmed/done are done.
    """
    out = {"pending": 0, "oldest_pending_date": None, "total": 0}
    try:
        with open(os.path.join(secretary_dir, "inbox.md"), encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return out
    oldest = None
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = [part.strip() for part in s.split("|")]
        if len(parts) < 3 or not s.startswith(("- ", "* ")):
            continue
        status = parts[-2].lower() if len(parts) >= 4 else parts[2].lower()
        if status == "pending":
            out["pending"] += 1
            out["total"] += 1
            m = DATE_RE.search(parts[0])
            if m:
                try:
                    dt.date.fromisoformat(m.group(1))
                except ValueError:
                    continue
                if oldest is None or m.group(1) < oldest:
                    oldest = m.group(1)
        elif status in ("confirmed", "done"):
            out["total"] += 1
    out["oldest_pending_date"] = oldest
    return out


def scan_projects(secretary_dir: str) -> dict:
    """name -> last-update date (explicit line wins, else file mtime)."""
    out: dict[str, dict] = {}
    pdir = os.path.join(secretary_dir, "projects")
    try:
        names = sorted(os.listdir(pdir))
    except FileNotFoundError:
        return out
    for name in names:
        if not name.endswith(".md"):
            continue
        key = name[:-3]
        path = os.path.join(pdir, name)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            mtime = dt.date.fromtimestamp(os.path.getmtime(path)).isoformat()
        except FileNotFoundError:
            continue
        m = re.search(r"(?:last.?update|updated)\s*:\s*(\d{4}-\d{2}-\d{2})",
                      text, re.I)
        out[key] = {"last_update": m.group(1) if m else mtime}
    return out


def count_custom_events(secretary_dir: str) -> dict:
    return {"events": calendar_stats(secretary_dir)["custom"]}


def calendar_stats(secretary_dir: str) -> dict:
    path = os.environ.get("CALENDAR_DB_PATH") or os.path.join(secretary_dir, "calendar.sqlite")
    return {**read_stats(path),
            "legacy_markdown": os.path.isfile(os.path.join(secretary_dir, "custom_schedule.md"))}


def daily_path(secretary_dir: str, day: str, suffix: str = ".md") -> str:
    return os.path.join(secretary_dir, "daily", day + suffix)


def rebuild_index(secretary_dir: str, state: dict, today: str | None = None) -> dict:
    """Rescan files into state['days'] + summaries. Files win on conflict."""
    ddir = os.path.join(secretary_dir, "daily")
    if Path(ddir).is_symlink():
        raise ValueError("daily directory must not be a symlink")
    try:
        files = sorted(os.listdir(ddir))
    except FileNotFoundError:
        files = []
    day_names = sorted({f[:-3] for f in files
                        if f.endswith(".md") and DATE_RE.fullmatch(f[:-3])})
    previous = {**state.get("snapshot_cache", {}), **state.get("days", {})}
    days: dict[str, dict] = {}
    warnings = []
    if any(re.fullmatch(r"\d{4}-\d{2}-\d{2}\.(gm|gn)\.md", name)
           and name[:10] not in day_names for name in files):
        warnings.append("orphan_snapshot")
    today = today or today_str(None, read_profile_timezone(secretary_dir))
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=29)).isoformat()
    for day in day_names:
        try:
            dt.date.fromisoformat(day)
        except ValueError:
            warnings.append("invalid_daily_date")
            continue
        if Path(daily_path(secretary_dir, day)).is_symlink():
            raise ValueError("daily records must not be symlinks")
        parsed = parse_daily(daily_path(secretary_dir, day))
        for kind, suffix in (("gm", ".gm.md"), ("gn", ".gn.md")):
            ptr = parsed[kind]["answer_file"]
            if ptr:
                apath = ptr if os.path.isabs(ptr) else os.path.join(secretary_dir, ptr)
            else:
                apath = daily_path(secretary_dir, day, suffix)
                if os.path.isfile(apath):
                    parsed[kind]["answer_file"] = os.path.relpath(apath, secretary_dir)
                else:
                    apath = None
            if apath:
                expected = Path(secretary_dir).resolve() / "daily" / (day + suffix)
                if Path(apath).resolve() != expected or Path(apath).is_symlink():
                    warnings.append("unsafe_answer_pointer")
                    parsed[kind]["answer_file"] = None
                    continue
            if apath and os.path.isfile(apath) and cutoff <= day <= today:
                metadata = os.stat(apath)
                fingerprint = [metadata.st_dev, metadata.st_ino, metadata.st_size,
                               metadata.st_mtime_ns, metadata.st_ctime_ns]
                cached_day = previous.get(day, {})
                cached = cached_day.get(kind, {}) if isinstance(cached_day, dict) else {}
                if not isinstance(cached, dict):
                    cached = {}
                if cached.get("fingerprint") == fingerprint and all(
                    isinstance(cached.get(k), int) and cached[k] >= 0 for k in ("chars", "tokens_est")
                ) and isinstance(cached.get("sha1"), str):
                    st = cached
                else:
                    st = stat_answer(apath)
                if st is None:
                    warnings.append("answer_disappeared")
                    continue
                parsed[kind].update({k: st[k] for k in ("chars", "tokens_est", "sha1")})
                parsed[kind]["fingerprint"] = fingerprint
                if parsed[kind]["answer_file"] is None:
                    parsed[kind]["answer_file"] = os.path.relpath(apath, secretary_dir)
            elif ptr and not os.path.isfile(apath):
                warnings.append("missing_answer")
        days[day] = parsed
    state["days"] = days
    gm_days = sorted(d for d, v in days.items() if v["gm"]["ran"])
    gn_days = sorted(d for d, v in days.items() if v["gn"]["ran"])
    state["last_gm_date"] = gm_days[-1] if gm_days else None
    state["last_gn_date"] = gn_days[-1] if gn_days else None
    state["inbox"] = scan_inbox(secretary_dir)
    state["projects"] = scan_projects(secretary_dir)
    state["calendar"] = calendar_stats(secretary_dir)
    state["custom_schedule"] = {"events": state["calendar"]["custom"]}
    tz = read_profile_timezone(secretary_dir)
    state["timezone"] = tz
    state["warnings"] = sorted(set(warnings))
    return state


def missed_days(state: dict, today: str) -> list[dict]:
    """Days in [first record, today) missing gm or gn, oldest first."""
    return missed_page(state, today, sys.maxsize, 0)["rows"]


def missed_page(state: dict, today: str, limit: int, offset: int) -> dict:
    """Count long gaps arithmetically; materialize only the requested page."""
    recorded = sorted(d for d in state.get("days", {}) if d < today)
    rows, total, skip = [], 0, offset

    def segment(start, length, missing, value=None):
        nonlocal total, skip
        if not missing:
            return
        total += length
        ignored = min(skip, length)
        skip -= ignored
        for i in range(ignored, min(length, ignored + limit - len(rows))):
            rows.append({"date": (start + dt.timedelta(days=i)).isoformat(), "missing": missing,
                         "gm_session": value["gm"]["session"] if value else None,
                         "gn_session": value["gn"]["session"] if value else None})

    if recorded:
        cursor = dt.date.fromisoformat(recorded[0])
        for name in recorded:
            day = dt.date.fromisoformat(name)
            segment(cursor, (day - cursor).days, ["gm", "gn"])
            value = state["days"][name]
            segment(day, 1, [k for k in ("gm", "gn") if not value[k]["ran"]], value)
            cursor = day + dt.timedelta(days=1)
        segment(cursor, (dt.date.fromisoformat(today) - cursor).days, ["gm", "gn"])
    return {"rows": rows, "total": total,
            "next_offset": offset + len(rows) if offset + len(rows) < total else None}


def answer_cost(state: dict, today: str, window: int) -> dict:
    """Total snapshot size/tokens over the last `window` days incl. today."""
    start = (dt.date.fromisoformat(today) - dt.timedelta(days=window - 1)).isoformat()
    chars = toks = files = 0
    for d in sorted(state.get("days", {})):
        if d < start or d > today:
            continue
        for kind in ("gm", "gn"):
            r = state["days"][d][kind]
            if r["ran"] and r["chars"]:
                chars += r["chars"]
                toks += r["tokens_est"]
                files += 1
    return {"window_days": window, "snapshots": files,
            "chars": chars, "tokens_est": toks}


# ---- commands ----

def cmd_check(secretary_dir: str, today: str, as_json: bool, limit: int = 7, offset: int = 0,
              timezone: str | None = None) -> int:
    if not os.path.isdir(secretary_dir):
        eprint(f"error: no {secretary_dir}/ yet. Run /secretary init first "
               "(it creates profile, daily/, inbox, calendar.sqlite).")
        return 1
    state = rebuild_index(secretary_dir, load_state(secretary_dir), today)
    if timezone is not None:
        state["timezone"] = timezone
    save_state(secretary_dir, state)
    day = state["days"].get(today, {"gm": blank_run(), "gn": blank_run()})
    page = missed_page(state, today, limit, offset)
    missed = page["rows"]
    c7 = answer_cost(state, today, 7)
    c30 = answer_cost(state, today, 30)
    if as_json:
        print(json.dumps({
            "today": today, "timezone": state.get("timezone", ""),
            "gm_today": {k: day["gm"][k] for k in blank_run()},
            "gn_today": {k: day["gn"][k] for k in blank_run()},
            "missed": missed, "missed_total": page["total"],
            "next_offset": page["next_offset"],
            "sections_today": day.get("sections", {k: False for k in SECTION_KEYS}),
            "inbox": state["inbox"],
            "projects_total": len(state["projects"]),
            "projects": dict(sorted(state["projects"].items())[offset:offset + limit]),
            "projects_next_offset": offset + limit if offset + limit < len(state["projects"]) else None,
            "calendar": state["calendar"],
            "answer_cost_7d": c7, "answer_cost_30d": c30,
            "warnings": state["warnings"],
            "news": news_overview(secretary_dir, today),
        }, separators=(",", ":"), ensure_ascii=False))
        return 0
    print(f"today: {today}")
    for kind in ("gm", "gn"):
        r = day[kind]
        if r["ran"]:
            extra = ""
            if r["answer_file"]:
                extra = (f" | answer: {r['answer_file']} "
                         f"({r['chars']} chars ~{r['tokens_est']} tok)")
            print(f"{kind} today: ALREADY RAN (session {r['session'] or '?'})"
                  f" — see that session before continuing.{extra}")
        else:
            print(f"{kind} today: not run yet.")
    if missed:
        print("missed days (finish oldest first):")
        for m in missed:
            print(f"  {m['date']}: missing {','.join(m['missing'])}")
        if page["total"] > len(missed):
            print(f"missed total: {page['total']}; use --offset/--limit for more.")
    elif not page["total"]:
        print("missed days: none.")
    else:
        print(f"missed total: {page['total']}; this page is empty.")
    ib = state["inbox"]
    if ib["pending"]:
        print(f"inbox: {ib['pending']} pending (oldest {ib['oldest_pending_date']}) "
              "— remind at /gn, else next /gm.")
    else:
        print("inbox: nothing pending.")
    if state["projects"]:
        stale = sorted(n for n, v in state["projects"].items()
                       if v["last_update"] < today)
        print(f"projects: {len(state['projects'])} tracked"
              + (f" | stale (not updated today): {', '.join(stale[:limit])}" if stale else ""))
    else:
        print("projects: none registered yet.")
    cal = state["calendar"]
    print(f"calendar: {cal['custom']} custom, {cal['imported']} approved imports, "
          f"{cal['pending']} awaiting review.")
    if cal["legacy_markdown"]:
        print("calendar: legacy Markdown exists; migrate explicitly with secretary_calendar.py --migrate-md PATH.")
    print(f"answer re-read cost: last 7d ~{c7['tokens_est']} tok "
          f"({c7['snapshots']} snapshots), last 30d ~{c30['tokens_est']} tok. "
           "Open snapshots only on demand, never in bulk.")
    if state["warnings"]:
        print("warnings: " + ", ".join(state["warnings"]))
    print("news: " + json.dumps(news_overview(secretary_dir, today), separators=(",", ":")))
    return 0


def ensure_daily_line(secretary_dir: str, day: str, kind: str,
                      session: str, answer_rel: str | None) -> None:
    """Create or update the `- gm: ...` / `- gn: ...` line in the daily file."""
    path = daily_path(secretary_dir, day)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if answer_rel:
        want = f"- {kind}: yes (session {session}) | answer: {answer_rel}"
    else:
        want = f"- {kind}: yes (session {session})"
    if not os.path.isfile(path):
        atomic_text(path, f"# {day}\n\n{want}\n")
        return
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    pat = re.compile(rf"^\s*[-*]\s*{kind}\s*:", re.I)
    hit = False
    for i, ln in enumerate(lines):
        if pat.match(ln):
            lines[i] = want
            hit = True
            break
    if not hit:
        insert_at = 1 if lines and lines[0].startswith("#") else 0
        lines.insert(insert_at, want)
    atomic_text(path, "\n".join(lines) + "\n")


def cmd_mark(secretary_dir: str, day: str, kind: str, session: str,
             answer_file: str | None, answer_stdin: bool, force: bool, as_json: bool = False) -> int:
    suffix = ".gm.md" if kind == "gm" else ".gn.md"
    if not re.fullmatch(r"[A-Za-z0-9_.:/-]+", session):
        return command_error("session_invalid", "--session must be a nonempty session identifier", 2, as_json)
    state = rebuild_index(secretary_dir, load_state(secretary_dir), day)
    cur = state["days"].get(day, {"gm": blank_run(), "gn": blank_run()})[kind]
    if cur["ran"] and not force:
        return command_error("already_ran", f"{kind} already ran on {day} "
                             f"(session {cur['session'] or '?'}); use the saved record", 2, as_json)
    answer_rel: str | None = None
    if answer_file or answer_stdin:
        if answer_stdin:
            text = sys.stdin.read(MAX_ANSWER_CHARS + 1)
        else:
            assert answer_file is not None
            try:
                with open(answer_file, encoding="utf-8") as f:
                    text = f.read(MAX_ANSWER_CHARS + 1)
            except (OSError, UnicodeError):
                return command_error("answer_unreadable", "cannot read answer file", 2, as_json)
        if len(text) > MAX_ANSWER_CHARS:
            return command_error("answer_too_large", "answer exceeds 1,048,576 characters", 2, as_json)
        if not text.strip():
            return command_error("answer_empty", "answer text is empty, not saving", 2, as_json)
        if boilerplate_categories(text):
            return command_error("answer_noncritical_boilerplate", "rewrite the reply without routine disclaimers; retain material warnings in concise form", 2, as_json)
        dest = daily_path(secretary_dir, day, suffix)
        if os.path.isfile(dest) and not force:
            return command_error("snapshot_exists", "snapshot exists; inspect it before an authorized replacement", 2, as_json)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        atomic_text(dest, text if text.endswith("\n") else text + "\n")
        answer_rel = os.path.relpath(dest, secretary_dir)
        st = stat_answer(dest)
        assert st is not None
        if not as_json:
            print(f"saved {kind} answer: {answer_rel} "
                  f"({st['chars']} chars ~{st['tokens_est']} tok). "
                  "Future reads: open only on demand.")
    else:
        eprint(f"note: no answer saved (pass --answer-file/--answer-stdin to "
               f"record the verbatim {kind} reply for later reference).")
    ensure_daily_line(secretary_dir, day, kind, session, answer_rel)
    state = rebuild_index(secretary_dir, state, day)
    save_state(secretary_dir, state)
    if as_json:
        run = state["days"][day][kind]
        print(json.dumps({"date": day, "kind": kind, **{k: run[k] for k in blank_run()}},
                         separators=(",", ":")))
    else:
        print(f"marked {kind} on {day} (session {session}).")
    return 0


def command_error(code: str, message: str, exit_code: int, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"error": code, "next": message}, separators=(",", ":")))
    else:
        eprint(f"error: {message}")
    return exit_code


def cmd_tokens(path: str, as_json: bool = False) -> int:
    st = stat_answer(path)
    if st is None:
        return command_error("answer_unreadable", "cannot read answer file", 1, as_json)
    if as_json:
        print(json.dumps(st, separators=(",", ":")))
        return 0
    print(f"{path}: {st['chars']} chars, {st['bytes']} bytes, "
          f"{st['lines']} lines, ~{st['tokens_est']} tokens (chars/4 heuristic), "
          f"sha {st['sha1']}")
    print("policy: --check + daily file are the cheap default read; "
          "open this snapshot only on explicit need, never bulk-read.")
    return 0


def news_overview(secretary_dir: str, today: str) -> dict:
    """Counts only; news.py is the authoritative backlog/read/delivery interface."""
    from news_reports import ReportStore, context_key, recent_days
    from news import load_sources, SOURCES_FILE

    fields = profile_fields(secretary_dir)
    if not fields.get("timezone") or not fields.get("news_country"):
        return {"status": "not_configured"}
    if not (Path(secretary_dir) / "news_reports.sqlite").exists():
        return {"missing": 7, "next": "news.py --backfill"}
    store = None
    try:
        country = fields["news_country"].upper()
        cfg = load_sources(fields.get("news_sources_path") or SOURCES_FILE)
        context = context_key(fields["timezone"], country, cfg)
        store = ReportStore(secretary_dir)
        plan = store.plan(context, recent_days(dt.date.fromisoformat(today)))
        return {**{s: sum(e["status"] == s for e in plan)
                   for s in ("missing", "partial", "collected", "delivered")},
                "next": "news.py --status"}
    except (OSError, ValueError, sqlite3.Error):
        return {"status": "unavailable", "next": "inspect news.py --status"}
    finally:
        if store:
            store.close()


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except (OSError, UnicodeError, ValueError, sqlite3.Error, ZoneInfoNotFoundError, OverflowError) as error:
        as_json = "--json" in (argv if argv is not None else sys.argv[1:])
        if as_json:
            busy = str(error).startswith("runtime_busy:")
            return command_error("runtime_busy" if busy else "state_unavailable",
                                 "retry later" if busy else "preserve files and check state sources/schema", 1, True)
        if isinstance(error, ValueError) and not isinstance(error, UnicodeError):
            eprint(f"error: {error}")
        else:
            eprint("error: state source/index is unreadable; preserve files and check access/encoding")
        return 1


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GoodMorning run-state index.")
    ap.add_argument("--secretary-dir", default=None)
    ap.add_argument("--today", default=None, help="override today YYYY-MM-DD")
    ap.add_argument("--timezone", help="IANA timezone; default profile, then system local")
    ap.add_argument("--limit", type=int, default=7, help="max missed-day/project rows (1..30)")
    ap.add_argument("--offset", type=int, default=0, help="missed-day/project page offset")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--mark-gm", action="store_true")
    g.add_argument("--mark-gn", action="store_true")
    g.add_argument("--rebuild", action="store_true")
    g.add_argument("--tokens", default=None, metavar="PATH")
    ap.add_argument("--session", default="", help="session name for --mark-*")
    answers = ap.add_mutually_exclusive_group()
    answers.add_argument("--answer-file", default=None)
    answers.add_argument("--answer-stdin", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    if args.tokens is not None:
        return cmd_tokens(args.tokens, args.json)

    secretary_dir = find_secretary_dir(args.secretary_dir)
    if not 1 <= args.limit <= 30 or args.offset < 0:
        ap.error("--limit must be 1..30 and --offset nonnegative")
    timezone = args.timezone or read_profile_timezone(secretary_dir)
    try:
        if timezone:
            ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        ap.error("timezone must be a valid IANA timezone")
    today = today_str(args.today, timezone)
    if not os.path.isdir(secretary_dir):
        return command_error("setup_required", "no secretary directory; confirm setup first", 1, args.json)
    with runtime_lock(secretary_dir, ".state.lock"):
        return execute_action(args, secretary_dir, today)


def execute_action(args, secretary_dir, today):

    if args.check:
        return cmd_check(secretary_dir, today, args.json, args.limit, args.offset, args.timezone)
    if args.rebuild:
        load_state(secretary_dir)  # Refuse a newer schema before writing anything.
        state = rebuild_index(secretary_dir, blank_state(), today)
        save_state(secretary_dir, state)
        if args.json:
            print(json.dumps({"rebuilt": True, "days_total": len(state["days"]),
                              "last_gm_date": state["last_gm_date"], "last_gn_date": state["last_gn_date"],
                              "warnings": state["warnings"]}, separators=(",", ":")))
        else:
            print(f"rebuilt {os.path.join(secretary_dir, STATE_NAME)}: "
                  f"{len(state['days'])} day(s), "
                  f"last gm {state['last_gm_date']}, last gn {state['last_gn_date']}, "
                  f"inbox pending {state['inbox']['pending']}.")
        return 0
    kind = "gm" if args.mark_gm else "gn"
    return cmd_mark(secretary_dir, today, kind, args.session,
                    args.answer_file, args.answer_stdin, args.force, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
