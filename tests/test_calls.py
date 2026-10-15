"""Secretary calls: manual scan is read-only; writes need session, key and revisions."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from support import TEMP_ROOT

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goodmorning.records.calls_store import CallsStore, scan
from goodmorning.records.inbox_store import InboxStore, initialize
from goodmorning.records.task_store import TaskStore

NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc).isoformat()
SES = "ses_test_calls"


def make_account(root):
    (root / "profile.md").write_text(
        "city: London, GB\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n")
    initialize(root)


class ScanTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        with patch.dict(os.environ, {}, clear=True):
            make_account(self.root)

    def test_scan_is_read_only_and_finds_kinds(self):
        inbox = InboxStore(self.root, write=True)
        try:
            tasks = TaskStore(inbox)
            inbox.mutate("add", {"kind": "todo", "raw": "ping",
                                 "task": {"title": "Prepare Atlas summary",
                                          "detail": "Due 2026-10-20, see 2026-10-20 plan.",
                                          "planned_date": "2026-10-20"}}, SES, "k-word", NOW)
            inbox.mutate("add", {"kind": "todo", "raw": "remind early Nov",
                                 "task": {"title": "11月初提醒这件事"}}, SES, "k-amb", NOW)
            inbox.mutate("add", {"kind": "event_proposal", "raw": "Dentist?",
                                 "draft": {"title": "Dentist", "date": "2026-10-15",
                                           "timezone": "Europe/London", "confirmed_day": True}},
                         SES, "k-tbc", NOW)
        finally:
            inbox.close()
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        found = scan(self.root)
        kinds = {(c["kind"], c["target_type"]) for c in found}
        self.assertIn(("task_wording", "task"), kinds)
        self.assertIn(("ambiguous_schedule", "task"), kinds)
        self.assertIn(("tbc_time", "draft"), kinds)
        # Read-only: scan wrote nothing, not even the calls database.
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}, before)
        self.assertFalse((self.root / "calls.sqlite").exists())

    def test_scan_ignores_punctuation_only_and_cancelled(self):
        inbox = InboxStore(self.root, write=True)
        try:
            receipt = inbox.mutate("add", {"kind": "todo", "raw": "Fix blur.",
                                           "task": {"title": "Fix weak blur."}}, SES, "k-punct", NOW)
            tasks = TaskStore(inbox)
            task = tasks.show(receipt["task_id"])
            tasks.mutate(receipt["task_id"], task["revision"],
                         {"status": "cancelled"}, SES, "k-cancel", NOW)
            receipt2 = inbox.mutate("add", {"kind": "todo", "raw": "currently do things",
                                            "task": {"title": "Currently do vague things etc."}}, SES, "k-filler", NOW)
            filler_id = receipt2["task_id"]
        finally:
            inbox.close()
        found = scan(self.root)
        ids = {c["target_id"] for c in found}
        self.assertNotIn(receipt["task_id"], ids)
        self.assertIn(filler_id, ids)


class WriteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        with patch.dict(os.environ, {}, clear=True):
            make_account(self.root)
        inbox = InboxStore(self.root, write=True)
        try:
            receipt = inbox.mutate("add", {"kind": "todo", "raw": "ping",
                                           "task": {"title": "Prepare Atlas summary"}}, SES, "k-t", NOW)
            self.task_id = receipt["task_id"]
            task = TaskStore(inbox).show(self.task_id)
            self.task_rev = task["revision"]
        finally:
            inbox.close()
        self.store = CallsStore(self.root, write=True)
        self.addCleanup(self.store.close)

    def payload(self, **over):
        base = {"title": "Clarify wording", "reason": "project prefix repeats the field",
                "question": "How should this read?", "kind": "task_wording",
                "target_type": "task", "target_id": self.task_id, "target_revision": self.task_rev}
        base.update(over)
        return base

    def test_add_lists_resolve_replay(self):
        receipt = self.store.add(self.payload(), SES, "call-1", NOW)
        self.assertTrue(receipt["saved"])
        self.assertEqual(self.store.show(receipt["id"])["status"], "open")
        self.assertEqual(len(self.store.all("open")), 1)
        # Same key + input replays instead of duplicating.
        again = self.store.add(self.payload(), SES, "call-1", NOW)
        self.assertTrue(again.get("replayed"))
        self.assertEqual(len(self.store.all()), 1)
        resolved = self.store.resolve(receipt["id"], 1, {"note": "fixed title"}, SES, "call-resolve", NOW)
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(self.store.all("open"), [])

    def test_duplicate_open_call_refused_and_closed_reusable(self):
        first = self.store.add(self.payload(), SES, "call-a", NOW)
        with self.assertRaisesRegex(ValueError, "duplicate_call"):
            self.store.add(self.payload(), SES, "call-b", NOW)
        self.store.dismiss(first["id"], 1, {}, SES, "call-c", NOW)
        second = self.store.add(self.payload(), SES, "call-d", NOW)
        self.assertTrue(second["saved"])

    def test_revision_conflict_and_key_conflict(self):
        receipt = self.store.add(self.payload(), SES, "call-a", NOW)
        with self.assertRaisesRegex(ValueError, "write_conflict"):
            self.store.resolve(receipt["id"], 99, {}, SES, "call-b", NOW)
        with self.assertRaisesRegex(ValueError, "request_conflict"):
            self.store.resolve(receipt["id"], 1, {"note": "x"}, SES, "call-a", NOW)

    def test_symlink_runtime_refused(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as other:
            link = Path(other) / "link"
            link.symlink_to(self.root)
            with self.assertRaisesRegex(ValueError, "unsafe_path"):
                CallsStore(link)


if __name__ == "__main__":
    unittest.main()
