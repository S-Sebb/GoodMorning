"""Known boilerplate is blocked; actionable warnings, attribution and dates survive."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from support import TEMP_ROOT
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from goodmorning.reply_policy import boilerplate_categories
from goodmorning.records.state import cmd_mark
from benchmarks.reply_templates import fixtures, render


class ReplyPolicyTests(unittest.TestCase):
    def test_reported_examples_are_noncritical_boilerplate(self):
        texts = [
            "UK reports for 6–7 October are also available if you want them later.",
            "Older coverage gaps remain unresolved; I have not started a retry loop.",
            "This is model data, not a local station measurement. Weather retrieval returned no warnings.",
            "These are publisher-feed headlines, not independently verified claims.",
            "There are **no pending ideas or calendar reviews**.",
        ]
        for text in texts:
            with self.subTest(text=text):
                self.assertTrue(boilerplate_categories(text))

    def test_material_warnings_and_normal_content_are_not_stripped_or_blocked(self):
        text = ("Good morning. Rain, 12–18°C; take an umbrella. AQI 27, good (CAMS). "
                "Weather STALE: last updated at 07:00; refresh failed. "
                "China news is unavailable. Your meetings overlap 11:00–12:00. "
                "The reply could not be saved. OpenAI reports a new model; benchmark claims need checking. "
                 "Discussion surfaced today; article publication date is unknown. "
                 "Good morning, you. That blocker is real; let's make the next step more manageable.")
        self.assertEqual(boilerplate_categories(text), [])

    def test_synthetic_brief_has_no_boilerplate_and_keeps_actionable_content(self):
        _, morning, night = fixtures()
        for kind, values in (("gm", morning), ("gn", night)):
            self.assertEqual(boilerplate_categories(render(kind, values)), [])
        gm = render("gm", morning)
        for detail in ("AQI 27", "STALE", "refresh failed", "coverage is incomplete", "bring slides"):
            self.assertIn(detail, gm)

    def test_bad_brief_is_rejected_before_snapshot_or_run_is_written(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            draft = Path(directory) / "draft.json"
            draft.write_text(json.dumps({'v': 1, 'greeting': 'Good morning.', 'opening': 'Weather retrieval returned no warnings.', 'sections': [['notes', [['p', 'Saved detail.']]]]}))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cmd_mark(directory, "2026-10-09", "gm", "ses-style-test", str(draft), False, False, True)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["error"], "answer_noncritical_boilerplate")
            self.assertFalse((Path(directory) / "daily/2026-10-09.gm.json").exists())
            self.assertFalse((Path(directory) / "daily/2026-10-09.md").exists())


if __name__ == "__main__":
    unittest.main()
