"""Local response cache and headline archive. No article bodies or credentials."""
import datetime as dt
import email.utils
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 4 * 1024 * 1024


class SourceUnavailable(OSError):
    """Controlled transport reason, never provider response text or credentials."""
    def __init__(self, reason):
        super().__init__("source unavailable")
        self.reason = reason


class NewsCache:
    def __init__(self, directory, enabled=True):
        self.enabled = enabled
        self.lock = threading.Lock()
        if enabled:
            os.makedirs(directory, exist_ok=True)
        self.db = sqlite3.connect(os.path.join(directory, "news.sqlite") if enabled else ":memory:",
                                  check_same_thread=False)
        try:
            self._initialize()
        except sqlite3.Error:
            self.db.close()
            raise

    def _initialize(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS responses (
                url TEXT PRIMARY KEY, body BLOB, checked REAL NOT NULL,
                etag TEXT, modified TEXT);
            CREATE TABLE IF NOT EXISTS cooldowns (host TEXT PRIMARY KEY, until REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS articles (
                scope TEXT NOT NULL, section TEXT NOT NULL, url TEXT NOT NULL,
                published TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY (scope, section, url));
            CREATE INDEX IF NOT EXISTS article_dates ON articles(published);
        """)
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=35)).isoformat()
        with self.db:
            self.db.execute("DELETE FROM articles WHERE published < ?", (cutoff,))
            self.db.execute("DELETE FROM responses WHERE checked < ?", (time.time() - 35 * 86400,))
            self.db.execute("DELETE FROM cooldowns WHERE until < ?", (time.time(),))

    def close(self):
        self.db.close()

    def archive(self, items, scope="all"):
        with self.lock, self.db:
            self.db.executemany("INSERT OR REPLACE INTO articles VALUES (?, ?, ?, ?, ?)",
                                [(scope, i["section"], i["url"], i["published"],
                                  json.dumps(i, ensure_ascii=False)) for i in items])

    def articles(self, start, end, scopes):
        with self.lock:
            rows = self.db.execute(
                "SELECT payload FROM articles WHERE published >= ? AND published < ? "
                "AND scope IN (" + ",".join("?" for _ in scopes) + ") ORDER BY published, url",
                (start.isoformat(), end.isoformat(), *scopes)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def publication_times(self, urls, scopes):
        """Look up only matching URLs, so rediscovery cannot re-date known articles."""
        urls = list(set(urls))
        known = {}
        with self.lock:
            for offset in range(0, len(urls), 200):
                batch = urls[offset:offset + 200]
                rows = self.db.execute("SELECT payload FROM articles WHERE url IN (" + ",".join("?" for _ in batch)
                    + ") AND scope IN (" + ",".join("?" for _ in scopes) + ")", (*batch, *scopes)).fetchall()
                for row in rows:
                    item = json.loads(row[0])
                    if item.get("date_basis", "published") == "published" and item.get("via", "rss") == "rss":
                        date = dt.datetime.fromisoformat(item["published"])
                        known[item["url"]] = min(date, known.get(item["url"], date))
        return known


class Fetcher:
    def __init__(self, cache, timeout=8, ttl=3600, offline=False, refresh=False,
                 opener=urllib.request.urlopen, clock=time.time):
        self.cache, self.timeout, self.ttl = cache, timeout, ttl
        self.offline, self.refresh = offline, refresh
        self.opener, self.clock = opener, clock
        self.stats = {"requests": 0, "cache_hits": 0, "revalidated": 0, "stale": 0}
        self.warnings = []

    def get(self, url, timeout=None, headers=None):
        # Authentication is passed in headers, never in the cache URL.
        host = urllib.parse.urlsplit(url).netloc
        now = self.clock()
        with self.cache.lock:
            row = self.cache.db.execute("SELECT body, checked, etag, modified FROM responses WHERE url=?",
                                        (url,)).fetchone()
            cooldown = self.cache.db.execute("SELECT until FROM cooldowns WHERE host=?", (host,)).fetchone()
        if row and (self.offline or (not self.refresh and 0 <= now - row[1] < self.ttl)):
            with self.cache.lock:
                self.stats["cache_hits"] += 1
            return bytes(row[0])
        if self.offline:
            raise OSError("offline: response not cached")
        if cooldown and cooldown[0] > now:
            return self._stale(row, host, now, "rate-limit cooldown")
        request_headers = {"User-Agent": os.environ.get("HTTP_USER_AGENT", "GoodMorning-news/2.0")}
        request_headers.update(headers or {})
        if row:
            if row[2]:
                request_headers["If-None-Match"] = row[2]
            if row[3]:
                request_headers["If-Modified-Since"] = row[3]
        with self.cache.lock:
            self.stats["requests"] += 1
        try:
            with self.opener(urllib.request.Request(url, headers=request_headers),
                             timeout=timeout or self.timeout) as response:
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValueError("response exceeds 4 MiB limit")
                etag, modified = response.headers.get("ETag"), response.headers.get("Last-Modified")
            with self.cache.lock, self.cache.db:
                self.cache.db.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?)",
                                      (url, body, now, etag, modified))
            return body
        except urllib.error.HTTPError as error:
            error.close()
            if error.code == 304 and row:
                with self.cache.lock, self.cache.db:
                    self.cache.db.execute("UPDATE responses SET checked=? WHERE url=?", (now, url))
                    self.stats["revalidated"] += 1
                return bytes(row[0])
            if error.code == 429:
                retry = (error.headers or {}).get("Retry-After", "3600")
                try:
                    delay = float(retry)
                except ValueError:
                    try:
                        delay = email.utils.parsedate_to_datetime(retry).timestamp() - now
                    except (ValueError, TypeError, OverflowError):
                        delay = 3600
                with self.cache.lock, self.cache.db:
                    self.cache.db.execute("INSERT OR REPLACE INTO cooldowns VALUES (?, ?)",
                                          (host, now + max(60, min(delay, 86400))))
            # Do not expose URLs, credentials, or provider response text in failures.
            return self._stale(row, host, now, f"HTTP {error.code}")
        except (OSError, ValueError):
            return self._stale(row, host, now, "network/response failure")

    def _stale(self, row, host, now, reason):
        if row and 0 <= now - row[1] <= 86400:
            with self.cache.lock:
                self.stats["stale"] += 1
                self.warnings.append(f"{host}: stale cached response ({reason})")
            return bytes(row[0])
        raise SourceUnavailable(reason)
