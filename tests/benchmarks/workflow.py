"""Synthetic context-size experiments; output characters, not actual billing."""

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import TEMP_ROOT
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from goodmorning.records.inbox_store import initialize, InboxStore, encode
from goodmorning.records.workflow import prepare
from goodmorning.records.state import cmd_check
from goodmorning.news.news_views import report_view


def main():
    with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
        root = Path(temporary)
        profile = 'city: "London, GB"\ntimezone: "UTC"\nnews_country: "GB"\nsecretary_language: "English"\nsecretary_tone: "Warm"\n'
        profile += "\n## Setup reference\n" + "- Reference prose not needed for this briefing.\n" * 80
        (root / "profile.md").write_text(profile)
        (root / "daily").mkdir()
        day = "2026-10-10"
        daily = f"# {day}\n## must-do\n" + "".join(f"- [ ] Synthetic task {n}\n" for n in range(20))
        daily += "\n## notes\n" + "Saved context not needed for a task selection.\n" * 100
        (root / "daily" / (day + ".md")).write_text(daily)
        initialize(root)
        store = InboxStore(root, write=True)
        try:
            for n in range(3):
                store.mutate("add", {"kind": "todo", "raw": f"Remember task {n}"}, "synthetic", str(n), day)
            old_state = io.StringIO()
            with patch.dict(os.environ, {"CALENDAR_DB_PATH": str(root / "calendar.sqlite")}), contextlib.redirect_stdout(old_state):
                cmd_check(str(root), day, True)
            before = len(profile) + len(daily) + len(old_state.getvalue()) + len(encode(store.list()))
        finally:
            store.close()
        with patch.dict(os.environ, {"CALENDAR_DB_PATH": str(root / "calendar.sqlite")}):
            after = len(encode(prepare(root, "gm", day)))
    stories = [{"date": day, "section": section, "title": f"Story {n}", "summary": "Known source claim. " * 12,
                "links": [{"source": "Synthetic", "url": f"https://example.invalid/{section}/{n}"}]}
               for section in ("ai", "major", "national") for n in range(30)]
    payload = {"date": day, "counts": {"ai": 4, "major": 4, "national": 4}, "notes": ["A material warning"],
               "stories": [story for n, story in enumerate(stories) if n % 30 < 4], "candidates": stories,
               "source_status": ["Collection diagnostics" * 30] * 20, "curation": {"state": "reviewed"}}
    row = {"payload": payload, "report_id": "synthetic", "status": "collected", "collected_at": 1}
    full, brief = len(encode(report_view(row, "full"))), len(encode(report_view(row, "stories")))
    assert report_view(row, "stories")["stories"] == payload["stories"]
    assert after < before and brief < full
    core_size = len((ROOT / "docs/core-rules.md").read_text())
    reference_size = len((ROOT / "docs/skill-rules.md").read_text())
    print(encode({"synthetic": True, "measures": "characters, not billed model tokens",
                  "preparation": {"before": before, "after": after, "reduction_percent": round(100 * (1-after/before), 1)},
                  "reviewed_news": {"before": full, "after": brief, "all_selected_stories_preserved": True,
                                    "reduction_percent": round(100 * (1-brief/full), 1)},
                  "instruction_sizes": {"core_characters": core_size,
                                        "edge_reference_characters": reference_size,
                                        "note": "Current documents, not a before/after agent-quality comparison"}}))


if __name__ == "__main__":
    main()
