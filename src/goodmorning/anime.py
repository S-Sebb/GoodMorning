#!/usr/bin/env python3
"""New anime episodes for the evening briefing, from AniList, Bangumi or MyAnimeList.

AniList and Bangumi need no keys. MyAnimeList lists need the server's MAL_CLIENT_ID;
their episodes come from AniList's schedule, which records each show's MAL ID.
The profile picks one source (`anime_source`), an optional public account whose
watching list is followed (`anime_account`) and extra title IDs on that source
(`anime_titles`). The briefing read lists episodes that aired since the previous
evening briefing, at most seven days back, as one code-owned `episodes` block.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date as Date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from goodmorning.runtime_files import atomic_text, cache_path, profile_fields, secretary_path

SOURCES = ('anilist', 'bangumi', 'myanimelist')
ANILIST = 'https://graphql.anilist.co'
MAL = 'https://api.myanimelist.net/v2'
BANGUMI = 'https://api.bgm.tv'
USER_AGENT = 'GoodMorning/1.0 (https://github.com/S-Sebb/GoodMorning)'
TTL = 3600
MAX_BYTES = 2_000_000
MAX_TITLES = 60
LOOKBACK = timedelta(days=7)


class AnimeError(Exception):
    """A safe, URL-free failure for user-facing output."""


def request(url, body=None, cache=None, headers=None):
    """GET, or POST a JSON body; successful responses are cached for an hour when cache is set."""
    key = hashlib.sha256((url + '\n' + json.dumps(body, sort_keys=True)).encode()).hexdigest()
    stored = Path(cache) / 'anime' / (key + '.json') if cache else None
    if stored and stored.is_file() and time.time() - stored.stat().st_mtime < TTL:
        try:
            return json.loads(stored.read_text(encoding='utf-8'))
        except ValueError:
            pass
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json', **(headers or {})}
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=10) as response:
            raw = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        error.close()
        if error.code in (403, 404) and url.startswith(MAL):
            raise AnimeError('not_found') from None  # MAL answers 403 for private lists.
        if error.code == 404:
            raise AnimeError('not_found') from None
        raise AnimeError(f'HTTP {error.code}') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AnimeError('network unavailable or timed out') from None
    if len(raw) > MAX_BYTES:
        raise AnimeError('provider response too large')
    try:
        value = json.loads(raw)
    except ValueError:
        raise AnimeError('invalid provider response') from None
    if stored:
        stored.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_text(stored, json.dumps(value, ensure_ascii=False))
    return value


def graphql(query, variables, cache=None):
    value = request(ANILIST, {'query': query, 'variables': variables}, cache)
    errors = value.get('errors') if isinstance(value, dict) else None
    if errors:
        if any(error.get('status') == 404 for error in errors):
            raise AnimeError('not_found')
        raise AnimeError('provider error')
    return value['data']


def https(url):
    return url if isinstance(url, str) and url.startswith('https://') else ''


def number(value):
    return f'{value:g}' if isinstance(value, (int, float)) else str(value)


# AniList: exact broadcast times; titles in native, English and romaji only.

MEDIA = 'id idMal title{romaji english native} coverImage{large} status seasonYear format'


def anilist_titles(media, language):
    names = media['title']
    original = names.get('native') or names.get('romaji') or names.get('english') or ''
    local = '' if language == 'zh-CN' else names.get('english') or names.get('romaji') or ''
    return original, '' if local == original else local


def anilist_watching(account, cache=None):
    data = graphql('query($u:String){MediaListCollection(userName:$u,type:ANIME,status_in:[CURRENT,REPEATING])'
                   '{lists{entries{media{' + MEDIA + '}}}}}', {'u': account}, cache)
    lists = (data.get('MediaListCollection') or {}).get('lists') or []
    return [entry['media'] for group in lists for entry in group['entries']]


def anilist_episodes(ids, start, end, language, cache=None):
    rows, page = [], 1
    while page <= 5:
        data = graphql('query($ids:[Int],$a:Int,$b:Int,$p:Int){Page(page:$p,perPage:50){pageInfo{hasNextPage}'
                       'airingSchedules(mediaId_in:$ids,airingAt_greater:$a,airingAt_lesser:$b,sort:TIME)'
                       '{episode airingAt media{' + MEDIA + '}}}}',
                       {'ids': ids, 'a': int(start.timestamp()), 'b': int(end.timestamp()), 'p': page}, cache)['Page']
        for item in data['airingSchedules']:
            original, local = anilist_titles(item['media'], language)
            rows.append({'id': 'anilist:' + str(item['media']['id']), 'title': original, 'local': local,
                         'episode': number(item['episode']), 'episode_title': '', 'episode_local': '',
                         'aired': datetime.fromtimestamp(item['airingAt'], timezone.utc),
                         'image': https(item['media']['coverImage'].get('large'))})
        if not data['pageInfo']['hasNextPage']:
            break
        page += 1
    return rows


def anilist_search(text, language, cache=None):
    data = graphql('query($s:String){Page(perPage:8){media(search:$s,type:ANIME,sort:SEARCH_MATCH){' + MEDIA + '}}}',
                   {'s': text}, cache)
    return [{'id': media['id'], 'mal_id': media.get('idMal'), **dict(zip(('title', 'local_title'), anilist_titles(media, language))),
             'year': media.get('seasonYear'), 'format': media.get('format'), 'status': media.get('status')}
            for media in data['Page']['media']]


# MyAnimeList: the user's list only; schedules and titles come from AniList.

def mal_watching(account):
    client = os.environ.get('MAL_CLIENT_ID')
    if not client:
        raise AnimeError('mal_unconfigured: MyAnimeList is not set up on this server; offer AniList or Bangumi')
    page = request(f'{MAL}/users/{urllib.parse.quote(account, safe="")}/animelist?status=watching&limit={MAX_TITLES}&nsfw=true',
                   headers={'X-MAL-CLIENT-ID': client})
    return [entry['node'] for entry in page['data']]


def anilist_from_mal(ids, cache=None):
    found = []
    for start in range(0, len(ids), 50):
        data = graphql('query($ids:[Int]){Page(perPage:50){media(idMal_in:$ids,type:ANIME){' + MEDIA + '}}}', {'ids': ids[start:start + 50]}, cache)
        found += [media['id'] for media in data['Page']['media']]
    return found


def mal_search(text, language, cache=None):
    """MAL IDs found through AniList's search, so no MAL key is needed to add a show."""
    found = [entry for entry in anilist_search(text, language, cache) if entry.get('mal_id')]
    for entry in found:
        entry['id'] = entry.pop('mal_id')
    return found


# Bangumi: Chinese titles and episode names, but broadcast dates only.

def bangumi_titles(subject, language):
    original = subject.get('name') or subject.get('name_cn') or ''
    local = subject.get('name_cn') or '' if language == 'zh-CN' else ''
    return original, '' if local == original else local


def bangumi_image(subject):
    images = subject.get('images') or {}
    return https(images.get('common') or images.get('large'))


def bangumi_watching(account, cache=None):
    subjects, offset = [], 0
    while offset < MAX_TITLES:
        page = request(f'{BANGUMI}/v0/users/{urllib.parse.quote(account, safe="")}/collections?'
                       f'subject_type=2&type=3&limit=50&offset={offset}', cache=cache)
        subjects += [{**entry['subject'], 'id': entry['subject_id']} for entry in page['data']]
        offset += 50
        if offset >= page['total']:
            break
    return subjects


def bangumi_subject(identifier, cache=None):
    return request(f'{BANGUMI}/v0/subjects/{identifier}', cache=cache)


def bangumi_latest(identifier, cache=None):
    """The last hundred main episodes; long runs such as Detective Conan exceed one page."""
    url = f'{BANGUMI}/v0/episodes?subject_id={identifier}&type=0&limit=100'
    page = request(url, cache=cache)
    if page['total'] > 100:
        page = request(url + f'&offset={page["total"] - 100}', cache=cache)
    return page['data']


def bangumi_episodes(subjects, first, last, language, cache=None):
    def episodes(subject):
        original, local = bangumi_titles(subject, language)
        found = []
        for item in bangumi_latest(subject['id'], cache):
            try:
                day = Date.fromisoformat(item.get('airdate') or '')
            except ValueError:
                continue
            if first <= day <= last:
                found.append({'id': 'bangumi:' + str(subject['id']), 'title': original, 'local': local,
                              'episode': number(item['ep']), 'episode_title': item.get('name') or '',
                              'episode_local': (item.get('name_cn') or '') if language == 'zh-CN' else '',
                              'aired': day, 'image': bangumi_image(subject)})
        return found
    with ThreadPoolExecutor(max_workers=4) as pool:
        return [row for rows in pool.map(episodes, subjects) for row in rows]


def bangumi_search(text, language, cache=None):
    data = request(f'{BANGUMI}/v0/search/subjects?limit=8', {'keyword': text, 'filter': {'type': [2]}}, cache)
    return [{'id': subject['id'], **dict(zip(('title', 'local_title'), bangumi_titles(subject, language))),
             'year': (subject.get('date') or '')[:4] or None, 'episodes': subject.get('eps')}
            for subject in data['data']]


# Briefing read.

def settings(runtime):
    fields = profile_fields(runtime)
    source = fields.get('anime_source', '').casefold()
    titles = [part for part in re.split(r'[\s,]+', fields.get('anime_titles', '')) if part]
    if source not in SOURCES or any(not part.isdigit() for part in titles):
        raise AnimeError('invalid_settings: anime_source must be anilist, bangumi or myanimelist and anime_titles comma-separated IDs')
    return {'enabled': fields.get('anime_updates', '').casefold() == 'true', 'source': source,
            'account': fields.get('anime_account', ''), 'titles': [int(part) for part in titles]}


def window(runtime, today, zone, now=None):
    """Since the previous evening briefing was saved, at most seven days back.

    Returns exact bounds, the broadcast days they cover, and the previous edition's date."""
    now = now or datetime.now(timezone.utc)
    earlier = sorted(path for path in (Path(runtime) / 'daily').glob('*.gn.json') if path.name[:10] < today)
    start = datetime.fromtimestamp(earlier[-1].stat().st_mtime, timezone.utc) if earlier else now - timedelta(days=1)
    start = max(start, now - LOOKBACK)
    return start, now, start.astimezone(zone).date(), earlier[-1].name[:10] if earlier else None


def episodes(runtime, today, zone_name, language, cache=None, now=None):
    chosen = settings(runtime)
    zone = ZoneInfo(zone_name)
    start, end, first, previous = window(runtime, today, zone, now)
    # Watching lists are read fresh for every briefing; only show data is cached.
    if chosen['source'] == 'anilist':
        ids = list(dict.fromkeys([media['id'] for media in (anilist_watching(chosen['account']) if chosen['account'] else [])]
                                 + chosen['titles']))[:MAX_TITLES]
        rows = anilist_episodes(ids, start, end, language, cache) if ids else []
    elif chosen['source'] == 'myanimelist':
        mal = list(dict.fromkeys([node['id'] for node in (mal_watching(chosen['account']) if chosen['account'] else [])]
                                 + chosen['titles']))[:MAX_TITLES]
        ids = anilist_from_mal(mal, cache)
        rows = anilist_episodes(ids, start, end, language, cache) if ids else []
    else:
        subjects = bangumi_watching(chosen['account']) if chosen['account'] else []
        known = {subject['id'] for subject in subjects}
        subjects += [bangumi_subject(identifier, cache) for identifier in chosen['titles'] if identifier not in known]
        subjects = subjects[:MAX_TITLES]
        ids = [subject['id'] for subject in subjects]
        # Broadcast days include the previous briefing's own day; drop what that briefing already listed.
        shown = {(row[0], row[3]) for row in saved_rows(runtime, previous)} if previous else set()
        rows = [row for row in bangumi_episodes(subjects, first, Date.fromisoformat(today), language, cache)
                if (row['id'], row['episode']) not in shown]
    rows.sort(key=lambda row: (row['aired'].astimezone(zone).replace(tzinfo=None) if isinstance(row['aired'], datetime)
                               else datetime.combine(row['aired'], datetime.min.time()), row['title'], row['episode']))
    block = [[row['id'], row['title'], row['local'], row['episode'], row['episode_title'], row['episode_local'],
              row['aired'].astimezone(zone).strftime('%Y-%m-%dT%H:%M') if isinstance(row['aired'], datetime) else row['aired'].isoformat(),
              row['image']] for row in rows][:50]
    return {'source': chosen['source'], 'titles_checked': len(ids),
            'since': start.astimezone(zone).isoformat(timespec='minutes') if chosen['source'] != 'bangumi' else first.isoformat(),
            'block': ['episodes', block] if block else None}


def saved_path(runtime, today):
    if Date.fromisoformat(today).isoformat() != today:
        raise ValueError('Use an ISO date')
    return Path(runtime) / 'browser-anime' / (today + '.json')


def save(runtime, today, result):
    """The briefing may show only rows this read returned."""
    target = saved_path(runtime, today)
    if target.parent.is_symlink() or target.is_symlink():
        raise ValueError('Refusing symlinked anime record')
    target.parent.mkdir(exist_ok=True, mode=0o700)
    atomic_text(target, json.dumps(result['block'][1] if result['block'] else [], ensure_ascii=False) + '\n')


def saved_rows(runtime, today):
    target = saved_path(runtime, today)
    if not target.is_file() or target.is_symlink() or target.stat().st_size > 200_000:
        return []
    return json.loads(target.read_text(encoding='utf-8'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secretary-dir')
    parser.add_argument('--cache-dir')
    parser.add_argument('--website-language', choices=('en', 'zh-CN'), default='en')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--date', help='Briefing read: episodes since the previous evening briefing')
    action.add_argument('--search', help='Find title IDs on --source')
    action.add_argument('--check-account', help='Confirm a public account and count its watching list on --source')
    parser.add_argument('--timezone')
    parser.add_argument('--source', type=str.lower, choices=SOURCES)
    args = parser.parse_args(argv)
    cache = cache_path(args.cache_dir)
    try:
        runtime = secretary_path(args.secretary_dir)
        if args.date:
            zone = args.timezone or profile_fields(runtime).get('timezone')
            result = episodes(runtime, args.date, zone, args.website_language, cache)
            save(runtime, args.date, result)
        elif not args.source:
            raise AnimeError('invalid_input: --search and --check-account need --source')
        elif args.search:
            found = {'anilist': anilist_search, 'bangumi': bangumi_search, 'myanimelist': mal_search}[args.source](args.search, args.website_language, cache)
            if args.source == 'anilist':
                for entry in found:
                    entry.pop('mal_id')
            result = {'source': args.source, 'results': found}
        else:
            watching = {'anilist': anilist_watching, 'bangumi': bangumi_watching, 'myanimelist': mal_watching}[args.source](args.check_account)
            titles = [('', item['title']) if args.source == 'myanimelist' else
                      (anilist_titles if args.source == 'anilist' else bangumi_titles)(item, args.website_language) for item in watching]
            result = {'source': args.source, 'account': args.check_account, 'watching': len(watching),
                      'examples': [local or original for original, local in titles[:8]]}
    except AnimeError as error:
        message = str(error)
        if message == 'not_found':
            message = 'not_found: no such public account or title on this source; check the spelling or privacy setting'
        print(json.dumps({'error': 'anime_unavailable', 'next': message}, ensure_ascii=False))
        return 1
    except (KeyError, TypeError, ValueError) as error:
        print(json.dumps({'error': 'anime_unavailable', 'next': f'unexpected provider data or settings: {error}'[:300]}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
