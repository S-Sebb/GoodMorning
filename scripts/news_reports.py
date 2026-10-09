"""Saved briefing reports, separate from transient HTTP/headline caches.

Collection is not delivery. Acknowledgements bind a session to an exact report.
Empty required sections stay unresolved; populated sections do not prove exhaustive
coverage. This store never fetches providers or edits daily Markdown.
"""

import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import time

MAX_ATTEMPTS = 3
RETRY_SECONDS = 3600


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def context_key(timezone, country, sources):
    effective = {"feeds": sources["feeds"],
                 "national": sources.get("countries", {}).get(country, []),
                  "domain_lean": sources.get("domain_lean", {})}
    if sources.get("ranking_policy", "legacy") != "legacy":
        effective["ranking_policy"] = sources["ranking_policy"]
    if sources.get("editorial_review"):
        effective["editorial_review"] = True
    return hashlib.sha256(encode([timezone, country, effective]).encode()).hexdigest()


def validate_payload(payload, day):
    if (not isinstance(day, str) or not isinstance(payload, dict) or payload.get("date") != day
            or not isinstance(payload.get("counts"), dict)
            or set(payload["counts"]) != {"ai", "major", "national"}
            or not all(type(n) is int and n >= 0 for n in payload["counts"].values())
            or not isinstance(payload.get("stories"), list)
            or not all(isinstance(s, dict) and s.get("date") == day
                       and s.get("section") in payload["counts"] for s in payload["stories"])
            or not isinstance(payload.get("notes"), list)):
        raise ValueError("invalid saved news report; preserve the database and inspect it")
    if dt.date.fromisoformat(day).isoformat() != day:
        raise ValueError("saved report date must be YYYY-MM-DD")
    actual = {section: sum(s["section"] == section for s in payload["stories"])
              for section in payload["counts"]}
    if actual != payload["counts"]:
        raise ValueError("saved news counts disagree with stories; preserve the database and inspect it")


class ReportStore:
    def __init__(self, directory, create=False):
        path = Path(directory) / "news_reports.sqlite"
        if create:
            self.db = sqlite3.connect(path, timeout=5)
        else:
            # A status/read command must not initialize personal data.
            self.db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        self.db.row_factory = sqlite3.Row
        try:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version not in (0, 1) or (version == 0 and tables) or (version == 1 and "reports" not in tables):
                raise ValueError("unsupported news report database; preserve it and check the version")
            if create:
                self.db.execute("PRAGMA journal_mode=WAL")
                self.db.executescript("""
                    CREATE TABLE IF NOT EXISTS reports (
                        context TEXT NOT NULL, day TEXT NOT NULL, report_id TEXT NOT NULL,
                        payload TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL,
                        retry_after REAL NOT NULL, delivered_session TEXT, collected_at REAL NOT NULL,
                        PRIMARY KEY (context, day));
                    PRAGMA user_version=1;
                """)
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def get(self, context, day):
        row = self.db.execute("SELECT * FROM reports WHERE context=? AND day=?", (context, day)).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["payload"] = json.loads(value["payload"])
        payload = value["payload"]
        validate_payload(payload, day)
        if (value["status"] not in ("missing", "partial", "collected", "delivered")
                or hashlib.sha256(encode(payload).encode()).hexdigest() != value["report_id"]):
            raise ValueError("invalid saved news report; preserve the database and inspect it")
        counts = payload["counts"].values()
        collected = all(counts)
        expected = "collected" if collected else "partial" if any(counts) else "missing"
        if (value["status"] != expected and not (value["status"] == "delivered" and collected)
                or (value["status"] == "delivered" and not value["delivered_session"])):
            raise ValueError("saved report status disagrees with coverage; preserve the database and inspect it")
        return value

    def plan(self, context, days, now=None, refresh=False):
        now = time.time() if now is None else now
        rows = []
        for day in days:
            row = self.get(context, day)
            status = row["status"] if row else "missing"
            retry = (row is None or (status in ("missing", "partial") and
                     row["attempts"] < MAX_ATTEMPTS and row["retry_after"] <= now))
            entry = {"date": day, "status": status, "fetch": refresh or retry}
            if row:
                entry.update(report_id=row["report_id"], counts=row["payload"]["counts"])
                if status in ("missing", "partial"):
                    entry.update(attempts=row["attempts"], retry_after=row["retry_after"],
                                 exhausted=row["attempts"] >= MAX_ATTEMPTS)
                if row["delivered_session"]:
                    entry["session"] = row["delivered_session"]
                if row["payload"].get("curation", {}).get("state") == "pending":
                    entry["editorial_review_pending"] = True
            rows.append(entry)
        return rows

    def older_backlog(self, context, before):
        counts = {row["status"]: row["count"] for row in self.db.execute(
            "SELECT status, COUNT(*) AS count FROM reports WHERE context=? AND day<? AND status!='delivered' GROUP BY status",
            (context, before))}
        if not counts:
            return {}
        ending = self.db.execute("SELECT MAX(day) FROM reports WHERE context=? AND day<? AND status!='delivered'",
                                 (context, before)).fetchone()[0]
        return {"counts": counts, "ending": ending}

    def save(self, context, payload, now=None, offline=False, refresh=False, expect=None):
        now = time.time() if now is None else now
        validate_payload(payload, payload.get("date") if isinstance(payload, dict) else None)
        text = encode(payload)
        report_id = hashlib.sha256(text.encode()).hexdigest()
        counts = payload["counts"]
        status = ("collected" if all(counts.values()) else
                  "partial" if any(counts.values()) else "missing")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.get(context, payload["date"])
            if expect is not None and (old is None or old["report_id"] != expect):
                raise ValueError("report_conflict: reread before applying editorial selection")
            # An acknowledgement made during a fetch must not be silently undone.
            if old and old["status"] == "delivered" and not refresh:
                return old
            attempts = (old["attempts"] if old else 0) + (0 if offline else 1)
            session = None
            if old and old["report_id"] == report_id and old["delivered_session"]:
                status, session = "delivered", old["delivered_session"]
            self.db.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?,?,?,?,?,?,?)",
                            (context, payload["date"], report_id, text, status, attempts,
                             now + RETRY_SECONDS, session, now))
        return self.get(context, payload["date"])

    def acknowledge(self, context, day, expected, session):
        if not session or not all(c.isalnum() or c in "_.:/-" for c in session):
            raise ValueError("session must be a nonempty session identifier")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.get(context, day)
            if row is None:
                raise ValueError("report_missing: collect and read the report first")
            if row["report_id"] != expected:
                raise ValueError("report_conflict: read the current report before acknowledging")
            if row["status"] not in ("collected", "delivered"):
                raise ValueError("report_unresolved: required sections are empty; do not mark delivered")
            if row["payload"].get("curation", {}).get("state") == "pending":
                raise ValueError("report_editorial_review_required: review and select candidates before delivery")
            if row["status"] != "delivered":
                self.db.execute("UPDATE reports SET status='delivered', delivered_session=? WHERE context=? AND day=?",
                                (session, context, day))
        return self.get(context, day)


def recent_days(today, window=7):
    # Newest first: an old gap cannot displace yesterday's report.
    return [(today - dt.timedelta(days=i)).isoformat() for i in range(1, window + 1)]
