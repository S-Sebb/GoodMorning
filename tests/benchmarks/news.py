"""Reproducible, network-free retrieval and output-size experiment."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from goodmorning.news import news
from goodmorning.news.news_cache import Fetcher, NewsCache


class Response:
    headers = {"ETag": '"fixture"'}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size):
        return b"fixture"


def experiment():
    urls = [f"https://source{i}.example/feed" for i in range(11)]

    def opener(*args, **kwargs):
        time.sleep(0.06)
        return Response()

    with tempfile.TemporaryDirectory() as directory:
        # Original transport: all RSS/HN requests sequential, uncached.
        start = time.monotonic()
        for url in urls:
            opener(url).read(1024)
        sequential = time.monotonic() - start
        cache = NewsCache(directory)
        fetcher = Fetcher(cache, opener=opener)
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(fetcher.get, urls))
        concurrent = time.monotonic() - start
        warm_fetcher = Fetcher(cache, opener=opener)
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(warm_fetcher.get, urls))
        warm = time.monotonic() - start
        cache.close()

    day = dt.date(2026, 10, 8)
    stories = []
    for section in ("ai", "major"):
        for i in range(4):
            members = [{"date": day.isoformat(), "section": section,
                        "title": f"Example {section} headline about important development {i}",
                        "source": source, "url": f"https://{source.lower()}.example/news/development-{i}",
                        "lean": "unrated", "published": "2026-10-08T12:00:00+00:00"}
                       for source in ("OutletA", "OutletB")]
            stories.extend(news.group_stories(members))
    # Same eight stories in each comparison; no content dropped except extra links/metadata.
    old_stories = [{k: s[k] for k in ("date", "section", "title", "time", "sources")} for s in stories]
    old_json = json.dumps({"since": str(day), "until": str(day), "failures": [], "stories": old_stories},
                          indent=2, ensure_ascii=False)
    compact_json = json.dumps({"since": str(day), "until": str(day), "timezone": "UTC", "country": None,
                               "failures": [], "coverage": news.coverage_for(stories, day, day),
                               "fetch": warm_fetcher.stats,
                               "stories": [news.compact_story(s, 1) for s in stories]},
                              ensure_ascii=False, separators=(",", ":"))
    compact_md = news.to_markdown(stories, day, day, 4, [])
    print(json.dumps({"sequential_seconds": round(sequential, 3),
                      "concurrent_seconds": round(concurrent, 3), "warm_seconds": round(warm, 3),
                      "cold_requests": fetcher.stats["requests"],
                      "warm_requests": warm_fetcher.stats["requests"],
                      "old_json_chars": len(old_json), "compact_json_chars": len(compact_json),
                      "json_reduction_percent": round(100 * (1 - len(compact_json) / len(old_json)), 1),
                      "compact_markdown_chars": len(compact_md),
                      "compact_markdown_tokens_est": (len(compact_md) + 3) // 4}, indent=2))


if __name__ == "__main__":
    experiment()
