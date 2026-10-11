#!/usr/bin/env python3
"""Fetch daily news for GoodMorning /gm.

Default: concurrent RSS + Hacker News, cached for one hour and archived
locally for backfill. GDELT is opt-in, not on the daily critical path.
Headlines are source wording, not verified neutral summaries. Outlet count
does not prove independent reporting. No article bodies or LLM calls.

Usage:
    python3 scripts/goodmorning.py news --since 2026-10-08 --until 2026-10-08
    python3 scripts/goodmorning.py news --since 2026-10-02 --until 2026-10-08 --format json
    python3 scripts/goodmorning.py news --provider rss --max-items 5 --since 2026-10-08

Date rules:
    - Defaults: yesterday in --timezone (UTC by default).
    - Max 7-day window enforced: (until - since).days must be <= 6.
    - Dates must not be in the future.

Config (env only, never hard-code keys):
    - NEWS_API_KEY: only needed with --provider newsapi (optional fallback).
    - GM_CACHE_DIR: response/headline cache (default: .cache/goodmorning).
    - HTTP_USER_AGENT: optional override for request User-Agent.
"""
import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .news_cache import Fetcher, NewsCache, SourceUnavailable
from .news_reports import ReportStore, context_key, recent_days
from goodmorning.runtime_files import profile_fields, runtime_lock, secretary_path, cache_path
from .news_views import report_view
from .news_rank import POLICY, rank_stories, source_genre
from .news_editorial import candidates as editorial_candidates, seal, curate, EditorialError

MAX_WINDOW_DAYS = 7
DEFAULT_MAX_ITEMS = 4
TIMEOUT = 8
UA = os.environ.get("HTTP_USER_AGENT", "GoodMorning-news/2.0")
SOURCES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_sources.json")
HN_API = "https://hn.algolia.com/api/v1/search"
GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"

STOPWORDS = frozenset(
    "the a an in on of to for and or as at by with from after amid over under "
    "says say said new says us uk live updates update report reports amid".split()
)
AI_PATTERN = re.compile(
    r"\b(?:AI|artificial intelligence|machine learning|deep learning|LLMs?|"
    r"large language models?|OpenAI|ChatGPT|Anthropic|Claude|DeepSeek|"
    r"GPT[-\s]?\d|generative|neural networks?|Gemini|Llama|Qwen|Mistral|"
    r"AlphaFold|reasoning models?|speech recognition)\b", re.IGNORECASE)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Fetch AI + major news for a date range.")
    p.add_argument("--since", default=None, help="Start date YYYY-MM-DD (default: yesterday locally)")
    p.add_argument("--until", default=None, help="End date YYYY-MM-DD (default: same as --since)")
    p.add_argument("--provider", default="all", choices=["all", "rss", "hn", "gdelt", "newsapi"],
                   help="'all' = RSS + HN; GDELT is opt-in for historical discovery.")
    p.add_argument("--format", default="markdown", choices=["markdown", "json"],
                   help="Output format (default: markdown).")
    p.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS,
                   help=f"Max stories per section per day (default: {DEFAULT_MAX_ITEMS}).")
    p.add_argument("--timeout", type=int, default=TIMEOUT, help="HTTP timeout seconds.")
    p.add_argument("--cache-dir", default=str(cache_path()),
                   help="Local response cache and headline archive directory.")
    p.add_argument("--no-cache", action="store_true", help="Use memory only; no persistent reads/writes.")
    p.add_argument("--offline", action="store_true", help="Read local archive/cache without network access.")
    p.add_argument("--refresh", action="store_true", help="Revalidate responses before the one-hour TTL.")
    p.add_argument("--timezone", default=None, help="IANA timezone (managed mode: profile; otherwise UTC).")
    p.add_argument("--country", help="Country ISO code, confirmed during initialization; adds national news.")
    p.add_argument("--sources", default=SOURCES_FILE, help="Feed config; country feeds can be user-local.")
    p.add_argument("--max-links", type=int, default=1, choices=[1, 2], help="Links per story (default: 1).")
    p.add_argument("--details", action="store_true", help="Include full source metadata in JSON.")
    p.add_argument("--view", choices=("full", "stories", "candidates"), default="full",
                   help="Saved --show/--curate projection; stories omits candidate/diagnostic history")
    p.add_argument("--offset", type=int, default=0, help="Candidate page offset for --show --view candidates")
    p.add_argument("--limit", type=int, default=10, help="Candidate page size, 1..30")
    p.add_argument("--audit", action="store_true", help="Include up to 30 ranked candidates and source diagnostics; no article fetches.")
    actions = p.add_mutually_exclusive_group()
    actions.add_argument("--latest", action="store_true", help="Today's developments as of collection time, separate from yesterday and delivery reports.")
    actions.add_argument("--curate", metavar="DATE", help="Apply assistant-reviewed candidate IDs to an undelivered saved report.")
    actions.add_argument("--curate-latest", metavar="PATH", help="Review an exact saved latest candidate JSON without fetching or writing report state.")
    p.add_argument("--selection-file", help="Runtime-local JSON list of candidate_id/reason choices.")
    actions.add_argument("--verify-sources", action="store_true", help="Fresh national-feed checks only; JSON counts, no report or delivery changes.")
    actions.add_argument("--backfill", action="store_true", help="Save unresolved reports from the last seven days; output a compact manifest.")
    actions.add_argument("--status", action="store_true", help="Read seven-day report statuses without fetching.")
    actions.add_argument("--show", metavar="DATE", help="Read one saved compact report without fetching.")
    actions.add_argument("--ack", metavar="DATE", help="Acknowledge delivery of an exact collected report.")
    p.add_argument("--secretary-dir", default=str(secretary_path()))
    p.add_argument("--today", help="Explicit YYYY-MM-DD for deterministic backfill/tests.")
    p.add_argument("--ending", help="Managed seven-day window ending on this past date (default yesterday).")
    p.add_argument("--expect", help="Current report_id from --show; required for --ack.")
    p.add_argument("--session", help="Delivery session identifier; required for --ack.")
    return p.parse_args(argv)


def parse_day(s, name):
    try:
        day = dt.date.fromisoformat(s)
        if day.isoformat() != s:
            raise ValueError
        return day
    except ValueError:
        sys.exit(f"error: --{name} must be YYYY-MM-DD, got '{s}'")


def load_sources(path=SOURCES_FILE):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict) or not isinstance(cfg.get("feeds"), list):
        raise ValueError("feed config needs a feeds list")
    countries = cfg.get("countries", {})
    if not isinstance(countries, dict) or not all(isinstance(v, list) for v in countries.values()):
        raise ValueError("countries must map ISO codes to feed lists")
    for feed in cfg["feeds"] + [f for feeds in countries.values() for f in feeds]:
        if (not isinstance(feed, dict) or not isinstance(feed.get("name"), str)
                or not isinstance(feed.get("url"), str) or not canonical_url(feed["url"])
                or feed.get("section") not in ("ai", "major", "national")):
            raise ValueError("invalid feed entry")
    if not isinstance(cfg.get("domain_lean", {}), dict):
        raise ValueError("domain_lean must be a mapping")
    if cfg.get("ranking_policy", POLICY) != POLICY:
        raise ValueError("unsupported ranking policy")
    if type(cfg.get("editorial_review", False)) is not bool:
        raise ValueError("editorial_review must be a boolean")
    for feed in cfg["feeds"] + [feed for feeds in countries.values() for feed in feeds]:
        if (feed.get("role", "journalism") not in ("journalism", "primary", "discovery")
                or type(feed.get("priority", 0)) is not int or not 0 <= feed.get("priority", 0) <= 3
                or type(feed.get("ai_topic", False)) is not bool):
            raise ValueError("invalid feed selection metadata")
    return cfg


def domain_of(url):
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def http_get(url, timeout, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def rss_pubdate(text):
    try:
        return email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None


def iso_pubdate(text):
    try:
        return dt.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def clean_title(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", html.unescape(text))).strip()[:240]


def canonical_url(url):
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return ""
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")]
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                                   urllib.parse.urlencode(query), ""))


def fetch_rss(url, timeout, fetch=http_get):
    data = fetch(url, timeout)
    root = ET.fromstring(data)
    items = []
    for item in root.iter():
        if item.tag not in ("item", "{http://purl.org/rss/1.0/}item"):
            continue
        ns = "{http://purl.org/rss/1.0/}" if item.tag.startswith("{") else ""
        title = clean_title(item.findtext(ns + "title") or "")
        link = (item.findtext(ns + "link") or "").strip()
        pub = rss_pubdate((item.findtext("pubDate") or "").strip())
        pub = pub or iso_pubdate(item.findtext("{http://purl.org/dc/elements/1.1/}date"))
        if title and link:
            description = item.findtext(ns + "description") or ""
            summary = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", html.unescape(description))).strip()[:600]
            items.append({"title": title, "url": link, "published": pub, "summary": summary})
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
        title_el = entry.find("{http://www.w3.org/2005/Atom}title")
        link_el = next((e for e in entry.findall("{http://www.w3.org/2005/Atom}link")
                        if e.get("rel", "alternate") == "alternate"), None)
        pub_el = entry.find("{http://www.w3.org/2005/Atom}published")
        date_basis = "published"
        if pub_el is None:
            pub_el = entry.find("{http://www.w3.org/2005/Atom}updated")
            date_basis = "updated"
        title = clean_title("".join(title_el.itertext())) if title_el is not None else ""
        link = link_el.get("href", "").strip() if link_el is not None else ""
        pub = None
        if pub_el is not None and pub_el.text:
            try:
                pub = dt.datetime.fromisoformat(pub_el.text.strip().replace("Z", "+00:00"))
            except ValueError:
                pub = None
        if title and link:
            description = entry.findtext("{http://www.w3.org/2005/Atom}summary") or ""
            summary = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", html.unescape(description))).strip()[:600]
            items.append({"title": title, "url": link, "published": pub, "date_basis": date_basis, "summary": summary})
    if root.tag not in ("rss", "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF",
                         "{http://www.w3.org/2005/Atom}feed"):
        raise ValueError("unrecognized feed format")
    return items[:200]


def fetch_hn(since, until, timeout, max_items=100, fetch=http_get):
    start_ts = int(dt.datetime.combine(since, dt.time.min, tzinfo=dt.timezone.utc).timestamp())
    end_ts = int(dt.datetime.combine(until + dt.timedelta(days=1), dt.time.min,
                                    tzinfo=dt.timezone.utc).timestamp())
    params = urllib.parse.urlencode({
        # Broad date-bounded discovery also finds releases named without 'AI'.
        "query": "",
        "tags": "story",
        "numericFilters": f"created_at_i>={start_ts},created_at_i<{end_ts}",
        "hitsPerPage": max_items,
    })
    d = json.loads(fetch(f"{HN_API}?{params}", timeout))
    out = []
    for h in d.get("hits", []):
        title = h.get("title") or ""
        url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        ts = h.get("created_at_i")
        pub = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc) if ts else None
        if title:
            points = h.get("points")
            out.append({"title": title.strip(), "url": url, "published": pub, "date_basis": "submitted",
                        "points": min(max(points, 0), 100000) if type(points) is int else 0, "role": "discovery"})
    return out


def fetch_gdelt(query, since, until, timeout, maxrecords=100, fetch=http_get):
    params = urllib.parse.urlencode({
        "query": f"{query} sourcelang:english",
        "mode": "artlist",
        "maxrecords": maxrecords,
        "format": "json",
        "startdatetime": since.strftime("%Y%m%d%H%M%S"),
        "enddatetime": (until + dt.timedelta(days=1)).strftime("%Y%m%d%H%M%S"),
    })
    url = f"{GDELT_API}?{params}"
    raw = json.loads(fetch(url, timeout))
    if not isinstance(raw, dict) or "articles" not in raw:
        raise ValueError("invalid GDELT response")
    out = []
    for a in (raw.get("articles", []) if isinstance(raw, dict) else []):
        title = (a.get("title") or "").strip()
        link = (a.get("url") or "").strip()
        pub = None
        seen = (a.get("seendate") or "").strip()  # YYYYMMDDTHHMMSSZ
        try:
            pub = dt.datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            pub = None
        if title and link:
            out.append({"title": title, "url": link, "published": pub,
                        "date_basis": "first_seen",
                        "domain": (a.get("domain") or domain_of(link))})
    return out


def fetch_newsapi(since, until, timeout, fetch=http_get):
    key = os.environ.get("NEWS_API_KEY", "")
    if not key:
        sys.exit("error: --provider newsapi needs NEWS_API_KEY env var. "
                 "Get one at https://newsapi.org, export NEWS_API_KEY=<key>, retry.")
    params = urllib.parse.urlencode({
        "q": "artificial intelligence",
        "from": since.isoformat(),
        "to": (until + dt.timedelta(days=1)).isoformat(),
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 50,
    })
    d = json.loads(fetch(f"https://newsapi.org/v2/everything?{params}", timeout,
                         headers={"X-Api-Key": key}))
    if d.get("status") != "ok":
        raise ValueError("NewsAPI request failed")
    out = []
    for a in d.get("articles", []):
        pub = None
        try:
            pub = dt.datetime.fromisoformat(a.get("publishedAt", "").replace("Z", "+00:00"))
        except ValueError:
            pass
        out.append({"title": (a.get("title") or "").strip(),
                    "url": (a.get("url") or "").strip(), "published": pub})
    return out


def bucket(items, source, section, lean, since, until, timezone=dt.timezone.utc):
    dated = []
    for it in items:
        pub = it["published"]
        if isinstance(pub, str):  # cache round-trip stores ISO strings
            try:
                pub = dt.datetime.fromisoformat(pub)
            except ValueError:
                pub = None
        if pub is None or pub.tzinfo is None:
            continue  # Never invent a date or timezone for backfill.
        day = pub.astimezone(timezone).date()
        title = clean_title(it["title"])
        try:
            url = canonical_url(it["url"])
        except ValueError:
            continue
        if not title or not url or not (since <= day <= until):
            continue
        dated.append({"date": day.isoformat(), "title": title, "source": source,
                      "url": url, "lean": lean,
                      "date_basis": it.get("date_basis", "published"),
                       "published": pub.astimezone(dt.timezone.utc).isoformat(), "section": section})
        for key in ("summary", "role", "priority", "points"):
            if key in it:
                dated[-1][key] = it[key]
    return dated


def title_words(title):
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def is_ai(title):
    return bool(AI_PATTERN.search(title))


def select_stories(stories, max_items):
    """Same day/section limit for both renderers; favor breadth over repeated outlets."""
    selected, counts, outlet_counts = [], {}, {}
    ordered = rank_stories(stories)
    deferred = []
    for story in ordered:
        if story.get("ranking", {}).get("eligible") is False:
            continue
        key = (story["date"], story["section"])
        if counts.get(key, 0) >= max_items:
            continue
        domain = domain_of(story["sources"][0]["url"])
        outlet_key = (*key, domain)
        if story["outlets"] == 1 and outlet_counts.get(outlet_key, 0) >= 2:
            deferred.append(story)
            continue
        selected.append(story)
        counts[key] = counts.get(key, 0) + 1
        outlet_counts[outlet_key] = outlet_counts.get(outlet_key, 0) + 1
    for story in deferred:
        key = story["date"], story["section"]
        if counts.get(key, 0) < max_items:
            selected.append(story)
            counts[key] = counts.get(key, 0) + 1
    positions = {id(story): index for index, story in enumerate(ordered)}
    selected.sort(key=lambda story: positions[id(story)])
    return selected


def compact_story(story, max_links):
    result = {"date": story["date"], "section": story["section"], "title": story["title"],
            "outlets": story["outlets"],
            "links": [{"source": s["source"], "url": s["url"]} for s in story["sources"][:max_links]]}
    if story.get("date_basis", "published") != "published":
        result["date_basis"] = story["date_basis"]
    if story.get("ranking"):
        result["ranking"] = story["ranking"]
        if story["sources"][0].get("summary"):
            result["summary"] = story["sources"][0]["summary"][:280]
        for link, source in zip(result["links"], story["sources"]):
            link["role"] = source.get("role", "unknown")
    return result


def coverage_for(stories, since, until, country=None):
    coverage = {}
    day = since
    sections = ["ai", "major"] + (["national"] if country else [])
    while day <= until:
        ds = day.isoformat()
        coverage[ds] = {section: sum(s["date"] == ds and s["section"] == section for s in stories)
                        for section in sections}
        day += dt.timedelta(days=1)
    return coverage


def group_stories(items):
    """Conservative headline matching; no transitive chains or neutrality claims."""
    groups = {}
    for item in sorted(items, key=lambda i: (i["date"], i["section"], i["url"], i["title"])):
        words = title_words(item["title"])

        def matches(member):
            if item["date"] != member["date"] or item["section"] != member["section"]:
                return False
            if item["url"] == member["url"] or item["title"].casefold() == member["title"].casefold():
                return True
            other = title_words(member["title"])
            numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", item["title"]))
            other_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", member["title"]))
            if numbers and other_numbers and numbers != other_numbers:
                return False
            negated = lambda text: bool(re.search(r"\b(?:not|no|never|denies|denied)\b", text, re.I))
            if negated(item["title"]) != negated(member["title"]):
                return False
            common = len(words & other)
            return common >= 4 and common / len(words | other) >= 0.55

        partition = groups.setdefault((item["date"], item["section"]), [])
        group = next((g for g in partition if all(matches(m) for m in g)), None)
        if group is None:
            partition.append([item])
        else:
            group.append(item)
    stories = []
    for members in (g for partition in groups.values() for g in partition):
        members.sort(key=lambda m: (m.get("via", "rss") != "rss",
                                    source_genre(m) != "news",
                                    m.get("role") == "primary", m["published"] or "~~~~",
                                    m["source"], m["title"]))
        # One link per publisher domain, not per retrieval path.
        seen, uniq = set(), []
        for m in members:
            publisher = domain_of(m["url"])
            if publisher in seen:
                continue
            seen.add(publisher)
            uniq.append(m)
        stories.append({"date": uniq[0]["date"], "section": uniq[0]["section"],
                        "title": uniq[0]["title"],
                        "time": (uniq[0]["published"] or "")[11:16] or "--:--",
                         "date_basis": uniq[0].get("date_basis", "published"),
                         "outlets": len(uniq), "sources": uniq})
    stories.sort(key=lambda s: (s["date"], s["section"], -s["outlets"],
                                s["sources"][0].get("via", "rss") != "rss",
                                -iso_pubdate(s["sources"][0]["published"]).timestamp(),
                                s["title"].casefold()))
    return stories


def groundnews_link(query):
    return f"https://ground.news/search?query={urllib.parse.quote(query)}"


def story_line_md(story, max_links=1):
    title = re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", story["title"])
    links = ", ".join(f"[{s['source']}]({s['url'].replace('(', '%28').replace(')', '%29')})"
                      for s in story["sources"][:max_links])
    count = "single outlet" if story["outlets"] == 1 else f"{story['outlets']} outlets"
    if story.get("date_basis", "published") != "published":
        count += f"; date {story['date_basis'].replace('_', ' ')}, not publication"
    return f"- {title} — {links}; {count}"


def to_markdown(stories, since, until, max_items, failures, max_links=1, country=None):
    lines = [f"# News {since.isoformat()} to {until.isoformat()}",
              "_Source headlines; outlet counts do not establish independent confirmation._", ""]
    if failures:
        lines.append("_Coverage notes:_")
        for f in failures:
            lines.append(f"- {f}")
        lines.append("")
    day = since
    while day <= until:
        ds = day.isoformat()
        lines.append(f"## {ds}")
        sections = [("ai", "AI news"), ("major", "World news")]
        if country:
            sections.append(("national", f"National news ({country})"))
        for section, heading in sections:
            lines.append(f"### {heading}")
            group = [s for s in stories if s["date"] == ds and s["section"] == section][:max_items]
            if not group:
                lines.append("(no dated items collected; coverage may be incomplete)")
            for story in group:
                lines.append(story_line_md(story, max_links))
        lines.append("")
        day += dt.timedelta(days=1)
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    try:
        return run(argv)
    except (OSError, UnicodeError, sqlite3.Error, ValueError, OverflowError) as error:
        # Never print provider text, configuration contents, or credentials.
        arguments = argv if argv is not None else sys.argv[1:]
        if any(action in arguments for action in ("--backfill", "--status", "--show", "--ack", "--curate", "--curate-latest")):
            busy = str(error).startswith("runtime_busy:")
            print(json.dumps({"error": "runtime_busy" if busy else "news_unavailable",
                              "next": str(error) if isinstance(error, EditorialError) else "retry later" if busy else "preserve files and check news storage/profile/schema"},
                             separators=(",", ":")))
        else:
            print("error: news storage/profile is unavailable or invalid; preserve files and check configuration", file=sys.stderr)
        return 1


def run(argv=None):
    args = parse_args(argv)
    args.secretary_dir = str(secretary_path(args.secretary_dir))
    args.cache_dir = str(cache_path(args.cache_dir))
    if not 1 <= args.limit <= 30 or args.offset < 0:
        raise ValueError("invalid news page size/offset")
    if (args.view != "full" or args.offset) and not (args.show or args.curate or args.curate_latest):
        raise ValueError("saved views require --show, --curate or --curate-latest")
    if args.curate_latest:
        if not args.selection_file or not args.expect or not args.session:
            sys.exit("error: --curate-latest needs --selection-file, --expect BATCH_ID and --session")
        value = runtime_json(args.curate_latest, args.secretary_dir)
        if not isinstance(value, dict):
            raise ValueError("invalid latest candidate snapshot")
        if (args.country and args.country.upper() != value.get("country")) or (args.timezone and args.timezone != value.get("timezone")):
            raise ValueError("latest snapshot country/timezone does not match the requested scope")
        if args.since or args.until or args.today or args.ending:
            raise ValueError("latest snapshot review preserves its collected date and cutoff")
        if value.get("scope") != "latest_today" or value.get("since") != dt.datetime.now(ZoneInfo(value["timezone"])).date().isoformat():
            sys.exit("error: only a current-day latest candidate snapshot can be reviewed")
        result = curate(value, runtime_json(args.selection_file, args.secretary_dir), args.expect, args.session)
        if args.view != "full":
            result = report_view({"payload": result, "report_id": None, "status": "stateless",
                                  "collected_at": value.get("as_of")}, args.view, args.offset, args.limit)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    if args.selection_file and not args.curate:
        sys.exit("error: --selection-file requires --curate or --curate-latest")
    managed = args.backfill or args.status or args.show or args.ack or args.curate
    if managed:
        fields = profile_fields(args.secretary_dir)
        args.timezone = args.timezone or fields.get("timezone")
        args.country = args.country or fields.get("news_country")
        if not args.timezone or not args.country:
            sys.exit("error: managed news requires confirmed timezone and news_country in profile or flags")
        if not os.path.isdir(args.secretary_dir):
            sys.exit("error: no secretary directory; confirm setup first")
        if args.sources == SOURCES_FILE and fields.get("news_sources_path"):
            args.sources = fields["news_sources_path"]
        if args.provider not in ("all", "rss") or not 1 <= args.max_items <= 10:
            sys.exit("error: managed news requires --provider all|rss and --max-items 1..10")
        if args.since or args.until or args.no_cache or args.details or args.audit:
            sys.exit("error: managed news uses a seven-day window and compact saved reports; omit --since/--until/--no-cache/--details")
    else:
        args.timezone = args.timezone or "UTC"
        if args.ending:
            sys.exit("error: --ending requires --backfill or --status")
        if args.expect or args.session:
            sys.exit("error: --expect and --session require --ack")
    try:
        timezone = ZoneInfo(args.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        sys.exit("error: --timezone must be a valid IANA timezone")
    today = parse_day(args.today, "today") if args.today else dt.datetime.now(timezone).date()
    if args.latest:
        if args.since or args.until or today != dt.datetime.now(timezone).date():
            sys.exit("error: --latest is for the current local day; omit historical dates and --since/--until")
        args.since = args.until = today.isoformat()
    yesterday = today - dt.timedelta(days=1)
    since = parse_day(args.since, "since") if args.since else yesterday
    until = parse_day(args.until, "until") if args.until else since
    if since > until:
        sys.exit(f"error: --since {since} is after --until {until}")
    if (until - since).days > MAX_WINDOW_DAYS - 1:
        sys.exit(f"error: max {MAX_WINDOW_DAYS}-day backfill exceeded "
                 f"({(until - since).days + 1} days requested)")
    if until > today:
        sys.exit(f"error: --until {until} is in the future")
    if args.max_items < 1:
        sys.exit("error: --max-items must be >= 1")
    if args.timeout < 1:
        sys.exit("error: --timeout must be >= 1")
    if args.offline and (args.no_cache or args.refresh):
        sys.exit("error: --offline cannot be combined with --no-cache or --refresh")
    try:
        cfg = load_sources(args.sources)
    except (OSError, ValueError, TypeError):
        sys.exit("error: --sources must be a readable news feed JSON config; see docs/news-pipeline.md")
    country = args.country.upper() if args.country else None
    national_feeds = cfg.get("countries", {}).get(country, []) if country else []
    national_feeds = [{**f, "section": "national"} for f in national_feeds]
    if country and not national_feeds:
        sys.exit("error: country has no configured national feeds; confirm feeds during initialization "
                  "and add them to the 'countries' map in --sources")
    if managed:
        return managed_reports(args, timezone, cfg, country, today)
    if args.verify_sources:
        if not country or args.offline:
            sys.exit("error: source verification requires --country and online access")
        return verify_sources(args, national_feeds, country, today, timezone)
    result = collect(args, since, until, timezone, cfg, country, today)
    if args.format == "json":
        output = {**result, "stories": result["stories"] if args.details else
                   [compact_story(s, args.max_links) for s in result["stories"]]}
        if cfg.get("editorial_review"):
            output = seal(output)
        print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    else:
        if cfg.get("editorial_review"):
            print("_Provisional candidate picks: assistant editorial review is required before presenting a final digest._\n")
        if args.latest:
            print(f"# Latest developments as of {result['as_of']} (not necessarily breaking or independently verified)\n")
        print(to_markdown(result["stories"], since, until, args.max_items,
                          result["failures"], args.max_links, country), end="")
    if not result["stories"]:
        print("error: no dated news available; coverage is incomplete", file=sys.stderr)
        return 1
    return 0


def verify_sources(args, feeds, country, today, timezone):
    """Setup checks never use archived headlines as evidence of feed health."""
    cache = NewsCache(args.cache_dir, enabled=False)
    fetcher = Fetcher(cache, args.timeout)
    def check(feed):
        try:
            raw = fetch_rss(feed["url"], args.timeout, fetcher.get)
            dated = bucket(raw, feed["name"], "national", feed.get("lean", "unrated"),
                           today - dt.timedelta(days=34), today, timezone)
            return {"name": feed["name"], "status": "verified" if dated else "pending",
                    "dated_items": len(dated), **({} if dated else {"reason": "no_recent_dated_items"})}
        except Exception as error:
            reason = error.reason if isinstance(error, SourceUnavailable) else "source_unavailable"
            return {"name": feed["name"], "status": "pending", "dated_items": 0, "reason": reason}
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(check, feeds))
        ok = bool(results) and all(row["status"] == "verified" for row in results)
        print(json.dumps({"country": country, "status": "verified" if ok else "pending",
                          "feeds": results, "fetch": fetcher.stats}, separators=(",", ":")))
        return 0 if ok else 1
    finally:
        cache.close()


def runtime_json(path, directory):
    """Only explicitly named JSON artifacts inside the selected runtime."""
    from pathlib import Path
    target = Path(path).resolve()
    if target.suffix != ".json" or not target.is_relative_to(Path(directory).resolve()):
        raise ValueError("editorial artifacts must be JSON inside the selected runtime")
    with target.open(encoding="utf-8") as stream:
        text = stream.read(4 * 1024 * 1024 + 1)
    if len(text) > 4 * 1024 * 1024:
        raise ValueError("editorial artifact exceeds the size limit")
    return json.loads(text)


def collect(args, since, until, timezone, cfg, country, today, requested_days=None):
    national_feeds = [{**f, "section": "national"} for f in cfg.get("countries", {}).get(country, [])]
    domain_lean = cfg.get("domain_lean", {})
    items, failures, source_status = [], [], []
    if args.provider == "newsapi" and not args.offline and not os.environ.get("NEWS_API_KEY"):
        sys.exit("error: --provider newsapi needs NEWS_API_KEY env var")
    try:
        cache = NewsCache(args.cache_dir, enabled=not args.no_cache)
    except (OSError, sqlite3.Error):
        sys.exit("error: news cache is unavailable; check the cache directory or use --no-cache")
    fetcher = Fetcher(cache, args.timeout, ttl=300 if args.latest else 3600, offline=args.offline, refresh=args.refresh)
    start = dt.datetime.combine(since, dt.time.min, timezone).astimezone(dt.timezone.utc)
    end = dt.datetime.combine(until + dt.timedelta(days=1), dt.time.min, timezone).astimezone(dt.timezone.utc)
    if args.latest:
        end = min(end, dt.datetime.now(dt.timezone.utc) + dt.timedelta(microseconds=1))
    jobs = []
    provider = args.provider
    if provider in ("all", "rss"):
        for feed in cfg["feeds"] + national_feeds:
            jobs.append((feed["name"], feed["section"], feed.get("lean", "unrated"),
                         lambda f=feed: fetch_rss(f["url"], args.timeout, fetcher.get)))
    # Query a UTC envelope, then filter exact local-day boundaries in bucket().
    query_since, query_until = start.date(), (end - dt.timedelta(seconds=1)).date()
    if provider in ("all", "hn"):
        query_day = since
        while query_day <= until:
            if requested_days is not None and query_day.isoformat() not in requested_days:
                query_day += dt.timedelta(days=1)
                continue
            day_start = dt.datetime.combine(query_day, dt.time.min, timezone).astimezone(dt.timezone.utc)
            day_end = dt.datetime.combine(query_day + dt.timedelta(days=1), dt.time.min,
                                          timezone).astimezone(dt.timezone.utc)
            hs, hu = day_start.date(), (day_end - dt.timedelta(seconds=1)).date()
            jobs.append(("Hacker News", "ai", "unrated",
                         lambda s=hs, u=hu: fetch_hn(s, u, args.timeout, fetch=fetcher.get)))
            query_day += dt.timedelta(days=1)
    if provider == "gdelt":
        jobs.append(("GDELT", "ai", "unrated",
                     lambda: fetch_gdelt("artificial intelligence", query_since, query_until,
                                         args.timeout, fetch=fetcher.get)))
    if provider == "newsapi":
        jobs.append(("NewsAPI", "ai", "unrated",
                     lambda: fetch_newsapi(query_since, query_until, args.timeout, fetch=fetcher.get)))

    def run(job):
        label, section, lean, fn = job
        try:
            raw = fn()
            metadata = next((feed for feed in cfg["feeds"] + national_feeds if feed["name"] == label), {})
            # Archive the whole feed window, not only requested days.
            archive_start = today - dt.timedelta(days=34)
            dated = bucket(raw, label, section, lean, archive_start, today, timezone)
            if section == "ai":
                dated = [i for i in dated if metadata.get("ai_topic") or is_ai(i["title"] + " " + i.get("summary", ""))]
            for item in dated:
                item["via"] = {"GDELT": "gdelt", "Hacker News": "hn", "NewsAPI": "newsapi"}.get(label, "rss")
                item.update(role=metadata.get("role", item.get("role", "journalism")), priority=metadata.get("priority", 0))
            if label in ("GDELT", "Hacker News", "NewsAPI"):
                for item in dated:
                    domain = domain_of(item["url"])
                    item["source"] = domain
                    item["lean"] = domain_lean.get(domain, "unrated")
            warning = None
            if raw and not dated:
                warning = f"{label}: no recent dated {section} items"
            status = {"source": label, "section": section, "status": "ok" if dated else "no_recent_dated_items",
                      "fetched_items": len(raw), "recent_topic_items": len(dated),
                      "window_items": sum(start <= iso_pubdate(item["published"]) < end for item in dated)}
            if dated and not status["window_items"]:
                status["status"] = "no_window_items"
            return dated, warning, status
        except Exception as error:
            reason = error.reason if isinstance(error, SourceUnavailable) else type(error).__name__
            return [], f"{label}: {reason} (source unavailable)", {"source": label, "section": section, "status": "unavailable", "reason": reason}

    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            for dated, warning, status in pool.map(run, [] if args.offline else jobs):
                source_status.append(status)
                if warning:
                    failures.append(warning)
                items.extend(dated)
        if provider in ("all", "rss"):
            world_scope = "rss:world:" + context_key("", "", {"feeds": cfg["feeds"]})
            cache.archive([i for i in items if i["via"] == "rss" and i["section"] != "national"], world_scope)
            scopes = [world_scope]
            if country:
                national_scope = f"rss:{country}:" + context_key("", country, {"feeds": [], "countries": {country: national_feeds}})
                cache.archive([i for i in items if i["section"] == "national"], national_scope)
                scopes.append(national_scope)
            if provider == "all":
                cache.archive([i for i in items if i["via"] == "hn"], "hn")
                scopes.append("hn")
        else:
            cache.archive(items, provider)
            scopes = [provider]
        archived = cache.articles(start, end, scopes)
        discovery = [item for item in archived if item.get("date_basis") in ("submitted", "first_seen")]
        known = cache.publication_times([item["url"] for item in discovery], scopes)
        def resurfaced_item(item):
            return item.get("date_basis") in ("submitted", "first_seen") and item["url"] in known and (
                not start <= known[item["url"]] < end or known[item["url"]].astimezone(timezone).date()
                != iso_pubdate(item["published"]).astimezone(timezone).date())
        resurfaced = sum(resurfaced_item(item) for item in discovery)
        archived = [item for item in archived if not resurfaced_item(item)]
        # Recompute local dates so changing --timezone does not corrupt attribution.
        for item in archived:
            item["date"] = iso_pubdate(item["published"]).astimezone(timezone).date().isoformat()
        uniq = {}
        for item in sorted(archived, key=lambda i: i.get("via", "rss") != "rss"):
            uniq.setdefault((item["section"], item["url"]), item)
        groups = group_stories(list(uniq.values()))
        stories = select_stories(groups, args.max_items)
        failures.extend(sorted(set(fetcher.warnings)))
        if args.offline:
            failures.append("offline: saved headlines only; no live coverage check")
        coverage = coverage_for(stories, since, until, country)
        result = {"since": since.isoformat(), "until": until.isoformat(),
                "timezone": args.timezone, "country": country, "failures": failures,
                "coverage": coverage, "fetch": fetcher.stats,
                "stories": stories, "source_status": source_status,
                "selection": {"policy": POLICY, "candidate_counts": coverage_for(groups, since, until, country),
                              "selected_counts": coverage, "importance_is_heuristic": True,
                              "resurfaced_discovery_items_excluded": resurfaced}}
        if args.audit:
            ranked = rank_stories(groups)
            sampled = [story for section in ("ai", "major", "national")
                       for story in [row for row in ranked if row["section"] == section][:10]]
            result["candidates"] = [compact_story(story, args.max_links) for story in sampled]
            result["candidates_truncated"] = len(sampled) < len(ranked)
        if args.latest:
            result.update(scope="latest_today", as_of=(end - dt.timedelta(microseconds=1)).astimezone(timezone).isoformat(timespec="seconds"),
                          response_cache_ttl_seconds=300)
        if cfg.get("editorial_review"):
            ranked = rank_stories(groups)
            pool = [story for day in sorted({row["date"] for row in ranked})
                    for section in ("ai", "major", "national")
                    for story in [row for row in ranked if row["date"] == day and row["section"] == section][:30]]
            result.update(candidates=editorial_candidates([compact_story(story, args.max_links) for story in pool]),
                          candidates_truncated=len(pool) < len(ranked), max_items=args.max_items,
                          curation={"required": True, "state": "pending"})
            result = seal(result)
        return result
    finally:
        cache.close()


def managed_reports(args, timezone, cfg, country, today):
    from pathlib import Path

    context = context_key(args.timezone, country, cfg)
    path = Path(args.secretary_dir) / "news_reports.sqlite"
    if (args.expect or args.session) and not (args.ack or args.curate):
        sys.exit("error: --expect and --session require --ack")
    if (args.refresh or args.offline) and not args.backfill:
        sys.exit("error: --refresh and --offline apply only to collection, not saved-report reads")
    date = parse_day(args.show or args.ack or args.curate, "report date") if args.show or args.ack or args.curate else None
    if date and date >= today:
        sys.exit("error: managed reports must be for a past local date")
    if args.ack and (not args.expect or not args.session):
        sys.exit("error: --ack requires --expect REPORT_ID and --session NAME")
    if args.curate and (not args.expect or not args.session or not args.selection_file):
        sys.exit("error: --curate requires --expect REPORT_ID, --session and --selection-file")
    ending = parse_day(args.ending, "ending") if args.ending else today - dt.timedelta(days=1)
    if ending >= today or (args.ending and (args.show or args.ack)):
        sys.exit("error: --ending must be a past date and applies only to --backfill or --status")
    days = recent_days(ending + dt.timedelta(days=1))
    if not path.exists() and not args.backfill:
        if args.show or args.ack or args.curate:
            sys.exit("error: report_missing: collect and read the report first")
        print(json.dumps({"timezone": args.timezone, "country": country,
                          "days": [{"date": d, "status": "missing", "fetch": True}
                                   for d in days]}, separators=(",", ":")))
        return 0
    store = ReportStore(args.secretary_dir, create=bool(args.backfill or args.ack or args.curate))
    try:
        if args.show or args.ack or args.curate:
            if args.ack:
                try:
                    row = store.acknowledge(context, date.isoformat(), args.expect, args.session)
                except ValueError as error:
                    message = str(error)
                    print(json.dumps({"error": message.split(":", 1)[0], "next": message}, separators=(",", ":")))
                    return 2
                output = {"date": row["day"], "status": row["status"],
                          "report_id": row["report_id"], "session": row["delivered_session"]}
            elif args.curate:
                row = store.get(context, date.isoformat())
                if row is None or row["report_id"] != args.expect:
                    raise ValueError("report_conflict: read the current collected report")
                if row["status"] == "delivered":
                    raise ValueError("already_delivered: preserve the original delivered report")
                reviewed = curate(row["payload"], runtime_json(args.selection_file, args.secretary_dir),
                                  row["payload"].get("candidate_batch_id"), args.session)
                saved = store.save(context, reviewed, offline=True, expect=args.expect)
                output = report_view(saved, args.view, args.offset, args.limit) if args.view != "full" else {
                    "date": saved["day"], "status": saved["status"], "report_id": saved["report_id"],
                    "curation": saved["payload"]["curation"]}
            else:
                row = store.get(context, date.isoformat())
                if row is None:
                    sys.exit("error: report_missing: collect under the current settings first")
                output = report_view(row, args.view, args.offset, args.limit) if args.view != "full" else {"report_id": row["report_id"], "status": row["status"],
                          "collected_at": dt.datetime.fromtimestamp(row["collected_at"], dt.timezone.utc).isoformat(timespec="seconds"),
                          **row["payload"]}
            print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
            return 0
        fetch_stats = {"requests": 0, "cache_hits": 0, "revalidated": 0, "stale": 0}
        source_status = []
        if args.backfill:
            # Recheck the plan under the lock; two agents must not fetch the same backlog.
            with runtime_lock(args.secretary_dir, ".news.lock"):
                plan = store.plan(context, days, refresh=args.refresh)
                wanted = [entry["date"] for entry in plan if entry["fetch"]]
                if wanted:
                    since, until = dt.date.fromisoformat(min(wanted)), dt.date.fromisoformat(max(wanted))
                    result = collect(args, since, until, timezone, cfg, country, today, set(wanted))
                    fetch_stats = result["fetch"]
                    source_status = result["source_status"]
                    for day in wanted:
                        payload = {"date": day, "timezone": args.timezone, "country": country,
                                   "provider": args.provider, "max_items": args.max_items, "max_links": args.max_links,
                                    "counts": result["coverage"][day], "notes": result["failures"],
                                    "selection": {**result["selection"],
                                        "candidate_counts": {day: result["selection"]["candidate_counts"][day]},
                                        "selected_counts": {day: result["coverage"][day]}},
                                    "source_status": source_status,
                                    "source_status_window": [result["since"], result["until"]],
                                    "stories": [compact_story(s, args.max_links) for s in result["stories"]
                                                if s["date"] == day]}
                        if cfg.get("editorial_review"):
                            pool = [item for item in result["candidates"] if item["date"] == day]
                            payload.update(candidates=pool, candidates_truncated=result["candidates_truncated"],
                                           curation={"required": True, "state": "pending"})
                            payload = seal(payload)
                        store.save(context, payload, offline=args.offline, refresh=args.refresh)
        plan = store.plan(context, days)
        print(json.dumps({"timezone": args.timezone, "country": country, "days": plan,
                           "fetch": fetch_stats, "source_status": source_status,
                          "older_undelivered": store.older_backlog(context, min(days)),
                          "next": "show collected dates, present them, then ack each exact report_id; empty sections stay unresolved"},
                         ensure_ascii=False, separators=(",", ":")))
        return 0 if all(e["status"] in ("collected", "delivered") for e in plan) or args.status else 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
