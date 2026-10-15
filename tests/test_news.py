import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import sys
import tempfile
from support import TEMP_ROOT
import threading
import unittest
import urllib.error
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from goodmorning.news import news
from goodmorning.news.news_cache import Fetcher, MAX_BYTES, NewsCache

DAY = dt.date(2026, 10, 8)
UTC = dt.timezone.utc


def article(title="AI company releases new language model", url="https://example.com/story", section="ai"):
    return {"title": title, "url": url, "source": "Example", "lean": "unrated",
            "published": "2026-10-08T12:00:00+00:00", "date": DAY.isoformat(), "section": section}


class Response:
    def __init__(self, body=b"data", headers=None):
        self.body, self.headers = body, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size):
        return self.body[:size]


class ParsingTests(unittest.TestCase):
    def parse(self, xml):
        return news.fetch_rss("https://example.com/feed", 1, lambda *args: xml.encode())

    def test_rss_and_cleaning(self):
        items = self.parse("""<rss><channel><item><title>AI &amp; chips</title>
            <link>https://example.com/a</link><pubDate>Thu, 08 Oct 2026 12:00:00 GMT</pubDate>
            </item></channel></rss>""")
        self.assertEqual(items[0]["title"], "AI & chips")
        self.assertEqual(items[0]["published"].hour, 12)

    def test_rdf_dw(self):
        items = self.parse('''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
            xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
            <item><title>World headline</title><link>https://dw.com/a</link>
            <dc:date>2026-10-08T12:00:00Z</dc:date></item></rdf:RDF>''')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["published"].date(), DAY)

    def test_atom_alternate_and_updated(self):
        items = self.parse('''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
            <title>AI model</title><link rel="self" href="https://example.com/api"/>
            <link rel="alternate" href="https://example.com/story"/>
            <updated>2026-10-08T12:00:00Z</updated></entry></feed>''')
        self.assertEqual(items[0]["url"], "https://example.com/story")
        self.assertEqual(items[0]["published"], dt.datetime(2026, 10, 8, 12, tzinfo=UTC))
        self.assertEqual(items[0]["date_basis"], "updated")

    def test_invalid_feed(self):
        with self.assertRaises(ValueError):
            self.parse("<html><body>blocked</body></html>")

    def test_undated_naive_and_out_of_window_rejected(self):
        items = [{"title": "Story", "url": "https://example.com", "published": pub}
                 for pub in (None, dt.datetime(2026, 10, 8), dt.datetime(2026, 10, 9, tzinfo=UTC))]
        self.assertEqual(news.bucket(items, "Test", "ai", "unrated", DAY, DAY), [])

    def test_timezone_boundary(self):
        item = {"title": "Story", "url": "https://example.com", "published": "2026-10-09T00:30:00+00:00"}
        items = news.bucket([item], "Test", "ai", "unrated", DAY, DAY, ZoneInfo("America/New_York"))
        self.assertEqual(items[0]["date"], DAY.isoformat())

    def test_url_tracking_and_invalid_schemes(self):
        self.assertEqual(news.canonical_url("https://EXAMPLE.com/a?id=3&utm_source=rss#frag"),
                         "https://example.com/a?id=3")
        self.assertEqual(news.canonical_url("javascript:alert(1)"), "")
        self.assertEqual(news.canonical_url("https://user:password@example.com"), "")

    def test_ai_filter(self):
        self.assertTrue(news.is_ai("Claude releases a new model"))
        self.assertTrue(news.is_ai("Machine learning improves climate forecasting"))
        self.assertFalse(news.is_ai("What strangers learn from your political donation"))
        self.assertFalse(news.is_ai("Airline launches flight"))

    def test_hn_date_is_submission_not_publication(self):
        payload = {"hits": [{"title": "AI headline", "url": "https://example.com/a",
                              "created_at_i": 1791460800}]}
        items = news.fetch_hn(DAY, DAY, 1, fetch=lambda *args: json.dumps(payload).encode())
        self.assertEqual(items[0]["date_basis"], "submitted")

    def test_gdelt_date_is_first_seen(self):
        payload = {"articles": [{"title": "AI headline", "url": "https://example.com/a",
                                 "seendate": "20261008T120000Z"}]}
        items = news.fetch_gdelt("AI", DAY, DAY, 1, fetch=lambda *args: json.dumps(payload).encode())
        self.assertEqual(items[0]["date_basis"], "first_seen")


class StoryTests(unittest.TestCase):
    def test_exact_url_grouped_despite_title_difference(self):
        stories = news.group_stories([article(), article("A completely different headline")])
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["outlets"], 1)

    def test_publisher_not_retrieval_path_count(self):
        a, b = article(), article(url="https://example.com/other")
        b["source"] = "Hacker News"
        self.assertEqual(news.group_stories([a, b])[0]["outlets"], 1)

    def test_two_domains_counted(self):
        stories = news.group_stories([article(), article(url="https://other.com/story")])
        self.assertEqual(stories[0]["outlets"], 2)

    def test_numbers_and_negation_do_not_merge(self):
        a = article("AI company releases language model version 3")
        b = article("AI company releases language model version 4", "https://b.com/a")
        c = article("AI company never releases language model version 3", "https://c.com/a")
        self.assertEqual(len(news.group_stories([a, b, c])), 3)

    def test_no_transitive_merge(self):
        a = article("alpha beta gamma delta epsilon zeta", "https://a.com/a")
        b = article("alpha beta gamma delta epsilon eta", "https://b.com/a")
        c = article("alpha beta gamma delta eta theta", "https://c.com/a")
        self.assertEqual(len(news.group_stories([a, b, c])), 2)

    def test_dates_and_sections_separate(self):
        a, b, c = article(), article(section="major"), article()
        c["date"] = "2026-10-07"
        self.assertEqual(len(news.group_stories([a, b, c])), 3)

    def test_per_day_section_limits_and_diversity(self):
        stories = [news.group_stories([article(f"OpenAI releases reasoning model {i}" if section == 'ai' else f"Government approves national budget legislation {i}", f"https://site{i}.com/a", section)])[0]
                   for section in ("ai", "major", "national") for i in range(5)]
        result = news.select_stories(stories, 2)
        self.assertEqual(len(result), 6)
        self.assertEqual(news.coverage_for(result, DAY, DAY, "US")[DAY.isoformat()],
                         {"ai": 2, "major": 2, "national": 2})

    def test_compact_links_and_markdown_escape(self):
        story = news.group_stories([article("AI [click](evil) model")])[0]
        compact = news.compact_story(story, 1)
        self.assertNotIn("sources", compact)
        self.assertEqual(len(compact["links"]), 1)
        self.assertEqual(compact["outlets"], 1)
        self.assertIn(r"\[click\]", news.story_line_md(story))

    def test_nonpublication_dates_are_labeled(self):
        item = article()
        item["date_basis"] = "first_seen"
        story = news.group_stories([item])[0]
        self.assertEqual(news.compact_story(story, 1)["date_basis"], "first_seen")
        self.assertNotIn("date_basis", news.compact_story(news.group_stories([article()])[0], 1))


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.cache = NewsCache(self.directory.name)
        self.now = 1000000
        self.calls = []

    def tearDown(self):
        self.cache.close()
        self.directory.cleanup()

    def fetcher(self, response=None, **kwargs):
        def opener(request, **options):
            self.calls.append(request)
            if isinstance(response, Exception):
                raise response
            return response or Response(headers={"ETag": '"version1"'})
        return Fetcher(self.cache, opener=opener, clock=lambda: self.now, **kwargs)

    def test_repeat_run_no_network(self):
        self.assertEqual(self.fetcher().get("https://example.com/feed"), b"data")
        self.assertEqual(self.fetcher().get("https://example.com/feed"), b"data")
        self.assertEqual(len(self.calls), 1)

    def test_refresh_and_future_clock_entry(self):
        url = "https://example.com/feed"
        self.fetcher().get(url)
        self.fetcher(refresh=True).get(url)
        self.now -= 10
        self.fetcher().get(url)
        self.assertEqual(len(self.calls), 3)

    def test_secret_header_not_cached(self):
        url = "https://newsapi.org/feed"
        self.fetcher().get(url, headers={"X-Api-Key": "test-secret"})
        self.assertEqual(self.calls[0].get_header("X-api-key"), "test-secret")
        dump = "\n".join(self.cache.db.iterdump())
        self.assertNotIn("test-secret", dump)

    def test_conditional_304(self):
        url = "https://example.com/feed"
        self.fetcher().get(url)
        self.now += 3601
        f = self.fetcher(urllib.error.HTTPError(url, 304, "unchanged", {}, None))
        self.assertEqual(f.get(url), b"data")
        self.assertEqual(self.calls[-1].get_header("If-none-match"), '"version1"')
        self.assertEqual(f.stats["revalidated"], 1)

    def test_429_cooldown_persists_across_fetchers_and_urls(self):
        url = "https://example.com/feed"
        f = self.fetcher(urllib.error.HTTPError(url, 429, "slow", {"Retry-After": "120"}, None))
        with self.assertRaises(OSError):
            f.get(url)
        with self.assertRaises(OSError):
            self.fetcher().get("https://example.com/another")
        self.assertEqual(len(self.calls), 1)
        self.now += 121
        self.fetcher().get(url)
        self.assertEqual(len(self.calls), 2)

    def test_retry_after_http_date(self):
        url = "https://example.com/feed"
        retry = news.email.utils.format_datetime(dt.datetime.fromtimestamp(self.now + 120, UTC))
        f = self.fetcher(urllib.error.HTTPError(url, 429, "slow", {"Retry-After": retry}, None))
        with self.assertRaises(OSError):
            f.get(url)
        until = self.cache.db.execute("SELECT until FROM cooldowns").fetchone()[0]
        self.assertEqual(until, self.now + 120)

    def test_stale_fallback_is_disclosed_and_expires(self):
        url = "https://example.com/feed"
        self.fetcher().get(url)
        self.now += 4000
        f = self.fetcher(OSError("sensitive URL and provider text"))
        self.assertEqual(f.get(url), b"data")
        self.assertEqual(f.stats["stale"], 1)
        self.assertNotIn("sensitive", f.warnings[0])
        self.now += 86400
        with self.assertRaises(OSError):
            f.get(url)

    def test_offline_never_calls_opener(self):
        f = self.fetcher(offline=True)
        with self.assertRaises(OSError):
            f.get("https://example.com/uncached")
        self.assertEqual(self.calls, [])

    def test_response_size_bounded(self):
        with self.assertRaises(OSError):
            self.fetcher(Response(b"x" * (MAX_BYTES + 1))).get("https://example.com/feed")

    def test_archive_survives_feed_rollover_and_provider_scopes(self):
        self.cache.archive([article()], "rss:world")
        self.cache.archive([article("Different", "https://hn.com/a")], "hn")
        start, end = dt.datetime(2026, 10, 8, tzinfo=UTC), dt.datetime(2026, 10, 9, tzinfo=UTC)
        self.assertEqual(len(self.cache.articles(start, end, ["rss:world"])), 1)
        self.assertEqual(len(self.cache.articles(start, end, ["rss:world", "hn"])), 2)
        self.assertEqual(len(self.cache.articles(start, end, ["rss:US"])), 0)

    def test_no_cache_creates_no_files(self):
        path = Path(self.directory.name) / "unused"
        cache = NewsCache(str(path), enabled=False)
        cache.archive([article()])
        cache.close()
        self.assertFalse(path.exists())


class CLITests(unittest.TestCase):
    def test_changed_national_feeds_cannot_reuse_legacy_country_archive(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            now = dt.datetime.now(UTC)
            day = now.date()
            cached = article("Old outlet story", section="national")
            cached.update(published=now.isoformat(), date=day.isoformat())
            cache = NewsCache(directory)
            cache.archive([cached], "rss:CN")
            cache.close()
            args = news.parse_args(["--cache-dir", directory, "--provider", "rss", "--country", "CN", "--timezone", "UTC"])
            cfg = {"feeds": [], "countries": {"CN": [{"name": "New outlet", "url": "https://new.invalid/feed", "section": "national"}]}}
            with patch.object(news, "fetch_rss", side_effect=OSError("unavailable")):
                result = news.collect(args, day, day, UTC, cfg, "CN", day)
            self.assertEqual(result["coverage"][day.isoformat()]["national"], 0)

    def invoke(self, args, feeds=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        cfg = {"feeds": feeds or [], "countries": {"US": [
            {"name": "US Feed", "url": "https://us.com/feed", "section": "national"}]}}
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(stderr), patch.object(news, "load_sources", return_value=cfg):
            code = news.main(["--since", DAY.isoformat(), "--cache-dir", directory, *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_validation_before_network(self):
        for args in (["--since", "2026-10-01", "--until", "2026-10-08"],
                     ["--timeout", "0"], ["--timezone", "Invalid/Zone"],
                     ["--offline", "--refresh"], ["--country", "XX"]):
            with self.subTest(args=args), patch.object(Fetcher, "get", side_effect=AssertionError("network")):
                with self.assertRaises(SystemExit):
                    self.invoke(args)

    def test_failure_output_does_not_leak_provider_text(self):
        with patch.object(news, "fetch_hn", side_effect=OSError("SECRET")):
            code, output, _ = self.invoke(["--provider", "hn", "--format", "json"])
        self.assertEqual(code, 1)
        self.assertNotIn("SECRET", output)
        self.assertEqual(json.loads(output)["coverage"][DAY.isoformat()]["ai"], 0)

    def test_national_and_world_are_separate(self):
        def rss(url, *args):
            return [{"title": "Government approves national budget legislation", "url": url.replace("feed", "article"),
                     "published": dt.datetime(2026, 10, 8, 12, tzinfo=UTC)}]
        feeds = [{"name": "World", "url": "https://world.com/feed", "section": "major"}]
        with patch.object(news, "fetch_rss", side_effect=rss):
            code, output, _ = self.invoke(["--provider", "rss", "--country", "US", "--format", "json"], feeds)
        self.assertEqual(code, 0)
        self.assertEqual({s["section"] for s in json.loads(output)["stories"]}, {"major", "national"})

    def test_sources_run_concurrently(self):
        barrier = threading.Barrier(2)

        def rss(url, *args):
            barrier.wait(timeout=2)
            return [{"title": "Government approves national budget legislation", "url": url.replace("feed", "article"),
                     "published": dt.datetime(2026, 10, 8, 12, tzinfo=UTC)}]

        feeds = [{"name": str(i), "url": f"https://world{i}.com/feed", "section": "major"}
                 for i in range(2)]
        with patch.object(news, "fetch_rss", side_effect=rss):
            code, _, _ = self.invoke(["--provider", "rss"], feeds)
        self.assertEqual(code, 0)

    def test_default_does_not_call_gdelt(self):
        item = {"title": "OpenAI releases reasoning model", "url": "https://example.com/a",
                "published": dt.datetime(2026, 10, 8, 12, tzinfo=UTC)}
        with patch.object(news, "fetch_hn", return_value=[item]), \
                patch.object(news, "fetch_gdelt") as gdelt:
            code, _, _ = self.invoke([])
        self.assertEqual(code, 0)
        gdelt.assert_not_called()

    def test_offline_reads_archive_without_source_calls(self):
        yesterday = dt.datetime.now(UTC).date() - dt.timedelta(days=1)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            cache = NewsCache(directory)
            item = article()
            item["published"] = f"{yesterday}T12:00:00+00:00"
            cache.archive([item], "hn")
            cache.close()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), patch.object(news, "fetch_hn", side_effect=AssertionError):
                code = news.main(["--since", yesterday.isoformat(), "--cache-dir", directory,
                                  "--offline", "--provider", "hn", "--format", "json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["fetch"]["requests"], 0)

    def test_corrupt_cache_is_not_deleted(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = Path(directory) / "news.sqlite"
            path.write_bytes(b"existing unrelated contents")
            with self.assertRaises(SystemExit) as stopped:
                news.main(["--cache-dir", directory])
            self.assertNotIn(stopped.exception.code, (0, None))
            self.assertEqual(path.read_bytes(), b"existing unrelated contents")


if __name__ == "__main__":
    unittest.main()
