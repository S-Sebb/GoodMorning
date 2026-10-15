"""Custom schedules: ask until unambiguous, save once, decide from code-owned rows."""
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from goodmorning.records.custom_store import CustomStore


def mkruntime():
    tmp = Path(tempfile.mkdtemp(prefix="sp-"))
    (tmp / "profile.md").write_text(
        'secretary_language: "English"\ncity: "London, GB"\nregion: "global"\n'
        'timezone: "Europe/London"\nwork_days: "Mon-Fri"\nwork_hours: "9:00-18:00"\n'
        'sleep_time: "23:30"\nsecretary_tone: "warm"\noccupations: "tester"\n'
        'expertise_fields: "testing"\nindustry: "testing"\nproject_scope: ""\n'
        'knowledge_area: ""\nnews_preference: "yesterday digest only"\nnews_country: "GB"\n'
        'news_additional_countries: ""\nnews_latest: "false"\nnews_sources_path: ""\n'
        'calendar_source: ""\n', encoding="utf-8")
    return tmp


def gym_policy(**over):
    base = {"base": "interval_days", "interval_days": 2, "start": "2026-10-13",
            "anchor": "last_completion", "miss_policy": "chase",
            "weekly_cap": 3, "nightly": "always"}
    base.update(over)
    return base


class CustomTests(unittest.TestCase):
    def setUp(self):
        self.root = mkruntime()

    def add(self, policy=None, key="k1", title="Go gym"):
        store = CustomStore(self.root, write=True)
        try:
            return store.add({"title": title, "detail": "stay fit",
                              "timezone": "Europe/London",
                              "policy": policy or gym_policy()},
                             "ses_test", key, "2026-10-13T10:00:00+01:00")
        finally:
            store.close()

    def test_ambiguous_policy_writes_nothing(self):
        store = CustomStore(self.root, write=True)
        try:
            with self.assertRaisesRegex(ValueError, "unambiguous|invalid_input"):
                store.add({"title": "Gym regularly", "timezone": "Europe/London",
                           "policy": {"base": "interval_days", "start": "2026-10-13"}},
                          "ses_test", "amb1", "2026-10-13T10:00:00+01:00")
            self.assertEqual(list(store.all()), [])
        finally:
            store.close()

    def test_other_account_cannot_create_or_write_schedule_database(self):
        other_uid = self.root.stat().st_uid + 1
        with patch('goodmorning.records.custom_store.os.geteuid', return_value=other_uid):
            with self.assertRaisesRegex(ValueError, 'runtime owner'):
                CustomStore(self.root, write=True)
        self.assertFalse((self.root/'custom.sqlite').exists())
        self.add()
        before = (self.root/'custom.sqlite').read_bytes()
        with patch('goodmorning.records.custom_store.os.geteuid', return_value=other_uid):
            with self.assertRaisesRegex(ValueError, 'runtime owner'):
                CustomStore(self.root, write=True)
        self.assertEqual((self.root/'custom.sqlite').read_bytes(), before)

    def test_read_connection_cannot_mutate_schedule_database(self):
        import sqlite3
        self.add()
        before = (self.root/'custom.sqlite').read_bytes()
        store = CustomStore(self.root)
        try:
            with self.assertRaisesRegex(sqlite3.OperationalError, 'readonly'):
                store.db.execute('DELETE FROM custom_rules')
        finally:
            store.close()
        self.assertEqual((self.root/'custom.sqlite').read_bytes(), before)

    def test_add_show_replay(self):
        receipt = self.add()
        store = CustomStore(self.root, write=False)
        try:
            shown = store.show(receipt["id"])
            self.assertEqual(shown["revision"], 1)
            self.assertEqual(shown["policy"]["interval_days"], 2)
        finally:
            store.close()
        store = CustomStore(self.root, write=True)
        try:
            replay = store.add({"title": "Go gym", "detail": "stay fit",
                                "timezone": "Europe/London", "policy": gym_policy()},
                               "ses_test", "k1", "2026-10-13T10:00:00+01:00")
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["id"], receipt["id"])
        finally:
            store.close()

    def test_due_chase_and_reanchor(self):
        receipt = self.add()
        rule_id = receipt["id"]
        store = CustomStore(self.root, write=False)
        try:
            rule = store.show(rule_id)
            self.assertTrue(store.due(rule, "2026-10-13")["due"])
            missed = store.due(rule, "2026-10-14")
            self.assertTrue(missed["due"])
            self.assertEqual(missed["reason"], "chasing_missed")
            # Complete on 13th -> next is 15th.
            store2 = CustomStore(self.root, write=True)
            try:
                store2.report(rule_id, 1, {"status": "done", "confirmed_completion": True},
                              "ses_test", "done13", "2026-10-13T20:00:00+01:00", "2026-10-13")
            finally:
                store2.close()
            rule = store.show(rule_id)
            self.assertEqual(store.due(rule, "2026-10-14")["reason"], "waiting_gap")
            self.assertTrue(store.due(rule, "2026-10-15")["due"])
        finally:
            store.close()

    def test_weekly_cap_stops(self):
        policy = gym_policy(anchor="fixed", miss_policy="fixed", weekly_cap=2)
        receipt = self.add(policy=policy, key="cap1")
        rule_id = receipt["id"]
        store = CustomStore(self.root, write=True)
        try:
            # Mon 2026-10-12 and Tue 2026-10-13 are same Mon-Sun week.
            store.report(rule_id, 1, {"status": "done", "confirmed_completion": True},
                         "ses_test", "c1", "2026-10-12T20:00:00+01:00", "2026-10-12")
            shown = store.show(rule_id)
            store.report(rule_id, shown["revision"], {"status": "done", "confirmed_completion": True},
                         "ses_test", "c2", "2026-10-13T20:00:00+01:00", "2026-10-13")
        finally:
            store.close()
        store = CustomStore(self.root, write=False)
        try:
            rule = store.show(rule_id)
            decision = store.due(rule, "2026-10-14")
            self.assertFalse(decision["due"])
            self.assertEqual(decision["reason"], "weekly_cap_reached")
            self.assertEqual(decision["weekly_count"], 2)
        finally:
            store.close()

    def test_future_completion_refused_and_briefing_rows(self):
        receipt = self.add(key="fut1")
        store = CustomStore(self.root, write=True)
        try:
            with self.assertRaisesRegex(ValueError, "future"):
                store.report(receipt["id"], 1, {"status": "done", "confirmed_completion": True},
                             "ses_test", "fut", "2026-10-13T10:00:00+01:00", "2026-10-14")
        finally:
            store.close()
        store = CustomStore(self.root, write=False)
        try:
            gm = store.briefing("2026-10-13", "gm")
            self.assertTrue(any(r["due"] for r in gm))
            gn = store.briefing("2026-10-14", "gn")
            # nightly always includes off-day for evening check
            self.assertTrue(len(gn) >= 1)
        finally:
            store.close()

    def test_workflow_prepare_includes_custom(self):
        self.add(key="wf1")
        from goodmorning.records.workflow import prepare
        result = prepare(str(self.root), "secretary")
        self.assertIn("custom", result)
        self.assertGreaterEqual(result["custom"]["total"], 1)

    def test_custom_receipts_highlight_as_custom_schedule(self):
        from goodmorning.web.chat_actions import read_changes
        receipt = self.add(key="hl1", title="Go gym")
        store = CustomStore(self.root, write=True)
        try:
            store.update(receipt["id"], 1, {"detail": "mornings"},
                         "ses_test", "hl-edit", "2026-10-13T11:00:00+01:00")
            shown = store.show(receipt["id"])
            store.report(receipt["id"], shown["revision"],
                         {"status": "done", "confirmed_completion": True},
                         "ses_test", "hl-done", "2026-10-13T20:00:00+01:00", "2026-10-13")
        finally:
            store.close()
        changes, unavailable = read_changes(self.root, "ses_test")
        customs = [c for c in changes if c["action"]["target"] == "custom"]
        self.assertFalse(unavailable)
        self.assertEqual([c["action"]["operation"] for c in customs],
                         ["added", "updated", "completed"])
        self.assertTrue(all(c["text"] == "Go gym" for c in customs))
        self.assertTrue(all(set(c) == {"id", "role", "kind", "text", "action", "at"} for c in customs))


class CustomPreflightTests(unittest.TestCase):
    """Focused evening check: custom due rows are checkable and complete once."""

    def setUp(self):
        import tempfile
        from datetime import datetime, timezone
        from threading import Thread
        from unittest.mock import patch
        from support import TEMP_ROOT
        sys.path.insert(0, str(REPO / "src"))
        from goodmorning.web.briefing_server import BrowserApp
        from support import FakeChamber
        from goodmorning.records.inbox_store import initialize as inbox_init
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        workers = []
        def worker(*args, **kwargs):
            thread = Thread(*args, **kwargs)
            workers.append(thread)
            return thread
        patcher = patch("goodmorning.web.briefing_server.threading.Thread", side_effect=worker)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = Path(self.temp.name)
        (self.root / "profile.md").write_text(
            "city: London, GB\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n")
        (self.root / "daily").mkdir()
        inbox_init(str(self.root))
        store = CustomStore(self.root, write=True)
        try:
            receipt = store.add({"title": "Go gym", "detail": "stay fit",
                                 "timezone": "Europe/London", "policy": gym_policy()},
                                "ses_test", "pre1", "2026-10-13T10:00:00+01:00")
            self.rule_id = receipt["id"]
        finally:
            store.close()
        self.chamber = FakeChamber()
        self.app = BrowserApp(self.root, self.chamber,
                              now=lambda: datetime(2026, 10, 13, 12, tzinfo=timezone.utc),
                              preflight=True)
        self.job = {"id": "b" * 32, "date": "2026-10-13", "kind": "gn",
                    "session": "ses_test", "state": "running", "workflow": 2}
        self.app.jobs["2026-10-13.gn"] = self.job
        self.app.save_jobs()

    def test_custom_appears_in_evening_check_and_completes_once(self):
        from goodmorning.briefings.briefing_preflight import initialize, answer
        context = initialize(self.root, self.job)
        choices = [t for t in context.get("feedback_tasks", []) if t.get("custom")]
        self.assertEqual(len(choices), 1)
        self.assertIn(choices[0]["id"], [o["value"] for o in context["form"]["fields"][0]["options"]])
        result = answer(self.root, self.job,
                        {"completed": [choices[0]["id"]], "details": "No other updates"})
        self.assertTrue(result["feedback"]["saved"])
        self.assertIn("Go gym", result["feedback"]["completed"])
        store = CustomStore(self.root, write=False)
        try:
            rule = store.show(self.rule_id)
            decision = store.due(rule, "2026-10-14")
            self.assertEqual(decision["reason"], "waiting_gap")
            self.assertEqual(decision["weekly_count"], 1)
        finally:
            store.close()
        # Same input replays instead of double-recording.
        again = answer(self.root, self.job,
                       {"completed": [choices[0]["id"]], "details": "No other updates"})
        self.assertTrue(again["feedback"]["saved"])


if __name__ == "__main__":
    unittest.main()
