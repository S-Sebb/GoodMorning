"""Transactional secretary memory: bounded current state, immutable input and audit.

Reads never create a store. Capture never returns previous messages. SQLite owns
the records.
"""

import contextlib
import datetime as dt
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from zoneinfo import ZoneInfo

from goodmorning.calendar.calendar_safety import safe_text
from goodmorning.runtime_files import profile_fields, runtime_lock

NAME = "inbox.sqlite"
VERSION = 2
KINDS = ("idea", "todo", "project_update", "event_proposal")
STATUSES = ("pending", "confirmed", "done")
ACTIVE = "(status='pending' OR needs_review=1)"
META = "seq,id,revision,kind,status,project,created_at,updated_at,summary,needs_review"


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def check_text(value, maximum, field, empty=True):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"invalid_input: {field} must be text, at most {maximum} characters")
    if safe_text(value) != value:
        raise ValueError("protected_input: remove credentials or protected links before saving")
    return value


def validate(payload, action):
    if not isinstance(payload, dict):
        raise ValueError("invalid_input: expected a JSON object")
    allowed = {"kind", "raw", "summary", "context", "questions", "project", "task", "also", "draft", "review_after"} if action == "add" else (
        {"detail"} if action == "append" else
        {"kind", "summary", "context", "questions", "project", "status", "reviewed", "review_after", "confirmed_completion"})
    if not payload or set(payload) - allowed:
        raise ValueError("invalid_input: empty payload or unsupported fields")
    if action == "add" and not {"kind", "raw"} <= set(payload):
        raise ValueError("invalid_input: capture requires kind and raw")
    if action == "append" and "detail" not in payload:
        raise ValueError("invalid_input: follow-up requires detail")
    for field, maximum in (("raw", 65536), ("detail", 65536), ("summary", 280),
                           ("context", 6000), ("project", 160)):
        if field in payload:
            check_text(payload[field], maximum, field, field not in ("raw", "detail", "summary"))
    if "kind" in payload and payload["kind"] not in KINDS:
        raise ValueError("invalid_input: unknown kind")
    if "status" in payload and payload["status"] not in STATUSES:
        raise ValueError("invalid_input: unknown status")
    if "reviewed" in payload and type(payload["reviewed"]) is not bool:
        raise ValueError("invalid_input: reviewed must be a boolean")
    from .task_store import date, validate as validate_task
    if 'review_after' in payload:
        check_text(payload['review_after'], 10, 'review_after')
        if payload['review_after']:
            date(payload['review_after'])
    if 'task' in payload:
        if payload.get('kind') != 'todo':
            raise ValueError('invalid_input: only TODO capture accepts task fields')
        validate_task(payload['task'])
    if 'also' in payload:
        # One request that is really several items: siblings from the same capture.
        if payload.get('kind') != 'todo' or not isinstance(payload['also'], list) or not 1 <= len(payload['also']) <= 4:
            raise ValueError('invalid_input: also lists 1..4 extra items for a TODO capture')
        for fields in payload['also']:
            if not isinstance(fields, dict) or not fields.get('title'):
                raise ValueError('invalid_input: every extra item needs its own title')
            validate_task(fields)
    if 'draft' in payload:
        if payload.get('kind') != 'event_proposal':
            raise ValueError('invalid_input: only event proposals accept draft fields')
        validate_task(payload['draft'], draft=True)
    if "questions" in payload:
        questions = payload["questions"]
        if not isinstance(questions, list) or len(questions) > 12:
            raise ValueError("invalid_input: questions must be a list of at most 12 strings")
        for question in questions:
            check_text(question, 1000, "question", False)
        if len(encode(questions)) > 2200:
            raise ValueError("invalid_input: questions exceed 2200 characters; keep focused questions")
        if action == 'add' and questions and payload.get('kind') in ('todo', 'event_proposal'):
            raise ValueError('clarification_required: ask the browser question before saving this task or event; do not capture a pending note')
    return dict(payload)


def stamp(directory):
    zone = profile_fields(directory).get("timezone")
    if not zone:
        raise ValueError("setup_required: profile timezone is missing")
    return dt.datetime.now(ZoneInfo(zone)).isoformat(timespec="seconds")


def create_schema(path):
    db = sqlite3.connect(path, timeout=0)
    try:
        schema = """
            BEGIN IMMEDIATE;
            CREATE TABLE entries (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                revision INTEGER NOT NULL CHECK(revision>0),
                 kind TEXT NOT NULL CHECK(kind IN ('idea','todo','project_update','event_proposal')),
                status TEXT NOT NULL CHECK(status IN ('pending','confirmed','done')),
                project TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                raw TEXT NOT NULL, summary TEXT NOT NULL, context TEXT NOT NULL,
                questions TEXT NOT NULL, needs_review INTEGER NOT NULL DEFAULT 0,
                 reviewed_event INTEGER NOT NULL DEFAULT 0,
                 review_after TEXT NOT NULL DEFAULT '');
            CREATE INDEX active_entries ON entries(status,seq);
            CREATE INDEX review_entries ON entries(needs_review,seq);
            CREATE INDEX project_entries ON entries(project,seq);
            CREATE TABLE events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id TEXT NOT NULL REFERENCES entries(id), revision INTEGER NOT NULL,
                action TEXT NOT NULL, created_at TEXT NOT NULL, session TEXT NOT NULL,
                detail TEXT NOT NULL, changes TEXT NOT NULL,
                request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, receipt TEXT NOT NULL);
            CREATE INDEX entry_events ON events(entry_id,seq);
         """
        from .task_store import SCHEMA
        db.executescript(schema + SCHEMA + 'PRAGMA user_version=2;COMMIT;')
    finally:
        db.close()


def read_snapshot(function):
    """Keep multi-query results consistent, including reads inside a write transaction."""
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        owned = not self.db.in_transaction
        if owned:
            self.db.execute("BEGIN")
        try:
            return function(self, *args, **kwargs)
        finally:
            if owned:
                self.db.rollback()
    return wrapped


class InboxStore:
    def __init__(self, directory, write=False, path=None):
        self.directory = Path(directory).resolve()
        path = Path(path) if path else Path(directory) / NAME
        if path.is_symlink():
            raise ValueError("unsafe_path: inbox database must be a regular file inside the selected runtime")
        self.db = sqlite3.connect(path.resolve().as_uri() + ("?mode=rw" if write else "?mode=ro"),
                                  uri=True, timeout=0, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            version = self.version = self.db.execute("PRAGMA user_version").fetchone()[0]
            tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version not in (1, VERSION) or not {"entries", "events"} <= tables:
                raise ValueError("unsupported_schema: preserve inbox database and check the installed version")
            if version == 2 and not {'tasks', 'task_occurrences', 'task_events', 'event_drafts'} <= tables:
                raise ValueError('unsupported_schema: incomplete task schema; preserve the database')
            if write and version == 1:
                raise ValueError('migration_required: review task --migrate, then explicitly upgrade with --confirm')
            self.status_sql = """(CASE WHEN kind='todo' AND EXISTS(SELECT 1 FROM tasks WHERE source_entry_id=entries.id)
                THEN CASE WHEN EXISTS(SELECT 1 FROM tasks WHERE source_entry_id=entries.id
                    AND json_extract(data,'$.status') IN ('open','partial','blocked')
                    AND COALESCE(json_extract(data,'$.kind'),'')='') THEN 'pending'
                WHEN EXISTS(SELECT 1 FROM tasks WHERE source_entry_id=entries.id
                    AND json_extract(data,'$.status')='done') THEN 'done' ELSE 'confirmed' END
                ELSE status END)""" if version == 2 else 'status'
            self.meta_sql = META.replace('status,', self.status_sql + ' AS status,')
            self.active_sql = '(' + self.status_sql + "='pending' OR needs_review=1)"
        except Exception:
            self.close()
            raise

    def close(self):
        self.db.close()

    @contextlib.contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def stats(self):
        row = self.db.execute(f"SELECT COUNT(*) total,COALESCE(SUM({self.active_sql}),0) pending,"
                              f"MIN(CASE WHEN {self.active_sql} THEN substr(created_at,1,10) END) oldest FROM entries").fetchone()
        return {"pending": row["pending"], "oldest_pending_date": row["oldest"], "total": row["total"]}

    @read_snapshot
    def list(self, status="active", kind=None, project=None, after=0, limit=7, budget=8000, search=None):
        conditions, params = [], []
        if status == "active":
            conditions.append(self.active_sql)
        elif status != "all":
            conditions.append(self.status_sql + "=?")
            params.append(status)
        for field, value in (("kind", kind), ("project", project)):
            if value is not None:
                conditions.append(field + "=?")
                params.append(value)
        if search is not None:
            check_text(search, 280, "search", False)
            literal = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            conditions.append("(summary LIKE ? ESCAPE '\\' OR context LIKE ? ESCAPE '\\' OR raw LIKE ? ESCAPE '\\')")
            params.extend([literal] * 3)
        where = " AND ".join(conditions) or "1"
        total = self.db.execute("SELECT COUNT(*) FROM entries WHERE " + where, params).fetchone()[0]
        rows = self.db.execute(f"SELECT {self.meta_sql},questions,length(context) context_chars,length(raw) raw_chars "
                               f"FROM entries WHERE {where} AND seq>? ORDER BY seq LIMIT ?",
                               [*params, after, limit + 1]).fetchall()
        items, size = [], 256
        for row in rows[:limit]:
            item = dict(row)
            item["questions"] = json.loads(item["questions"])
            item["needs_review"] = bool(item["needs_review"])
            cost = len(encode(item)) + 1
            if size + cost > budget:
                break
            items.append(item)
            size += cost
        more = len(rows) > len(items)
        if more and not items:
            raise ValueError("output_budget: increase --budget to fit one complete item")
        return {"items": items, "total": total, "next_after": items[-1]["seq"] if more else None}

    @read_snapshot
    def show(self, identifier):
        review = ',review_after' if self.version == 2 else ''
        row = self.db.execute(f"SELECT {self.meta_sql},context,questions,length(raw) raw_chars,reviewed_event{review} "
                               "FROM entries WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("not_found: inbox ID does not exist")
        item = dict(row)
        item["questions"] = json.loads(item["questions"])
        item["needs_review"] = bool(item["needs_review"])
        item["unreviewed_details"] = self.db.execute(
            "SELECT COUNT(*) FROM events WHERE entry_id=? AND action='append' AND seq>?",
            (identifier, item["reviewed_event"])).fetchone()[0]
        if self.version == 2:
            item['task_ids'] = [r[0] for r in self.db.execute('SELECT id FROM tasks WHERE source_entry_id=?', (identifier,))]
            item['draft_ids'] = [r[0] for r in self.db.execute('SELECT id FROM event_drafts WHERE source_entry_id=?', (identifier,))]
        return item

    @read_snapshot
    def history(self, identifier, after=0, limit=7):
        self.show(identifier)
        rows = self.db.execute("SELECT seq event,revision,action,created_at,session,length(detail) detail_chars,"
                               "length(changes) changes_chars FROM events WHERE entry_id=? AND seq>? "
                               "ORDER BY seq LIMIT ?", (identifier, after, limit + 1)).fetchall()
        items = [dict(row) for row in rows[:limit]]
        return {"id": identifier, "items": items,
                "next_after": items[-1]["event"] if len(rows) > limit else None}

    def text(self, identifier, event=False, offset=0, chars=2000):
        table, key = ("events", "seq") if event else ("entries", "id")
        field = "CASE WHEN detail!='' THEN detail ELSE changes END" if event else "raw"
        row = self.db.execute(f"SELECT length({field}) total,substr({field},?,?) text "
                               f"FROM {table} WHERE {key}=?", (offset + 1, chars, identifier)).fetchone()
        if row is None:
            raise ValueError("not_found: inbox ID or event does not exist")
        end = offset + len(row["text"])
        return {"id": identifier, "offset": offset, "text": row["text"], "total_chars": row["total"],
                "next_offset": end if end < row["total"] else None}

    def mutate(self, action, payload, session, request_key, now, identifier=None, revision=None):
        payload = validate(payload, action)
        check_text(session, 200, "session", False)
        check_text(request_key, 240, "request_key", False)
        digest = hashlib.sha256(encode([action, identifier, revision, payload, session]).encode()).hexdigest()
        with self.transaction():
            if self.db.execute('SELECT 1 FROM task_events WHERE request_key=?', (request_key,)).fetchone():
                raise ValueError('request_conflict: request key belongs to a task operation')
            previous = self.db.execute("SELECT fingerprint,receipt FROM events WHERE request_key=?",
                                       (request_key,)).fetchone()
            if previous:
                if previous["fingerprint"] != digest:
                    raise ValueError("request_conflict: request key already belongs to different input")
                return {**json.loads(previous["receipt"]), "replayed": True}
            if action == "add":
                identifier = "ib_" + uuid.uuid4().hex[:16]
                revision = 1
                from .task_store import default_title
                summary = payload.get("summary") or default_title(payload["raw"])
                self.db.execute("INSERT INTO entries (id,revision,kind,status,project,created_at,updated_at,"
                                "raw,summary,context,questions) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                (identifier, revision, payload["kind"], "pending", payload.get("project", ""),
                                 now, now, payload["raw"], summary, payload.get("context", ""),
                                  encode(payload.get("questions", []))))
                if 'review_after' in payload:
                    self.db.execute('UPDATE entries SET review_after=? WHERE id=?', (payload['review_after'], identifier))
                from .task_store import capture
                linked = capture(self.db, identifier, payload, now)
            else:
                linked = {}
                current = self.show(identifier)
                if action == 'update' and payload.get('questions') and current['kind'] in ('todo', 'event_proposal'):
                    raise ValueError('clarification_required: ask the browser question before changing this task or event; do not save pending questions in the inbox')
                if action == "update" and revision != current["revision"]:
                    raise ValueError("write_conflict: revision changed; show the entry and reconcile")
                revision = current["revision"] + 1
                if action == "append":
                    self.db.execute("UPDATE entries SET revision=?,updated_at=?,needs_review=1 WHERE id=?",
                                    (revision, now, identifier))
                else:
                    reviewed = payload.get("reviewed", False)
                    if payload.get('kind') == 'todo' and current['kind'] != 'todo':
                        raise ValueError('organization_required: use task --adopt to create source-linked actions')
                    if current['kind'] == 'todo' and payload.get('kind', 'todo') != 'todo':
                        from .task_store import TaskStore
                        if any(TaskStore(self).show(task_id)['status'] not in ('done', 'cancelled') for task_id in current['task_ids']):
                            raise ValueError('organization_required: resolve live actions before reclassifying their capture')
                    if current['kind'] == 'event_proposal' and payload.get('status', 'pending') != 'pending':
                        # A separate calendar event would leave the draft showing as a TBC duplicate.
                        from .task_store import TaskStore
                        for draft_id in current['draft_ids']:
                            if TaskStore(self).show(draft_id, True)['state'] not in ('converted', 'withdrawn'):
                                raise ValueError(f'organization_required: event draft {draft_id} is still open; '
                                                 'save its time with task --convert instead of calendar --add, or withdraw it '
                                                 'with task --update --draft {"state":"withdrawn"}, before closing this capture')
                    if current["needs_review"] and payload.get("status", "pending") != "pending" and not reviewed:
                        raise ValueError("unreviewed_details: incorporate saved follow-ups before closing")
                    if current['kind'] == 'todo' and payload.get('status') == 'done':
                        if payload.get('confirmed_completion') is not True or len(current['task_ids']) != 1:
                            raise ValueError('confirmation_required: complete exact task IDs with confirmed_completion')
                        from .task_store import TaskStore
                        task = TaskStore(self).show(current['task_ids'][0])
                        if task['repeat']:
                            raise ValueError('occurrence_required: use task --report for one recurring day')
                        data = {k: v for k, v in task.items() if k not in ('id', 'source_entry_id', 'revision', 'created_at', 'updated_at')}
                        data['status'] = 'done'
                        self.db.execute('UPDATE tasks SET revision=revision+1,updated_at=?,data=? WHERE id=?', (now, encode(data), task['id']))
                    updates = {k: encode(v) if k == "questions" else v
                               for k, v in payload.items() if k not in ('reviewed', 'confirmed_completion')}
                    updates.update(revision=revision, updated_at=now)
                    if reviewed:
                        updates.update(needs_review=0, reviewed_event=self.db.execute(
                            "SELECT COALESCE(MAX(seq),0) FROM events WHERE entry_id=?", (identifier,)).fetchone()[0])
                    self.db.execute("UPDATE entries SET " + ",".join(k + "=?" for k in updates) + " WHERE id=?",
                                    [*updates.values(), identifier])
            receipt = {"saved": True, "id": identifier, "revision": revision, "action": action, **linked}
            event = self.db.execute("INSERT INTO events (entry_id,revision,action,created_at,session,detail,"
                                    "changes,request_key,fingerprint,receipt) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                    (identifier, revision, action, now, session, payload.get("detail", ""),
                                     encode({k: v for k, v in payload.items() if k != "detail"}),
                                     request_key, digest, "")).lastrowid
            receipt["event"] = event
            self.db.execute("UPDATE events SET receipt=? WHERE seq=?", (encode(receipt), event))
            return receipt


def initialize(directory):
    path = Path(directory) / NAME
    with runtime_lock(directory, ".inbox.lock"):
        if path.exists():
            store = InboxStore(directory)
            store.close()
            return {"initialized": True}
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            create_schema(path)
        except Exception:
            path.unlink()
            raise
    return {"initialized": True}
