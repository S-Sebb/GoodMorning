#!/usr/bin/env python3
"""Steam game sales for the evening briefing; public store data, no keys.

The profile picks a store country (`game_country`), an optional public Steam
account whose wishlist is followed (`game_account`, a SteamID64), a discount
threshold for every game (`game_threshold`, percent) and extra games
(`game_titles`, comma-separated app IDs; `APPID:PERCENT` overrides the threshold
for that game, wishlisted or not). The briefing read lists every followed game
currently discounted at or above its threshold as one code-owned `deals` block.
"""
import argparse
from datetime import date as Date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from goodmorning.runtime_files import atomic_text, cache_path, profile_fields, secretary_path

API = 'https://api.steampowered.com'
STORE = 'https://store.steampowered.com'
ASSETS = 'https://shared.akamai.steamstatic.com/store_item_assets/'
USER_AGENT = 'GoodMorning/1.0 (https://github.com/S-Sebb/GoodMorning)'
TTL = 3600
MAX_BYTES = 4_000_000
MAX_GAMES = 500
BATCH = 100
LANGUAGES = {'en': 'english', 'zh-CN': 'schinese'}


class GameError(Exception):
    """A safe, URL-free failure for user-facing output."""


def request(url, cache=None, raw=False):
    """GET; successful responses are cached for an hour."""
    key = hashlib.sha256(url.encode()).hexdigest()
    stored = Path(cache) / 'games' / (key + '.json') if cache else None
    if stored and stored.is_file() and time.time() - stored.stat().st_mtime < TTL:
        try:
            return json.loads(stored.read_text(encoding='utf-8'))
        except ValueError:
            pass
    headers = {'User-Agent': USER_AGENT, 'Accept': 'text/xml' if raw else 'application/json'}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as response:
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        error.close()
        raise GameError('not_found' if error.code == 404 else f'HTTP {error.code}') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise GameError('network unavailable or timed out') from None
    if len(body) > MAX_BYTES:
        raise GameError('provider response too large')
    try:
        value = body.decode('utf-8') if raw else json.loads(body)
    except ValueError:
        raise GameError('invalid provider response') from None
    if stored:
        stored.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_text(stored, json.dumps(value, ensure_ascii=False))
    return value


def steam_id(account, cache=None):
    """A SteamID64 from an ID, a profile URL or a custom profile name."""
    account = account.strip().rstrip('/')
    match = re.search(r'(?:steamcommunity\.com/(?:id|profiles)/)?([^/\s]+)$', account)
    name = match.group(1) if match else ''
    if re.fullmatch(r'7656\d{13}', name):
        return name
    if not re.fullmatch(r'[A-Za-z0-9_-]{2,64}', name):
        raise GameError('not_found')
    found = re.search(r'<steamID64>(\d{17})</steamID64>',
                      request(f'https://steamcommunity.com/id/{name}/?xml=1', cache, raw=True))
    if not found:
        raise GameError('not_found')
    return found.group(1)


def wishlist(account, cache=None):
    """App IDs on a public wishlist, highest priority first; a private one reads as empty."""
    items = request(f'{API}/IWishlistService/GetWishlist/v1/?steamid={account}', cache)['response'].get('items') or []
    return [item['appid'] for item in sorted(items, key=lambda item: item.get('priority', 0))]


def store_items(ids, country, language, cache=None):
    """Names, cover art and the current price of each app, in batches."""
    items = []
    for start in range(0, len(ids), BATCH):
        query = {'ids': [{'appid': identifier} for identifier in ids[start:start + BATCH]],
                 'context': {'language': LANGUAGES[language], 'country_code': country},
                 'data_request': {'include_assets': True}}
        url = f'{API}/IStoreBrowseService/GetItems/v1/?' + urllib.parse.urlencode({'input_json': json.dumps(query, separators=(',', ':'))})
        items += [item for item in request(url, cache)['response'].get('store_items') or [] if item.get('success') == 1]
    return items


def cover(item):
    assets = item.get('assets') or {}
    name = assets.get('header') or assets.get('main_capsule')
    template = assets.get('asset_url_format') or ''
    return ASSETS + template.replace('${FILENAME}', name) if name and template.startswith('steam/') else ''


def search(text, country, language, cache=None):
    found = request(f'{STORE}/api/storesearch/?' + urllib.parse.urlencode(
        {'term': text, 'cc': country, 'l': LANGUAGES[language]}), cache).get('items') or []
    return [{'id': item['id'], 'name': item['name']} for item in found if item.get('type') == 'app'][:8]


# Briefing read.

def settings(runtime):
    fields = profile_fields(runtime)
    country = fields.get('game_country', '').upper()
    threshold = fields.get('game_threshold', '')
    titles = [part for part in re.split(r'[\s,]+', fields.get('game_titles', '')) if part]
    if (not re.fullmatch('[A-Z]{2}', country) or not threshold.isdigit() or not 1 <= int(threshold) <= 100
            or any(not re.fullmatch(r'\d{1,9}(?::(?:100|[1-9]\d?))?', part) for part in titles)):
        raise GameError('invalid_settings: game_country needs a two-letter code, game_threshold a percent from 1 to 100 '
                        'and game_titles comma-separated app IDs, each optionally APPID:PERCENT')
    overrides = {int(part.split(':')[0]): int(part.split(':')[1]) if ':' in part else None for part in titles}
    return {'enabled': fields.get('game_sales', '').casefold() == 'true', 'country': country,
            'account': fields.get('game_account', ''), 'threshold': int(threshold), 'titles': overrides}


def deals(runtime, zone_name, language, cache=None):
    chosen = settings(runtime)
    zone = ZoneInfo(zone_name)
    ids = list(dict.fromkeys((wishlist(chosen['account'], cache) if chosen['account'] else []) + list(chosen['titles'])))[:MAX_GAMES]
    rows = []
    for item in store_items(ids, chosen['country'], language, cache) if ids else []:
        price = item.get('best_purchase_option') or {}
        discount = price.get('discount_pct') or 0
        if not discount or discount < (chosen['titles'].get(item['appid']) or chosen['threshold']):
            continue
        ends = [entry['discount_end_date'] for entry in price.get('active_discounts') or [] if entry.get('discount_end_date')]
        rows.append(['steam:' + str(item['appid']), item.get('name') or '', discount,
                     price.get('formatted_final_price') or '', price.get('formatted_original_price') or '',
                     datetime.fromtimestamp(min(ends), timezone.utc).astimezone(zone).strftime('%Y-%m-%dT%H:%M') if ends else '',
                     cover(item)])
    rows = sorted((row for row in rows if row[1] and row[3]), key=lambda row: (-row[2], row[1].casefold()))[:50]
    return {'country': chosen['country'], 'games_checked': len(ids), 'threshold': chosen['threshold'],
            'block': ['deals', rows] if rows else None}


def saved_path(runtime, today):
    if Date.fromisoformat(today).isoformat() != today:
        raise ValueError('Use an ISO date')
    return Path(runtime) / 'browser-games' / (today + '.json')


def save(runtime, today, result):
    """The briefing may show only rows this read returned."""
    target = saved_path(runtime, today)
    if target.parent.is_symlink() or target.is_symlink():
        raise ValueError('Refusing symlinked game record')
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
    parser.add_argument('--website-language', choices=tuple(LANGUAGES), default='en')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--date', help='Briefing read: followed games on sale at or above their threshold')
    action.add_argument('--search', help='Find Steam app IDs by name')
    action.add_argument('--check-account', help='Resolve a Steam profile name, URL or ID and count its public wishlist')
    parser.add_argument('--timezone')
    parser.add_argument('--country', type=str.upper, help='Store country for --search, e.g. GB')
    args = parser.parse_args(argv)
    cache = cache_path(args.cache_dir)
    try:
        runtime = secretary_path(args.secretary_dir)
        if args.date:
            zone = args.timezone or profile_fields(runtime).get('timezone')
            result = deals(runtime, zone, args.website_language, cache)
            save(runtime, args.date, result)
        elif args.search:
            if not args.country or not re.fullmatch('[A-Z]{2}', args.country):
                raise GameError('invalid_input: --search needs --country, a two-letter store country')
            result = {'results': search(args.search, args.country, args.website_language, cache)}
        else:
            account = steam_id(args.check_account, None)
            result = {'account': account, 'wishlist': len(wishlist(account, None))}
            if not result['wishlist']:
                result['note'] = 'empty or private: the wishlist is followed only while its game details are public'
    except GameError as error:
        message = str(error)
        if message == 'not_found':
            message = 'not_found: no such Steam profile; check the name or link'
        print(json.dumps({'error': 'games_unavailable', 'next': message}, ensure_ascii=False))
        return 1
    except (KeyError, TypeError, ValueError) as error:
        print(json.dumps({'error': 'games_unavailable', 'next': f'unexpected provider data or settings: {error}'[:300]}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
