"""Network-free evidence for bounded summaries and snapshot/report reuse."""

import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import sys
import tempfile
from support import TEMP_ROOT
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import state
from news_reports import ReportStore, context_key, recent_days


def experiment():
    today = dt.date(2026, 10, 9)
    with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
        root = Path(directory)
        (root / "daily").mkdir()
        for i in range(120):
            day = (today - dt.timedelta(days=i)).isoformat()
            (root / "daily" / f"{day}.md").write_text(f"- gm: yes | answer: daily/{day}.gm.md\n- gn: no\n")
            (root / "daily" / f"{day}.gm.md").write_text("x" * 2000)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(state, "stat_answer", wraps=state.stat_answer) as reads:
            state.main(["--secretary-dir", directory, "--today", str(today), "--check", "--json"])
            cold_reads = reads.call_count
        compact_state = output.getvalue()
        value = json.loads(compact_state)
        assert value["answer_cost_30d"]["tokens_est"] == 15000
        with contextlib.redirect_stdout(io.StringIO()), patch.object(state, "stat_answer", wraps=state.stat_answer) as reads:
            state.main(["--secretary-dir", directory, "--today", str(today), "--check", "--json"])
            warm_reads = reads.call_count
        assert warm_reads == 0
        full = state.rebuild_index(directory, state.load_state(directory), str(today))
        unbounded_state = json.dumps({**value, "missed": state.missed_days(full, str(today))}, indent=2)

        cfg = {"feeds": [], "countries": {"US": []}}
        context = context_key("UTC", "US", cfg)
        store = ReportStore(directory, create=True)
        reports = []
        try:
            for day in recent_days(today):
                stories = [{"date": day, "section": section,
                            "title": f"Example {section} development number {i}: detailed publisher headline",
                            "outlets": 1, "links": [{"source": "Example",
                                                       "url": f"https://example.com/{day}/{section}/{i}"}]}
                           for section in ("ai", "major", "national") for i in range(4)]
                row = store.save(context, {"date": day, "timezone": "UTC", "country": "US",
                                          "counts": {"ai": 4, "major": 4, "national": 4},
                                          "stories": stories, "notes": []}, now=0)
                reports.append(row["payload"])
            manifest = json.dumps(store.plan(context, recent_days(today)), separators=(",", ":"))
            all_reports = json.dumps(reports, separators=(",", ":"))
            assert sum(sum(r["counts"].values()) for r in reports) == 84
        finally:
            store.close()

        metrics = {"state": {"unbounded_summary_chars": len(unbounded_state),
                             "bounded_summary_chars": len(compact_state),
                             "summary_reduction_percent": round(100 * (1 - len(compact_state) / len(unbounded_state)), 1),
                             "missed_total": value["missed_total"], "missed_rows_returned": len(value["missed"]),
                             "old_full_rebuild_snapshot_reads": 120,
                             "cold_snapshot_reads": cold_reads, "warm_snapshot_reads": warm_reads,
                             "answer_cost_30d_tokens_est": value["answer_cost_30d"]["tokens_est"]},
                   "news": {"all_saved_report_chars": len(all_reports), "manifest_chars": len(manifest),
                            "manifest_reduction_percent": round(100 * (1 - len(manifest) / len(all_reports)), 1),
                            "stories_retained": 84, "repeat_reports_needing_fetch": sum(e["fetch"] for e in json.loads(manifest))},
                   "limits": "chars measure output size, not exact tokens; summaries page/gate detail rather than discard it; no live services tested"}
        print(json.dumps(metrics, separators=(",", ":")))


if __name__ == "__main__":
    experiment()
