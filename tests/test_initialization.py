"""Initialization failure regressions; synthetic inputs, no real providers."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from support import TEMP_ROOT
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from goodmorning import setup_check
from goodmorning.news import news


class InitializationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_missing_runtime_preflight_never_creates_files_or_fetches(self):
        path = self.root / "missing"
        out = io.StringIO()
        with patch.object(setup_check.subprocess, "Popen", side_effect=AssertionError("network")), contextlib.redirect_stdout(out):
            self.assertEqual(setup_check.main(["--secretary-dir", str(path)]), 1)
        self.assertFalse(path.exists())
        self.assertEqual(json.loads(out.getvalue())["missing_fields"], ["secretary_language", "city", "timezone", "news_country"])

    def test_ready_profile_does_not_require_optional_context_or_integrations(self):
        (self.root / "profile.md").write_text("secretary_language: English\ncity: London, GB\ntimezone: Europe/London\nnews_country: GB\nnews_additional_countries: CN, GB\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(setup_check.main(["--secretary-dir", str(self.root)]), 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["countries"], ["GB", "CN"])
        self.assertEqual(data["checks"], {})
        self.assertFalse(data["verification_complete"])
        self.assertEqual(data["language_status"], "confirmed")
        self.assertEqual(list(self.root.iterdir()), [self.root / "profile.md"])

    def test_parallel_checks_share_hard_elapsed_deadline(self):
        command = [sys.executable, "-c", "import time; time.sleep(5)"]
        started = time.monotonic()
        result = setup_check.run_checks({"a": command, "b": command}, 0.15)
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(all(row["reason"] == "timeout" for row in result.values()))

    def test_new_profile_language_is_required_but_never_defaulted(self):
        (self.root / "profile.md").write_text('secretary_language: ""\ncity: London, GB\ntimezone: Europe/London\nnews_country: GB\n')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(setup_check.main(["--secretary-dir", str(self.root)]), 1)
        data = json.loads(output.getvalue())
        self.assertEqual(data["missing_fields"], ["secretary_language"])
        self.assertIsNone(data["secretary_language"])
        self.assertEqual(data["language_status"], "missing")

    def test_confirmed_language_is_independent_of_news_country_and_location(self):
        (self.root / "profile.md").write_text('secretary_language: 简体中文\ncity: London, GB\ntimezone: Europe/London\nnews_country: GB\n')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(setup_check.main(["--secretary-dir", str(self.root)]), 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["secretary_language"], "简体中文")
        self.assertEqual(data["language_status"], "confirmed")
        self.assertEqual(data["countries"], ["GB"])

    def test_optional_configuration_failures_preserve_valid_profile_and_do_not_fetch(self):
        (self.root / "profile.md").write_text("secretary_language: English\ncity: London, GB\ntimezone: Europe/London\nnews_country: XX\n")
        out = io.StringIO()
        with patch.object(setup_check.subprocess, "Popen", side_effect=AssertionError("network")), contextlib.redirect_stdout(out):
            self.assertEqual(setup_check.main(["--secretary-dir", str(self.root), "--verify", "news"]), 1)
        data = json.loads(out.getvalue())
        self.assertTrue(data["profile_ready"])
        self.assertEqual(data["checks"]["news:XX"]["reason"], "missing_or_invalid_country_feed_configuration")

    def test_zero_exit_with_partial_weather_is_not_verification_success(self):
        command = [sys.executable, "-c", 'print(\'{"country":"GB","warnings":[],"aqi":null}\')']
        result = setup_check.run_checks({"weather": command}, 1)
        self.assertEqual(result["weather"]["status"], "pending")

    def test_partial_check_keeps_counts_and_actionable_details(self):
        payload = {"status": "pending", "feeds": [{"name": "Synthetic", "dated_items": 0}], "next": "Choose supported feeds."}
        command = [sys.executable, "-c", "import sys; print(" + repr(json.dumps(payload)) + "); sys.exit(1)"]
        result = setup_check.run_checks({"news": command}, 1)
        self.assertEqual(result["news"]["status"], "pending")
        self.assertEqual(result["news"]["result"], payload)

    def test_national_verification_calls_only_chosen_feeds_and_creates_no_cache(self):
        config = {"feeds": [{"name": "Unneeded world", "url": "https://world.invalid/feed", "section": "major"}],
                  "countries": {"GB": [{"name": "Chosen national", "url": "https://national.invalid/feed", "section": "national"}]}}
        import datetime as dt
        raw = [{"title": "Synthetic national item", "url": "https://national.invalid/story", "published": dt.datetime.now(dt.timezone.utc)}]
        out = io.StringIO()
        with patch.object(news, "load_sources", return_value=config), patch.object(news, "fetch_rss", return_value=raw) as fetch, contextlib.redirect_stdout(out):
            code = news.main(["--verify-sources", "--country", "GB", "--timezone", "UTC", "--cache-dir", str(self.root / "unused")])
        self.assertEqual(code, 0)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.args[0], "https://national.invalid/feed")
        self.assertFalse((self.root / "unused").exists())
        self.assertNotIn("stories", json.loads(out.getvalue()))


if __name__ == "__main__":
    unittest.main()
