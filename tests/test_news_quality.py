"""Approved importance policy, collection diagnostics and current-day separation."""

import contextlib
import datetime as dt
import io
import json
import hashlib
from pathlib import Path
import sys
import tempfile
from support import TEMP_ROOT, frozen_datetime
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from goodmorning.news import news
from goodmorning.news.news_rank import POLICY, importance
from goodmorning.news.news_reports import context_key
from goodmorning.news.news_cache import Fetcher, NewsCache, SourceUnavailable

DAY = dt.date(2026, 10, 8)
UTC = dt.timezone.utc


def item(title, section="ai", hour=12, **extra):
    return {"title": title, "section": section, "date": str(DAY), "published": f"{DAY}T{hour:02d}:00:00+00:00",
            "source": "Synthetic", "url": "https://example.invalid/" + hashlib.sha256(title.encode()).hexdigest()[:16],
            "lean": "unrated", **extra}


class QualityTests(unittest.TestCase):
    def test_unrelated_copyright_lawsuit_is_not_ai_even_from_ai_feed(self):
        story=news.group_stories([item('DistroKid has been quietly taking down songs in response to UMG lawsuit',
            summary='Music distribution and copyright takedowns.',priority=3)])[0]
        ranked=importance(story)
        self.assertFalse(ranked['eligible'])
        self.assertFalse(ranked['ai_relevant'])
        self.assertEqual(news.select_stories([story],4),[])
        story['sources'][0]['summary']='The lawsuit concerns artificial intelligence music training.'
        self.assertTrue(importance(story)['ai_relevant'])

    def test_consequential_release_beats_newer_promotions_and_roundups(self):
        raw = [item("Fox News AI Newsletter: tech boom", hour=23),
               item("How Oracle turns days of work into minutes with ChatGPT", hour=22, role="primary"),
               item("Pollo AI turns creative ideas into campaigns with OpenAI", hour=21, role="primary"),
               item("Anthropic launches AI security scans for open-source projects", hour=10)]
        selected = news.select_stories(news.group_stories(raw), 4)
        self.assertEqual([story["title"] for story in selected], [raw[-1]["title"]])
        self.assertIn("safety_security_or_governance", selected[0]["ranking"]["reasons"])

    def test_war_or_national_policy_beats_celebrity_and_isolated_trespass(self):
        for section in ("major", "national"):
            raw = [item("Prince Harry describes depression after leaving UK", section, 23),
                   item("Two men arrested for trespass at RAF base", section, 22),
                   item("Government announces national NHS budget legislation", section, 10)]
            result = news.select_stories(news.group_stories(raw), 4)
            self.assertEqual([story["title"] for story in result], [raw[-1]["title"]])

    def test_popularity_and_political_lean_do_not_turn_promotions_into_major_news(self):
        story = news.group_stories([item("AI newsletter promotion with discount", points=100000)])[0]
        for lean in ("center", "lean-left", "lean-right"):
            story["sources"][0]["lean"] = lean
            self.assertFalse(importance(story)["eligible"])

    def test_primary_model_release_is_not_blindly_excluded(self):
        story = news.group_stories([item("Introducing new open weights reasoning model", role="primary")])[0]
        self.assertTrue(importance(story)["eligible"])
        self.assertIn("first_party_claims", importance(story)["reasons"])

    def test_thin_day_does_not_fill_quota_with_low_signal_items(self):
        result = news.select_stories(news.group_stories([item("An entertaining AI anecdote")]), 4)
        self.assertEqual(result, [])

    def test_background_mentions_do_not_outrank_the_actual_event(self):
        background = item("Carrier returns home after long deployment", "major", 23, summary="Its deployment involved a war and government decisions.")
        event = item("Government signs ceasefire after missile attacks", "major", 10)
        result = news.select_stories(news.group_stories([background,event]),4)
        self.assertEqual(result[0]["title"],event["title"])
        self.assertFalse(importance(news.group_stories([background])[0])["eligible"])

    def test_opinion_and_sport_are_not_presented_as_straight_public_affairs_news(self):
        for path in ("opinion/world-opinion", "sport/football"):
            story=news.group_stories([item("Government threatens sanctions after nuclear war", "national",url="https://example.invalid/"+path+"/story")])[0]
            self.assertFalse(importance(story)["eligible"])
            self.assertNotEqual(importance(story)["genre"],"news")

    def test_trade_war_is_economic_policy_not_armed_conflict(self):
        ranked=importance(news.group_stories([item("EU acts to avert China trade war","major")])[0])
        self.assertNotIn("conflict_disaster_or_public_health",ranked["reasons"])
        self.assertIn("public_affairs_or_economic_consequence",ranked["reasons"])

    def test_diversity_preference_does_not_discard_four_qualified_single_publisher_items(self):
        stories=news.group_stories([item("Government approves NHS budget legislation "+str(i),"national",10+i) for i in range(4)])
        self.assertEqual(len(news.select_stories(stories,4)),4)

    def test_default_policy_has_one_report_namespace(self):
        cfg = {"feeds": [], "countries": {"GB": []}}
        self.assertEqual(context_key("UTC", "GB", cfg), context_key("UTC", "GB", {**cfg, "ranking_policy": POLICY}))

    def test_discovery_dates_are_not_claimed_as_publication(self):
        story = news.group_stories([item("OpenAI releases reasoning model", date_basis="submitted", role="discovery")])[0]
        ranked = news.select_stories([story], 4)[0]
        compact = news.compact_story(ranked, 1)
        self.assertEqual(compact["date_basis"], "submitted")
        self.assertIn("discovery_or_update_date_not_publication", compact["ranking"]["reasons"])

    def test_feed_excerpt_can_identify_ai_without_a_title_keyword(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            args = news.parse_args(["--provider", "rss", "--cache-dir", directory])
            cfg = {"feeds": [{"name":"Synthetic","url":"https://example.invalid/feed","section":"ai"}], "ranking_policy":POLICY}
            raw = [{"title":"Introducing the new reasoning system","url":"https://example.invalid/model",
                    "published":dt.datetime(2026,10,8,12,tzinfo=UTC), "summary":"An artificial intelligence reasoning model with public benchmark research."}]
            with patch.object(news,"fetch_rss",return_value=raw):
                result=news.collect(args,DAY,DAY,UTC,cfg,None,DAY+dt.timedelta(days=1))
            self.assertEqual(len(result["stories"]),1)
            self.assertEqual(result["source_status"][0]["window_items"],1)

    def test_http_404_is_visible_without_provider_text(self):
        import urllib.error
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            cache=NewsCache(directory,enabled=False)
            self.addCleanup(cache.close)
            def unavailable(*args,**kwargs):
                raise urllib.error.HTTPError("https://example.invalid/feed",404,"private provider text",{},None)
            with self.assertRaises(SourceUnavailable) as failure:
                Fetcher(cache,opener=unavailable).get("https://example.invalid/feed")
            self.assertEqual(failure.exception.reason,"HTTP 404")
            self.assertNotIn("private provider text",str(failure.exception))


Clock = frozen_datetime(dt.datetime(2026, 10, 9, 12, tzinfo=UTC))


class LatestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.tmp.cleanup)

    def test_latest_is_current_day_only_excludes_future_and_writes_no_report_store(self):
        cfg={"feeds":[{"name":"Synthetic","url":"https://example.invalid/feed","section":"ai","ai_topic":True}],"ranking_policy":POLICY}
        raw=[{"title":"AI company releases new reasoning model","url":"https://example.invalid/"+str(day)+str(hour),
              "published":Clock(2026,10,day,hour,tzinfo=UTC)} for day,hour in ((8,11),(9,11),(9,20))]
        output=io.StringIO()
        with patch.object(news.dt,"datetime",Clock),patch.object(news,"load_sources",return_value=cfg),patch.object(news,"fetch_rss",return_value=raw),contextlib.redirect_stdout(output):
            code=news.main(["--latest","--provider","rss","--timezone","UTC","--cache-dir",self.tmp.name,"--format","json"])
        self.assertEqual(code,0)
        data=json.loads(output.getvalue())
        self.assertEqual(data["since"],"2026-10-09")
        self.assertEqual(data["scope"],"latest_today")
        self.assertEqual(len(data["stories"]),1)
        self.assertFalse((Path(self.tmp.name)/"news_reports.sqlite").exists())

    def test_latest_cannot_silently_mix_with_historical_selection(self):
        with self.assertRaises(SystemExit),contextlib.redirect_stderr(io.StringIO()):
            news.main(["--latest","--since","2026-10-08","--no-cache"])

    def test_discovery_resurfacing_known_old_article_is_not_latest_news(self):
        cfg={"feeds":[{"name":"Synthetic","url":"https://example.invalid/feed","section":"ai","ai_topic":True}],"ranking_policy":POLICY}
        args=news.parse_args(["--latest","--cache-dir",self.tmp.name])
        old={"title":"OpenAI releases new reasoning model","url":"https://example.invalid/old","published":Clock(2026,10,8,10,tzinfo=UTC)}
        rediscovered={**old,"published":Clock(2026,10,9,11,tzinfo=UTC),"date_basis":"submitted"}
        with patch.object(news.dt,"datetime",Clock),patch.object(news,"fetch_rss",return_value=[old]),patch.object(news,"fetch_hn",return_value=[rediscovered]):
            result=news.collect(args,dt.date(2026,10,9),dt.date(2026,10,9),UTC,cfg,None,dt.date(2026,10,9))
        self.assertEqual(result["stories"],[])
        self.assertEqual(result["selection"]["resurfaced_discovery_items_excluded"],1)


if __name__ == "__main__":
    unittest.main()
