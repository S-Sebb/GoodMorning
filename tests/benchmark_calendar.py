"""Synthetic comparison with the old full-file scan and verbose schedule JSON."""

import json
from pathlib import Path
import statistics
import sys
import tempfile
from support import TEMP_ROOT
from time import perf_counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from calendar_store import CalendarStore, encode
from secretary_calendar import _CUSTOM_LINE


def main():
    with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder:
        folder = Path(folder)
        store = CalendarStore(str(folder / "calendar.sqlite"))
        origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
        notes = "Bring slides and review the agenda before the meeting. " * 9
        items, lines = [], []
        for i in range(10000):
            start = origin + timedelta(days=i // 10, hours=i % 10 + 8)
            end = start + timedelta(hours=1)
            title = f"Meeting {i}"
            items.append(({"subject": title, "start": start.isoformat(), "end": end.isoformat(),
                           "location": "Room 301", "notes": notes}, None))
            lines.append(f"- {start:%Y-%m-%d %H:%M}-{end:%H:%M} | {title} | Room 301 | {notes}\n")
        store.add_many(items, "benchmark")
        markdown = folder / "custom_schedule.md"
        markdown.write_text("".join(lines))
        start, end = origin + timedelta(days=280), origin + timedelta(days=283)

        def legacy_scan():
            rows = []
            with markdown.open() as f:
                for line in f:
                    day, s, e, subject, location, description = _CUSTOM_LINE.match(line).groups()
                    s = datetime.fromisoformat(f"{day}T{s}").replace(tzinfo=timezone.utc)
                    e = datetime.fromisoformat(f"{day}T{e}").replace(tzinfo=timezone.utc)
                    if e >= start and s <= end:
                        rows.append({"subject": subject.strip(), "start": s.isoformat(), "end": e.isoformat(),
                                     "location": location.strip(), "online": "", "organizer": "",
                                     "source": "custom", "prep": "allow travel, confirm Room 301",
                                     "notes": description.strip()[:500]})
            return rows

        def measure(fn):
            timings = []
            for _ in range(10):
                before = perf_counter()
                result = fn()
                timings.append((perf_counter() - before) * 1000)
            return statistics.median(timings), result

        old_ms, old = measure(legacy_scan)
        new_ms, new = measure(lambda: store.query(start, end))
        for row in new:
            row["prep"] = "allow travel, confirm Room 301"
        old_text, new_text = json.dumps(old, ensure_ascii=False, indent=2), encode(new)
        self_check = len(old) == len(new) == 30
        assert self_check
        store.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store.close()
        print(encode({"events": 10000, "window_days": 3, "returned": len(new), "iterations": 10,
                      "legacy_scan_median_ms": round(old_ms, 3), "sqlite_query_median_ms": round(new_ms, 3),
                      "legacy_json_chars": len(old_text), "compact_json_chars": len(new_text),
                      "legacy_tokens_est": (len(old_text) + 3) // 4,
                      "compact_tokens_est": (len(new_text) + 3) // 4,
                      "markdown_bytes": markdown.stat().st_size,
                      "sqlite_with_history_bytes": (folder / "calendar.sqlite").stat().st_size,
                      "token_method": "chars/4 heuristic, not a tokenizer"}))


if __name__ == "__main__":
    main()
