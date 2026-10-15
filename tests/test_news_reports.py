"""Managed news workflow; fake feeds only, never user profiles or live providers."""

import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from support import TEMP_ROOT
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from goodmorning.news import news
from goodmorning.records import state
from goodmorning.news.news_reports import MAX_ATTEMPTS, ReportStore, context_key, recent_days
from goodmorning.runtime_files import runtime_lock

TODAY = dt.date(2026, 10, 9)
DAY = "2026-10-08"
CFG = {"feeds": [{"name": "AI", "section": "ai", "url": "https://ai.example/feed"},
                 {"name": "World", "section": "major", "url": "https://world.example/feed"}],
       "countries": {"US": [{"name": "US", "section": "national", "url": "https://us.example/feed"}]}}


def payload(day=DAY, counts=None, notes=None):
    counts = counts or {"ai": 1, "major": 1, "national": 1}
    return {"date": day, "timezone": "UTC", "country": "US", "counts": counts,
            "notes": notes or [], "stories": [
                {"date": day, "section": section, "title": f"{section} headline {i}",
                 "outlets": 1, "links": [{"source": "Example", "url": f"https://example.com/{section}/{i}"}]}
                for section, count in counts.items() for i in range(count)]}


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.directory = self.tmp.name
        self.store = ReportStore(self.directory, create=True)
        self.addCleanup(self.store.close)
        self.context = context_key("UTC", "US", CFG)

    def test_collection_is_not_delivery_and_ack_is_idempotent(self):
        row = self.store.save(self.context, payload(), now=0)
        self.assertEqual(row["status"], "collected")
        self.assertIsNone(row["delivered_session"])
        delivered = self.store.acknowledge(self.context, DAY, row["report_id"], "ses-first")
        self.assertEqual(delivered["status"], "delivered")
        again = self.store.acknowledge(self.context, DAY, row["report_id"], "ses-second")
        self.assertEqual(again["delivered_session"], "ses-first")

    def test_empty_sections_remain_unresolved(self):
        for counts, expected in (({"ai": 1, "major": 0, "national": 1}, "partial"),
                                 ({"ai": 0, "major": 0, "national": 0}, "missing")):
            row = self.store.save(self.context, payload(counts=counts), now=0)
            self.assertEqual(row["status"], expected)
            with self.assertRaisesRegex(ValueError, "report_unresolved"):
                self.store.acknowledge(self.context, DAY, row["report_id"], "ses-one")

    def test_stale_ack_cannot_mark_changed_report(self):
        first = self.store.save(self.context, payload(), now=0)
        second = self.store.save(self.context, payload(notes=["source unavailable"]), now=1)
        self.assertNotEqual(first["report_id"], second["report_id"])
        with self.assertRaisesRegex(ValueError, "report_conflict"):
            self.store.acknowledge(self.context, DAY, first["report_id"], "ses-old")
        self.assertEqual(self.store.get(self.context, DAY)["status"], "collected")

    def test_delivery_during_collection_is_not_overwritten(self):
        first = self.store.save(self.context, payload(), now=0)
        self.store.acknowledge(self.context, DAY, first["report_id"], "ses-one")
        row = self.store.save(self.context, payload(notes=["different"]), now=1)
        self.assertEqual(row["status"], "delivered")
        self.assertEqual(row["report_id"], first["report_id"])
        row = self.store.save(self.context, payload(notes=["different"]), now=2, refresh=True)
        self.assertEqual(row["status"], "collected")

    def test_partial_retry_cooldown_and_attempt_cap(self):
        item = payload(counts={"ai": 1, "major": 0, "national": 0})
        for i in range(MAX_ATTEMPTS):
            self.store.save(self.context, item, now=i * 4000)
            self.assertFalse(self.store.plan(self.context, [DAY], now=i * 4000 + 1)[0]["fetch"])
        plan = self.store.plan(self.context, [DAY], now=999999)[0]
        self.assertTrue(plan["exhausted"])
        self.assertFalse(plan["fetch"])
        self.assertTrue(self.store.plan(self.context, [DAY], now=999999, refresh=True)[0]["fetch"])

    def test_offline_attempts_do_not_exhaust_network_retries(self):
        self.store.save(self.context, payload(counts={"ai": 0, "major": 0, "national": 0}),
                        now=0, offline=True)
        self.assertEqual(self.store.get(self.context, DAY)["attempts"], 0)

    def test_changed_country_timezone_and_sources_are_separate(self):
        self.store.save(self.context, payload(), now=0)
        for context in (context_key("America/New_York", "US", CFG),
                        context_key("UTC", "CA", CFG),
                        context_key("UTC", "US", {**CFG, "feeds": []})):
            self.assertIsNone(self.store.get(context, DAY))

    def test_corrupt_payload_is_not_treated_as_missing(self):
        self.store.save(self.context, payload(), now=0)
        with self.store.db:
            self.store.db.execute("UPDATE reports SET payload='{}'")
        with self.assertRaisesRegex(ValueError, "invalid saved"):
            self.store.plan(self.context, [DAY])

    def test_save_over_corrupt_row_raises_and_preserves_it(self):
        self.store.save(self.context, payload(), now=0)
        with self.store.db:
            self.store.db.execute("UPDATE reports SET payload='{}'")
        query = "SELECT * FROM reports WHERE context=? AND day=?"
        before = tuple(self.store.db.execute(query, (self.context, DAY)).fetchone())
        with self.assertRaises(ValueError):
            self.store.save(self.context, payload(notes=["retry"]), now=1, refresh=True)
        self.assertEqual(tuple(self.store.db.execute(query, (self.context, DAY)).fetchone()), before)

    def test_bad_counts_are_rejected_before_transaction(self):
        item = payload()
        item["counts"]["ai"] = 10
        with self.assertRaisesRegex(ValueError, "counts disagree"):
            self.store.save(self.context, item)
        self.assertIsNone(self.store.get(self.context, DAY))

    def test_database_identity_and_future_version_are_preserved(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = Path(directory) / "news_reports.sqlite"
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE unrelated (value TEXT)")
            db.commit()
            db.close()
            with self.assertRaises(ValueError):
                ReportStore(directory, create=True)
            db = sqlite3.connect(path)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone()[0], "unrelated")
            db.execute("PRAGMA user_version=999")
            db.close()
            with self.assertRaises(ValueError):
                ReportStore(directory, create=True)


class ManagedCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "profile.md").write_text('timezone: "UTC"\nnews_country: "US"\n')
        self.config = patch.object(news, "load_sources", return_value=CFG)
        self.config.start()
        self.addCleanup(self.config.stop)
        self.calls = []

    def rss(self, url, *args):
        self.calls.append(url)
        return [{"title": "OpenAI releases reasoning model" if "ai." in url else "Government approves national budget legislation",
                 "url": url.replace("feed", f"story-{i}"),
                 "published": dt.datetime.combine(TODAY - dt.timedelta(days=i), dt.time(12), dt.timezone.utc)}
                for i in range(1, 8)]

    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                patch.object(news, "fetch_rss", side_effect=self.rss), \
                patch.object(news, "fetch_hn", return_value=[]):
            code = news.main(["--secretary-dir", str(self.root), "--cache-dir", str(self.root / "cache"),
                              "--today", TODAY.isoformat(), *args])
        return code, json.loads(out.getvalue()) if out.getvalue() else None, err.getvalue()

    def test_status_is_read_only_and_initializes_nothing(self):
        before = sorted(p.name for p in self.root.iterdir())
        code, result, _ = self.invoke("--status")
        self.assertEqual(code, 0)
        self.assertEqual(len(result["days"]), 7)
        self.assertEqual(self.calls, [])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)

    def test_end_to_end_backfill_show_ack_state_overview_and_no_repeat_fetch(self):
        code, result, _ = self.invoke("--backfill")
        self.assertEqual(code, 0)
        self.assertTrue(all(d["status"] == "collected" for d in result["days"]))
        self.assertNotIn("stories", result)
        self.assertEqual(len(self.calls), 3)
        code, report, _ = self.invoke("--show", DAY)
        self.assertEqual(code, 0)
        self.assertEqual(report["counts"], {"ai": 1, "major": 1, "national": 1})
        code, ack, _ = self.invoke("--ack", DAY, "--expect", report["report_id"], "--session", "ses-gm")
        self.assertEqual(code, 0)
        self.assertEqual(ack["status"], "delivered")
        self.calls.clear()
        code, repeat, _ = self.invoke("--backfill")
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(repeat["fetch"]["requests"], 0)
        overview = state.news_overview(str(self.root), TODAY.isoformat())
        self.assertEqual(overview["delivered"], 1)
        self.assertEqual(overview["collected"], 6)

    def test_markdown_news_heading_cannot_claim_delivery(self):
        (self.root / "daily").mkdir()
        (self.root / "daily" / f"{DAY}.md").write_text("## news\nNo items.\n")
        code, result, _ = self.invoke("--status")
        self.assertTrue(all(d["status"] == "missing" for d in result["days"]))

    def test_failed_feed_partial_keeps_private_free_notes_and_cannot_be_acknowledged(self):
        original = self.rss

        def failing(url, *args):
            if "world." in url:
                raise OSError("PRIVATE provider detail")
            return original(url, *args)

        self.rss = failing
        code, result, _ = self.invoke("--backfill")
        self.assertEqual(code, 1)
        self.assertTrue(all(d["status"] == "partial" for d in result["days"]))
        _, report, _ = self.invoke("--show", DAY)
        self.assertEqual(report["status"], "partial")
        self.assertTrue(report["notes"])
        self.assertNotIn("PRIVATE", json.dumps(report))
        code, error, _ = self.invoke("--ack", DAY, "--expect", report["report_id"], "--session", "ses-gm")
        self.assertEqual(code, 2)
        self.assertEqual(error["error"], "report_unresolved")
        self.calls.clear()
        self.invoke("--backfill")
        self.assertEqual(self.calls, [])

    def test_invalid_ack_session_is_refused_and_report_stays_collected(self):
        self.invoke("--backfill")
        _, report, _ = self.invoke("--show", DAY)
        code, error, _ = self.invoke("--ack", DAY, "--expect", report["report_id"], "--session", "bad session!")
        self.assertEqual(code, 2)
        self.assertIn("error", error)
        _, after, _ = self.invoke("--show", DAY)
        self.assertEqual(after["status"], "collected")
        self.assertEqual(after["report_id"], report["report_id"])

    def test_show_and_ack_do_not_fetch(self):
        self.invoke("--backfill")
        self.calls.clear()
        _, report, _ = self.invoke("--show", DAY)
        self.invoke("--ack", DAY, "--expect", report["report_id"], "--session", "ses-ok")
        self.assertEqual(self.calls, [])

    def test_country_is_never_inferred_from_city(self):
        (self.root / "profile.md").write_text('timezone: "UTC"\ncity: "London, GB"\n')
        with self.assertRaises(SystemExit) as stopped:
            self.invoke("--backfill")
        self.assertNotIn(stopped.exception.code, (0, None))
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / "news_reports.sqlite").exists())

    def test_explicit_refresh_reopens_changed_delivered_report(self):
        self.invoke("--backfill")
        _, report, _ = self.invoke("--show", DAY)
        self.invoke("--ack", DAY, "--expect", report["report_id"], "--session", "ses-gm")
        original = self.rss
        self.rss = lambda url, *args: [{**i, "title": i["title"] + " changed"} for i in original(url, *args)]
        _, result, _ = self.invoke("--backfill", "--refresh")
        self.assertEqual(result["days"][0]["status"], "collected")
        self.assertNotEqual(result["days"][0]["report_id"], report["report_id"])

    def test_news_lock_prevents_provider_calls(self):
        with runtime_lock(str(self.root), ".news.lock"):
            code, error, _ = self.invoke("--backfill")
        self.assertEqual(code, 1)
        self.assertEqual(error["error"], "runtime_busy")
        self.assertEqual(self.calls, [])

    def test_profile_news_sources_path_is_used(self):
        (self.root / "profile.md").write_text('timezone: UTC\nnews_country: US\nnews_sources_path: secretary/custom-feeds.json\n')
        self.invoke("--status")
        news.load_sources.assert_called_with("secretary/custom-feeds.json")

    def test_sparse_backfill_queries_hn_only_for_unresolved_dates(self):
        self.invoke("--backfill")
        context = context_key("UTC", "US", CFG)
        store = ReportStore(str(self.root), create=True)
        try:
            for day in ("2026-10-02", "2026-10-08"):
                with store.db:
                    store.db.execute("DELETE FROM reports WHERE context=? AND day=?", (context, day))
        finally:
            store.close()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch.object(news, "fetch_rss", side_effect=self.rss), \
                patch.object(news, "fetch_hn", return_value=[]) as hn:
            result = news.main(["--backfill", "--secretary-dir", str(self.root),
                                "--cache-dir", str(self.root / "cache"), "--today", str(TODAY)])
        self.assertEqual(result, 0)
        self.assertEqual(hn.call_count, 2)

    def test_recent_window_prioritizes_yesterday_across_dst(self):
        days = recent_days(dt.date(2026, 11, 2))
        self.assertEqual(days[0], "2026-11-01")
        self.assertEqual(days[-1], "2026-10-26")

    def test_presentation_options_do_not_hide_existing_reports(self):
        self.invoke("--backfill", "--max-items", "2", "--max-links", "2")
        code, report, _ = self.invoke("--show", DAY)
        self.assertEqual(code, 0)
        self.assertEqual(report["max_items"], 2)
        self.calls.clear()
        self.invoke("--backfill", "--max-items", "5")
        self.assertEqual(self.calls, [])

    def test_older_window_and_backlog_are_explicit_and_bounded(self):
        self.invoke("--backfill", "--ending", "2026-10-01")
        code, old, _ = self.invoke("--status", "--ending", "2026-10-01")
        self.assertEqual(code, 0)
        self.assertEqual(len(old["days"]), 7)
        self.assertEqual(old["days"][0]["date"], "2026-10-01")
        _, current, _ = self.invoke("--status")
        self.assertEqual(current["older_undelivered"], {"counts": {"missing": 7}, "ending": "2026-10-01"})


if __name__ == "__main__":
    unittest.main()
