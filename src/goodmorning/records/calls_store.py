"""Secretary calls: manual, review-approved clarifications for stored records.

Calls never watch, scan, or write on their own. A manual `calls --scan`
produces a read-only candidate report. Only explicitly approved candidates
become open calls via `calls --add`. Each open call links to one stored
target (task, entry, draft, or calendar event) plus a prefilled secretary
prompt. The user answers in secretary chat through the existing native
question flow; the call itself is resolved or dismissed explicitly with
revision checks. Storage lives in the selected runtime as calls.sqlite,
separate from inbox.sqlite so no task migration is needed.
"""

import datetime as dt
import hashlib
import json
import re
import sqlite3
import uuid
from pathlib import Path

from goodmorning.runtime_files import runtime_lock

NAME = "calls.sqlite"

SCHEMA = """
CREATE TABLE calls (
    id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE call_events (
    seq INTEGER PRIMARY KEY, item_id TEXT NOT NULL, action TEXT NOT NULL,
    at TEXT NOT NULL, session TEXT NOT NULL, snapshot TEXT NOT NULL,
    request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, receipt TEXT NOT NULL);
"""

KINDS = ("task_wording", "ambiguous_schedule", "tbc_time", "calendar_review")
TARGETS = ("task", "entry", "draft", "event")
STATUSES = ("open", "resolved", "dismissed")


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _checked_text(value, maximum, field, empty=True):
    from .inbox_store import check_text
    return check_text(value, maximum, field, empty)


def _date(value):
    if not isinstance(value, str) or dt.date.fromisoformat(value).isoformat() != value:
        raise ValueError("invalid_date: use YYYY-MM-DD")
    return value


def validate_call(data):
    if not isinstance(data, dict) or set(data) - {"title", "reason", "question", "kind",
                                                  "target_type", "target_id", "target_revision",
                                                  "chat_id", "status"}:
        raise ValueError("invalid_input: call needs title, reason, question, kind, target and status")
    _checked_text(data.get("title", ""), 140, "title", False)
    _checked_text(data.get("reason", ""), 2000, "reason", False)
    _checked_text(data.get("question", ""), 2000, "question", False)
    if data.get("kind") not in KINDS:
        raise ValueError("invalid_input: unknown call kind")
    if data.get("target_type") not in TARGETS:
        raise ValueError("invalid_input: unknown call target")
    _checked_text(data.get("target_id", ""), 200, "target id", False)
    if type(data.get("target_revision")) is not int or data["target_revision"] < 1:
        raise ValueError("invalid_input: call needs its target revision")
    if data.get("chat_id", ""):
        _checked_text(data["chat_id"], 200, "chat id", False)
    if data.get("status", "open") not in STATUSES:
        raise ValueError("invalid_input: call status must be open, resolved or dismissed")
    return {"title": data["title"], "reason": data["reason"], "question": data["question"],
            "kind": data["kind"], "target_type": data["target_type"],
            "target_id": data["target_id"], "target_revision": data["target_revision"],
            "chat_id": data.get("chat_id", ""), "status": data.get("status", "open")}


_FILLER = re.compile(r"^(currently|there is|there are|please)\b", re.IGNORECASE)
_TIMING_WORD = re.compile("每天|每周|every day|every week|every saturday|every friday", re.IGNORECASE)
_MONTH_WORD = re.compile(r"\d{1,2}月|early|mid-|^\d{4}-\d{2}-\d{2}|10\.26|11月初", re.IGNORECASE)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _task_text_issues(title, detail, project):
    """Material vagueness only: project prefix, filler opener, etc. fog.

    Trailing periods, capitalization, length, and honest empty details are
    not material and never produce candidates on their own.
    """
    issues = []
    if project and title.startswith(project + " "):
        issues.append("project prefix repeats the structured project field")
    if _FILLER.match(title):
        issues.append("filler opener before the imperative verb")
    if "etc." in title or "etc." in detail:
        issues.append("etc. fog hides the specific object")
    return issues


def scan(runtime):
    """Read-only candidate report. Never writes, never dispatches work."""
    directory = Path(runtime)
    if directory.is_symlink():
        raise ValueError("unsafe_path: calls scan must belong to this runtime")
    candidates = []
    inbox_path = directory / "inbox.sqlite"
    if inbox_path.is_symlink():
        raise ValueError("unsafe_path: inbox store must belong to this runtime")
    if inbox_path.exists():
        db = sqlite3.connect(f"file:{inbox_path}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 2:
                for row in db.execute("SELECT id, revision, data FROM tasks"):
                    item = dict(row)
                    try:
                        data = json.loads(item["data"])
                    except (ValueError, TypeError):
                        continue
                    if data.get("status") == "cancelled":
                        continue
                    title = data.get("title", "") or ""
                    detail = data.get("detail", "") or ""
                    project = data.get("project", "") or ""
                    structured_timing = bool(data.get("repeat") or data.get("planned_date") or data.get("due_date"))
                    for issue in _task_text_issues(title, detail, project):
                        candidates.append({"kind": "task_wording", "target_type": "task",
                                           "target_id": item["id"], "target_revision": item["revision"],
                                           "title": title[:140], "reason": issue,
                                           "question": f"Please clarify this saved task ({item['id']}): {issue}."})
                    prose_timing = bool(_TIMING_WORD.search(title) or _TIMING_WORD.search(detail)
                                        or _MONTH_WORD.search(title))
                    if prose_timing and not structured_timing and data.get("status") == "open":
                        candidates.append({"kind": "ambiguous_schedule", "target_type": "task",
                                           "target_id": item["id"], "target_revision": item["revision"],
                                           "title": title[:140],
                                           "reason": "timing lives only in prose with no repeat, workday, or deadline",
                                           "question": f"When should this saved task ({item['id']}) surface: one-off or repeat, exact start, exact end?"})
                    if _TIMING_WORD.search(title) and data.get("repeat"):
                        candidates.append({"kind": "task_wording", "target_type": "task",
                                           "target_id": item["id"], "target_revision": item["revision"],
                                           "title": title[:140],
                                           "reason": "timing word in the title duplicates the saved repeat rule",
                                           "question": f"Please confirm this saved task ({item['id']}) reads clearly without its timing word."})
                    if _ISO_DATE.search(detail) and structured_timing:
                        candidates.append({"kind": "task_wording", "target_type": "task",
                                           "target_id": item["id"], "target_revision": item["revision"],
                                           "title": title[:140],
                                           "reason": "detail restates dates already held in structured timing fields",
                                           "question": f"Please confirm this saved task ({item['id']}) keeps dates only in its structured fields."})
                for row in db.execute("SELECT id, revision, data FROM event_drafts"):
                    item = dict(row)
                    try:
                        data = json.loads(item["data"])
                    except (ValueError, TypeError):
                        continue
                    if data.get("confirmed_day") and data.get("state") == "needs-details":
                        candidates.append({"kind": "tbc_time", "target_type": "draft",
                                           "target_id": item["id"], "target_revision": item["revision"],
                                           "title": (data.get("title", "") or "")[:140],
                                           "reason": "day confirmed but clock time missing",
                                           "question": f"What exact start and end should this TBC appointment ({item['id']}) use?"})
        finally:
            db.close()
    cal_path = directory / "calendar.sqlite"
    if cal_path.is_symlink():
        raise ValueError("unsafe_path: calendar store must belong to this runtime")
    if cal_path.exists():
        try:
            cdb = sqlite3.connect(f"file:{cal_path}?mode=ro", uri=True)
            cdb.row_factory = sqlite3.Row
            try:
                if cdb.execute("PRAGMA user_version").fetchone()[0] == 1:
                    for row in cdb.execute("SELECT id, revision, raw_json FROM events WHERE review='pending' LIMIT 50"):
                        item = dict(row)
                        try:
                            raw = json.loads(item["raw_json"]) if item["raw_json"] else {}
                        except (ValueError, TypeError):
                            raw = {}
                        subject = raw.get("subject", "") or ""
                        candidates.append({"kind": "calendar_review", "target_type": "event",
                                           "target_id": item["id"], "target_revision": item["revision"],
                                           "title": subject[:140],
                                           "reason": "imported change awaits one-by-one review",
                                           "question": f"Please review this calendar import ({item['id']}) with your secretary."})
            finally:
                cdb.close()
        except sqlite3.Error:
            pass
    return candidates


class CallsStore:
    def __init__(self, directory, write=False):
        self.directory = Path(directory)
        if self.directory.is_symlink():
            raise ValueError("unsafe_path: calls store must belong to this runtime")
        path = self.directory / NAME
        if path.is_symlink():
            raise ValueError("unsafe_path: calls store must belong to this runtime")
        if not path.exists():
            if not write:
                raise ValueError("setup_required: no secretary calls saved yet")
            with runtime_lock(self.directory, ".calls.lock"):
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

    def show(self, call_id):
        row = self.db.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        if row is None:
            raise ValueError("not_found: secretary call does not exist")
        item = dict(row)
        item.update(json.loads(item.pop("data")))
        return item

    def all(self, status=""):
        query = "SELECT * FROM calls ORDER BY rowid"
        rows = self.db.execute(query).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item.update(json.loads(item.pop("data")))
            if not status or item["status"] == status:
                items.append(item)
        return items

    def add(self, payload, session, key, now):
        from .inbox_store import check_text
        check_text(session, 200, "session", False)
        check_text(key, 240, "request key", False)
        if not isinstance(payload, dict) or set(payload) - {"title", "reason", "question", "kind",
                                                             "target_type", "target_id", "target_revision", "chat_id"}:
            raise ValueError("invalid_input: call add needs title, reason, question, kind and target")
        data = validate_call({"status": "open", **payload})
        digest = hashlib.sha256(encode(["add", payload, session]).encode()).hexdigest()
        with runtime_lock(self.directory, ".calls.lock"):
            previous = self.db.execute(
                "SELECT fingerprint,receipt FROM call_events WHERE request_key=?", (key,)).fetchone()
            if previous:
                if previous["fingerprint"] != digest:
                    raise ValueError("request_conflict: key belongs to different input")
                return {**json.loads(previous["receipt"]), "replayed": True}
            open_dup = self.db.execute(
                "SELECT id FROM calls WHERE json_extract(data,'$.target_id')=? AND json_extract(data,'$.status')='open'",
                (data["target_id"],)).fetchone()
            if open_dup:
                raise ValueError("duplicate_call: an open call already covers this record")
            call_id = "call_" + uuid.uuid4().hex[:16]
            self.db.execute("INSERT INTO calls VALUES (?,?,?,?,?)",
                            (call_id, 1, now, now, encode(data)))
            result = {"saved": True, "id": call_id, "revision": 1}
            self.db.execute("INSERT INTO call_events VALUES (NULL,?,?,?,?,?,?,?,?)",
                            (call_id, "add", now, session, encode(payload), key, digest, encode(result)))
            self.db.commit()
            return result

    def _close(self, call_id, expected, payload, session, key, now, action):
        from .inbox_store import check_text
        check_text(session, 200, "session", False)
        check_text(key, 240, "request key", False)
        if action == "resolve":
            if not isinstance(payload, dict) or set(payload) - {"target_new_revision", "note"}:
                raise ValueError("invalid_input: resolve takes optional target_new_revision and note")
            if "note" in payload:
                check_text(payload["note"], 2000, "note", False)
            if "target_new_revision" in payload and (
                    type(payload["target_new_revision"]) is not int or payload["target_new_revision"] < 1):
                raise ValueError("invalid_input: target revision must be a positive integer")
        elif not isinstance(payload, dict) or set(payload) - {"note"}:
            raise ValueError("invalid_input: dismiss takes an optional note")
        else:
            if "note" in payload:
                check_text(payload["note"], 2000, "note", False)
        digest = hashlib.sha256(encode([call_id, expected, payload, session, action]).encode()).hexdigest()
        with runtime_lock(self.directory, ".calls.lock"):
            previous = self.db.execute(
                "SELECT fingerprint,receipt FROM call_events WHERE request_key=?", (key,)).fetchone()
            if previous:
                if previous["fingerprint"] != digest:
                    raise ValueError("request_conflict: key belongs to different input")
                return {**json.loads(previous["receipt"]), "replayed": True}
            current = self.show(call_id)
            if expected != current["revision"]:
                raise ValueError("write_conflict: call changed; reread and reconcile")
            if current["status"] != "open":
                raise ValueError("write_conflict: only open calls can be resolved or dismissed")
            merged = {k: current[k] for k in ("title", "reason", "question", "kind", "target_type",
                                              "target_id", "target_revision", "chat_id", "status")}
            merged["status"] = "resolved" if action == "resolve" else "dismissed"
            merged = validate_call(merged)
            self.db.execute("UPDATE calls SET revision=revision+1,updated_at=?,data=? WHERE id=?",
                            (now, encode(merged), call_id))
            result = {"saved": True, "id": call_id, "revision": expected + 1, "status": merged["status"]}
            self.db.execute("INSERT INTO call_events VALUES (NULL,?,?,?,?,?,?,?,?)",
                            (call_id, action, now, session, encode(payload), key, digest, encode(result)))
            self.db.commit()
            return result

    def resolve(self, call_id, expected, payload, session, key, now):
        return self._close(call_id, expected, payload or {}, session, key, now, "resolve")

    def dismiss(self, call_id, expected, payload, session, key, now):
        return self._close(call_id, expected, payload or {}, session, key, now, "dismiss")
