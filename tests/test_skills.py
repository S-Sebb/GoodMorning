"""Skill/command contracts and a deterministic fake-data morning/night dry run."""

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

KINDS = ("gm", "gn", "eureka", "secretary")


class SkillContractTests(unittest.TestCase):
    def test_skills_have_discoverable_metadata_and_complete_workflows(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                path = ROOT / ".opencode/skills" / kind / "SKILL.md"
                text = path.read_text()
                metadata = re.match(r"---\n(.*?)\n---\n", text, re.S).group(1)
                self.assertIn(f"name: {kind}\n", metadata + "\n")
                self.assertRegex(metadata, r"description: .+")
                for marker in ("Trigger:", "Inputs:", "Output:", "##", "Errors"):
                    self.assertIn(marker, text)
                references = re.findall(r"`(\.\./\.\./\.\./[^`]+)`", text)
                self.assertGreaterEqual(len(references), 2)
                for reference in references:
                    self.assertTrue((path.parent / reference).resolve().is_file(), reference)
                self.assertIn("skill-rules.md", text)
                self.assertLess(len(text), 6500)

    def test_slash_commands_load_exact_skills_without_execution_or_delegation(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                text = (ROOT / ".opencode/commands" / f"{kind}.md").read_text()
                self.assertIn(f"Load the `{kind}` skill using the skill tool", text)
                self.assertEqual(text.count("$ARGUMENTS"), 1)
                self.assertIn("subagent: false", text)
                self.assertNotIn("!`", text)
                self.assertNotRegex(text, r"(?m)^(?:agent|model):")

    def test_shared_rules_preserve_delivery_and_confirmation_boundaries(self):
        text = (ROOT / "docs/skill-rules.md").read_text()
        for required in ("Never acknowledge before sending", "partial", "--expect-revision",
                         "outcome_unknown", "--force", "runtime_busy", "SECRETARY_DIR",
                         "Never use a made-up", "Do not silently backdate"):
            self.assertIn(required, text)

    def test_skills_prefer_interactive_questions_with_consent_and_fallback(self):
        shared = (ROOT / "docs/skill-rules.md").read_text()
        for required in ("`question` tool", "structured question UI in OpenChamber",
                         "multiple: true", "built-in custom-answer input",
                         "not consent", "unavailable or unusable", "normal conversation and wait",
                         "Do not ask again", "customised", "Optional personal-context questions offer a skip"):
            self.assertIn(required, shared)
        for kind in KINDS:
            with self.subTest(kind=kind):
                skill = (ROOT / ".opencode/skills" / kind / "SKILL.md").read_text()
                template = (ROOT / "templates" / f"{kind}.reply.template.md").read_text()
                self.assertIn("`question`", skill)
                self.assertIn("`question`", template)

    def test_setup_invites_optional_role_context_and_all_skills_can_use_it(self):
        secretary = (ROOT / ".opencode/skills/secretary/SKILL.md").read_text()
        shared = (ROOT / "docs/skill-rules.md").read_text()
        for field in ("occupations", "expertise_fields"):
            self.assertIn(f"`{field}`", secretary)
            self.assertIn(f"`{field}`", shared)
        self.assertIn("These fields are optional", secretary)
        self.assertIn("You can skip", secretary)
        self.assertIn("older profiles remain valid", secretary)
        self.assertIn("across all four skills", shared)
        self.assertIn("Do not assume knowledge from a job", shared)

    def test_initialization_is_staged_bounded_and_does_not_launch_repairs(self):
        secretary = (ROOT / ".opencode/skills/secretary/SKILL.md").read_text()
        guide = (ROOT / "docs/initialization.md").read_text()
        for marker in ("setup_check.py", "--budget 20", "news_additional_countries",
                       "unsupported recurrence/imports remain pending", "If setup alone was requested, stop"):
            self.assertIn(marker, secretary)
        for marker in ("shared 20-second elapsed budget", "dummy", "Initialization need not import any events", "not a reason to restart setup",
                       "never a raw live-file copy", "not whether every preference", "not a code-writing detour"):
            self.assertIn(marker, guide)

    def test_reply_language_is_first_initialization_question_and_applies_across_skills(self):
        secretary = (ROOT / ".opencode/skills/secretary/SKILL.md").read_text()
        guide = (ROOT / "docs/initialization.md").read_text()
        shared = (ROOT / "docs/skill-rules.md").read_text()
        self.assertIn("first initialization question is `secretary_language`", secretary)
        self.assertIn("Wait for the answer before other setup questions", guide)
        self.assertLess(guide.index("Which language would you like"), guide.index("location/timezone"))
        self.assertIn("across gm/gn/eureka/secretary", shared)
        self.assertIn("raw captured ideas", shared)
        self.assertIn("For older profiles lacking it", shared)

    def test_all_four_reply_shapes_render_without_instructions_or_placeholders(self):
        report, morning, night = fixtures()
        cases = {"gm": morning, "gn": night,
                 "eureka": {"capture_status": "I've saved your idea for Demo as pending, so we can return to it.",
                            "next_question_or_action": "Would you like to clarify it together now, or leave it for later?"},
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


if __name__ == "__main__":
    unittest.main()
