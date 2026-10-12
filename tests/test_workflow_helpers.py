"""Deterministic preparation/amendments/views; no personal records or providers."""

import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from goodmorning.records import daily, workflow
from goodmorning.news import news
from goodmorning.news.news_editorial import candidates, seal
from goodmorning.news.news_views import report_view
from goodmorning.news.news_reports import ReportStore, context_key
from goodmorning.records.inbox_store import initialize, InboxStore
from goodmorning.runtime_files import secretary_path, cache_path, calendar_path
from goodmorning.calendar.calendar_store import CalendarStore

DAY = "2026-10-10"


class HelpersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"SECRETARY_DIR": str(self.root)}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        (self.root / "profile.md").write_text('city: "London, GB"\ntimezone: "Europe/London"\n'
            'news_country: "GB"\nnews_additional_countries: "CN,GB"\nsecretary_language: "English"\n'
            'secretary_tone: "Warm"\nnews_latest: "false"\n')

    def file(self, text):
        path = self.root / "daily" / (DAY + ".md")
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)
        return path

    def test_capture_is_one_command_and_does_not_scan_state_or_history(self):
        initialize(self.root)
        args = ["--capture", "todo", "--session", "ses-test", "--request-key", "turn-1", "--input-stdin"]
        outputs = []
        for _ in range(2):
            out = io.StringIO()
            with patch.object(workflow, "rebuild_index", side_effect=AssertionError("state scan")), \
                 patch("sys.stdin", io.StringIO('{"raw":"Buy milk tomorrow"}')), contextlib.redirect_stdout(out):
                self.assertEqual(workflow.main(args), 0)
            outputs.append(json.loads(out.getvalue()))
        self.assertEqual(outputs[0]["title"], "Todo Buy milk tomorrow")
        self.assertEqual(outputs[0]["id"], outputs[1]["id"])
        self.assertTrue(outputs[1]["replayed"])
        self.assertFalse((self.root / "state.json").exists())
        self.assertFalse((self.root / "daily").exists())
        self.assertFalse((self.root / "calendar.sqlite").exists())

    def test_eureka_captures_action_words_and_requirements_as_pending_data_only(self):
        initialize(self.root)
        target = self.root / "project.py"
        target.write_text("# Existing project, not authorized for edits\n")
        raw = (f'Research the alternatives, then build and fix {target}.\n'
               'Use Python; deploy tomorrow and book a review at 10:00.')
        args = ["--capture", "eureka", "--session", "ses-test",
                "--request-key", "idea-actions", "--input-stdin"]
        payload = {"raw": raw, "context": "Full requirements supplied, capture only."}
        with patch.object(workflow, "rebuild_index", side_effect=AssertionError("state scan")), \
             patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(workflow.main(args), 0)
        receipt = json.loads(out.getvalue())
        self.assertTrue(receipt["saved"])
        store = InboxStore(self.root)
        self.addCleanup(store.close)
        current = store.show(receipt["id"])
        self.assertEqual(current["kind"], "idea")
        self.assertEqual(current["status"], "pending")
        self.assertEqual(store.text(receipt["id"])["text"], raw)
        self.assertEqual(target.read_text(), "# Existing project, not authorized for edits\n")
        for name in ("state.json", "daily", "calendar.sqlite"):
            self.assertFalse((self.root / name).exists())

    def test_preparation_checks_duplicates_before_loading_daily_tasks_or_inbox(self):
        self.file(f"# {DAY}\n- gm: yes (session ses-original)\n")
        before = set(self.root.iterdir())
        with patch.object(workflow, "daily_show", side_effect=AssertionError("unnecessary read")):
            result = workflow.prepare(self.root, "gm", DAY)
        self.assertTrue(result["duplicate"])
        self.assertEqual(result["original_session"], "ses-original")
        self.assertNotIn("title", result)
        self.assertEqual(set(self.root.iterdir()), before)

    def test_prepare_dates_configuration_and_missing_setup_are_local(self):
        result = workflow.prepare(self.root, "gm", DAY)
        self.assertEqual(result["yesterday"], "2026-10-09")
        self.assertEqual(result["tomorrow"], "2026-10-11")
        self.assertEqual(result["news"]["countries"], ["GB", "CN"])
        self.assertFalse(result["news"]["latest_enabled"])
        self.assertEqual(result["daily"]["sha256"], "missing")
        self.assertFalse((self.root / "state.json").exists())
        missing = self.root / "missing"
        result = workflow.prepare(missing, "todo")
        self.assertFalse(result["profile_ready"])
        self.assertEqual(result["missing_fields"][0], "secretary_language")
        self.assertFalse(missing.exists())

    def test_native_duplicate_uses_json_pointer_without_history_or_content_reads(self):
        self.file(f'# {DAY}\n- gm: yes (session ses-original) | answer: daily/{DAY}.gm.json\n')
        payload = {'v': 1, 'greeting': 'Hello.', 'opening': 'Saved once.', 'sections': [['notes', [['p', 'Preserved.']]]]}
        (self.root / 'daily' / f'{DAY}.gm.json').write_text(json.dumps(payload))
        with patch.object(workflow, 'daily_show', side_effect=AssertionError('task read')), \
             patch.object(workflow, 'rebuild_index', side_effect=AssertionError('history read')):
            result = workflow.prepare(self.root, 'gm', DAY)
        self.assertTrue(result['duplicate'])
        self.assertEqual(result['answer_file'], f'daily/{DAY}.gm.json')
        self.assertEqual(result['original_session'], 'ses-original')

    def test_non_english_title_is_not_guessed(self):
        profile = self.root / "profile.md"
        profile.write_text(profile.read_text().replace('"English"', '"Chinese"'))
        self.assertIsNone(workflow.prepare(self.root, "secretary", DAY)["title"])

    def test_optional_calendar_error_does_not_restart_setup_or_invent_empty_schedule(self):
        (self.root / "calendar.config.json").write_text("{invalid")
        result = workflow.prepare(self.root, "gm", DAY)
        self.assertTrue(result["ready"])
        self.assertIsNone(result["paths"]["calendar_db"])
        self.assertIn("calendar_configuration", result)

    def test_prepare_does_not_read_snapshot_bodies_or_scan_unrelated_project_records(self):
        from goodmorning.records import state
        self.file(f"# {DAY}\n- gm: no\n")
        with patch.object(state, "stat_answer", side_effect=AssertionError("snapshot body")), \
             patch.object(state, "scan_projects", side_effect=AssertionError("unrelated project")), \
             patch.object(state, "calendar_stats", side_effect=AssertionError("calendar scan")):
            self.assertTrue(workflow.prepare(self.root, "gm", DAY)["ready"])

    def test_daily_add_preserves_completed_tasks_run_lines_and_unrelated_work(self):
        original = f"# {DAY}\n- gm: yes (session first)\n\n## must-do\n- [x] Existing task\n\n## notes\nPrivate unrelated prose\n"
        path = self.file(original)
        digest = daily.show(self.root, DAY)["sha256"]
        daily.amend(self.root, DAY, digest, {"tasks": {"must-do": [{"text": "Existing task"}, {"text": "New task"}]}})
        text = path.read_text()
        self.assertIn("- [x] Existing task", text)
        self.assertEqual(text.count("Existing task"), 1)
        self.assertIn("- [ ] New task", text)
        self.assertIn("- gm: yes (session first)", text)
        self.assertIn("## notes\nPrivate unrelated prose\n", text)
        self.assertFalse((path.parent / (DAY + ".gm.md")).exists())

    def test_daily_completion_requires_confirmation_and_current_hash(self):
        path = self.file(f"# {DAY}\n## must-do\n- [ ] A\n- [ ] B\n")
        view = daily.show(self.root, DAY)
        first = view["tasks"][0]["id"]
        with self.assertRaisesRegex(ValueError, "confirmation_required"):
            daily.amend(self.root, DAY, view["sha256"], {"complete": [first]})
        daily.amend(self.root, DAY, view["sha256"], {"complete": [first], "confirmed_completion": True})
        self.assertIn("- [x] A", path.read_text())
        self.assertIn("- [ ] B", path.read_text())
        with self.assertRaisesRegex(ValueError, "write_conflict"):
            daily.amend(self.root, DAY, view["sha256"], {"append": {"feedback": ["stale"]}})

    def test_daily_ref_deduplicates_changed_reminder_without_overwriting_completion(self):
        ref = "ib_0123456789abcdef"
        self.file(f"# {DAY}\n## must-do\n- [x] Original reminder <!-- inbox:{ref} -->\n")
        view = daily.show(self.root, DAY)
        receipt = daily.amend(self.root, DAY, view["sha256"], {"tasks": {"must-do": [{"text": "Changed reminder", "ref": ref}]}})
        self.assertFalse(receipt["changed"])

    def test_flexible_checklist_uses_exact_completion_and_cross_group_deduplication(self):
        path=self.file(f"# {DAY}\n## must-do\n- [x] Important task\n")
        daily.amend(self.root,DAY,daily.show(self.root,DAY)['sha256'],{'tasks':{'flexible':[
            {'text':'Important task'},{'text':'Untimed task'}]}})
        view=daily.show(self.root,DAY)
        self.assertEqual(len(view['tasks']),2)
        task=next(t for t in view['tasks'] if t['section']=='flexible')
        with self.assertRaisesRegex(ValueError,'confirmation_required'):
            daily.amend(self.root,DAY,view['sha256'],{'complete':[task['id']]})
        for mode in ('append','replace'):
            with self.assertRaisesRegex(ValueError,'unsupported section'):
                daily.amend(self.root,DAY,view['sha256'],{mode:{'flexible':['Do not erase task states']}})
        daily.amend(self.root,DAY,view['sha256'],{'complete':[task['id']],'confirmed_completion':True})
        self.assertIn('- [x] Untimed task',path.read_text())
        self.assertEqual(path.read_text().count('Important task'),1)

    def test_daily_updates_are_exact_noops_not_duplicate_diary_entries(self):
        payload = {"append": {"feedback": ["User reported a blocker."]}, "tasks": {"nice-to-do": [{"text": "Optional reading"}]}}
        daily.amend(self.root, DAY, "missing", payload)
        view = daily.show(self.root, DAY)
        second = daily.amend(self.root, DAY, view["sha256"], payload)
        self.assertFalse(second["changed"])
        self.assertEqual(second["sha256"], view["sha256"])

    def test_daily_fenced_examples_are_untouched_and_secret_payload_refused(self):
        path = self.file(f"# {DAY}\n```text\n## must-do\n- [ ] Example\n```\n## must-do\n- [ ] Real task\n")
        view = daily.show(self.root, DAY)
        self.assertEqual(len(view["tasks"]), 1)
        daily.amend(self.root, DAY, view["sha256"], {"complete": [view["tasks"][0]["id"]], "confirmed_completion": True})
        self.assertIn("- [ ] Example", path.read_text())
        with self.assertRaisesRegex(ValueError, "protected_input"):
            daily.amend(self.root, DAY, daily.show(self.root, DAY)["sha256"], {"append": {"progress": ["token=secret"]}})

    def test_daily_pages_flag_long_text_and_preserve_exact_section(self):
        self.file(f"# {DAY}\n## must-do\n" + "- [ ] " + "Long task " * 100 + "\n- [ ] Other\n")
        page = daily.show(self.root, DAY, limit=1)
        self.assertTrue(page["tasks"][0]["text_truncated"])
        self.assertEqual(page["next_offset"], 1)
        self.assertGreater(daily.show(self.root, DAY, section="must-do")["total_chars"], 1000)

    def test_runtime_defaults_ignore_current_checkout_and_expand_home(self):
        with patch.dict(os.environ, {"HOME": str(self.root), "SECRETARY_DIR": "~/chosen", "GM_CACHE_DIR": "~/cache"}, clear=True):
            self.assertEqual(secretary_path(), self.root / "chosen")
            self.assertEqual(cache_path(), self.root / "cache")
            self.assertEqual(news.parse_args([]).secretary_dir, str(self.root / "chosen"))

    def test_configured_calendar_path_is_shared_by_state_and_workflow(self):
        path = self.root / "chosen.sqlite"
        (self.root / "calendar.config.json").write_text(json.dumps({"calendar_db": str(path)}))
        self.assertEqual(calendar_path(self.root), path)
        self.assertEqual(workflow.prepare(self.root, "secretary", DAY)["paths"]["calendar_db"], str(path))

    def test_calendar_readonly_never_creates_or_rewrites_storage(self):
        path = self.root / "missing" / "calendar.sqlite"
        with self.assertRaises(sqlite3.OperationalError):
            CalendarStore(str(path), readonly=True)
        self.assertFalse(path.parent.exists())
        actual = self.root / "calendar.sqlite"
        CalendarStore(str(actual)).close()
        store = CalendarStore(str(actual), readonly=True)
        self.addCleanup(store.close)
        self.assertEqual(store.stats()["total"], 0)
        with self.assertRaises(sqlite3.OperationalError):
            store.con.execute("DELETE FROM events")


class NewsViewTests(unittest.TestCase):
    def report(self):
        stories = [{"date": "2026-10-09", "section": section, "title": "Important AI event" if section == 'ai' else "Important event", "summary": "Evidence and uncertainty.",
                    "links": [{"source": "Synthetic", "url": "https://example.invalid/" + section}]} for section in ("ai", "major", "national")]
        pool = candidates(stories * 1)
        payload = seal({"date": "2026-10-09", "country": "GB", "timezone": "UTC", "counts": {"ai": 1, "major": 1, "national": 1},
                        "stories": stories, "candidates": pool, "notes": ["Material coverage warning"], "source_status": ["diagnostics" * 200],
                        "curation": {"required": True, "state": "pending"}, "max_items": 4})
        return {"payload": payload, "report_id": "current", "status": "collected", "collected_at": 1}

    def test_stories_view_keeps_all_selected_evidence_and_warnings_not_candidates(self):
        row = self.report()
        result = report_view(row)
        self.assertEqual(result["stories"], row["payload"]["stories"])
        self.assertEqual(result["notes"], row["payload"]["notes"])
        self.assertNotIn("candidates", result)
        self.assertNotIn("source_status", result)
        self.assertLess(len(json.dumps(result)), len(json.dumps(report_view(row, "full"))))

    def test_candidate_pages_return_complete_evidence_and_current_report_id(self):
        row = self.report()
        first = report_view(row, "candidates", limit=2)
        last = report_view(row, "candidates", offset=first["next_offset"], limit=2)
        self.assertEqual(first["candidates"] + last["candidates"], row["payload"]["candidates"])
        self.assertEqual(first["report_id"], "current")
        self.assertIsNone(last["next_offset"])

    def test_curate_can_return_saved_stories_without_an_extra_show_or_fetch(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            cfg = {"feeds": [], "countries": {"GB": [{"name": "Synthetic", "section": "national", "url": "https://example.invalid/rss"}]}}
            row = self.report()
            store = ReportStore(directory, create=True)
            self.addCleanup(store.close)
            saved = store.save(context_key("UTC", "GB", cfg), row["payload"])
            selection = root / "selection.json"
            selection.write_text(json.dumps([{"candidate_id": item["candidate_id"], "reason": "Reviewed consequential evidence."} for item in row["payload"]["candidates"]]))
            out = io.StringIO()
            with patch.object(news, "load_sources", return_value=cfg), patch.object(news, "collect", side_effect=AssertionError("provider fetch")), contextlib.redirect_stdout(out):
                code = news.main(["--secretary-dir", directory, "--timezone", "UTC", "--country", "GB", "--today", DAY,
                                  "--curate", "2026-10-09", "--selection-file", str(selection), "--expect", saved["report_id"], "--session", "ses-test", "--view", "stories"])
            result = json.loads(out.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(result["curation"]["state"], "reviewed")
            self.assertEqual(len(result["stories"]), 3)
            self.assertNotIn("candidates", result)
            self.assertEqual(store.get(context_key("UTC", "GB", cfg), "2026-10-09")["status"], "collected")


if __name__ == "__main__":
    unittest.main()
