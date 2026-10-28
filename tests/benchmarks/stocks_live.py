"""Opt-in paid trials for stock gain/loss: the evening section and saving holdings in chat.

Real models work through a private source copy whose CLI swaps Tencent quotes for
synthetic fixtures, so no live market data is read. Holdings arrive as pasted
broker text, a synthetic broker screenshot, or a trade update. Assertions check
records and documents; tone, language and grounding need manual review of the
retained transcripts. The screenshot case needs Playwright to draw its image.
"""
import argparse
from datetime import datetime, timedelta, timezone
import io
import json
import re
from pathlib import Path
import sys
import time
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from benchmarks.anime_live import account, copy_source
from benchmarks.briefing_tone_live import CheckpointBridge, commands, link_handoff, observe
from benchmarks import trial_engine
from benchmarks.trial_engine import TrialBridge
from benchmarks.task_tone_live import context, matrix_lock, save
from goodmorning import stocks
from goodmorning.runtime_files import profile_fields
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import models

# The fixture market: `RUNTIME/stocks-fixture.json` picks ok or fail.
TRIAL_CLI = '''from datetime import date, timedelta
from pathlib import Path
import json, os, sys, uuid
from urllib.parse import parse_qs, urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning import stocks
from goodmorning.cli import main
runtime = Path(os.environ['SECRETARY_DIR'])
fixture = json.loads((runtime/'stocks-fixture.json').read_text())
call = uuid.uuid4().hex
with (runtime/'trial-commands.jsonl').open('a') as log:
    log.write(json.dumps({'call':call, 'argv':sys.argv[1:]}, ensure_ascii=False)+'\\n')
# symbol: (Chinese name, provider code, English name, pinyin, previous close, close)
MARKET = {'sh600519': ('贵州茅台', '600519', '', 'gzmt', 1329.0, 1324.97), 'sz000001': ('平安银行', '000001', '', 'payh', 11.5, 11.65),
          'sh601318': ('中国平安', '601318', '', 'zgpa', 51.88, 51.67), 'usAAPL': ('苹果', 'AAPL.OQ', 'Apple Inc.', 'apple', 342.0, 343.46),
          'usTSLA': ('特斯拉', 'TSLA.OQ', 'Tesla, Inc.', 'tesla', 362.44, 354.72), 'usNVDA': ('英伟达', 'NVDA.OQ', 'Nvidia Corporation', 'nvidia', 217.23, 214.13)}
# Index code: (previous close, close); A-shares beat the CSI 300, US holdings trail the S&P 500.
INDEX = {'sh000001': (3600.0, 3610.0), 'sh000300': (4000.0, 3960.0), 'sz399006': (2600.0, 2587.0),
         'us.INX': (7600.0, 7676.0), 'us.IXIC': (26000.0, 26390.0), 'us.DJI': (52000.0, 52260.0)}
today = date.fromisoformat(fixture['today'])
# closed: the last bars end before a three-day A-share closure around today, which reopens two days on.
days = [(today - timedelta(days=n)).isoformat() for n in ((3, 2) if fixture['mode'] == 'closed' else (2, 1))]
def request(url, cache=None, encoding='utf-8'):
    if url.startswith(stocks.SEARCH):
        term = parse_qs(urlsplit(url).query)['q'][0].casefold()
        found = [f"{s[:2]}~{(v[1].lower() if s.startswith('us') else v[1])}~{v[2] or v[0]}~{v[3]}~{'GP' if s.startswith('us') else 'GP-A'}"
                 for s, v in MARKET.items() if any(term in field.casefold() for field in (s[2:], v[0], v[2], v[3]))]
        return 'v_hint="' + ('^'.join(found).encode('unicode_escape').decode() or 'N') + '"'
    if url.startswith(stocks.SZSE_CALENDAR):
        first = date.fromisoformat(url[len(stocks.SZSE_CALENDAR):] + '-01')
        listed = [first + timedelta(days=n) for n in range(31) if (first + timedelta(days=n)).month == first.month]
        shut = lambda day: fixture['mode'] == 'closed' and abs((day - today).days) <= 1
        return json.dumps({'data': [{'jyrq': day.isoformat(), 'jybz': '0' if shut(day) else '1'} for day in listed]})
    if fixture['mode'] == 'fail':
        raise stocks.StockError('HTTP 503')
    if url.startswith(stocks.QUOTE):
        lines = []
        for symbol in url[len(stocks.QUOTE):].split(','):
            if symbol in MARKET:
                fields = [''] * 50
                fields[1], fields[2], fields[3], fields[46] = MARKET[symbol][0], MARKET[symbol][1], str(MARKET[symbol][5]), MARKET[symbol][2]
                lines.append(f'v_{symbol}="' + '~'.join(fields) + '";')
        return chr(10).join(lines)
    code = url[len(stocks.KLINE):].split(',')[0]
    if code in INDEX:
        return json.dumps({'data': {code: {'day': [[day, '0', str(close), '0', '0', '1000'] for day, close in zip(days, INDEX[code])]}}})
    symbol = next(s for s, v in MARKET.items() if (s[:2] + v[1] if s.startswith('us') else s) == code)
    bars = [[day, '0', str(price), '0', '0', '1000'] for day, price in zip(days, MARKET[symbol][4:6])]
    return json.dumps({'data': {code: {'qfqday': bars}}})
stocks.request = request
try:
    code = main()
except SystemExit as error:
    code = error.code if isinstance(error.code, int) else 0 if error.code is None else 1
with (runtime/'trial-commands.jsonl').open('a') as log:
    log.write(json.dumps({'call':call, 'exit':code or 0})+'\\n')
raise SystemExit(code)
'''

BRIEFINGS = {'evening-holdings': ('ok', 'playful'), 'evening-failed': ('fail', 'formal'), 'evening-closed': ('closed', 'default')}
CHATS = ('enable-paste', 'enable-screenshot', 'update-trade', 'replace-all', 'swap-several', 'adjust-shares', 'unclear-list')
CHANGES = ('update-trade', 'replace-all', 'swap-several', 'adjust-shares', 'unclear-list')
ADVICE_WORDS = ('should buy', 'should sell', 'buy more', 'sell now', 'will rise', 'will fall', 'rebound', 'recover', 'target price',
                '建议买入', '建议卖出', '加仓', '减仓', '抄底', '会反弹', '会上涨', '会下跌', '目标价')
PASTE = {'en': ('Please add my stocks to the night briefing. From my broker app:\n\n'
                'Code    Name             Qty     Avg cost   Last       Mkt value    P/L\n'
                '600519  Kweichow Moutai  100     1,450.00   1,324.97   132,497.00   -12,503.00\n'
                '000001  Ping An Bank     2,000   10.80      11.65      23,300.00    +1,700.00\n'
                'AAPL    Apple            30      180.00     343.46     10,303.80    +4,903.80\n'
                'TSLA    Tesla            10      --         354.72     3,547.20     --'),
         'zh-CN': ('帮我把持仓加到晚间简报里，下面是券商 App 里复制的：\n\n'
                   '证券代码  证券名称  持仓数量  成本价    现价      市值        浮动盈亏\n'
                   '600519    贵州茅台  100       1450.00   1324.97   132497.00   -12503.00\n'
                   '000001    平安银行  2000      10.80     11.65     23300.00    +1700.00\n'
                   'AAPL      苹果      30        180.00    343.46    10303.80    +4903.80\n'
                   'TSLA      特斯拉    10        --        354.72    3547.20     --')}
MESSAGES = {('enable-screenshot', 'en'): 'Here is a screenshot of my holdings. Please show their daily gain/loss in my night briefing.',
            ('enable-screenshot', 'zh-CN'): '这是我的持仓截图，帮我在晚间简报里看每天的盈亏。',
            ('update-trade', 'en'): 'I sold all my Tesla today, and bought 200 shares of Ping An Bank (000001) at 11.20.',
            ('update-trade', 'zh-CN'): '今天把特斯拉全卖了，另外买了 200 股平安银行（000001），成本 11.20。',
            ('replace-all', 'en'): 'Forget my old stock list completely. I now hold only China Ping An 601318, 500 shares at 48, and Nvidia, 40 shares at 95.',
            ('replace-all', 'zh-CN'): '之前的持仓全部清掉不要了，我现在只有中国平安 601318 500 股成本 48，英伟达 40 股成本 95。',
            ('swap-several', 'en'): 'I sold all my Apple. Then I bought 500 shares of China Ping An (601318) at 48 and 40 Nvidia at 95.',
            ('swap-several', 'zh-CN'): '苹果全部卖掉了，然后买了 500 股中国平安（601318），成本 48，还有 40 股英伟达，成本 95。',
            ('adjust-shares', 'en'): 'Two fixes: I actually have 150 Moutai shares, not 100, same cost. And I sold 5 of my 10 Tesla shares.',
            ('adjust-shares', 'zh-CN'): '改两处：茅台其实是 150 股不是 100 股，成本不变；特斯拉 10 股卖掉了 5 股。',
            ('unclear-list', 'en'): 'My holdings: China Ping An 601318, 500 shares at 48; Nvidia, 40 shares at 95.',
            ('unclear-list', 'zh-CN'): '我的持仓：中国平安 601318，500 股，成本 48；英伟达 40 股，成本 95。'}
EXPECTED = {'enable-paste': {'sh600519': (100, 1450), 'sz000001': (2000, 10.8), 'usAAPL': (30, 180), 'usTSLA': (10, None)},
            'enable-screenshot': {'sh601318': (500, 48), 'usNVDA': (40, 95), 'sh600519': (100, 1450)},
            'update-trade': {'sh600519': (100, 1450), 'usAAPL': (30, 180), 'sz000001': (200, 11.2)},
            'replace-all': {'sh601318': (500, 48), 'usNVDA': (40, 95)},
            'swap-several': {'sh600519': (100, 1450), 'usTSLA': (10, 250), 'sh601318': (500, 48), 'usNVDA': (40, 95)},
            'adjust-shares': {'sh600519': (150, 1450), 'usTSLA': (5, 250), 'usAAPL': (30, 180)},
            # Asked whether the list replaces or adds to the saved one, the user replaces it.
            'unclear-list': {'sh601318': (500, 48), 'usNVDA': (40, 95)}}
# Moutai was stated on 1 September; the rest predate dated entries.
SAVED = 'stock_report: "true"\nstock_holdings: "sh600519:100:1450@2026-09-01, usTSLA:10:250, usAAPL:30:180"\n'
SCREEN = '''<html><body style="margin:0;font:15px system-ui,sans-serif;background:#f5f6f8;width:420px">
<div style="background:#c8102e;color:#fff;padding:14px 16px;font-weight:600">{title}</div>
<table style="width:100%;border-collapse:collapse;background:#fff">{rows}</table></body></html>'''


def fixture(runtime, mode, now):
    save(runtime/'stocks-fixture.json', {'mode':mode, 'today':now.date().isoformat()})


def source_copy(folder, runtime):
    source = copy_source(folder, runtime)
    (source/'scripts/goodmorning.py').write_text(TRIAL_CLI)
    return source


def screenshot(language):
    """A synthetic broker holdings screen; the market-value and P/L columns are traps for shares and cost."""
    from playwright.sync_api import sync_playwright
    head = (('Stock', 'Qty', 'Avg cost', 'Mkt value', 'P/L') if language == 'en' else ('股票', '持仓', '成本价', '市值', '盈亏'))
    data = [('中国平安 601318', '500', '48.00', '25,835.00', '+1,835.00'), ('NVDA Nvidia', '40', '95.00', '8,565.20', '+4,765.20'),
            ('贵州茅台 600519', '100', '1,450.00', '132,497.00', '-12,503.00')]
    cell = '<td style="padding:12px 10px;border-bottom:1px solid #e3e5e8">{}</td>'
    rows = ('<tr style="color:#667">' + ''.join(cell.format(h) for h in head) + '</tr>'
            + ''.join('<tr>' + ''.join(cell.format(v) for v in row) + '</tr>' for row in data))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width': 420, 'height': 260}, device_scale_factor=2)
        page.set_content(SCREEN.format(title='Holdings' if language == 'en' else '我的持仓', rows=rows))
        image = page.screenshot(full_page=True)
        browser.close()
    return image


def run_briefing(output, language, selected, scenario, now):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    mode, tone = BRIEFINGS[scenario]
    zone = 'Europe/London' if language == 'en' else 'Asia/Shanghai'
    runtime = account(folder, language, tone, 'stock_report: "true"\nstock_holdings: "sh600519:100:1450, sz000001:2000, usAAPL:30:180, sh688999:10"\n', zone)
    fixture(runtime, mode, now)
    source = source_copy(folder, runtime)
    bridge = CheckpointBridge(trial_engine.Engine(source, runtime).start(), False, language)
    app = BrowserApp(runtime, bridge, now=lambda: now, preflight=True)
    day = app.today()
    result = {'scenario':scenario, 'language':language, 'tone':tone, 'model':selected, 'checks':[],
              'review':'pending manual language/tone/grounding review'}
    try:
        bridge.verify_scope()
        save(folder/'start-intent.json', {'date':day, 'kind':'gn'})
        with context(language, selected):
            job = app.start(day, 'gn')['job']
            form = app.status(job)['forms'][0]
            option = next(o['value'] for f in form['fields'] if f['key'] == 'details' for o in f['options'])
            app.reply(job, 'form', form['id'], {'answer':{'details':option}})
        status = observe(app, bridge, job, folder, 'original', language, selected)
        assert status['state'] == 'ready', 'Edition did not finish; inspect preserved status/transcript'
        document = json.loads(app.source(day, 'gn').read_text())
        save(folder/'original.document.json', document)
        section = document['sections'][-1]
        assert section[0] == 'stocks', 'Stocks was not the last section'
        blocks = section[1]
        text = json.dumps(section, ensure_ascii=False)
        if mode != 'fail':
            returned = json.loads((runtime/'browser-stocks'/(day + '.json')).read_text())
            assert len(returned[1]) == 3, 'Fixture holdings were not returned by the read'
            assert len(returned) == 4 and len(returned[3]) == 6, 'The market overview was not returned by the read'
            assert blocks[0] == returned, 'Holdings block was not copied unchanged'
            assert section[2:3] and section[2].strip(), 'Holdings published without a short note'
            assert '688999' in text, 'The unknown code was not named'
            result['note'] = section[2]
            result['checks'].append('Read block copied unchanged with its market overview and a note; unknown code named '
                                    '(manual review: any benchmark comparison matches `markets` and stays factual)')
        else:
            assert [block[0] for block in blocks] == ['p'], 'Failed read did not publish one paragraph'
            result['checks'].append('Unavailable line published, section not skipped')
        if mode == 'closed':
            closed = returned[2]['CNY']
            assert closed['next'], 'The fixture closure has no next trading day'
            # The note names the next trading day by date, weekday or "the day after tomorrow", spaced or not, never as ISO.
            upcoming = datetime.fromisoformat(closed['next'])
            written = (f'{upcoming.month}月{upcoming.day}日', f'{upcoming:%B}{upcoming.day}', f'{upcoming:%b}{upcoming.day}',
                       upcoming.strftime('%A'), '周' + '一二三四五六日'[upcoming.weekday()], '后天', 'dayaftertomorrow')
            result['note'] = section[2]
            note = ''.join(section[2].split()).casefold()
            assert any(form.casefold() in note for form in written), 'The note did not give the next trading day'
            assert not re.search(r'\d{4}-\d{2}-\d{2}', section[2]), 'The note printed an ISO date'
            result['checks'].append('Closed A-shares: block carries the closure; note names the next trading day in everyday words '
                                    '(manual review: says closed, calls the move the last trading day\'s)')
        result['advice_words'] = [word for word in ADVICE_WORDS if word in text.casefold()]
        assert not result['advice_words'], 'The section gave advice or a forecast'
        result['stocks_reads'] = [entry['argv'] for entry in commands(runtime) if entry['argv'][:1] == ['stocks']]
        assert link_handoff(folder, 'original', f'/d/{day}/gn'), 'Final reply was not a briefing-link handoff'
        result['checks'].append('Short saved-briefing link handoff')
        result['functional_complete'] = True
        print(f'{language} {selected} {scenario}: {len(result["checks"])} checks passed', flush=True)
    except Exception as error:
        result['failure'] = str(error)[:1500]
        result['functional_complete'] = False
        print(f'{language} {selected} {scenario}: INCOMPLETE — {result["failure"]}', flush=True)
    finally:
        bridge.close()
        save(folder/'result.json', result)
    return result


def settings(runtime):
    fields = profile_fields(runtime)
    return {key:fields.get(key) for key in ('stock_report', 'stock_holdings')}


def answer(form, language, scenario=''):
    """Confirm what the secretary read; these fixtures leave nothing else to choose."""
    picks = (('replace', 'only these', 'instead', '替换', '换成', '覆盖', '只保留', '只要') if scenario == 'unclear-list' else ()) + ('yes', 'correct', 'confirm', 'save', 'looks right', 'go ahead', 'without', 'skip', 'no cost',
             '对', '确认', '保存', '没问题', '是', '不用', '跳过', '好')
    sentence = 'Yes, that is right; save it.' if language == 'en' else '对，没问题，保存吧。'
    values = {}
    for field in form['fields']:
        options = field.get('options') or []
        labels = [(option.get('label', '') + ' ' + str(option.get('value', ''))).casefold() for option in options]
        chosen = next((option['value'] for word in picks for option, label in zip(options, labels) if word in label), None)
        if chosen is not None:
            values[field['key']] = [chosen] if field.get('type') == 'multiselect' else chosen
        elif field.get('type') == 'string' or field.get('custom'):
            values[field['key']] = sentence
        else:
            raise AssertionError('Unsupported synthetic question; inspect it instead of guessing: ' + json.dumps(field, ensure_ascii=False)[:500])
    return values


def run_chat(output, language, selected, scenario, now):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    zone = 'Europe/London' if language == 'en' else 'Asia/Shanghai'
    tone = {'enable-paste':'playful', 'update-trade':'formal', 'swap-several':'playful', 'adjust-shares':'formal'}.get(scenario, 'default')
    runtime = account(folder, language, tone, SAVED if scenario in CHANGES else '', zone)
    fixture(runtime, 'ok', now)
    source = source_copy(folder, runtime)
    before = (runtime/'profile.md').read_text()
    bridge = TrialBridge(trial_engine.Engine(source, runtime).start())
    app = BrowserApp(runtime, bridge)
    chat = uuid.uuid4().hex
    message = PASTE[language] if scenario == 'enable-paste' else MESSAGES[scenario, language]
    body = {'id':chat, 'mode':'secretary', 'text':message}
    if scenario == 'enable-screenshot':
        image = screenshot(language)
        (folder/'holdings.png').write_bytes(image)
        upload = uuid.uuid4().hex
        app.chats.uploads.receive(upload, 'holdings.png', io.BytesIO(image), len(image))
        body['attachments'] = [upload]
    result = {'scenario':scenario, 'language':language, 'tone':tone, 'model':selected, 'message':message, 'turns':[],
              'review':'pending manual language/tone review'}
    confirm = {('unclear-list', 'en'): 'Replace the old ones; keep only these. Save it.', ('unclear-list', 'zh-CN'): '替换掉旧的，只保留这两只，保存吧。'}.get(
        (scenario, language), 'Yes, that is right; save it.' if language == 'en' else '对，没问题，保存吧。')
    proceed = 'Please go on.' if language == 'en' else '继续吧。'

    def wait():
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            with context(language, selected):
                status = app.chats.status(chat)
            if status['permissions']:
                raise AssertionError('Unexpected permission; not auto-approved: ' + json.dumps(status['permissions'])[:500])
            if status['state'] in ('idle', 'waiting'):
                return status
            if status['state'] in ('uncertain', 'unavailable'):
                raise AssertionError('Uncertain delivery; inspect, never replay')
            time.sleep(3)
        raise TimeoutError('No settled reply within ten minutes')

    started = datetime.now(ZoneInfo(zone)).date().isoformat()
    try:
        with context(language, selected):
            app.chats.start(body)
        seen, followed = 0, 0
        for _ in range(6):
            status = wait()
            replies = [m['text'] for m in status['messages'][seen:] if m['role'] == 'assistant' and m['text'].strip()]
            seen = len(status['messages'])
            turn = {'assistant':replies, 'forms':status['forms'], 'settings':settings(runtime)}
            result['turns'].append(turn)
            save(folder/'result.json', result)
            if not status['forms']:
                if turn['settings'] == settings_before(before) and followed < 3:
                    followed += 1  # A plain-text question gets a plain confirmation; a turn that stopped early only a nudge.
                    asked = any(mark in text.casefold() for text in replies for mark in ('?', '？', 'confirm', '确认'))
                    turn['followed_up'] = confirm if asked else proceed
                    with context(language, selected):
                        app.chats.send(chat, {'id':uuid.uuid4().hex, 'text':turn['followed_up']})
                    continue
                break
            turn['answered'] = answer(status['forms'][0], language, scenario)
            with context(language, selected):
                app.chats.reply(chat, 'form', status['forms'][0]['id'], {'answer':turn['answered']})
        save(folder/'messages.json', status['messages'])
        saved = settings(runtime)
        result['settings'] = saved
        assert saved['stock_report'] == 'true', 'The section was not turned on'
        held = stocks.holdings(saved['stock_holdings'] or '')
        assert {symbol: entry[:2] for symbol, entry in held.items()} == EXPECTED[scenario], 'Saved holdings differ: ' + repr(saved['stock_holdings'])
        # An unchanged Moutai keeps its date; every other entry is new, changed or was undated, so it carries the account's today.
        days = {started, datetime.now(ZoneInfo(zone)).date().isoformat()}
        kept = scenario in ('update-trade', 'swap-several')
        assert all(entry[2] == '2026-09-01' if kept and symbol == 'sh600519' else entry[2] in days for symbol, entry in held.items()), \
            'Entries were not dated as expected: ' + repr(saved['stock_holdings'])
        first = next(i for i, turn in enumerate(result['turns']) if turn['settings'] != settings_before(before))
        assert any('answered' in turn or turn.get('followed_up') == confirm for turn in result['turns'][:first]), \
            'Holdings were saved before the user confirmed them'
        if scenario == 'unclear-list':
            asked = json.dumps([turn['forms'] for turn in result['turns'][:first]] + [turn['assistant'] for turn in result['turns'][:first]], ensure_ascii=False).casefold()
            assert any(word in asked for word in ('replace', '替换', '换成', '覆盖')) and any(word in asked for word in ('add', '加', '追加', '新增')), \
                'Did not ask whether the new list replaces or adds to the saved holdings'
        after = (runtime/'profile.md').read_text().splitlines()
        assert [line for line in before.splitlines() if not line.startswith('stock_')] == \
            [line for line in after if not line.startswith('stock_')], 'Unrelated profile lines changed'
        result['checks'] = ['Holdings saved exactly after confirmation; unrelated lines unchanged']
        result['functional_complete'] = True
        print(f'{language} {selected} {scenario}: passed', flush=True)
    except Exception as error:
        result['failure'] = str(error)[:1500]
        result['functional_complete'] = False
        print(f'{language} {selected} {scenario}: INCOMPLETE — {result["failure"]}', flush=True)
    finally:
        bridge.close()
        save(folder/'result.json', result)
    return result


def settings_before(profile):
    lines = dict(line.split(': ', 1) for line in profile.splitlines() if line.startswith('stock_'))
    return {key:lines[key].strip('"') if key in lines else None for key in ('stock_report', 'stock_holdings')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    trial_engine.add_arguments(parser)
    parser.add_argument('--language', choices=('en', 'zh-CN'), required=True)
    parser.add_argument('--model', choices=tuple(models.MODELS), help='Defaults to the production model for the language')
    parser.add_argument('--only', nargs='*', choices=(*BRIEFINGS, *CHATS))
    args = parser.parse_args()
    output = trial_engine.private_output(parser, args.output)
    selected = args.model or models.for_language(args.language)
    with matrix_lock(output):
        output.mkdir(mode=0o700)
        trial_engine.copy_release(output/'release', args.source.resolve())
        now = datetime.now(timezone.utc)
        chosen = args.only or (*BRIEFINGS, *CHATS)
        results = [(run_briefing if name in BRIEFINGS else run_chat)(output, args.language, selected, name, now) for name in chosen]
        save(output/'matrix.json', {'model':selected, 'language':args.language, 'cases':results, 'limitations':[
            'Synthetic Tencent quote fixtures and a drawn broker screenshot; no live market data or public deployment.',
            'One sample per scenario and model; prose needs manual review.']})
        if not all(result.get('functional_complete') for result in results):
            raise SystemExit(1)


if __name__ == '__main__':
    main()
