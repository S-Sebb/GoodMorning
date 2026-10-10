"""Voice contract and synthetic preservation checks, not a human-style rating."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from reply_policy import boilerplate_categories
from benchmark_reply_templates import fixtures, render


class ReplyVoiceTests(unittest.TestCase):
    def test_all_skills_and_templates_reference_shared_voice_design(self):
        for kind in ("gm", "gn", "eureka", "todo", "secretary"):
            skill = (ROOT / "docs/workflows" / f"{kind}.md").read_text()
            template = (ROOT / "templates" / (kind + ".reply.template.md")).read_text()
            self.assertIn("reply-voice.md", skill)
            self.assertIn("reply-voice.md", template)

    def test_materiality_gate_does_not_remove_personality_or_require_brevity(self):
        shared = (ROOT / "docs/skill-rules.md").read_text()
        for marker in ("emotional acknowledgement", "not a brevity filter", "not a dashboard",
                       "not a decorative greeting", "emotionally responsive", "preserve agency"):
            self.assertIn(marker, shared.casefold())
        guide = (ROOT / "docs/reply-voice.md").read_text()
        for marker in ("playful, lightly flirty", "not a generated newspaper", "not necessarily a short response",
                       "Do not infer exhaustion", "not just facts decorated with a greeting"):
            self.assertIn(marker.casefold(), guide.casefold())

    def test_relational_language_is_not_boilerplate(self):
        text = ("Good morning, you. I'd rather the rain didn't get the last laugh. "
                "That blocker is real; let's make the next step more manageable. "
                "I'm interested in the connection you've drawn, and we can explore it together.")
        self.assertEqual(boilerplate_categories(text), [])

    def test_expressive_fixtures_keep_sources_facts_and_material_warnings(self):
        report, morning, night = fixtures()
        gm, gn = render("gm", morning), render("gn", night)
        for story in report["stories"]:
            self.assertIn(story["title"], gm)
            self.assertIn(story["links"][0]["url"], gm)
        for value in ("AQI 27", "STALE", "refresh failed", "10:00–11:00", "bring slides", "30 minutes"):
            self.assertIn(value, gm)
        self.assertIn("I'd keep the umbrella handy", gm)
        self.assertIn("we can polish", gm)
        self.assertIn("useful foundation", gn)
        self.assertIn("Good night, you", gn)
        self.assertNotIn("[x]", gm)
        self.assertEqual(boilerplate_categories(gm), [])
        self.assertEqual(boilerplate_categories(gn), [])


if __name__ == "__main__":
    unittest.main()
