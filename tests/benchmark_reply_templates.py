"""Render synthetic replies without a model, network, or personal runtime data."""

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def render(kind, values):
    document = (ROOT / "templates" / f"{kind}.reply.template.md").read_text()
    body = re.search(r"```markdown\n(.*?)\n```", document, re.S).group(1)
    return body.format_map(values).strip() + "\n"


def fixtures():
    report = {"date": "2026-10-08", "timezone": "UTC", "country": "US",
              "counts": {"ai": 1, "major": 1, "national": 1},
              "notes": ["World feed: stale cached response"],
              "stories": [
                  {"date": "2026-10-08", "section": section, "title": title,
                   "outlets": 1, "links": [{"source": "Example", "url": f"https://example.invalid/{section}"}],
                   **({"date_basis": "submitted"} if section == "ai" else {})}
                  for section, title in (("ai", "AI research tool released"),
                                         ("major", "World research agreement announced"),
                                         ("national", "National research funding announced"))]}
    summaries = {"ai": "Researchers released a tool for reproducible AI research.",
                 "major": "Research agencies announced a joint agreement.",
                 "national": "A national programme announced new research funding."}
    for story in report["stories"]:
        story["summary"] = summaries[story["section"]]
    lines = {s["section"]: f"- {s['title']}. {s['summary']} [Example]({s['links'][0]['url']})"
             + ("; submission date, not publication" if s.get("date_basis") else "")
             for s in report["stories"]}
    morning = {"greeting": "Good morning, you", "date": "2026-10-09",
               "weather": "### Temperature\n- 12–18°C; a mild day.\n"
                          "- Weather STALE: last updated at 07:00 UTC; refresh failed.\n\n"
                          "### Precipitation\n- Rain likely. I'd keep the umbrella handy.\n\n"
                          "### AQI\n- AQI 27, good.\n\n"
                          "Light layers should be comfortable; keep your wet-weather plan in mind.",
               "news_date": report["date"], "news_country": "US", "news_ai": lines["ai"],
               "news_world": lines["major"], "news_national": lines["national"],
               "schedule": "Timezone: UTC\n\n| Date | Time | Event | Place | Preparation |\n"
                           "|---|---|---|---|---|\n"
                           "| 2026-10-10 | 10:00–11:00 | Demo review | Room A | bring slides |",
               "must_do": "- [ ] Draft Demo's outline. High priority; estimate 30 minutes.\n"
                          "  - Goal: a clear structure for tomorrow's review.\n"
                          "  - I'd start with the main questions; we can polish the wording afterward.",
               "nice_to_do": "- [ ] If you have time, you could do some optional reading for Demo. "
                             "The current estimate is about 20 minutes.",
               "reminders": "- World news coverage is incomplete (stale cached source). "
                            "One idea needs clarification; revisit it at /gn.",
               "closing": "If you'd like, we can start with the outline's main question and give the rest a clearer shape. "
                          "I'm quite happy to help you untangle that part."}
    night = {"greeting": "Good evening, you", "date": "2026-10-09", "progress": "- Demo outline completed—a useful foundation for tomorrow's review.",
             "open_tasks": "- The optional reading is still open. If it still feels useful, "
                           "a manageable next step would be to read one paper tomorrow.",
             "tomorrow_date": "2026-10-10", "tomorrow_schedule": morning["schedule"],
             "reminders": "- There is one idea still waiting to be clarified. We can look at it now, "
                          "or pick it up at the next /gm—whichever works better for you.",
             "closing": "You've given tomorrow's review a useful foundation. Good night, you—we can pick up the optional reading when it suits your plan."}
    return report, morning, night


def experiment():
    report, morning, night = fixtures()
    gm, gn = render("gm", morning), render("gn", night)
    verbose = json.dumps({"weather": morning["weather"], "news": report,
                          "schedule": morning["schedule"], "tasks": {
                              "must_do": morning["must_do"], "nice_to_do": morning["nice_to_do"]},
                          "reminders": morning["reminders"]}, indent=2)
    print(json.dumps({"gm_chars": len(gm), "gm_tokens_est": (len(gm) + 3) // 4,
                      "gn_chars": len(gn), "gn_tokens_est": (len(gn) + 3) // 4,
                      "verbose_fixture_chars": len(verbose),
                      "gm_reduction_percent": round(100 * (1 - len(gm) / len(verbose)), 1),
                      "stories_presented": len(report["stories"]),
                      "limits": "descriptive sizes, not reply budgets or quality scores; synthetic formatting only; "
                                "chars/4 is not exact model tokens; no live agent or provider tested"},
                     separators=(",", ":")))


if __name__ == "__main__":
    experiment()
