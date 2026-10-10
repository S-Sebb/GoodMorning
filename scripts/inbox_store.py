"""Transactional secretary memory: bounded current state, immutable input and audit.

Reads never create a store. Capture never returns previous messages. SQLite owns
the records; Markdown is supported only for explicit, lossless legacy migration.
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
import tempfile
import uuid
from zoneinfo import ZoneInfo

from calendar_safety import safe_text
from runtime_files import atomic_text, profile_fields, runtime_lock

NAME = "inbox.sqlite"
VERSION = 1
KINDS = ("idea", "todo", "project_update")
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
    allowed = {"kind", "raw", "summary", "context", "questions", "project"} if action == "add" else (
        {"detail"} if action == "append" else
        {"kind", "summary", "context", "questions", "project", "status", "reviewed"})
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
    if "questions" in payload:
        questions = payload["questions"]
        if not isinstance(questions, list) or len(questions) > 12:
            raise ValueError("invalid_input: questions must be a list of at most 12 strings")
        for question in questions:
            check_text(question, 1000, "question", False)
        if len(encode(questions)) > 2200:
            raise ValueError("invalid_input: questions exceed 2200 characters; keep focused questions")
    return dict(payload)


def stamp(directory):
    zone = profile_fields(directory).get("timezone")
    if not zone:
        raise ValueError("setup_required: profile timezone is missing")
    return dt.datetime.now(ZoneInfo(zone)).isoformat(timespec="seconds")


def create_schema(path):
    db = sqlite3.connect(path, timeout=0)
    try:
        db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE entries (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                revision INTEGER NOT NULL CHECK(revision>0),
                kind TEXT NOT NULL CHECK(kind IN ('idea','todo','project_update')),
                status TEXT NOT NULL CHECK(status IN ('pending','confirmed','done')),
                project TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                raw TEXT NOT NULL, summary TEXT NOT NULL, context TEXT NOT NULL,
                questions TEXT NOT NULL, needs_review INTEGER NOT NULL DEFAULT 0,
                reviewed_event INTEGER NOT NULL DEFAULT 0);
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
            CREATE TABLE migration (source_hash TEXT PRIMARY KEY, backup TEXT NOT NULL, count INTEGER NOT NULL);
            PRAGMA user_version=1;
            COMMIT;
        """)
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
        path = Path(path) if path else Path(directory) / NAME
        if path.is_symlink():
            raise ValueError("unsafe_path: inbox database must be a regular file inside the selected runtime")
        self.db = sqlite3.connect(path.resolve().as_uri() + ("?mode=rw" if write else "?mode=ro"),
                                  uri=True, timeout=0, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version != VERSION or not {"entries", "events", "migration"} <= tables:
                raise ValueError("unsupported_schema: preserve inbox database and check the installed version")
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
        row = self.db.execute(f"SELECT COUNT(*) total,COALESCE(SUM({ACTIVE}),0) pending,"
                              f"MIN(CASE WHEN {ACTIVE} THEN substr(created_at,1,10) END) oldest FROM entries").fetchone()
        return {"pending": row["pending"], "oldest_pending_date": row["oldest"], "total": row["total"]}

    @read_snapshot
    def list(self, status="active", kind=None, project=None, after=0, limit=7, budget=8000, search=None):
        conditions, params = [], []
        if status == "active":
            conditions.append(ACTIVE)
        elif status != "all":
            conditions.append("status=?")
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
        rows = self.db.execute(f"SELECT {META},questions,length(context) context_chars,length(raw) raw_chars "
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
        row = self.db.execute(f"SELECT {META},context,questions,length(raw) raw_chars,reviewed_event "
                               "FROM entries WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("not_found: inbox ID does not exist")
        item = dict(row)
        item["questions"] = json.loads(item["questions"])
        item["needs_review"] = bool(item["needs_review"])
        item["unreviewed_details"] = self.db.execute(
            "SELECT COUNT(*) FROM events WHERE entry_id=? AND action='append' AND seq>?",
            (identifier, item["reviewed_event"])).fetchone()[0]
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
            previous = self.db.execute("SELECT fingerprint,receipt FROM events WHERE request_key=?",
                                       (request_key,)).fetchone()
            if previous:
                if previous["fingerprint"] != digest:
                    raise ValueError("request_conflict: request key already belongs to different input")
                return {**json.loads(previous["receipt"]), "replayed": True}
            if action == "add":
                identifier = "ib_" + uuid.uuid4().hex[:16]
                revision = 1
                summary = payload.get("summary") or " ".join(payload["raw"].split())[:280]
                self.db.execute("INSERT INTO entries (id,revision,kind,status,project,created_at,updated_at,"
                                "raw,summary,context,questions) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                (identifier, revision, payload["kind"], "pending", payload.get("project", ""),
                                 now, now, payload["raw"], summary, payload.get("context", ""),
                                 encode(payload.get("questions", []))))
            else:
                current = self.show(identifier)
                if action == "update" and revision != current["revision"]:
                    raise ValueError("write_conflict: revision changed; show the entry and reconcile")
                revision = current["revision"] + 1
                if action == "append":
                    self.db.execute("UPDATE entries SET revision=?,updated_at=?,needs_review=1 WHERE id=?",
                                    (revision, now, identifier))
                else:
                    reviewed = payload.get("reviewed", False)
                    if current["needs_review"] and payload.get("status", "pending") != "pending" and not reviewed:
                        raise ValueError("unreviewed_details: incorporate saved follow-ups before closing")
                    updates = {k: encode(v) if k == "questions" else v
                               for k, v in payload.items() if k != "reviewed"}
                    updates.update(revision=revision, updated_at=now)
                    if reviewed:
                        updates.update(needs_review=0, reviewed_event=self.db.execute(
                            "SELECT COALESCE(MAX(seq),0) FROM events WHERE entry_id=?", (identifier,)).fetchone()[0])
                    self.db.execute("UPDATE entries SET " + ",".join(k + "=?" for k in updates) + " WHERE id=?",
                                    [*updates.values(), identifier])
            receipt = {"saved": True, "id": identifier, "revision": revision, "action": action}
            event = self.db.execute("INSERT INTO events (entry_id,revision,action,created_at,session,detail,"
                                    "changes,request_key,fingerprint,receipt) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                    (identifier, revision, action, now, session, payload.get("detail", ""),
                                     encode({k: v for k, v in payload.items() if k != "detail"}),
                                     request_key, digest, "")).lastrowid
            receipt["event"] = event
            self.db.execute("UPDATE events SET receipt=? WHERE seq=?", (encode(receipt), event))
            return receipt


def legacy_entries(text):
    """Parse only entry headers; preserve every continuation in the migration audit."""
    entries, active = [], None
    for line in text.splitlines(keepends=True):
        if line.startswith(("- ", "* ")) and "|" in line:
            try:
                head, status, project = line.rstrip("\r\n").rsplit("|", 2)
                timestamp, raw = head[2:].split("|", 1)
            except ValueError:
                raise ValueError("invalid_legacy: malformed inbox entry; preserve and inspect source") from None
            timestamp, raw, status, project = timestamp.strip(), raw.strip(), status.strip(), project.strip()
            if status not in STATUSES or not re.match(r"^\d{4}-\d{2}-\d{2}(?: |$)", timestamp):
                raise ValueError("invalid_legacy: invalid status or timestamp; preserve and inspect source")
            dt.date.fromisoformat(timestamp[:10])
            try:
                value = json.loads(raw)
            except ValueError:
                value = raw
            if isinstance(value, dict):
                if "raw" not in value or value.get("kind", "idea") not in KINDS:
                    raise ValueError("invalid_legacy: unsupported entry object; preserve and inspect source")
                payload = {"kind": value.get("kind", "idea"), "raw": value["raw"], "project": project}
            else:
                payload = {"kind": "idea", "raw": value if isinstance(value, str) else raw, "project": project}
            validate(payload, "add")
            active = {"payload": payload, "status": status, "timestamp": timestamp,
                      "legacy": line, "object": value if isinstance(value, dict) else {}}
            entries.append(active)
        elif active:
            active["legacy"] += line
        elif line.strip() and not line.lstrip().startswith(("#", "<!--")):
            raise ValueError("invalid_legacy: unassigned source text; preserve and inspect source")
    return entries


def pointer(backup):
    return ("# Inbox moved to SQLite\n\n"
            "Use scripts/inbox.py with an explicit --secretary-dir. Do not append here.\n"
            "Active memory: inbox.sqlite. Read only relevant IDs through the helper.\n"
            f"Original, unchanged migration archive: {backup}\n")


def initialize(directory):
    path = Path(directory) / NAME
    with runtime_lock(directory, ".inbox.lock"):
        if path.exists():
            store = InboxStore(directory)
            store.close()
            return {"initialized": True}
        if (Path(directory) / "inbox.md").exists():
            raise ValueError("migration_required: existing Markdown inbox needs explicit --migrate")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            create_schema(path)
        except Exception:
            path.unlink()
            raise
    return {"initialized": True}


def migrate(directory, session):
    """Backup first, build privately, publish atomically, then leave an archive pointer.

    An interrupted pointer replacement is resumable. Changed legacy sources or an
    unrelated existing database are refused instead of overwriting either record.
    """
    source = Path(directory) / "inbox.md"
    destination = Path(directory) / NAME
    with runtime_lock(directory, ".inbox.lock"):
        if source.is_symlink():
            raise ValueError("unsafe_path: legacy inbox must not be a symlink")
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if destination.exists():
            store = InboxStore(directory)
            try:
                previous = store.db.execute("SELECT * FROM migration").fetchone()
            finally:
                store.close()
            if previous is None or not re.fullmatch(r"inbox\.legacy-[0-9a-f]{16}\.md", previous["backup"]):
                raise ValueError("migration_conflict: missing or invalid migration metadata; preserve the database")
            if (Path(directory) / previous["backup"]).is_symlink():
                raise ValueError("unsafe_path: migration archive must not be a symlink")
            if data not in (pointer(previous["backup"]).encode(),
                                                (Path(directory) / previous["backup"]).read_bytes()):
                raise ValueError("migration_conflict: inbox sources changed or database already exists; inspect both")
            backup = Path(directory) / previous["backup"]
            if hashlib.sha256(backup.read_bytes()).hexdigest() != previous["source_hash"]:
                raise ValueError("migration_conflict: migration archive changed; preserve and inspect it")
            atomic_text(source, pointer(previous["backup"]))
            return {"migrated": True, "entries": previous["count"], "backup": previous["backup"], "replayed": True}
        entries = legacy_entries(data.decode("utf-8"))
        check_text(data.decode("utf-8"), max(len(data), 1), "legacy source")
        backup = Path(directory) / ("inbox.legacy-" + digest[:16] + ".md")
        try:
            with open(backup, "xb") as stream:
                os.chmod(backup, 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if backup.is_symlink() or backup.read_bytes() != data:
                raise ValueError("migration_conflict: existing archive differs; preserve it") from None
        fd, name = tempfile.mkstemp(prefix=".inbox-migrate-", dir=directory)
        os.close(fd)
        temporary = Path(name)
        try:
            create_schema(temporary)
            store = InboxStore(directory, write=True, path=temporary)
            try:
                for number, entry in enumerate(entries):
                    payload = entry["payload"]
                    obj = entry["object"]
                    # Current view keeps available supplied details; full legacy text is
                    # retained separately, not silently squeezed into a summary.
                    continuation = "".join(entry["legacy"].splitlines(keepends=True)[1:]).strip()
                    supplied = obj.get("details", "")
                    context = supplied if isinstance(supplied, str) else encode(supplied)
                    context = "\n".join(part for part in (context, continuation) if part)
                    payload["context"] = context[:6000]
                    questions = obj.get("clarification", [])
                    if isinstance(questions, list) and entry["status"] == "pending":
                        payload["questions"] = questions
                    receipt = store.mutate("add", payload, session, f"migration:{digest}:{number}", entry["timestamp"])
                    store.db.execute("UPDATE entries SET status=?,needs_review=? WHERE id=?",
                                     (entry["status"], int(len(context) > 6000), receipt["id"]))
                    store.db.execute("UPDATE events SET detail=? WHERE seq=?", (entry["legacy"], receipt["event"]))
                store.db.execute("INSERT INTO migration VALUES (?,?,?)", (digest, backup.name, len(entries)))
                store.db.commit()
            finally:
                store.close()
            if source.read_bytes() != data:
                raise ValueError("migration_conflict: source changed during migration; retry after inspection")
            with open(temporary, "rb") as stream:
                os.fsync(stream.fileno())
            os.link(temporary, destination)  # Never overwrite an existing store.
            atomic_text(source, pointer(backup.name))
        finally:
            temporary.unlink(missing_ok=True)
    return {"migrated": True, "entries": len(entries), "backup": backup.name}
