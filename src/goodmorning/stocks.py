#!/usr/bin/env python3
"""Stock gain/loss for the evening briefing: A-shares and US stocks, public Tencent quotes, no keys.

The profile lists holdings in `stock_holdings` as comma-separated
`SYMBOL:SHARES[:COST][@DATE]` (`sh600519:100:1650.5@2026-10-20, usAAPL:12.5`):
`sh`/`sz`/`bj` plus six digits for A-shares, `us` plus the ticker for US stocks,
an optional cost per share in the stock's own currency, and the date the user
stated those shares and cost. The briefing read reports each market's latest
closed session, so a night briefing in China shows today's A-share close and the
previous US session, as one code-owned `holdings` block.

Cash dividends whose ex-date falls after DATE count toward the total gain/loss,
pre-tax, as brokers do. Bonus or transfer shares are only flagged: the share count
is the user's to restate.
"""
import argparse
from datetime import date as Date, datetime, time as Time, timedelta
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

QUOTE = 'https://qt.gtimg.cn/q='
KLINE = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='
SEARCH = 'https://smartbox.gtimg.cn/s3/?'
USER_AGENT = 'GoodMorning/1.0 (https://github.com/S-Sebb/GoodMorning)'
TTL = 600
MAX_BYTES = 2_000_000
MAX_HOLDINGS = 50
SYMBOL = r'(?:sh|sz|bj)\d{6}|us[A-Z][A-Z0-9.-]{0,9}'
# Each market's zone and the time its daily bar is final.
MARKETS = {'CNY': (ZoneInfo('Asia/Shanghai'), Time(15, 10)), 'USD': (ZoneInfo('America/New_York'), Time(16, 10))}


class StockError(Exception):
    """A safe, URL-free failure for user-facing output."""


def request(url, cache=None, encoding='utf-8'):
    """GET text; successful responses are cached for ten minutes."""
    key = hashlib.sha256(url.encode()).hexdigest()
    stored = Path(cache) / 'stocks' / (key + '.txt') if cache else None
    if stored and stored.is_file() and time.time() - stored.stat().st_mtime < TTL:
        return stored.read_text(encoding='utf-8')
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': USER_AGENT}), timeout=10) as response:
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        error.close()
        raise StockError(f'HTTP {error.code}') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise StockError('network unavailable or timed out') from None
    if len(body) > MAX_BYTES:
        raise StockError('provider response too large')
    try:
        value = body.decode(encoding)
    except UnicodeDecodeError:
        raise StockError('invalid provider response') from None
    if stored:
        stored.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_text(stored, value)
    return value


def quotes(symbols, cache=None):
    """Name, provider code and currency of each symbol Tencent knows; unknown symbols are absent."""
    found = {}
    for symbol, body in re.findall(r'v_(\w+(?:\.\w+)?)="([^"]*)"', request(QUOTE + ','.join(symbols), cache, 'gbk')):
        fields = body.split('~')
        if len(fields) < 47 or symbol not in symbols:
            continue
        us = symbol.startswith('us')
        # A-share names come padded with spaces (五 粮 液).
        name = fields[1] if us else ''.join(fields[1].split())
        if not us and re.match('XD|XR|DR', name):
            # Ex-dividend/rights days prefix the name and cut it to four characters (XD中国人); search has the full name.
            name = next((hit['name'] for hit in search(symbol[2:], cache) if hit['symbol'] == symbol), name[2:])
        found[symbol] = {'name': name, 'english': fields[46] if us else '', 'code': 'us' + fields[2] if us else symbol,
                         'currency': 'USD' if us else 'CNY', 'price': float(fields[3])}
    return found


def bars(code, start=None, cache=None):
    """Daily bars as (date, close, volume, corporate action or None), oldest first: the last few, or every one since start."""
    data = json.loads(request(f'{KLINE}{code},day,{start or ""},,{1000 if start else 6},qfq', cache))['data'][code]
    return [(row[0], float(row[2]), float(row[5]), row[6] if len(row) > 6 and isinstance(row[6], dict) else None)
            for row in data.get('qfqday') or data.get('day') or []]


def action(event, currency):
    """(ex-date, cash per share, whether the share count changes) from Tencent's dividend note."""
    content = event.get('FHcontent') or ''
    if currency == 'CNY':
        cash = float(event['fh_sh']) / 10 if event.get('fh_sh') else 0.0
        shares = bool(re.search('[送转配]', content))
    else:
        paid = re.search(r'每股分配([\d.]+)美元', content)
        cash = float(paid.group(1)) if paid else 0.0
        shares = bool(content) and not paid
    return event.get('cqr', ''), cash, shares


def search(text, cache=None):
    hint = re.search(r'v_hint="(.*)"', request(SEARCH + urllib.parse.urlencode({'v': 2, 'q': text, 't': 'all'}), cache))
    results = []
    for entry in json.loads('"' + hint.group(1) + '"').split('^') if hint and hint.group(1) not in ('', 'N') else []:
        market, code, name, _, kind = (entry.split('~') + [''] * 5)[:5]
        if market in ('sh', 'sz', 'bj', 'us') and (kind.startswith('GP') or kind in ('ETF', 'LOF')):
            results.append({'symbol': market + (code.rsplit('.', 1)[0].upper() if market == 'us' else code), 'name': name})
    return results[:8]


# Briefing read.

def number(value):
    value = float(value)
    if not 0 < value < 1e9:
        raise ValueError
    return int(value) if value == int(value) else value


def holdings(text):
    """{symbol: (shares, cost or None, since or None)} from SYMBOL:SHARES[:COST][@DATE] parts."""
    chosen = {}
    for part in [part for part in re.split(r'[\s,]+', text) if part]:
        entry, _, since = part.partition('@')
        pieces = entry.split(':')
        try:
            if not re.fullmatch(SYMBOL, pieces[0]) or len(pieces) not in (2, 3) or pieces[0] in chosen:
                raise ValueError
            if since and Date.fromisoformat(since).isoformat() != since:
                raise ValueError
            chosen[pieces[0]] = (number(pieces[1]), number(pieces[2]) if len(pieces) == 3 else None, since or None)
        except ValueError:
            raise StockError(f'invalid_settings: {part[:40]} is not SYMBOL:SHARES[:COST][@YYYY-MM-DD] '
                             '(sh600519:100:1650.5@2026-10-20, usAAPL:12.5), each symbol once') from None
    if not 1 <= len(chosen) <= MAX_HOLDINGS:
        raise StockError(f'invalid_settings: stock_holdings needs 1 to {MAX_HOLDINGS} holdings')
    return chosen


def settled(series, currency, now):
    """Drop today's bar while that market is still trading."""
    zone, close = MARKETS[currency]
    local = now.astimezone(zone)
    if series and series[-1][0] == local.date().isoformat() and local.time() < close:
        return series[:-1]
    return series


def report(runtime, language, cache=None, now=None):
    chosen = holdings(profile_fields(runtime).get('stock_holdings', ''))
    now = now or datetime.now().astimezone()
    known = quotes(list(chosen), cache)
    missing = [symbol for symbol in chosen if symbol not in known]
    rows = []
    for symbol, info in known.items():
        shares, cost, since = chosen[symbol]
        # Enough history for the day's move, and every corporate action since the holding was stated.
        start = min(since, (now.date() - timedelta(days=20)).isoformat()) if since else None
        series = settled(bars(info['code'], start, cache), info['currency'], now)
        if not series:
            missing.append(symbol)
            continue
        day, close, volume, _ = series[-1]
        # No trade that session (suspended): unchanged rather than an older day's move.
        previous = series[-2][1] if len(series) > 1 and volume > 0 else close
        counted, today, flagged = 0.0, 0.0, False
        for bar in series:
            if not bar[3]:
                continue
            ex, cash, changes = action(bar[3], info['currency'])
            ex = ex or bar[0]
            if since and since < ex <= day:
                counted += cash
            if ex == day:
                today += cash
            flagged = flagged or changes and (since < ex <= day if since else ex == day)
        name = info['english'] if language == 'en' and info['english'] else info['name']
        rows.append([symbol, name, day, shares, close, previous, cost, info['currency'], round(counted, 4), round(today, 4), flagged])
    latest = {}
    for row in rows:
        latest[row[7]] = max(latest.get(row[7], ''), row[2])
    for row in rows:
        if row[2] < latest[row[7]]:
            row[5] = row[4]
    rows.sort(key=lambda row: (row[7] != 'CNY', -(row[4] - row[5]) * row[3], row[0]))
    return {'block': ['holdings', rows] if rows else None, 'markets': summaries(rows, language),
            'not_found': [symbol[2:] for symbol in missing]}


def summaries(rows, language='en'):
    """Per-market totals the note may mention; the rendered section computes the same."""
    from goodmorning.web import language as ui
    markets = []
    for currency, label in (('CNY', 'A-shares'), ('USD', 'US stocks')):
        group = [row for row in rows if row[7] == currency]
        if not group:
            continue
        before = sum(row[5] * row[3] for row in group)
        change = sum((row[4] - row[5]) * row[3] for row in group)
        costed = [row for row in group if row[6]]
        market = {'market': ui.text(label, lang=language), 'currency': currency, 'session': max(row[2] for row in group), 'day_change': round(change, 2),
                  'day_percent': round(change / before * 100, 2), 'value': round(sum(row[4] * row[3] for row in group), 2),
                  'up': sum(row[4] > row[5] for row in group), 'down': sum(row[4] < row[5] for row in group)}
        if costed:
            market['total_change'] = round(sum((row[4] - row[6] + row[8]) * row[3] for row in costed), 2)
        markets.append(market)
    return markets


def saved_path(runtime, today):
    if Date.fromisoformat(today).isoformat() != today:
        raise ValueError('Use an ISO date')
    return Path(runtime) / 'browser-stocks' / (today + '.json')


def save(runtime, today, result):
    """The briefing may show only rows this read returned."""
    target = saved_path(runtime, today)
    if target.parent.is_symlink() or target.is_symlink():
        raise ValueError('Refusing symlinked stock record')
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
    action.add_argument('--date', help="Briefing read: each holding's latest closed session")
    action.add_argument('--search', help='Find symbols by name, code or ticker')
    action.add_argument('--check', help='Validate a stock_holdings value and name each symbol before saving it')
    parser.add_argument('--timezone', help='Accepted for symmetry with other reads; market hours use exchange time')
    args = parser.parse_args(argv)
    cache = cache_path(args.cache_dir)
    try:
        if args.date:
            runtime = secretary_path(args.secretary_dir)
            result = report(runtime, args.website_language, cache)
            save(runtime, args.date, result)
        elif args.search:
            result = {'results': search(args.search, cache)}
        else:
            # Code dates entries, not the model: undated ones (new, changed or saved before dates) get today in the user's timezone.
            today = datetime.now(ZoneInfo(profile_fields(secretary_path(args.secretary_dir)).get('timezone') or 'UTC')).date().isoformat()
            chosen = {symbol: (shares, cost, since or today) for symbol, (shares, cost, since) in holdings(args.check).items()}
            known = quotes(list(chosen), None)
            result = {'holdings': [{'symbol': symbol, 'code': symbol[2:], 'name': known[symbol]['english'] if args.website_language == 'en' and known[symbol]['english']
                                    else known[symbol]['name'], 'shares': shares, 'cost': cost, 'since': since, 'currency': known[symbol]['currency'],
                                    'price': known[symbol]['price']} for symbol, (shares, cost, since) in chosen.items() if symbol in known],
                      'not_found': [symbol[2:] for symbol in chosen if symbol not in known],
                      'save': ', '.join(f'{symbol}:{shares}' + (f':{cost}' if cost else '') + '@' + since
                                        for symbol, (shares, cost, since) in chosen.items() if symbol in known)}
    except StockError as error:
        print(json.dumps({'error': 'stocks_unavailable', 'next': str(error)}, ensure_ascii=False))
        return 1
    except (KeyError, TypeError, ValueError, IndexError) as error:
        print(json.dumps({'error': 'stocks_unavailable', 'next': f'unexpected provider data or settings: {error}'[:300]}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
