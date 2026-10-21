"""Focused calendar pipeline tests; all data is synthetic."""

import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from support import TEMP_ROOT
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from goodmorning.calendar.calendar_store import CalendarStore, normalize, read_stats
from goodmorning.calendar.secretary_calendar import custom_event, main
from goodmorning.records.state import rebuild_index, blank_state


def event(**changes):
    return {"subject": "Group meeting", "start": "2026-10-10T09:00:00+01:00",
            "end": "2026-10-10T10:00:00+01:00", "location": "Room 301", **changes}


START = datetime(2026, 10, 10, tzinfo=timezone.utc)
END = datetime(2026, 10, 11, tzinfo=timezone.utc)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.path = str(Path(self.tmp.name) / "calendar.sqlite")
        self.env = patch.dict(os.environ, {"CALENDAR_DB_PATH": self.path})
        self.env.start()
        self.store = CalendarStore(self.path)

    def tearDown(self):
        self.store.close()
        self.env.stop()
        self.tmp.cleanup()

    def imported(self, **changes):
        self.store.import_events("work", [{"external_id": "meeting-1", **event(**changes)}])
        return self.store.con.execute("SELECT id FROM events WHERE external_id='meeting-1'").fetchone()[0]

    def test_custom_dedup_and_positional_notes(self):
        parsed = custom_event("2026-10-10 09:00-10:00 | Meeting | | Bring card", timezone.utc)
        self.assertNotIn("location", parsed)
        self.assertEqual(parsed["notes"], "Bring card")
        first = self.store.add(parsed)
        self.assertEqual(first, self.store.add(parsed))
        self.assertEqual(len(self.store.history(first)), 1)

    def test_credentials_are_redacted_before_any_import_history_is_saved(self):
        secret = "fictional-meeting-secret"
        data = event(notes="Bring slides.\nPasscode: " + secret + "\nhttps://teams.microsoft.com/meet/123?p=" + secret)
        self.store.import_events("work", [{"external_id": "meeting", **data}])
        dump = "\n".join(self.store.con.iterdump())
        self.assertFalse(secret in dump, "meeting credentials reached the calendar database")
        raw = self.store.query(START, END, details=True)[0]
        self.assertIn("Bring slides", raw["notes"])

    def test_redaction_is_idempotent_and_keeps_adjacent_preparation_and_public_links(self):
        from goodmorning.calendar.calendar_safety import safe_text
        text = 'Join with Passcode: "fictional secret". Bring slides. https://example.org/registration?p=2'
        redacted = safe_text(text)
        self.assertFalse("fictional secret" in redacted)
        self.assertIn("Bring slides", redacted)
        self.assertIn("https://example.org/registration?p=2", redacted)
        self.assertEqual(safe_text(redacted), redacted)

    def test_teams_boilerplate_is_not_briefing_preparation(self):
        from goodmorning.calendar.calendar_safety import clean_preparation
        boilerplate = (
            "______________________________________________________________________\n"
            "Microsoft Teams meeting Join: [protected link omitted; use original invitation] "
            "Meeting ID: 385 888 978 982 162 Passcode: [omitted; use original invitation]\n"
            "______________________________________________________________________\n"
            "Need help?https://aka.ms/JoinTeamsMeeting?omkt=en-GB> | "
            "System reference:<[protected link omitted; use original invitation]> "
            "For organisers: Meeting options<https://teams.microsoft.com/meetingOptions/?organizerId=abc>\n"
            "[Company Logo] Privacy and security<https://www.imperial.ac.uk/media/x.pdf>\n"
            "______________________________________________________________________"
        )
        self.assertEqual(clean_preparation(boilerplate), "")
        self.assertEqual(clean_preparation(clean_preparation(boilerplate)), "")
        mixed = ("Bring slides.\nMicrosoft Teams meeting Join: "
                 "https://teams.microsoft.com/l/meetup-join/abc\nMeeting ID: 123")
        self.assertEqual(clean_preparation(mixed), "Bring slides.")
        public = "Bring slides. https://example.org/registration?p=2"
        self.assertEqual(clean_preparation(public), public)

    def test_schedule_query_filters_boilerplate_but_show_keeps_original(self):
        notes = ("Bring slides.\nMicrosoft Teams meeting Join: "
                 "https://teams.microsoft.com/l/meetup-join/abc\nMeeting ID: 123")
        eid = self.imported(notes=notes)
        rows = self.store.query(START, END, details=True)
        self.assertEqual(rows[0]["notes"], "Bring slides.")
        shown = self.store.get(eid)
        self.assertIn("Microsoft Teams meeting Join", shown["approved"]["notes"])
        # Pure boilerplate yields no preparation notes in schedule reads.
        self.store.change(eid, "update", shown["revision"],
                          {"notes": "Microsoft Teams meeting Join: https://teams.microsoft.com/l/meetup-join/abc"})
        rows = self.store.query(START, END, details=True)
        self.assertNotIn("notes", rows[0])

    def test_legacy_record_output_is_redacted_without_rewriting_database(self):
        secret = "fictional-legacy-secret"
        eid = self.store.add(event())
        legacy = event(notes="Passcode: " + secret)
        self.store.con.execute("UPDATE events SET approved_json=? WHERE id=?", (json.dumps(legacy), eid))
        self.store.con.commit()
        from goodmorning.calendar.calendar_store import encode
        self.assertFalse(secret in encode(self.store.get(eid)))
        self.assertTrue(secret in self.store.con.execute("SELECT approved_json FROM events WHERE id=?", (eid,)).fetchone()[0])

    def test_imports_apply_directly_and_source_changes_keep_notice_and_wording(self):
        from goodmorning.records.display import wording
        eid = self.imported(notes="Lengthy provider description")
        self.assertEqual(self.store.query(START, END)[0]["subject"], "Group meeting")
        words = {lang: {"morning": {"title": title, "detail": ""}, "schedule": title}
                 for lang, title in (("en", "Team sync"), ("zh", "团队例会"))}
        current = self.store.change(eid, "update", 1, {"notice": {"morning": 2}, "display": words})
        self.assertEqual(self.store.import_events("work", [{"external_id": "meeting-1", **event(notes="Lengthy provider description")}])["unchanged"], 1)
        self.store.import_events("work", [{"external_id": "meeting-1", **event(start="2026-10-10T11:00:00+01:00", end="2026-10-10T12:00:00+01:00", notes="Lengthy provider description")}])
        moved = self.store.get(eid)["approved"]
        self.assertEqual((moved["start"], moved["notice"]), ("2026-10-10T10:00:00+00:00", {"morning": 2}))
        self.assertEqual(wording(moved, "event", "morning", "en")["title"], "Team sync")  # Only the time moved.
        self.store.import_events("work", [{"external_id": "meeting-1", **event(subject="Renamed by organizer")}])
        renamed = self.store.get(eid)
        self.assertIsNone(wording(renamed["approved"], "event", "morning", "en"))
        self.assertEqual(renamed["revision"], current["revision"] + 2)
        self.assertEqual(len(self.store.history(eid)), 4)

    def test_source_cancellation_applies(self):
        eid = self.imported()
        self.store.import_events("work", [{"external_id": "meeting-1", "status": "cancelled"}])
        self.assertEqual(self.store.query(START, END), [])
        self.assertEqual(self.store.get(eid)["approved"]["status"], "cancelled")

    def test_pending_reviews_from_older_versions_apply_once(self):
        eid = self.imported()
        self.store.con.execute("UPDATE events SET review='pending',approved_json=NULL,starts=NULL,ends=NULL WHERE id=?", (eid,))
        self.store.con.commit()
        self.assertEqual(self.store.query(START, END), [])
        self.assertEqual(self.store.apply_pending("calendar-feed"), 1)
        self.assertEqual(self.store.query(START, END)[0]["subject"], "Group meeting")
        self.assertEqual(self.store.apply_pending("calendar-feed"), 0)

    def test_changes_cover_imports_since_the_previous_edition(self):
        moved = self.imported()
        self.store.import_events("work", [{"external_id": "gone", **event(subject="Lunch")}])
        self.store.mark("2026-10-09.gn")
        self.store.import_events("work", [{"external_id": "meeting-1", **event(start="2026-10-10T11:00:00+01:00", end="2026-10-10T12:00:00+01:00")},
                                          {"external_id": "gone", "status": "cancelled"},
                                          {"external_id": "new", **event(subject="Review")}])
        self.store.change(moved, "update", self.store.get(moved)["revision"], {"location": "Room 9"})  # Secretary edits are not reported.
        self.store.mark("2026-10-10.gm")
        changes = {c["after"]["subject"]: c for c in self.store.changes("2026-10-10.gm")}
        self.assertEqual(set(changes), {"Group meeting", "Lunch", "Review"})
        self.assertEqual(changes["Group meeting"]["before"]["start"], "2026-10-10T08:00:00+00:00")
        self.assertEqual(changes["Group meeting"]["after"]["location"], "Room 9")
        self.assertIsNone(changes["Review"]["before"])
        self.assertEqual(changes["Lunch"]["after"]["status"], "cancelled")
        self.assertEqual(len(self.store.changes("2026-10-09.gn")), 3)  # The first edition reports from its own start; its window stays open.
        self.store.mark("2026-10-10.gn")
        self.assertEqual(self.store.changes("2026-10-10.gn"), [])
        self.assertEqual(self.store.changes("2026-10-11.gm"), [])  # Unmarked editions report nothing.

    def test_update_cancel_and_history(self):
        eid = self.store.add(event())
        revised = self.store.change(eid, "update", 1, {"subject": "New title"}, "test-session")
        self.assertEqual(revised["revision"], 2)
        self.store.change(eid, "cancel", 2)
        self.assertEqual(self.store.query(START, END), [])
        self.assertEqual(self.store.history(eid)[1]["actor"], "test-session")
        self.assertEqual(self.store.history(eid)[-1]["snapshot"]["approved"]["subject"], "Group meeting")
        with self.assertRaisesRegex(ValueError, "edited or cancelled"):
            self.store.add(event())

    def test_import_batches_are_atomic(self):
        with self.assertRaises(ValueError):
            self.store.import_events("work", [{"external_id": "valid", **event()},
                                              {"external_id": "bad", **event(end="bad")}])
        self.assertEqual(self.store.stats()["total"], 0)
        with self.assertRaises(ValueError):
            self.store.import_events("work", [{"external_id": "same", **event()},
                                              {"external_id": "same", **event()}])
        self.assertEqual(self.store.stats()["total"], 0)

    def test_identity_not_title_dedup(self):
        self.store.import_events("work", [{"external_id": "same", "occurrence_id": "1", **event()},
                                          {"external_id": "same", "occurrence_id": "2", **event()}])
        self.store.import_events("personal", [{"external_id": "same", **event()}])
        self.assertEqual(len(self.store.query(START, END)), 3)
        self.assertEqual(len(self.store.query(START, END, source="work")), 2)
        self.assertEqual(self.store.import_events("work", [])["changed"], 0)
        self.assertEqual(len(self.store.query(START, END)), 3)

    def test_overlap_and_exclusive_midnight(self):
        self.store.add(event(start="2026-10-09T23:00:00Z", end="2026-10-10T00:00:00Z"))
        self.store.add(event(start="2026-10-09T23:00:00Z", end="2026-10-10T01:00:00Z"))
        self.store.add(event(start="2026-10-11T00:00:00Z", end="2026-10-11T01:00:00Z"))
        self.assertEqual(len(self.store.query(START, END)), 1)

    def test_all_day_dst_and_overnight(self):
        eid = self.store.add(event(all_day=True, timezone="Europe/London",
                                  start="2026-10-25", end="2026-10-26"))
        row = self.store.get(eid)
        self.assertEqual(row["ends"] - row["starts"], 25 * 3600)
        self.store.add(event(start="2026-10-10T23:30:00Z", end="2026-10-11T01:00:00Z"))
        self.assertEqual(len(self.store.query(START, END)), 1)

    def test_invalid_dates_and_unknown_fields(self):
        for data in (event(start="2026-10-10T09:00:00"), event(end="2026-10-10T07:00:00Z"),
                     event(subject=""), event(recurrence="FREQ=DAILY"), event(all_day="yes"),
                     {"subject": "Missing times"}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                normalize(data)

    def test_ambiguous_shorthand_requires_offsets(self):
        tz = ZoneInfo("Europe/London")
        for text in ("2026-10-25 01:30-02:30 | Meeting", "2026-03-29 01:30-02:30 | Meeting"):
            with self.assertRaisesRegex(ValueError, "local time"):
                custom_event(text, tz)

    def test_compact_output_pagination_and_details(self):
        for i in range(3):
            self.store.add(event(subject=f"Meeting {i}", notes="x" * 5000))
        rows = self.store.query(START, END, limit=2)
        self.assertEqual(len(rows), 2)
        self.assertNotIn("notes", rows[0])
        self.assertEqual(len(self.store.query(START, END, offset=2)), 1)
        self.assertEqual(len(self.store.query(START, END, details=True)[0]["notes"]), 5000)

    def test_stale_writes_across_connections(self):
        eid = self.store.add(event())
        other = CalendarStore(self.path)
        try:
            self.store.change(eid, "update", 1, {"location": "New room"})
            with self.assertRaisesRegex(ValueError, "changed"):
                other.change(eid, "cancel", 1)
        finally:
            other.close()

    def test_concurrent_adds_are_idempotent(self):
        def add_once(_):
            store = CalendarStore(self.path)
            try:
                return store.add(event())
            finally:
                store.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(add_once, range(8)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(self.store.stats()["total"], 1)
        self.assertEqual(len(self.store.history(ids[0])), 1)

    def test_failed_history_write_rolls_back_event(self):
        self.store.con.execute("CREATE TRIGGER fail_history BEFORE INSERT ON history "
                               "BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.add(event())
        self.assertEqual(self.store.stats()["total"], 0)

    def test_future_schema_is_not_rewritten(self):
        other_path = Path(self.tmp.name) / "future.sqlite"
        con = sqlite3.connect(other_path)
        con.execute("PRAGMA user_version=2")
        con.close()
        with self.assertRaisesRegex(ValueError, "version 2"):
            CalendarStore(str(other_path))
        con = sqlite3.connect(other_path)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        con.close()

    def test_unrelated_database_is_not_modified(self):
        path = Path(self.tmp.name) / "unrelated.sqlite"
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE unrelated(value TEXT)")
        con.close()
        with self.assertRaisesRegex(ValueError, "not a secretary calendar"):
            CalendarStore(str(path))
        con = sqlite3.connect(path)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
                         [("unrelated",)])
        con.close()

    def test_readonly_never_creates_or_rewrites_storage(self):
        path = Path(self.tmp.name) / "missing" / "calendar.sqlite"
        with self.assertRaises(sqlite3.OperationalError):
            CalendarStore(str(path), readonly=True)
        self.assertFalse(path.parent.exists())
        store = CalendarStore(self.path, readonly=True)
        self.addCleanup(store.close)
        self.assertEqual(store.stats()["total"], 0)
        with self.assertRaises(sqlite3.OperationalError):
            store.con.execute("DELETE FROM events")

    def test_state_summary_reads_database_not_markdown(self):
        self.store.add(event())
        self.imported()
        summary = rebuild_index(self.tmp.name, blank_state())
        self.assertEqual(summary["calendar"]["custom"], 1)
        self.assertEqual(summary["calendar"]["imported"], 1)
        self.assertEqual(read_stats(str(Path(self.tmp.name) / "absent.sqlite"))["total"], 0)
        self.assertFalse((Path(self.tmp.name) / "absent.sqlite").exists())


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)

    def tearDown(self):
        self.tmp.cleanup()

    def run_command(self, *args, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            old = sys.stdin
            sys.stdin = io.StringIO(stdin)
            try:
                code = main(["--secretary-dir", self.tmp.name, "--db", str(Path(self.tmp.name) / "calendar.sqlite"),
                             "--timezone", "Europe/London", *args])
            finally:
                sys.stdin = old
        return code, out.getvalue(), err.getvalue()

    def test_conversational_import_edit_and_read(self):
        code, out, _ = self.run_command("--import-json", "-", stdin=json.dumps(
            {"source": "work", "events": [{"external_id": "abc", **event()}]}))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["new"], 1)
        _, out, _ = self.run_command("--from", "2026-10-10", "--json")
        imported = json.loads(out)[0]
        code, _, _ = self.run_command("--update", imported["id"], "--event-json", '{"subject":"Team sync"}')
        self.assertEqual(code, 2)
        code, _, _ = self.run_command("--update", imported["id"], "--expect-revision", "1",
                                     "--event-json", '{"subject":"Team sync"}')
        self.assertEqual(code, 0)
        _, out, _ = self.run_command("--from", "2026-10-10", "--json")
        self.assertEqual(json.loads(out)[0]["subject"], "Team sync")

    def test_invalid_flags_and_no_live_provider_fetch(self):
        for args in (("--days", "0"), ("--event-json", "{}"), ("--limit", "501"),
                     ("--offset", "-1"), ("--timezone", "Invalid/Zone"),
                     ("--add", "--event-json", "null")):
            self.assertEqual(self.run_command(*args)[0], 2)
        self.assertFalse((Path(self.tmp.name) / "calendar.sqlite").exists())
        self.assertEqual(self.run_command("--json")[0], 2)
        self.assertFalse((Path(self.tmp.name) / "calendar.sqlite").exists())
        self.assertEqual(self.run_command("--init")[0], 0)
        code, out, _ = self.run_command("--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [])


if __name__ == "__main__":
    unittest.main()
