"""Custom schedules for ambiguous rhythms that fixed repeats cannot express.

Storage lives in the selected runtime as custom.sqlite, separate from
inbox.sqlite so no task migration is needed. Writes need the actual session
and a stable request key, revision checks, and bounded JSON. Completions are
user-confirmed dates only; silence never counts.
"""

import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

from goodmorning.runtime_files import runtime_lock

NAME = "custom.sqlite"

SCHEMA = """
CREATE TABLE custom_rules (
    id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE custom_completions (
    id TEXT PRIMARY KEY, rule_id TEXT NOT NULL REFERENCES custom_rules(id),
    date TEXT NOT NULL, revision INTEGER NOT NULL, status TEXT NOT NULL,
    detail TEXT NOT NULL, UNIQUE(rule_id,date));
CREATE TABLE custom_events (
    seq INTEGER PRIMARY KEY, item_id TEXT NOT NULL, action TEXT NOT NULL,
    at TEXT NOT NULL, session TEXT NOT NULL, snapshot TEXT NOT NULL,
    request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, receipt TEXT NOT NULL);
"""


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _checked_text(value, maximum, field, empty=True):
    from .inbox_store import check_text
    return check_text(value, maximum, field, empty)


def _date(value):
    if not isinstance(value, str) or dt.date.fromisoformat(value).isoformat() != value:
        raise ValueError("invalid_date: use YYYY-MM-DD")
    return value


def validate_policy(policy):
    if not isinstance(policy, dict):
        raise ValueError("invalid_input: custom policy must be an object")
    allowed = {"base", "interval_days", "weekdays", "start", "anchor",
               "miss_policy", "weekly_cap", "nightly"}
    if set(policy) - allowed:
        raise ValueError("invalid_input: unsupported custom policy fields")
    base = policy.get("base")
    if base not in ("interval_days", "weekdays"):
        raise ValueError("invalid_input: custom base needs interval_days or weekdays; ask which rhythm was meant")
    if base == "interval_days":
        interval = policy.get("interval_days")
        if type(interval) is not int or not 1 <= interval <= 366:
            raise ValueError("invalid_input: interval_days must be 1..366; ask for the exact gap")
        if "weekdays" in policy:
            raise ValueError("invalid_input: use interval_days or weekdays, not both")
    else:
        weekdays = policy.get("weekdays")
        if (not isinstance(weekdays, list) or not 1 <= len(weekdays) <= 7
                or any(type(d) is not int or not 0 <= d <= 6 for d in weekdays)
                or len(set(weekdays)) != len(weekdays)):
            raise ValueError("invalid_input: weekdays are distinct 0=Monday..6=Sunday; ask which days were meant")
        if "interval_days" in policy:
            raise ValueError("invalid_input: use interval_days or weekdays, not both")
    _date(policy.get("start", ""))
    if policy.get("start", "") == "":
        raise ValueError("invalid_input: custom start date is required; ask when the rhythm starts")
    if policy.get("anchor") not in ("fixed", "last_completion"):
        raise ValueError("invalid_input: anchor must be fixed or last_completion; ask whether a finish restarts the gap")
    if policy.get("miss_policy") not in ("chase", "fixed"):
        raise ValueError("invalid_input: miss_policy must be chase or fixed; ask whether a miss shifts the next reminder")
    cap = policy.get("weekly_cap", None)
    if cap is not None and (type(cap) is not int or not 1 <= cap <= 7):
        raise ValueError("invalid_input: weekly_cap must be 1..7 or null; ask how many per Mon-Sun week stops reminders")
    if policy.get("nightly", "due_only") not in ("due_only", "always"):
        raise ValueError("invalid_input: nightly must be due_only or always; ask whether off-days still need an evening check")
    return {
        "base": base,
        "start": policy["start"],
        "anchor": policy["anchor"],
        "miss_policy": policy["miss_policy"],
        "weekly_cap": cap,
        "nightly": policy.get("nightly", "due_only"),
        **({"interval_days": policy["interval_days"]} if base == "interval_days" else {"weekdays": sorted(policy["weekdays"])}),
    }


def validate_rule(data):
    if not isinstance(data, dict) or set(data) - {"title", "detail", "timezone", "status", "policy"}:
        raise ValueError("invalid_input: custom rule needs title, detail, timezone, status and policy")
    _checked_text(data.get("title", ""), 600, "title", False)
    _checked_text(data.get("detail", ""), 5000, "detail", True)
    timezone = data.get("timezone", "")
    _checked_text(timezone, 160, "timezone", False)
    ZoneInfo(timezone)
    if data.get("status", "open") not in ("open", "done", "cancelled"):
        raise ValueError("invalid_input: custom status must be open, done or cancelled")
    return {
        "title": data["title"],
        "detail": data.get("detail", ""),
        "timezone": timezone,
        "status": data.get("status", "open"),
        "policy": validate_policy(data.get("policy", {})),
    }


def _week_bounds(day, timezone):
    # Week is Mon-Sun in the rule timezone. Dates are stored as rule-local days.
    target = dt.date.fromisoformat(day)
    try:
        # Keep wall dates stable; timezone only defines week membership for edge cases.
        ZoneInfo(timezone)
    except Exception:
        pass
    monday = target - dt.timedelta(days=target.weekday())
    return monday.isoformat(), (monday + dt.timedelta(days=6)).isoformat()


def _fixed_due_dates(policy, day):
    start = dt.date.fromisoformat(policy["start"])
    target = dt.date.fromisoformat(day)
    if target < start:
        return []
    if policy["base"] == "interval_days":
        step = policy["interval_days"]
        dates = []
        cursor = start
        while cursor <= target:
            dates.append(cursor.isoformat())
            cursor += dt.timedelta(days=step)
        return dates
    return [d.isoformat() for d in
            (start + dt.timedelta(days=n) for n in range((target - start).days + 1))
            if d.weekday() in policy["weekdays"]]


def _next_after_last(policy, last_done):
    base = dt.date.fromisoformat(last_done)
    if policy["base"] == "interval_days":
        return (base + dt.timedelta(days=policy["interval_days"])).isoformat()
    cursor = base + dt.timedelta(days=1)
    for _ in range(8):
        if cursor.weekday() in policy["weekdays"]:
            return cursor.isoformat()
        cursor += dt.timedelta(days=1)
    return cursor.isoformat()


class CustomStore:
    def __init__(self, directory, write=False):
        self.directory = Path(directory)
        path = self.directory / NAME
        if path.is_symlink():
            raise ValueError("unsafe_path: custom store must belong to this runtime")
        if not path.exists():
            if not write:
                raise ValueError("setup_required: no custom schedules saved yet")
            with runtime_lock(self.directory, ".custom.lock"):
                if not path.exists():
                    db = sqlite3.connect(path)
                    try:
                        db.executescript(SCHEMA)
                        db.commit()
                    finally:
                        db.close()
            try:
                path.chmod(0o600)
            except OSError:
                pass
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row

    def close(self):
        self.db.close()

    def show(self, rule_id):
        row = self.db.execute("SELECT * FROM custom_rules WHERE id=?", (rule_id,)).fetchone()
        if row is None:
            raise ValueError("not_found: custom rule does not exist")
        item = dict(row)
        item.update(json.loads(item.pop("data")))
        completions = [dict(r) for r in self.db.execute(
            "SELECT * FROM custom_completions WHERE rule_id=? ORDER BY date", (rule_id,))]
        item["completions"] = completions
        return item

    def all(self):
        for row in self.db.execute("SELECT * FROM custom_rules ORDER BY rowid"):
            item = dict(row)
            item.update(json.loads(item.pop("data")))
            yield item

    def _history(self, rule_id):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM custom_completions WHERE rule_id=? AND status='done' ORDER BY date",
            (rule_id,))]

    def due(self, rule, day):
        """Code-owned decision for one rule on one day. Secretary words it, never recomputes it."""
        _date(day)
        if rule["status"] in ("done", "cancelled"):
            return {"due": False, "reason": "closed", "weekly_count": 0, "last_done": None, "next_due": ""}
        policy = rule["policy"]
        if day < policy["start"]:
            return {"due": False, "reason": "before_start", "weekly_count": 0, "last_done": None, "next_due": policy["start"]}
        week_start, week_end = _week_bounds(day, rule["timezone"])
        done_rows = [r for r in self._history(rule["id"]) if week_start <= r["date"] <= week_end]
        weekly_count = len(done_rows)
        last_done = self.db.execute(
            "SELECT MAX(date) FROM custom_completions WHERE rule_id=? AND status='done'",
            (rule["id"],)).fetchone()[0]
        cap = policy.get("weekly_cap")
        if cap is not None and weekly_count >= cap:
            return {"due": False, "reason": "weekly_cap_reached", "weekly_count": weekly_count,
                    "last_done": last_done, "next_due": ""}
        if policy["anchor"] == "last_completion" and last_done:
            nxt = _next_after_last(policy, last_done)
            if day < nxt:
                return {"due": False, "reason": "waiting_gap", "weekly_count": weekly_count,
                        "last_done": last_done, "next_due": nxt}
            if day == nxt:
                return {"due": True, "reason": "due", "weekly_count": weekly_count,
                        "last_done": last_done, "next_due": nxt}
            # day > nxt: chase or fixed
            if policy["miss_policy"] == "chase":
                return {"due": True, "reason": "chasing_missed", "weekly_count": weekly_count,
                        "last_done": last_done, "next_due": nxt}
            # fixed miss: only due on fixed cadence dates
            fixed = _fixed_due_dates(policy, day)
            if day in fixed and day not in {r["date"] for r in self._history(rule["id"])}:
                return {"due": True, "reason": "due", "weekly_count": weekly_count,
                        "last_done": last_done, "next_due": day}
            return {"due": False, "reason": "off_cadence", "weekly_count": weekly_count,
                    "last_done": last_done, "next_due": fixed[-1] if fixed else nxt}
        # fixed anchor
        fixed = _fixed_due_dates(policy, day)
        if day in fixed:
            if day in {r["date"] for r in self._history(rule["id"])}:
                return {"due": False, "reason": "already_done", "weekly_count": weekly_count,
                        "last_done": last_done, "next_due": day}
            return {"due": True, "reason": "due", "weekly_count": weekly_count,
                    "last_done": last_done, "next_due": day}
        if policy["miss_policy"] == "chase" and fixed:
            latest = fixed[-1]
            done_dates = {r["date"] for r in self._history(rule["id"])}
            if latest not in done_dates:
                return {"due": True, "reason": "chasing_missed", "weekly_count": weekly_count,
                        "last_done": last_done, "next_due": latest}
        return {"due": False, "reason": "off_cadence", "weekly_count": weekly_count,
                "last_done": last_done, "next_due": fixed[-1] if fixed else policy["start"]}

    def briefing(self, day, kind="gm"):
        """Code-owned rows for briefings. Secretary copies wording, never invents dates."""
        _date(day)
        rows = []
        for rule in self.all():
            if rule["status"] in ("done", "cancelled"):
                continue
            decision = self.due(rule, day)
            nightly = rule["policy"].get("nightly", "due_only")
            include = decision["due"] or (kind == "gn" and nightly == "always")
            if not include:
                continue
            rows.append({
                "id": rule["id"], "revision": rule["revision"],
                "occurrence_id": f"cuoc_{rule['id'][3:]}_" + day.replace("-", ""),
                "date": day if decision["due"] else "",
                "due": decision["due"], "reason": decision["reason"],
                "weekly_count": decision["weekly_count"], "last_done": decision["last_done"],
                "next_due": decision["next_due"],
                "title": rule["title"], "detail": rule["detail"],
                "timezone": rule["timezone"], "policy": rule["policy"],
            })
        rows.sort(key=lambda r: (not r["due"], r["next_due"] or "9999", r["title"], r["id"]))
        return rows

    def add(self, payload, session, key, now):
        from .inbox_store import check_text
        check_text(session, 200, "session", False)
        check_text(key, 240, "request key", False)
        if not isinstance(payload, dict) or set(payload) - {"title", "detail", "timezone", "policy"}:
            raise ValueError("invalid_input: custom add needs title, timezone and policy; ask until unambiguous")
        data = validate_rule({"status": "open", **payload})
        digest = hashlib.sha256(encode(["add", payload, session]).encode()).hexdigest()
        with runtime_lock(self.directory, ".custom.lock"):
            previous = self.db.execute(
                "SELECT fingerprint,receipt FROM custom_events WHERE request_key=?", (key,)).fetchone()
            if previous:
                if previous["fingerprint"] != digest:
                    raise ValueError("request_conflict: key belongs to different input")
                return {**json.loads(previous["receipt"]), "replayed": True}
            rule_id = "cu_" + uuid.uuid4().hex[:16]
            self.db.execute("INSERT INTO custom_rules VALUES (?,?,?,?,?)",
                            (rule_id, 1, now, now, encode(data)))
            result = {"saved": True, "id": rule_id, "revision": 1}
            self.db.execute("INSERT INTO custom_events VALUES (NULL,?,?,?,?,?,?,?,?)",
                            (rule_id, "add", now, session, encode(payload), key, digest, encode(result)))
            self.db.commit()
            return result

    def update(self, rule_id, expected, payload, session, key, now):
        from .inbox_store import check_text
        check_text(session, 200, "session", False)
        check_text(key, 240, "request key", False)
        if not isinstance(payload, dict) or not payload or set(payload) - {"title", "detail", "timezone", "policy", "status"}:
            raise ValueError("invalid_input: custom update needs nonempty title/detail/timezone/policy/status changes")
        digest = hashlib.sha256(encode([rule_id, expected, payload, session]).encode()).hexdigest()
        with runtime_lock(self.directory, ".custom.lock"):
            previous = self.db.execute(
                "SELECT fingerprint,receipt FROM custom_events WHERE request_key=?", (key,)).fetchone()
            if previous:
                if previous["fingerprint"] != digest:
                    raise ValueError("request_conflict: key belongs to different input")
                return {**json.loads(previous["receipt"]), "replayed": True}
            current = self.show(rule_id)
            if expected != current["revision"]:
                raise ValueError("write_conflict: custom rule changed; reread and reconcile")
            merged = {k: current[k] for k in ("title", "detail", "timezone", "status", "policy")}
            merged.update(payload)
            merged = validate_rule(merged)
            self.db.execute("UPDATE custom_rules SET revision=revision+1,updated_at=?,data=? WHERE id=?",
                            (now, encode(merged), rule_id))
            result = {"saved": True, "id": rule_id, "revision": expected + 1}
            self.db.execute("INSERT INTO custom_events VALUES (NULL,?,?,?,?,?,?,?,?)",
                            (rule_id, "update", now, session, encode(payload), key, digest, encode(result)))
            self.db.commit()
            return result

    def report(self, rule_id, expected, payload, session, key, now, day):
        """User-confirmed completion on its actual date. Future dates are refused."""
        from .inbox_store import check_text
        check_text(session, 200, "session", False)
        check_text(key, 240, "request key", False)
        _date(day)
        if not isinstance(payload, dict) or payload.get("status") != "done" or payload.get("confirmed_completion") is not True:
            raise ValueError("confirmation_required: custom completion needs status done plus confirmed_completion true")
        detail = payload.get("detail", "")
        _checked_text(detail, 5000, "detail", True)
        reported = dt.datetime.fromisoformat(now)
        current = self.show(rule_id)
        if current.get("timezone"):
            reported = reported.astimezone(ZoneInfo(current["timezone"]))
        if day > reported.date().isoformat():
            raise ValueError("invalid_date: future work cannot already be completed")
        digest = hashlib.sha256(encode([rule_id, expected, payload, session, day, True]).encode()).hexdigest()
        with runtime_lock(self.directory, ".custom.lock"):
            previous = self.db.execute(
                "SELECT fingerprint,receipt FROM custom_events WHERE request_key=?", (key,)).fetchone()
            if previous:
                if previous["fingerprint"] != digest:
                    raise ValueError("request_conflict: key belongs to different input")
                return {**json.loads(previous["receipt"]), "replayed": True}
            current = self.show(rule_id)
            if expected != current["revision"]:
                raise ValueError("write_conflict: custom rule changed; reread and reconcile")
            if current["status"] in ("done", "cancelled"):
                raise ValueError("write_conflict: closed custom rule cannot gain completions")
            occurrence_id = f"cuoc_{rule_id[3:]}_" + day.replace("-", "")
            self.db.execute("INSERT INTO custom_completions VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                            "revision=excluded.revision,status=excluded.status,detail=excluded.detail",
                            (occurrence_id, rule_id, day, 1, "done", detail))
            self.db.execute("UPDATE custom_rules SET revision=revision+1,updated_at=? WHERE id=?", (now, rule_id))
            result = {"saved": True, "id": rule_id, "revision": expected + 1, "occurrence_id": occurrence_id}
            self.db.execute("INSERT INTO custom_events VALUES (NULL,?,?,?,?,?,?,?,?)",
                            (rule_id, "report", now, session, encode({"day": day, "input": payload}), key, digest, encode(result)))
            self.db.commit()
            return result
