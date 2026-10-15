"""Task wording: revised titles at capture plus a gm polish pass on synthetic runtimes."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from goodmorning.records.inbox_store import InboxStore, initialize
from goodmorning.records.task_store import TaskStore, default_title
from goodmorning.records import routing

DAY = "2026-10-13"
NOW = DAY + "T12:00:00+01:00"


class DefaultTitleTests(unittest.TestCase):
    def test_fallback_strips_trailing_period_and_capitalizes(self):
        self.assertEqual(default_title("Write convincing paper."), "Write convincing paper")
        self.assertEqual(default_title("review together with agent a plan"),
                         "Review together with agent a plan")
        self.assertEqual(default_title("  Fix   spacing.  "), "Fix spacing")


class CaptureWordingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        with patch.dict(os.environ, {}, clear=True):
            (self.root / "profile.md").write_text(
                "city: London, GB\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n")
            initialize(self.root)
            self.inbox = InboxStore(self.root, write=True)
        self.addCleanup(self.inbox.close)
        self.tasks = TaskStore(self.inbox)

    def capture(self, raw, key, **fields):
        return self.inbox.mutate("add", {"kind": "todo", "raw": raw, **fields}, "ses_test", key, NOW)

    def test_revised_summary_and_task_title_are_saved_raw_stays_verbatim(self):
        raw = "Currently there's a weird stretch of the message box on the secretary page sometimes preventing user message input, fix that."
        receipt = self.capture(
            raw, "polish-1",
            summary="Fix secretary page message-box stretch blocking input",
            task={"title": "Fix secretary page message-box stretch blocking input",
                  "detail": "Message box sometimes stretches and blocks typing; keep open until Alex confirms after deployment."},
        )
        task = self.tasks.show(receipt["task_id"])
        self.assertEqual(task["title"], "Fix secretary page message-box stretch blocking input")
        self.assertIn("blocks typing", task["detail"])
        self.assertNotIn("blocks typing", self.inbox.text(receipt["id"])["text"])
        self.assertEqual(self.inbox.text(receipt["id"])["text"], raw)

    def test_polish_updates_canonical_copy_then_briefing_packs_exact_rows(self):
        for edition in ("gm", "gn"):
            receipt = self.capture("Write convincing paper.", f"{edition}-polish-1", project="MRHarmon",
                                   task={"planned_date": DAY, "detail": "Setup choice confirmed."})
            task = self.tasks.show(receipt["task_id"])
            self.assertEqual(task["title"], "Write convincing paper")
            # Secretary walkthrough before packing: same meaning, clearer wording.
            # No project prefix: the project lives in its structured field.
            polished = self.tasks.mutate(
                receipt["task_id"], task["revision"],
                {"title": "Draft convincing-paper outline",
                 "detail": "Persuasive framing is still missing; draft the outline as the next step."},
                "ses_test", f"polish:ses_test:{receipt['task_id']}:{task['revision']}", NOW)
            self.assertTrue(polished["saved"])
            updated = self.tasks.show(receipt["task_id"])
            view = routing.prepare(self.root, DAY, edition)
            row = next(r for r in view["tasks"]["items"] if r["id"] == receipt["task_id"])
            self.assertEqual((row["title"], row["detail"]), (updated["title"], updated["detail"]))
            doc = {"v": 2, "greeting": "Hello.", "opening": "Synthetic.",
                   "sections": [["tasks", [view["blocks"]["tasks"]]]]}
            routing.validate_sources(self.root, doc, DAY, edition)
            # A stale pre-polish copy fails validation, proving pack-after-polish matters.
            stale = {"v": 2, "greeting": "Hello.", "opening": "Synthetic.",
                     "sections": [["tasks", [["actions", [[row["id"], row["revision"], row["occurrence_id"],
                                                            row["date"], row["status"],
                                                            "Write convincing paper", row["detail"]]]]]]]}
            with self.assertRaisesRegex(ValueError, "source_conflict"):
                routing.validate_sources(self.root, stale, DAY, edition)


if __name__ == "__main__":
    unittest.main()
