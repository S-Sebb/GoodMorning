"""Skill contracts and a deterministic fake-data morning/night dry run."""

import contextlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from support import TEMP_ROOT
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from news_reports import ReportStore, context_key
from secretary_calendar import main as calendar_main
from state import main as state_main, scan_inbox
from benchmark_reply_templates import fixtures, render

KINDS = ("gm", "gn", "eureka", "todo", "secretary")


class SkillContractTests(unittest.TestCase):
    def test_skills_have_discoverable_metadata_and_complete_workflows(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                path = ROOT / "docs/workflows" / f"{kind}.md"
                text = path.read_text()
                metadata = re.match(r"---\n(.*?)\n---\n", text, re.S).group(1)
                self.assertIn(f"name: {kind}\n", metadata + "\n")
                self.assertRegex(metadata, r"description: .+")
                for marker in ("Trigger:", "Inputs:", "Output:", "##", "Errors"):
                    self.assertIn(marker, text)
                references = re.findall(r"`((?:docs|templates)/[^`]+\.md)`", text)
                self.assertGreaterEqual(len(references), 2)
                for reference in references:
                    self.assertTrue((ROOT / reference).is_file(), reference)
                self.assertIn("skill-rules.md", text)
                self.assertLess(len(text), 6800)

    def test_skill_source_is_inactive_and_no_project_wrappers_exist(self):
        text = (ROOT / "skill-source/goodmorning.md").read_text()
        self.assertIn("name: goodmorning", text)
        self.assertIn("Keep the current session and model; do not delegate", text)
        for kind in KINDS:
            self.assertIn(f"docs/workflows/{kind}.md", text)
        self.assertEqual(list((ROOT / ".opencode").rglob("*.md")), [])
        self.assertEqual(list(ROOT.glob("**/SKILL.md")), [])

    def test_shared_rules_preserve_delivery_and_confirmation_boundaries(self):
        text = (ROOT / "docs/skill-rules.md").read_text()
        for required in ("Never acknowledge before sending", "partial", "--expect-revision",
                         "outcome_unknown", "--force", "runtime_busy", "SECRETARY_DIR",
                         "Never use a made-up", "Do not silently backdate"):
            self.assertIn(required, text)

    def test_inbox_contract_uses_helpers_not_transcripts_or_legacy_edits(self):
        shared = (ROOT / "docs/skill-rules.md").read_text()
        guide = (ROOT / "docs/inbox-pipeline.md").read_text()
        self.assertLess(len(shared), 24000)
        for marker in ("not every", "assistant answer", "--append ID", "--show ID", "inbox-pipeline.md"):
            self.assertIn(marker, shared)
        for marker in ("--request-key", "--expect-revision", "needs_review", "byte-for-byte",
                       "No silent item/question truncation", "not a running diary", "not every"):
            self.assertIn(marker, guide)
        for kind in KINDS:
            text = (ROOT / "docs/workflows" / f"{kind}.md").read_text()
            self.assertIn("inbox.py", text)
            self.assertIn("inbox-pipeline.md", text)
            self.assertNotIn("YYYY-MM-DD HH:MM TIMEZONE |", text)
        todo = (ROOT / "docs/workflows/todo.md").read_text()
        self.assertNotIn("state.py --", todo)
        self.assertIn("No full state rebuild", todo)

    def test_news_rules_are_loaded_only_for_news_work(self):
        shared = (ROOT / "docs/skill-rules.md").read_text()
        news = (ROOT / "docs/news-delivery.md").read_text()
        self.assertIn("Capture-only workflows do not load it", shared)
        self.assertIn("Read `docs/news-delivery.md`", (ROOT / "docs/workflows/gm.md").read_text())
        for marker in ("Never acknowledge before sending", "news_additional_countries",
                       "current report/batch ID", "no same-day fetch or section", "no delivery ledger"):
            self.assertIn(marker, news)

    def test_normal_workflows_load_compact_core_and_mechanical_helpers(self):
        entry = (ROOT / "skill-source/goodmorning.md").read_text()
        core = (ROOT / "docs/core-rules.md").read_text()
        self.assertIn("Read `docs/core-rules.md`", entry)
        self.assertLess(len(core), 10000)
        for boundary in ("Never acknowledge", "user-confirmed", "current revision", "outcome_unknown",
                         "do not delegate", "not consent", "Do not save every exchange", "first", "--force"):
            self.assertIn(boundary, core)
        for kind in KINDS:
            text = (ROOT / "docs/workflows" / f"{kind}.md").read_text()
            self.assertIn("core-rules.md", text)
            self.assertIn("workflow.py", text)
        gm = (ROOT / "docs/workflows/gm.md").read_text()
        self.assertIn("--view candidates", gm)
        self.assertIn("--view stories", gm)
        self.assertIn("--json --details", gm)
        for kind in ("gm", "gn", "secretary"):
            self.assertIn("daily.py", (ROOT / "docs/workflows" / f"{kind}.md").read_text())

    def test_gm_gn_use_fixed_openchamber_conversation_titles(self):
        shared = (ROOT / "docs/skill-rules.md").read_text()
        for required in ("GoodMorning YYYY-MM-DD", "GoodNight YYYY-MM-DD",
                         "Secretary SUMMARY", "Eureka SUMMARY", "Todo SUMMARY",
                         "OPENCODE_SESSION_ID", "opencode api patch",
                         "never\n  on a duplicate stop", "rename failure internal"):
            self.assertIn(required, shared)
        self.assertNotIn("Secretary YYYY-MM-DD", shared)
        self.assertIn("all five workflows", shared)
        self.assertNotIn("for gm/gn only", shared)
        self.assertIn("very short", shared)
        self.assertIn("in the\n  user's `secretary_language`", shared)
        self.assertIn("English defaults", shared)
        self.assertIn("translate only the prefix", shared)
        self.assertIn("not translated", shared)
        gm = (ROOT / "docs/workflows/gm.md").read_text()
        gn = (ROOT / "docs/workflows/gn.md").read_text()
        eureka = (ROOT / "docs/workflows/eureka.md").read_text()
        secretary = (ROOT / "docs/workflows/secretary.md").read_text()
        todo = (ROOT / "docs/workflows/todo.md").read_text()
        self.assertIn("`GoodMorning DATE`", gm)
        self.assertIn("shared title rule", gm)
        self.assertIn("`GoodNight DATE`", gn)
        self.assertIn("shared title rule", gn)
        self.assertNotIn("`GoodNight DATE`", gm)
        self.assertNotIn("`GoodMorning DATE`", gn)
        self.assertIn("`Secretary SUMMARY`", secretary)
        self.assertIn("shared title rule", secretary)
        self.assertNotIn("`Secretary DATE`", secretary)
        self.assertIn("`Eureka SUMMARY`", eureka)
        self.assertIn("shared title rule", eureka)
        self.assertIn("very short", eureka)
        self.assertNotIn("`Secretary SUMMARY`", gm)
        self.assertNotIn("`Secretary SUMMARY`", gn)
        self.assertNotIn("`Eureka SUMMARY`", gm)
        self.assertNotIn("`Eureka SUMMARY`", gn)
        self.assertIn("`Todo SUMMARY`", todo)
        self.assertIn("shared title rule", todo)
        for text in (gm, gn, eureka, todo, secretary):
            self.assertIn("`secretary_language`", text)

    def test_skills_prefer_interactive_questions_with_consent_and_fallback(self):
        shared = (ROOT / "docs/skill-rules.md").read_text()
        for required in ("`question` tool", "structured question UI in OpenChamber",
                         "multiple: true", "built-in custom-answer input",
                         "not consent", "unavailable or unusable", "normal conversation and wait",
                         "Do not ask again", "customised", "Optional personal-context questions offer a skip"):
            self.assertIn(required, shared)
        for kind in KINDS:
            with self.subTest(kind=kind):
                skill = (ROOT / "docs/workflows" / f"{kind}.md").read_text()
                template = (ROOT / "templates" / f"{kind}.reply.template.md").read_text()
                self.assertIn("`question`", skill)
                self.assertIn("`question`", template)

    def test_eureka_saves_by_default_and_accepts_details_without_a_keyword(self):
        skill = (ROOT / "docs/workflows/eureka.md").read_text()
        template = (ROOT / "templates/eureka.reply.template.md").read_text()
        shared = (ROOT / "docs/skill-rules.md").read_text()
        secretary = (ROOT / "docs/workflows/secretary.md").read_text()
        for text in (skill, template):
            self.assertIn("optional clarification via `Clarify`", text)
            self.assertIn("idea as is", text)
            self.assertNotIn("Say `Clarify` if you want me", text)
            self.assertIn("remaining", text)
            self.assertNotIn("Use `question` for now/later", text)
            self.assertNotIn("Use `question` for the now/later choice", text)
        for marker in ("Do not ask for a now/later choice by default",
                       "no special keyword", "Preserve the original raw idea",
                       "not as a duplicate idea", "skip clarification questions",
                       "only after the user confirms"):
            self.assertIn(marker, skill)
        self.assertIn("no reply is required", shared)
        for marker in ("do not require `/eureka` or `Clarify`", "existing pending entry",
                       "prior answers", "remaining ambiguity", "successful authorized organization"):
            self.assertIn(marker, secretary)

    def test_idea_details_are_saved_before_questions_and_resurface_by_workflow(self):
        shared = (ROOT / "docs/skill-rules.md").read_text()
        for marker in ("save each supplied idea and follow-up detail", "immediately, before asking",
                       "unassigned pending input", "Do not lose input when the user stops replying",
                       "unchecked", "clarification TODO", "clarification question",
                       "`/secretary`, include a reminder", "do not block a briefing"):
            self.assertIn(marker, shared)
        for kind, marker in (("eureka", "Save follow-up details immediately"),
                             ("gm", "unchecked clarification TODOs"),
                             ("gn", "Ask focused questions for pending clarification"),
                             ("secretary", "Save ideas/details immediately")):
            text = (ROOT / "docs/workflows" / f"{kind}.md").read_text()
            self.assertIn(marker, text)

    def test_project_updates_save_before_clarification_and_follow_up_across_skills(self):
        shared = (ROOT / "docs/skill-rules.md").read_text()
        for marker in ('kind: "project_update"', "user's exact wording",
                       "before asking for clarification", "clarification is required",
                       "silence is never confirmation", "decision versus a suggestion",
                       "Keep uncertain changes out of confirmed", "Preserve\n  `raw`",
                       "all agreed,\n  authorized record updates succeed",
                       "At the next `/gm`", "unchecked clarification TODO",
                       "At `/gn`", "At `/secretary`", "Repeat until resolved",
                       "not permission to install a scheduler"):
            self.assertIn(marker, shared)
        secretary = (ROOT / "docs/workflows/secretary.md").read_text()
        self.assertIn("before asking questions", secretary)
        self.assertIn("outstanding project-update questions", secretary)
        for kind in ("secretary", "gm", "gn"):
            with self.subTest(kind=kind):
                skill = (ROOT / "docs/workflows" / f"{kind}.md").read_text()
                template = (ROOT / "templates" / f"{kind}.reply.template.md").read_text()
                self.assertIn("shared pending project-update workflow", skill)
                self.assertIn("clarification", template)
        project = (ROOT / "templates/project.template.md").read_text()
        self.assertIn("Save raw reports immediately", project)
        self.assertIn("before applying them here", project)
        self.assertNotIn("before saving", project)

    def test_setup_invites_optional_role_context_and_all_skills_can_use_it(self):
        secretary = (ROOT / "docs/workflows/secretary.md").read_text()
        shared = (ROOT / "docs/skill-rules.md").read_text()
        for field in ("occupations", "expertise_fields"):
            self.assertIn(f"`{field}`", secretary)
            self.assertIn(f"`{field}`", shared)
        self.assertIn("These fields are optional", secretary)
        self.assertIn("You can skip", secretary)
        self.assertIn("older profiles remain valid", secretary)
        self.assertIn("across all five workflows", shared)
        self.assertIn("Do not assume knowledge from a job", shared)

    def test_initialization_is_staged_bounded_and_does_not_launch_repairs(self):
        secretary = (ROOT / "docs/workflows/secretary.md").read_text()
        guide = (ROOT / "docs/initialization.md").read_text()
        for marker in ("setup_check.py", "--budget 20", "news_additional_countries",
                       "unsupported recurrence/imports remain pending", "If setup alone was requested, stop"):
            self.assertIn(marker, secretary)
        for marker in ("shared 20-second elapsed budget", "dummy", "Initialization need not import any events", "not a reason to restart setup",
                       "never a raw live-file copy", "not whether every preference", "not a code-writing detour"):
            self.assertIn(marker, guide)

    def test_reply_language_is_first_initialization_question_and_applies_across_skills(self):
        secretary = (ROOT / "docs/workflows/secretary.md").read_text()
        guide = (ROOT / "docs/initialization.md").read_text()
        shared = (ROOT / "docs/skill-rules.md").read_text()
        self.assertIn("first initialization question is `secretary_language`", secretary)
        self.assertIn("Wait for the answer before other setup questions", guide)
        self.assertLess(guide.index("Which language would you like"), guide.index("location/timezone"))
        self.assertIn("across gm/gn/eureka/todo/secretary", shared)
        self.assertIn("raw captured ideas", shared)
        self.assertIn("For older profiles lacking it", shared)
        self.assertIn("conversation", shared)
        self.assertIn("titles", shared)
        self.assertIn("English defaults", shared)

    def test_all_five_reply_shapes_render_without_instructions_or_placeholders(self):
        report, morning, night = fixtures()
        cases = {"gm": morning, "gn": night,
                 "eureka": {"capture_status": "I've saved your idea for Demo as pending, so we can return to it.",
                             "next_question_or_action": "Say `Clarify` if you want me to work out the details with you, otherwise we can leave it as is."},
                 "todo": {"capture_status": "Saved your TODO: buy milk."},
                 "secretary": {"outcome": "I've updated Demo's goal using what you confirmed.",
                               "details_or_open_items": "The remote file hasn't been updated because a conflicting change needs review.",
                               "next_question_or_action": "Let's check the current file before deciding how to combine the changes."}}
        for kind, values in cases.items():
            with self.subTest(kind=kind):
                reply = render(kind, values)
                self.assertNotRegex(reply, r"\{[a-z_]+\}")
                self.assertNotIn("```", reply)
                self.assertNotIn("Use this", reply)
        gm, gn = render("gm", morning), render("gn", night)
        for story in report["stories"]:
            self.assertIn(story["title"], gm)
            self.assertIn(story["links"][0]["url"], gm)
        for fact in ("STALE", "refresh failed", "AQI 27", "submission date", "bring slides", "stale cached"):
            self.assertIn(fact, gm)
        self.assertNotIn("[x]", gm)

    def test_todo_is_record_only_until_explicit_discussion_request(self):
        skill = (ROOT / "docs/workflows/todo.md").read_text()
        template = (ROOT / "templates/todo.reply.template.md").read_text()
        shared = (ROOT / "docs/skill-rules.md").read_text()
        for marker in ('kind: "todo"', "user's exact wording", "Verify the write",
                       "Do not ask for a project, deadline, priority", "do not delegate",
                       "supplied details alone do not request clarification",
                       "Do not ask clarification questions", "execute the TODO",
                       "do not offer calendar confirmation", "Discuss only if the user says `Clarify`",
                       "requests a more detailed explanation", "Only user-confirmed completion",
                       "not an automatic clarification TODO or question", "--secretary-dir RUNTIME"):
            self.assertIn(marker, skill)
        for marker in ("Do not ask clarification questions", "no reply is required",
                       "only when the", "never claim the task itself was completed"):
            self.assertIn(marker, template)
        self.assertIn("idea/project-update clarification reminder rules do not apply", shared)
        self.assertIn("Except record-only TODO capture", shared)
        for kind in ("gm", "gn", "secretary"):
            text = (ROOT / "docs/workflows" / f"{kind}.md").read_text()
            self.assertIn('kind: "todo"' if kind == "gn" else "TODO", text)
        self.assertEqual(render("todo", {"capture_status": "Saved your TODO: buy milk."}),
                         "Saved your TODO: buy milk.\n")

    def test_user_replies_prioritize_clarity_and_customised_tone_without_length_targets(self):
        shared = (ROOT / "docs/skill-rules.md").read_text()
        self.assertIn("Clean formatting and clarity take priority over stylistic tone", shared)
        self.assertIn("customised `secretary_tone` throughout every reply", shared)
        self.assertIn("not just", shared)
        self.assertIn("questions", shared)
        self.assertIn("errors", shared)
        self.assertIn("internal reads and stored summaries efficient", shared)
        for kind in KINDS:
            with self.subTest(kind=kind):
                text = (ROOT / "templates" / f"{kind}.reply.template.md").read_text()
                self.assertIn("Clean formatting and clarity", text)
                self.assertIn("customised tone", text)
                self.assertIn("throughout", text)
                self.assertIn("not an override", text)
                self.assertNotRegex(text, r"\d+ estimated English tokens|one line per|Two lines normally")


class FakeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ("daily", "projects"):
            (self.root / name).mkdir()
        profile = (ROOT / "templates/profile.template.md").read_text()
        self.sources = {"feeds": [], "countries": {"US": [
            {"name": "Synthetic national feed", "url": "https://example.invalid/feed", "section": "national"}]}}
        sources_path = self.root / "news_sources.json"
        sources_path.write_text(json.dumps(self.sources))
        (self.root / "profile.md").write_text(profile.replace('timezone: ""', 'timezone: "UTC"')
                                             .replace('news_country: ""', 'news_country: "US"')
                                             .replace('news_sources_path: ""', f'news_sources_path: "{sources_path}"'))
        project = (ROOT / "templates/project.template.md").read_text()
        (self.root / "projects/demo.md").write_text(project.replace('name: ""', 'name: "Demo"')
                                                   .replace('last_update: ""', 'last_update: 2026-10-09'))
        self.env = patch.dict(os.environ, {"SECRETARY_DIR": str(self.root)}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def call(self, function, arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = function(arguments)
        self.assertEqual(code, 0, err.getvalue())
        return json.loads(out.getvalue())

    def test_pending_project_update_survives_without_reply_and_retains_raw_follow_up(self):
        inbox = self.root / "inbox.md"
        project = self.root / "projects/demo.md"
        original_project = project.read_text()
        raw = 'After the meeting, switch Demo to the partner plan.\nTODO: A | B; "soon".'
        update = {"kind": "project_update", "raw": raw, "details": [],
                  "clarification": ["Was the partner plan agreed or suggested?",
                                    "Which TODOs and deadline replace the current plan?"]}
        prefix = "- 2026-10-09 15:00 UTC | "
        suffix = " | pending | Demo\n"
        idea = '- 2026-10-08 07:00 UTC | Existing idea | pending | Demo\n'
        inbox.write_text(idea + prefix + json.dumps(update) + suffix)

        # No clarification reply: both notes remain discoverable on later runs.
        for day in ("2026-10-09", "2026-10-10"):
            rebuilt = self.call(state_main, ["--today", day, "--rebuild", "--json"])
            self.assertTrue(rebuilt["rebuilt"])
            state = self.call(state_main, ["--today", day, "--check", "--json"])
            self.assertEqual(state["inbox"]["pending"], 2)
            self.assertEqual(state["inbox"]["oldest_pending_date"], "2026-10-08")
            self.assertEqual(project.read_text(), original_project)

        # Simulate attaching a supplied detail to the same note, not a new capture.
        update["details"].append("It was only suggested; keep the current goal for now.")
        update["clarification"] = ["Which proposed TODOs should we keep for review?"]
        inbox.write_text(idea + prefix + json.dumps(update) + suffix)
        line = inbox.read_text().splitlines()[1]
        restored = json.loads(line[len(prefix):-len(suffix.rstrip("\n"))])
        self.assertEqual(restored["raw"], raw)
        self.assertEqual(restored["details"], update["details"])
        self.assertEqual(restored["clarification"], update["clarification"])
        self.assertEqual(scan_inbox(str(self.root))["total"], 2)
        self.assertEqual(scan_inbox(str(self.root))["pending"], 2)
        self.assertTrue(inbox.read_text().startswith(idea))
        self.assertEqual(project.read_text(), original_project)

    def test_capture_morning_delivery_and_night_records(self):
        report, morning, night = fixtures()
        (self.root / "inbox.md").write_text('- 2026-10-09 07:00 UTC | "Try a synthetic demo" | pending | Demo\n')
        self.assertEqual(scan_inbox(str(self.root))["pending"], 1)
        self.call(calendar_main, ["--init", "--timezone", "UTC"])
        event = {"subject": "Demo review", "start": "2026-10-10T10:00:00+00:00",
                 "end": "2026-10-10T11:00:00+00:00", "location": "Room A", "notes": "Bring slides"}
        self.call(calendar_main, ["--add", "--event-json", json.dumps(event), "--actor", "dry-run-setup"])
        schedule = self.call(calendar_main, ["--from", "2026-10-10", "--days", "1", "--timezone", "UTC",
                                            "--json", "--details"])
        self.assertEqual(schedule[0]["notes"], "Bring slides")

        context = context_key("UTC", "US", self.sources)
        store = ReportStore(str(self.root), create=True)
        self.addCleanup(store.close)
        row = store.save(context, report)
        self.assertEqual(row["status"], "collected")
        gm = render("gm", morning)
        gm_input = self.root / "gm-reply.md"
        gm_input.write_text(gm)
        daily = self.root / "daily/2026-10-09.md"
        daily.write_text("# 2026-10-09\n\n## weather\n- Synthetic forecast; STALE.\n"
                         "\n## news\n- 2026-10-08: AI/world/national 1/1/1; stale feed warning.\n"
                         "\n## schedule\n- Tomorrow: Demo review; bring slides.\n"
                         "\n## must-do\n- [ ] Demo: draft outline\n"
                         "\n## nice-to-do\n- [ ] Demo: optional reading\n")
        marked = self.call(state_main, ["--today", "2026-10-09", "--mark-gm", "--session", "dry-run-gm",
                                       "--answer-file", str(gm_input), "--json"])
        self.assertTrue(marked["ran"])
        self.assertEqual((self.root / "daily/2026-10-09.gm.md").read_text(), gm)
        self.assertNotIn("[x]", daily.read_text())
        self.assertEqual(store.get(context, report["date"])["status"], "collected")

        # Simulate presentation to a test-only user-facing stream, not real delivery.
        visible_reply = io.StringIO()
        visible_reply.write(gm)
        self.assertEqual(visible_reply.getvalue(), gm)
        store.acknowledge(context, report["date"], row["report_id"], "dry-run-gm")
        self.assertEqual(store.get(context, report["date"])["status"], "delivered")

        # The synthetic user confirms only the outline; optional reading stays open.
        daily.write_text(daily.read_text().replace("- [ ] Demo: draft outline", "- [x] Demo: draft outline")
                         + "\n## feedback\n- User confirmed outline complete; reading not done.\n"
                         "\n## progress\n- Demo: outline complete; next: one paper.\n")
        gn = render("gn", night)
        gn_input = self.root / "gn-reply.md"
        gn_input.write_text(gn)
        self.call(state_main, ["--today", "2026-10-09", "--mark-gn", "--session", "dry-run-gn",
                               "--answer-file", str(gn_input), "--json"])
        summary = self.call(state_main, ["--today", "2026-10-09", "--check", "--json"])
        self.assertTrue(summary["gm_today"]["ran"])
        self.assertTrue(summary["gn_today"]["ran"])
        self.assertTrue(summary["sections_today"]["feedback"])
        self.assertEqual((self.root / "daily/2026-10-09.gn.md").read_text(), gn)
        self.assertEqual((self.root / "daily/2026-10-09.gm.md").read_text(), gm)
        self.assertIn("- [ ] Demo: optional reading", daily.read_text())
        self.assertEqual(summary["inbox"]["pending"], 1)
        self.assertEqual(summary["news"]["delivered"], 1)

    def test_todo_capture_preserves_raw_text_without_changing_project_or_daily_tasks(self):
        inbox = self.root / "inbox.md"
        project = self.root / "projects/demo.md"
        original_project = project.read_text()
        original_idea = "- 2026-10-08 07:00 UTC | Existing idea | pending | Demo\n"
        raw = 'Email A | B tomorrow.\nTODO: ask about "pending | done".'
        todo = {"kind": "todo", "raw": raw, "details": []}
        prefix = "- 2026-10-09 15:00 UTC | "
        suffix = " | pending | \n"
        inbox.write_text(original_idea + prefix + json.dumps(todo) + suffix)
        for day in ("2026-10-09", "2026-10-10"):
            self.call(state_main, ["--secretary-dir", str(self.root), "--today", day,
                                   "--rebuild", "--json"])
            result = self.call(state_main, ["--secretary-dir", str(self.root), "--today", day,
                                            "--check", "--json"])
            self.assertEqual(result["inbox"]["pending"], 2)
            self.assertEqual(project.read_text(), original_project)
            self.assertEqual(list((self.root / "daily").iterdir()), [])
        todo["details"].append("Also attach the invoice; no deadline yet.")
        inbox.write_text(original_idea + prefix + json.dumps(todo) + suffix)
        line = inbox.read_text().splitlines()[1]
        restored = json.loads(line[len(prefix):-len(suffix.rstrip("\n"))])
        self.assertEqual(restored, todo)
        self.assertEqual(restored["raw"], raw)
        self.assertEqual(scan_inbox(str(self.root))["total"], 2)
        self.assertTrue(inbox.read_text().startswith(original_idea))
        self.assertEqual(project.read_text(), original_project)
        inbox.write_text(original_idea + prefix + json.dumps(todo) + " | done | \n")
        self.assertEqual(scan_inbox(str(self.root))["pending"], 1)
        self.assertEqual(scan_inbox(str(self.root))["total"], 2)

    def test_pending_details_survive_without_a_clarification_reply(self):
        raw = '- 2026-10-09 07:00 UTC | "Try a synthetic demo" | pending | Demo\n'
        details = '  Details: "Use a small dataset first."\n'
        unresolved = '  Clarification needed: which dataset?\n'
        inbox = self.root / "inbox.md"
        inbox.write_text(raw + details + unresolved)
        self.call(state_main, ["--today", "2026-10-10", "--rebuild", "--json"])
        summary = self.call(state_main, ["--today", "2026-10-10", "--check", "--json"])
        self.assertEqual(summary["inbox"]["pending"], 1)
        self.assertEqual(summary["inbox"]["total"], 1)
        self.assertEqual(inbox.read_text(), raw + details + unresolved)


if __name__ == "__main__":
    unittest.main()
