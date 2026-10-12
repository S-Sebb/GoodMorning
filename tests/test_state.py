"""State contracts, corruption recovery, bounded output, and cooperating writers."""

import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from support import TEMP_ROOT
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from goodmorning.records import state
from goodmorning.runtime_files import runtime_lock
from goodmorning.briefings.briefing_document import encode
from goodmorning.records.inbox_store import InboxStore, initialize

TODAY = "2026-10-09"
ANSWER = encode({'v': 1, 'greeting': 'Good morning.', 'opening': 'A clear start.', 'sections': [['notes', [['p', 'Keep this detail.']]]]})


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "daily").mkdir()
        self.env = patch.dict(os.environ, {"SECRETARY_DIR": str(self.root)}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = state.main(["--today", TODAY, *args])
        return code, out.getvalue(), err.getvalue()

    def daily(self, day, text):
        path = self.root / "daily" / f"{day}.md"
        path.write_text(text)
        return path

    def test_env_directory_and_empty_timezone(self):
        (self.root / "profile.md").write_text('timezone:\nwork_days: "Monday"\n')
        self.assertEqual(state.read_profile_timezone(str(self.root)), "")
        self.assertEqual(state.find_secretary_dir(None), str(self.root))
        code, output, _ = self.invoke("--check", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["timezone"], "")

    def test_profile_timezone_drives_local_today(self):
        class Clock(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return dt.datetime(2026, 10, 9, 0, 30, tzinfo=dt.timezone.utc).astimezone(tz)

        with patch.object(state.dt, "datetime", Clock):
            self.assertEqual(state.today_str(None, "America/New_York"), "2026-10-08")

    def test_invalid_timezone_and_noncanonical_date(self):
        (self.root / "profile.md").write_text("timezone: Invalid/Zone\n")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            state.main(["--check"])
        with self.assertRaises(SystemExit):
            state.today_str("20261009")

    def test_mark_duplicate_snapshot_and_preserve_daily_edits(self):
        path = self.daily(TODAY, f"# {TODAY}\n\n## must-do\n- [ ] Existing task\n")
        answer = self.root / "answer.txt"
        answer.write_text(ANSWER)
        self.assertEqual(self.invoke("--mark-gm", "--session", "ses-first", "--answer-file", str(answer))[0], 0)
        first = path.read_text()
        self.assertIn("Existing task", first)
        code, _, error = self.invoke("--mark-gm", "--session", "ses-second")
        self.assertEqual(code, 2)
        self.assertIn("ses-first", error)
        self.assertEqual(path.read_text(), first)
        self.assertEqual((self.root / "daily" / f"{TODAY}.gm.json").read_text(), ANSWER)

    def test_session_injection_and_empty_answers_leave_no_run(self):
        self.assertEqual(self.invoke("--mark-gm", "--session", "bad\n- gn: yes")[0], 2)
        with patch.object(sys, "stdin", io.StringIO(" ")):
            self.assertEqual(self.invoke("--mark-gm", "--session", "ses-ok", "--answer-stdin")[0], 2)
        self.assertFalse((self.root / "daily" / f"{TODAY}.md").exists())

    def test_fenced_examples_are_not_completed_runs(self):
        path = self.daily(TODAY, "```text\n- gm: yes (session example)\n## news\n```\n- gn: no\n")
        day = state.parse_daily(str(path))
        self.assertFalse(day["gm"]["ran"])
        self.assertFalse(day["sections"]["news"])

    def test_conflicting_run_lines_fail_instead_of_guessing(self):
        self.daily(TODAY, "- gm: yes (session first)\n- gm: no\n")
        self.assertEqual(self.invoke("--check")[0], 1)

    def test_corrupt_index_recovers_but_future_version_is_preserved(self):
        self.daily(TODAY, "- gm: yes (session ses-source)\n")
        index = self.root / "state.json"
        index.write_text("{broken")
        code, output, error = self.invoke("--check", "--json")
        self.assertEqual(code, 0)
        self.assertIn("WARN", error)
        self.assertEqual(json.loads(output)["gm_today"]["session"], "ses-source")
        for value in ({"version": 999}, {"version": 1, "days": []}):
            index.write_text(json.dumps(value))
            code, _, _ = self.invoke("--check")
            if value["version"] == 999:
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(index.read_text()), value)
            else:
                self.assertEqual(code, 0)

    def test_invalid_daily_date_and_missing_snapshot_are_visible(self):
        self.daily("2026-02-30", "- gm: yes\n")
        self.daily(TODAY, f"- gm: yes | answer: daily/{TODAY}.gm.json\n")
        code, output, _ = self.invoke("--check", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["warnings"], ["invalid_daily_date", "missing_answer"])

    def test_external_answer_pointer_is_never_opened(self):
        secret = self.root / "private.txt"
        secret.write_text("private")
        self.daily(TODAY, f"- gm: yes | answer: {secret}\n")
        with patch.object(state, "stat_answer", side_effect=AssertionError("unsafe read")):
            code, output, _ = self.invoke("--check", "--json")
        self.assertEqual(code, 0)
        self.assertIn("unsafe_answer_pointer", json.loads(output)["warnings"])

    def test_inbox_counts_status_column_not_idea_words(self):
        initialize(self.root)
        store = InboxStore(self.root, write=True)
        self.addCleanup(store.close)
        receipt = store.mutate('add', {'kind': 'idea', 'raw': 'pending work is done', 'project': 'demo'}, 'ses_fixture', 'a', '2026-10-07T12:00:00+00:00')
        store.mutate('update', {'status': 'confirmed'}, 'ses_fixture', 'b', '2026-10-07T12:00:00+00:00', receipt['id'], 1)
        store.mutate('add', {'kind': 'idea', 'raw': 'confirmed mechanism', 'project': 'demo'}, 'ses_fixture', 'c', '2026-10-08T12:00:00+00:00')
        self.assertEqual(state.scan_inbox(str(self.root)),
                         {"pending": 1, "oldest_pending_date": "2026-10-08", "total": 2})

    def test_thirty_day_cost_survives_persistence_and_warm_checks_read_no_snapshots(self):
        for i in range(30):
            day = (dt.date.fromisoformat(TODAY) - dt.timedelta(days=i)).isoformat()
            self.daily(day, f"- gm: yes (session ses-{i}) | answer: daily/{day}.gm.json\n")
            (self.root / "daily" / f"{day}.gm.json").write_text(ANSWER)
        code, output, _ = self.invoke("--check", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["answer_cost_30d"]["tokens_est"], 30 * ((len(ANSWER) + 3) // 4))
        self.assertEqual(len(json.loads((self.root / "state.json").read_text())["days"]), 14)
        with patch.object(state, "stat_answer", side_effect=AssertionError("warm snapshot read")):
            code, output, _ = self.invoke("--check", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["answer_cost_30d"]["snapshots"], 30)
        self.assertNotIn("fingerprint", output)

    def test_snapshot_edit_invalidates_cached_stats(self):
        self.daily(TODAY, "- gm: yes\n")
        answer = self.root / "daily" / f"{TODAY}.gm.json"
        answer.write_text(ANSWER)
        self.invoke("--check")
        changed = ANSWER.replace('A clear start.', 'A new and longer opening.')
        answer.write_text(changed)
        code, output, _ = self.invoke("--check", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["gm_today"]["chars"], len(changed))

    def test_long_gap_paging_is_bounded_and_counts_old_history(self):
        self.daily("2000-01-01", "- gm: yes\n- gn: yes\n")
        code, output, _ = self.invoke("--check", "--json", "--limit", "3")
        value = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(len(value["missed"]), 3)
        self.assertEqual(value["missed"][0]["date"], "2000-01-02")
        expected = (dt.date.fromisoformat(TODAY) - dt.date(2000, 1, 1)).days - 1
        self.assertEqual(value["missed_total"], expected)
        self.assertEqual(value["next_offset"], 3)
        self.assertLess(len(output), 2500)
        code, output, _ = self.invoke("--check", "--json", "--offset", str(expected - 1))
        self.assertEqual(json.loads(output)["missed"][0]["date"], "2026-10-08")

    def test_cooperating_writer_lock_prevents_mutation(self):
        with runtime_lock(str(self.root), ".state.lock"):
            result = subprocess.run([sys.executable, str(ROOT / "scripts/goodmorning.py"), "state",
                                     "--mark-gm", "--session", "ses-race", "--today", TODAY],
                                    env=os.environ.copy(), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn("runtime_busy", result.stderr)
        self.assertFalse((self.root / "daily" / f"{TODAY}.md").exists())

    def test_missing_runtime_is_not_initialized(self):
        missing = self.root / "absent"
        code, _, _ = self.invoke("--secretary-dir", str(missing), "--check")
        self.assertEqual(code, 1)
        self.assertFalse(missing.exists())

    def test_mark_and_duplicate_have_single_json_responses(self):
        with patch.object(sys, 'stdin', io.StringIO(ANSWER)):
            code, output, _ = self.invoke("--mark-gm", "--session", "ses-json", "--answer-stdin", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["session"], "ses-json")
        code, output, _ = self.invoke("--mark-gm", "--session", "ses-repeat", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["error"], "already_ran")

    def test_browser_owned_edition_refuses_foreign_save_even_with_force(self):
        jobs = self.root / "browser-jobs"
        jobs.mkdir()
        (jobs / "jobs.json").write_text(json.dumps(
            {f"{TODAY}.gm": {"id": "b" * 32, "date": TODAY, "kind": "gm", "state": "complete", "session": "ses-owner"}}))
        answer = self.root / "answer.txt"
        answer.write_text(ANSWER)
        for extra in ([], ["--force"]):
            code, output, _ = self.invoke("--mark-gm", "--session", "ses-other", "--answer-file", str(answer), "--json", *extra)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output)["error"], "browser_owned")
        self.assertFalse((self.root / "daily" / f"{TODAY}.md").exists())
        code, _, _ = self.invoke("--mark-gm", "--session", "ses-owner", "--answer-file", str(answer), "--json")
        self.assertEqual(code, 0)
        (jobs / "jobs.json").write_text("{broken")
        code, _, _ = self.invoke("--mark-gm", "--session", "ses-after", "--answer-file", str(answer), "--force", "--json")
        self.assertEqual(code, 0)

    def test_oversized_answer_is_rejected_before_writing(self):
        with patch.object(state, "MAX_ANSWER_CHARS", 10), patch.object(sys, "stdin", io.StringIO("x" * 11)):
            code, output, _ = self.invoke("--mark-gm", "--session", "ses-size", "--answer-stdin", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["error"], "answer_too_large")
        self.assertFalse((self.root / "daily" / f"{TODAY}.gm.json").exists())

    def test_unreadable_daily_encoding_is_not_reported_as_missing(self):
        (self.root / "daily" / f"{TODAY}.md").write_bytes(b"\xff")
        code, output, _ = self.invoke("--check", "--json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["error"], "state_unavailable")

    def test_orphan_snapshot_is_reported_and_not_overwritten(self):
        path = self.root / "daily" / f"{TODAY}.gm.json"
        path.write_text(ANSWER)
        code, output, _ = self.invoke("--check", "--json")
        self.assertIn("orphan_snapshot", json.loads(output)["warnings"])
        with patch.object(sys, "stdin", io.StringIO(ANSWER)):
            code, output, _ = self.invoke("--mark-gm", "--session", "ses-new", "--answer-stdin", "--json")
        self.assertEqual(json.loads(output)["error"], "snapshot_exists")
        self.assertEqual(path.read_text(), ANSWER)

    def test_explicit_rebuild_recomputes_snapshot_metadata(self):
        self.daily(TODAY, "- gm: yes\n")
        (self.root / "daily" / f"{TODAY}.gm.json").write_text(ANSWER)
        self.invoke("--check")
        with patch.object(state, "stat_answer", wraps=state.stat_answer) as reads:
            code, output, _ = self.invoke("--rebuild", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output)["rebuilt"])
        self.assertEqual(reads.call_count, 1)


if __name__ == "__main__":
    unittest.main()
