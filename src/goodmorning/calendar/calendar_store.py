"""Transactional calendar storage. Original imports never become schedule entries directly."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import date, datetime, time, timezone, timedelta
from pathlib import Path
from .calendar_safety import clean_preparation, safe_value

FIELDS = {"subject", "start", "end", "timezone", "all_day", "location", "online",
          "organizer", "notes", "status", "repeat"}
IMPORT_FIELDS = FIELDS | {"external_id", "occurrence_id"}


def encode(value) -> str:
    return json.dumps(safe_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize(data: dict) -> dict:
    """Validate explicit offsets, or exclusive date endpoints for all-day events."""
    if not isinstance(data, dict) or set(data) - FIELDS:
        raise ValueError("event must be an object containing only supported event fields")
    out = safe_value(dict(data))
    status = out.setdefault("status", "confirmed")
    if status not in ("confirmed", "cancelled"):
        raise ValueError("status must be confirmed or cancelled")
    for key in FIELDS - {"all_day", "repeat"}:
        if key in out and not isinstance(out[key], str):
            raise ValueError(f"{key} must be a string")
    for key in ("location", "online", "organizer", "notes"):
        if out.get(key) == "":
            out.pop(key)
    all_day = out.setdefault("all_day", False)
    if not isinstance(all_day, bool):
        raise ValueError("all_day must be a boolean")
    if "timezone" in out:
        from zoneinfo import ZoneInfo
        ZoneInfo(out["timezone"])
    if status == "cancelled" and "start" not in out and "end" not in out:
        return out
    if not out.get("subject", "").strip():
        raise ValueError("subject is required")
    out["subject"] = out["subject"].strip()
    if all_day:
        from zoneinfo import ZoneInfo
        ZoneInfo(out.get("timezone", ""))  # No guessing the calendar's day boundary.
        start = date.fromisoformat(out.get("start", ""))
        end = date.fromisoformat(out.get("end", ""))
    else:
        start = datetime.fromisoformat(out.get("start", ""))
        end = datetime.fromisoformat(out.get("end", ""))
        if start.utcoffset() is None or end.utcoffset() is None:
            raise ValueError("start and end need explicit UTC offsets")
        start = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
    if end <= start:
        raise ValueError("end must be after start; all-day end is exclusive")
    if 'repeat' in out:
        rule = out['repeat']
        if (not all_day or end != start + timedelta(days=1) or not isinstance(rule,dict)
                or set(rule) != {'yearly','start'} or rule['yearly'] is not True
                or not isinstance(rule['start'],str) or date.fromisoformat(rule['start']).isoformat()!=rule['start']):
            raise ValueError('annual observance needs one all-day date and repeat {yearly:true,start:YYYY-MM-DD}')
        if (start.month,start.day)==(2,29):
            raise ValueError('clarification_required: define non-leap-year handling before recording an annual February 29 observance')
        if rule['start'] > start.isoformat():
            raise ValueError('annual series start must not follow its original approved occurrence')
    out["start"], out["end"] = start.isoformat(), end.isoformat()
    return out


def endpoints(data: dict) -> tuple[datetime, datetime]:
    if data.get("all_day"):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(data["timezone"])
        return tuple(datetime.combine(date.fromisoformat(data[k]), time(), tz)
                     for k in ("start", "end"))
    return tuple(datetime.fromisoformat(data[k]) for k in ("start", "end"))


class CalendarStore:
    def __init__(self, path: str, readonly=False):
        if readonly:
            self.con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
            self.con.row_factory = sqlite3.Row
            try:
                version = self.con.execute("PRAGMA user_version").fetchone()[0]
                tables = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if version != 1 or not {"events", "history"} <= tables:
                    raise ValueError("unsupported calendar database; preserve it and inspect setup")
            except Exception:
                self.con.close()
                raise
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path, timeout=10)
        self.con.row_factory = sqlite3.Row
        version = self.con.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.con.close()
            raise ValueError(f"unsupported calendar database version {version}")
        tables = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if (version == 0 and tables) or (version == 1 and not {"events", "history"} <= tables):
            self.con.close()
            raise ValueError("existing database is not a secretary calendar; choose another --db path")
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, source TEXT NOT NULL,
                external_id TEXT NOT NULL, occurrence_id TEXT NOT NULL DEFAULT '',
                raw_json TEXT, raw_hash TEXT, raw_revision INTEGER NOT NULL DEFAULT 0,
                review TEXT NOT NULL CHECK(review IN ('pending','approved','rejected')),
                approved_json TEXT, starts REAL, ends REAL,
                revision INTEGER NOT NULL,
                UNIQUE(source, external_id, occurrence_id)
            );
            CREATE INDEX IF NOT EXISTS events_window ON events(starts, ends);
            CREATE INDEX IF NOT EXISTS events_review ON events(review);
            CREATE TABLE IF NOT EXISTS history (
                seq INTEGER PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id),
                revision INTEGER NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL,
                at TEXT NOT NULL, snapshot TEXT NOT NULL,
                UNIQUE(event_id, revision)
            );
            PRAGMA user_version=1;
        """)

    def close(self):
        self.con.close()

    def get(self, event_id: str) -> dict:
        row = self.con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if row is None:
            import re
            if isinstance(event_id,str) and re.fullmatch('[0-9a-f]{16}',event_id):
                year=int(event_id[:4],16)
                candidates=self.con.execute("SELECT * FROM events WHERE substr(id,1,12)=? AND json_type(approved_json,'$.repeat')='object'",(event_id[4:],)).fetchall()
                if 1 <= year <= 9999 and len(candidates)==1:
                    projected=self.annual_occurrence(candidates[0],year)
                    if projected and projected['id']==event_id:
                        out=dict(candidates[0]);out['id']=event_id
                        out['raw']=json.loads(out.pop('raw_json')) if out.get('raw_json') else None
                        out.pop('raw_json',None);out.pop('approved_json')
                        out.update(approved=projected['approved'],series_event_id=candidates[0]['id'],projected=True)
                        a,b=endpoints(out['approved']);out.update(starts=a.timestamp(),ends=b.timestamp())
                        return out
            raise ValueError(f"unknown event {event_id}")
        out = dict(row)
        for key in ("raw_json", "approved_json"):
            value = out.pop(key)
            out[key.removesuffix("_json")] = json.loads(value) if value else None
        return out

    def annual_occurrence(self, row, year):
        data=normalize(json.loads(row['approved_json']))
        if self.con.execute("SELECT COUNT(*) FROM events WHERE substr(id,1,12)=? AND json_type(approved_json,'$.repeat')='object'",(row['id'][:12],)).fetchone()[0]!=1:
            raise ValueError('annual series identity is ambiguous; preserve both sources and inspect')
        original=date.fromisoformat(data['start'])
        target=date(year,original.month,original.day)
        if target.isoformat()<data['repeat']['start']:
            return None
        if target==original:
            return {'id':row['id'],'approved':data}
        identifier=format(year,'04x')+row['id'][:12]
        if self.con.execute('SELECT 1 FROM events WHERE id=?',(identifier,)).fetchone():
            raise ValueError('annual occurrence identity conflicts with a saved event; preserve both and inspect')
        data={**data,'start':target.isoformat(),'end':(target+timedelta(days=1)).isoformat()}
        return {'id':identifier,'approved':data}

    def _audit(self, event_id: str, action: str, actor: str):
        item = self.get(event_id)
        self.con.execute("INSERT INTO history(event_id,revision,action,actor,at,snapshot) "
                         "VALUES(?,?,?,?,?,?)", (event_id, item["revision"], action, actor,
                         datetime.now(timezone.utc).isoformat(), encode(item)))

    def _set_approved(self, event_id: str, data: dict):
        start, end = (None, None) if data["status"] == "cancelled" else endpoints(data)
        self.con.execute("UPDATE events SET approved_json=?,starts=?,ends=? WHERE id=?",
                         (encode(data), start.timestamp() if start else None,
                          end.timestamp() if end else None, event_id))

    def add(self, data: dict, actor: str = "secretary", external_id: str | None = None) -> str:
        normalized = normalize(data)
        event_id = self.add_many([(normalized, external_id)], actor)[0]
        if self.get(event_id)["approved"] != normalized:
            raise ValueError(f"original event {event_id} was edited or cancelled; read --show before restoring it")
        return event_id

    def add_many(self, items: list[tuple[dict, str | None]], actor: str) -> list[str]:
        validated = [(normalize(data), key) for data, key in items]
        if any(data["status"] != "confirmed" for data, _ in validated):
            raise ValueError("new custom events must be confirmed, not cancelled")
        ids = []
        with self.con:
            self.con.execute("BEGIN IMMEDIATE")
            for data, key in validated:
                key = key or hashlib.sha256(encode(data).encode()).hexdigest()
                old = self.con.execute("SELECT id FROM events WHERE source='custom' "
                                       "AND external_id=?", (key,)).fetchone()
                if old:
                    ids.append(old[0])
                    continue
                event_id = uuid.uuid4().hex[:16]
                self.con.execute("INSERT INTO events(id,source,external_id,review,revision) "
                                 "VALUES(?,'custom',?,'approved',1)", (event_id, key))
                self._set_approved(event_id, data)
                self._audit(event_id, "add", actor)
                ids.append(event_id)
        return ids

    def stage(self, source: str, events: list[dict], actor: str = "secretary") -> dict:
        if not isinstance(source, str) or not source.strip() or source == "custom":
            raise ValueError("imports need a nonempty source other than custom")
        if source != source.strip():
            raise ValueError("source must not have leading or trailing whitespace")
        if not isinstance(events, list):
            raise ValueError("events must be a list")
        validated, seen = [], set()
        for item in events:
            if not isinstance(item, dict) or set(item) - IMPORT_FIELDS:
                raise ValueError("unsupported import fields")
            key, occurrence = item.get("external_id"), item.get("occurrence_id", "")
            if not isinstance(key, str) or not key or not isinstance(occurrence, str):
                raise ValueError("external_id required; occurrence_id must be a string")
            if (key, occurrence) in seen:
                raise ValueError("duplicate source identity in import batch")
            seen.add((key, occurrence))
            data = normalize({k: v for k, v in item.items() if k in FIELDS})
            validated.append((key, occurrence, data))
        result = {"new": 0, "changed": 0, "unchanged": 0}
        with self.con:
            self.con.execute("BEGIN IMMEDIATE")
            for key, occurrence, data in validated:
                raw = encode(data)
                digest = hashlib.sha256(raw.encode()).hexdigest()
                old = self.con.execute("SELECT * FROM events WHERE source=? AND "
                                       "external_id=? AND occurrence_id=?",
                                       (source, key, occurrence)).fetchone()
                if old and old["raw_hash"] == digest:
                    result["unchanged"] += 1
                    continue
                if old:
                    event_id = old["id"]
                    self.con.execute("UPDATE events SET raw_json=?,raw_hash=?,"
                                     "raw_revision=raw_revision+1,revision=revision+1,"
                                     "review='pending' WHERE id=?", (raw, digest, event_id))
                    result["changed"] += 1
                else:
                    event_id = uuid.uuid4().hex[:16]
                    self.con.execute("INSERT INTO events(id,source,external_id,occurrence_id,"
                                     "raw_json,raw_hash,raw_revision,review,revision) "
                                     "VALUES(?,?,?,?,?,?,1,'pending',1)",
                                     (event_id, source, key, occurrence, raw, digest))
                    result["new"] += 1
                self._audit(event_id, "import", actor)
        return result

    def change(self, event_id: str, action: str, expected: int,
               patch: dict | None = None, actor: str = "secretary") -> dict:
        if action not in ("approve", "reject", "update", "cancel"):
            raise ValueError("unknown event action")
        if patch is not None and (not isinstance(patch, dict) or set(patch) - FIELDS):
            raise ValueError("unsupported event patch")
        with self.con:
            self.con.execute("BEGIN IMMEDIATE")
            old = self.get(event_id)
            if old.get('projected'):
                raise ValueError('clarification_required: this annual occurrence is projected; confirm series scope before editing its source event')
            if old["revision"] != expected:
                raise ValueError("event changed; read it again before writing")
            if action in ("approve", "reject"):
                if old["source"] == "custom" or old["review"] != "pending":
                    raise ValueError("only pending imports can be reviewed")
                if action == "approve":
                    data = normalize(old["raw"] | (patch or {}))
                    # A simplification may not silently undo a provider cancellation.
                    if old["raw"]["status"] == "cancelled" and data["status"] != "cancelled":
                        raise ValueError("cannot approve a cancellation as confirmed")
                    self._set_approved(event_id, data)
                elif patch:
                    raise ValueError("reject does not accept event changes")
                review = "approved" if action == "approve" else "rejected"
            else:
                if old["approved"] is None:
                    raise ValueError("review the imported event before editing")
                if action == "cancel" and patch:
                    raise ValueError("cancel does not accept event changes")
                data = normalize(old["approved"] | (patch or {}) |
                                 ({"status": "cancelled"} if action == "cancel" else {}))
                self._set_approved(event_id, data)
                review = old["review"]
            self.con.execute("UPDATE events SET review=?,revision=revision+1 WHERE id=?",
                             (review, event_id))
            self._audit(event_id, action, actor)
        return self.get(event_id)

    def pending(self, limit: int = 20, offset: int = 0) -> list[dict]:
        rows = self.con.execute("SELECT id,source,raw_json,raw_revision,revision "
                                "FROM events WHERE review='pending' ORDER BY rowid LIMIT ? OFFSET ?",
                                (limit, offset))
        return [{"id": r["id"], "source": r["source"], "revision": r["revision"],
                 "raw_revision": r["raw_revision"],
                 **{k: v for k, v in json.loads(r["raw_json"]).items()
                    if k in ("subject", "start", "end", "status", "all_day")}} for r in rows]

    def query(self, start: datetime, end: datetime, source: str = "auto",
              no_custom: bool = False, limit: int = 100, offset: int = 0,
              details: bool = False) -> list[dict]:
        owned=not self.con.in_transaction
        if owned:
            self.con.execute('BEGIN')
        try:
            return self._query(start,end,source,no_custom,limit,offset,details)
        finally:
            if owned:
                self.con.rollback()

    def _query(self, start, end, source, no_custom, limit, offset, details):
        clauses, params = ["starts < ?", "ends > ?"], [end.timestamp(), start.timestamp()]
        if source != "auto":
            clauses.append("source=?")
            params.append(source)
        if no_custom:
            clauses.append("source!='custom'")
        series_clauses=["starts IS NOT NULL", "json_type(approved_json,'$.repeat')='object'"]
        series_params=[]
        if source!='auto':
            series_clauses.append('source=?');series_params.append(source)
        if no_custom:
            series_clauses.append("source!='custom'")
        series=self.con.execute('SELECT id,source,revision,review,approved_json FROM events WHERE '+ ' AND '.join(series_clauses),series_params).fetchall()
        params.extend([limit+offset if series and limit>=0 else limit, 0 if series else offset])
        rows = self.con.execute("SELECT id,source,revision,review,approved_json FROM events WHERE "
                                + " AND ".join(clauses) + " ORDER BY starts,id LIMIT ? OFFSET ?", params)
        out = []
        for row in rows:
            data = json.loads(row["approved_json"])
            if not details:
                data = {k: v for k, v in data.items() if k not in ("notes", "organizer") and v != ""}
            elif "notes" in data:
                # Schedule reads show concise preparation, never join boilerplate.
                # Review of originals/revisions still uses --show/--pending.
                cleaned = clean_preparation(data.get("notes", ""))
                if cleaned:
                    data["notes"] = cleaned
                else:
                    data.pop("notes", None)
            out.append({"id": row["id"], "source": row["source"], "revision": row["revision"],
                         **data, **({"pending_change": True} if row["review"] == "pending" else {})})
        if series:
            from zoneinfo import ZoneInfo
            for row in series:
                data=json.loads(row['approved_json'])
                zone=ZoneInfo(data['timezone'])
                first=max(start.astimezone(zone).year,date.fromisoformat(data['repeat']['start']).year)
                last=end.astimezone(zone).year
                if limit>=0:
                    last=min(last,first+limit+offset)
                for year in range(first,last+1):
                    projected=self.annual_occurrence(row,year)
                    if not projected or projected['id']==row['id']:
                        continue  # The original approved occurrence was already queried.
                    value=projected['approved'];begin,finish=endpoints(value)
                    if begin>=end or finish<=start:
                        continue
                    if not details:
                        value={k:v for k,v in value.items() if k not in ('notes','organizer') and v!=''}
                    elif 'notes' in value:
                        cleaned=clean_preparation(value.get('notes',''))
                        if cleaned:
                            value['notes']=cleaned
                        else:
                            value.pop('notes',None)
                    out.append({'id':projected['id'],'source':row['source'],'revision':row['revision'],
                        **value,'series_event_id':row['id'], 'projected':True,
                        **({'pending_change':True} if row['review']=='pending' else {})})
            out.sort(key=lambda item:(endpoints(item)[0].timestamp(),item['id']))
            out=out[offset:offset+limit] if limit>=0 else out[offset:]
        return out

    def history(self, event_id: str, limit: int = 20, offset: int = 0) -> list[dict]:
        item=self.get(event_id)
        event_id=item.get('series_event_id',event_id)
        rows = self.con.execute("SELECT revision,action,actor,at,snapshot FROM history "
                                "WHERE event_id=? ORDER BY revision DESC LIMIT ? OFFSET ?",
                                (event_id, limit, offset))
        return [{**dict(r), "snapshot": json.loads(r["snapshot"])} for r in rows]

    def stats(self) -> dict:
        row = self.con.execute("SELECT COUNT(*) AS total, "
                               "COUNT(CASE WHEN source='custom' AND starts IS NOT NULL THEN 1 END) AS custom, "
                               "COUNT(CASE WHEN source!='custom' AND starts IS NOT NULL THEN 1 END) AS imported, "
                               "COUNT(CASE WHEN review='pending' THEN 1 END) AS pending FROM events").fetchone()
        return dict(row)


def read_stats(path: str) -> dict:
    """Read the small summary without creating or migrating a database."""
    if not Path(path).is_file():
        return {"total": 0, "custom": 0, "imported": 0, "pending": 0}
    store = CalendarStore.__new__(CalendarStore)
    store.con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    store.con.row_factory = sqlite3.Row
    try:
        return store.stats()
    finally:
        store.close()
