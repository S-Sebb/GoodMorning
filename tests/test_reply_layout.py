"""Structured reply examples preserve content without framing or decorative bold."""

from pathlib import Path
import re
import unittest

from benchmark_reply_templates import fixtures, render

ROOT = Path(__file__).resolve().parents[1]


class LayoutTests(unittest.TestCase):
    def test_short_greeting_goes_directly_to_first_section(self):
        _, values, _ = fixtures()
        reply = render("gm", values)
        before_weather = reply.split("## Weather", 1)[0]
        self.assertEqual([line for line in before_weather.splitlines() if line.strip() and line != "---"],
                         [values["greeting"] + " — " + values["date"]])

    def test_weather_order_and_optional_extreme_warning(self):
        _, values, _ = fixtures()
        weather = values["weather"]
        self.assertLess(weather.index("### Temperature"), weather.index("### Precipitation"))
        self.assertLess(weather.index("### Precipitation"), weather.index("### AQI"))
        self.assertNotIn("### Extreme weather warning", weather)
        extreme = "### Extreme weather warning\n- Flood warning; avoid the affected route.\n\n"
        values["weather"] = weather.replace("### AQI", extreme + "### AQI")
        reply = render("gm", values)
        self.assertLess(reply.index("### Precipitation"), reply.index("### Extreme weather warning"))
        self.assertLess(reply.index("### Extreme weather warning"), reply.index("### AQI"))

    def test_major_sections_use_headings_rules_and_no_bold_dividers(self):
        _, values, _ = fixtures()
        reply = render("gm", values)
        for heading in ("Weather", "News —", "Schedule", "Must-do", "Nice-to-do", "Reminders"):
            self.assertIn("\n---\n\n## " + heading, reply)
        self.assertIn("### AI", reply)
        self.assertIn("### World", reply)
        self.assertNotRegex(reply, r"(?m)^\*\*[^\n]+\*\*$")

    def test_calendar_is_a_timetable_in_morning_and_night(self):
        _, morning, night = fixtures()
        for kind, values in (("gm", morning), ("gn", night)):
            reply = render(kind, values)
            self.assertIn("| Date | Time | Event | Place | Preparation |", reply)
            self.assertIn("| 2026-10-10 | 10:00–11:00 | Demo review | Room A | bring slides |", reply)

    def test_source_summaries_are_used_directly_with_links(self):
        report, values, _ = fixtures()
        reply = render("gm", values)
        for story in report["stories"]:
            self.assertIn(story["summary"], reply)
            self.assertIn(story["links"][0]["url"], reply)
        self.assertNotIn("worth your attention", reply)

    def test_instructions_require_neutral_summaries_and_timetable(self):
        shared = (ROOT / "docs/skill-rules.md").read_text()
        template = (ROOT / "templates/gm.reply.template.md").read_text()
        for marker in ("Weather order", "chronological timetable", "Bold only", "No extra", "Neutral assessment"):
            self.assertIn(marker, shared)
        self.assertIn("No news preambles", (ROOT / ".opencode/skills/gm/SKILL.md").read_text())
        self.assertIn("existing source summary", re.sub(r"\s+", " ", template))

    def test_brief_takeaways_and_closing_do_not_displace_structure_or_sources(self):
        report, values, _ = fixtures()
        reply = render("gm", values)
        self.assertIn("Light layers should be comfortable", reply.split("\n---\n\n## News", 1)[0])
        self.assertTrue(reply.rstrip().endswith(values["closing"]))
        self.assertEqual(len(values["closing"].split(". ")), 2)
        for story in report["stories"]:
            self.assertIn(story["summary"], reply)
            self.assertIn(story["links"][0]["url"], reply)
        self.assertIn("| Date | Time | Event | Place | Preparation |", reply)
        self.assertNotIn("Let's give the important things a little room to breathe", reply)

    def test_optional_flavor_is_grounded_not_required_or_news_padding(self):
        guide = (ROOT / "docs/reply-voice.md").read_text()
        template = (ROOT / "templates/gm.reply.template.md").read_text()
        self.assertIn("optional one- or two-sentence takeaway", guide)
        self.assertIn("Do not repeat the whole section", guide)
        self.assertIn("Neither summaries nor closing", template)
        self.assertIn("No long pep talk", template)

    def test_yesterday_only_preference_excludes_same_day_sections(self):
        skill = (ROOT / ".opencode/skills/gm/SKILL.md").read_text()
        shared = (ROOT / "docs/skill-rules.md").read_text()
        template = (ROOT / "templates/gm.reply.template.md").read_text()
        self.assertIn("today's news waits", skill)
        self.assertIn("news_latest: false", skill)
        self.assertIn("no same-day fetch or section", shared)
        self.assertIn("9 October stories wait until the 10 October briefing", template)

    def test_night_layout_starts_directly_and_retains_the_warm_closing(self):
        _, _, night = fixtures()
        reply = render("gn", night)
        before_today = reply.split("## Today", 1)[0]
        self.assertEqual([line for line in before_today.splitlines() if line.strip() and line != "---"],
                         [night["greeting"] + " — " + night["date"]])
        for heading in ("Today", "Still open", "Tomorrow", "Reminders"):
            self.assertIn("\n---\n\n## " + heading, reply)
        self.assertTrue(reply.rstrip().endswith(night["closing"]))
        self.assertNotRegex(reply, r"(?m)^\*\*[^\n]+\*\*$")

    def test_night_instructions_separate_reported_progress_from_calendar_and_agent_work(self):
        skill = (ROOT / ".opencode/skills/gn/SKILL.md").read_text()
        template = (ROOT / "templates/gn.reply.template.md").read_text()
        for marker in ("actual outcomes", "this agent", "unfinished", "chronological rows", "while waiting for feedback"):
            self.assertIn(marker, skill)
        self.assertIn("Task / Reported outcome / Next step", template)
        self.assertIn("not the timetable", template)


if __name__ == "__main__":
    unittest.main()
