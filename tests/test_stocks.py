"""Stock gain/loss: Tencent reads, closed sessions, the code-owned block and its evening section."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT, offline_provider_reads
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning import stocks
from goodmorning.briefings import briefing_document as native
from goodmorning.briefings.briefing_job import act
from goodmorning.briefings.briefing_preflight import answer, initialize as preflight
from goodmorning.records.inbox_store import initialize
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import language as ui

DAY = '2026-10-19'
# 22:00 in Shanghai: A-shares closed today, New York is mid-session.
NIGHT = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
# symbol: (Chinese name, provider code, English name, daily bars as (date, close, volume))
MARKET = {'sh600519': ('贵州茅台', '600519', '', [('2026-10-16', 1329.0, 9), ('2026-10-19', 1324.97, 9)]),
          'sz000001': ('平安银行', '000001', '', [('2026-10-16', 11.5, 9), ('2026-10-19', 11.65, 9)]),
          'sz000002': ('万科A', '000002', '', [('2026-10-15', 7.1, 9), ('2026-10-16', 7.0, 9)]),
          'usAAPL': ('苹果', 'AAPL.OQ', 'Apple Inc.', [('2026-10-15', 342.0, 9), ('2026-10-16', 343.46, 9), ('2026-10-19', 344.9, 9)])}


def fake_tencent(url, cache=None, encoding='utf-8'):
    if url.startswith(stocks.QUOTE):
        lines = []
        for symbol in url[len(stocks.QUOTE):].split(','):
            if symbol in MARKET:
                name, code, english, series = MARKET[symbol]
                fields = [''] * 50
                fields[1], fields[2], fields[3], fields[46] = name, code, str(series[-1][1]), english
                lines.append(f'v_{symbol}="{"~".join(fields)}";')
        return '\n'.join(lines)
    if url.startswith(stocks.KLINE):
        code = url[len(stocks.KLINE):].split(',')[0]
        symbol = next(key for key, value in MARKET.items() if (key[:2] + value[1] if key.startswith('us') else key) == code)
        return json.dumps({'data': {code: {'qfqday': [[day, '0', str(close), '0', '0', str(volume)] for day, close, volume in MARKET[symbol][3]]}}})
    return 'v_hint="sh~600519~\\u8d35\\u5dde\\u8305\\u53f0~gzmt~GP-A^sh~000001~\\u4e0a\\u8bc1\\u6307\\u6570~szzs~ZS^us~brk.b.n~Berkshire~bks~GP"'


class StockTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        request = patch.object(stocks, 'request', fake_tencent)
        request.start(); self.addCleanup(request.stop)

    def read(self, holdings, language='en', now=NIGHT):
        (self.root / 'profile.md').write_text(f'timezone: Asia/Shanghai\nstock_report: "true"\nstock_holdings: "{holdings}"\n')
        return stocks.report(self.root, language, now=now)

    def test_each_market_reports_its_latest_closed_session(self):
        result = self.read('sh600519:100:1450, usAAPL:30, sz000001:2000')
        # Tonight's A-share close; Apple's 19 October bar is still trading, so Friday's session is reported.
        self.assertEqual(result['block'], ['holdings', [
            ['sz000001', '平安银行', DAY, 2000, 11.65, 11.5, None, 'CNY'],
            ['sh600519', '贵州茅台', DAY, 100, 1324.97, 1329.0, 1450, 'CNY'],
            ['usAAPL', 'Apple Inc.', '2026-10-16', 30, 343.46, 342.0, None, 'USD']]])
        cny, usd = result['markets']
        self.assertEqual((cny['day_change'], cny['up'], cny['down'], cny['total_change']), (-103.0, 1, 1, -12503.0))
        self.assertEqual((usd['session'], usd['day_change']), ('2026-10-16', 43.8))
        self.assertNotIn('total_change', usd)
        self.assertEqual(self.read('usAAPL:30', 'zh-CN')['block'][1][0][1], '苹果')
        later = self.read('usAAPL:30', now=datetime(2026, 10, 19, 20, 30, tzinfo=timezone.utc))
        self.assertEqual(later['block'][1][0][2:6], [DAY, 30, 344.9, 343.46])

    def test_a_stock_without_that_session_shows_no_move_and_unknown_symbols_are_named(self):
        result = self.read('sz000002:1000, sh600519:100, sh999999:5')
        held = {row[0]: row for row in result['block'][1]}
        self.assertEqual(held['sz000002'][2:6], ['2026-10-16', 1000, 7.0, 7.0])
        self.assertEqual(result['not_found'], ['sh999999'])
        self.assertIn('No trading', native.render_block(result['block'], {}, DAY))

    def test_holdings_must_be_symbol_shares_and_optional_cost(self):
        self.assertEqual(stocks.holdings('sh600519:100:1650.5, usBRK.B:2.5'), {'sh600519': (100, 1650.5), 'usBRK.B': (2.5, None)})
        for bad in ('', '600519:100', 'sh600519', 'sh600519:0', 'sh600519:100:x', 'usaapl:1', 'sh600519:1, sh600519:2'):
            with self.assertRaisesRegex(stocks.StockError, 'invalid_settings'):
                stocks.holdings(bad)

    def test_search_keeps_stocks_and_funds_but_not_indexes(self):
        self.assertEqual(stocks.search('x'), [{'symbol': 'sh600519', 'name': '贵州茅台'}, {'symbol': 'usBRK.B', 'name': 'Berkshire'}])

    def test_holding_blocks_stay_in_their_section_and_render_totals(self):
        rows = self.read('sh600519:100:1450, sz000001:2000, usAAPL:30:180')['block'][1]
        document = {'v': 2, 'greeting': 'Hi.', 'opening': 'Tonight.', 'sections': [['stocks', [['holdings', rows]], 'A calm day.']]}
        native.validate(document)
        row = rows[0]
        for bad in ([['games', [['holdings', rows]]]], [['stocks', [['list', ['x']]]]], [['stocks', [['holdings', [row[:3] + ['100'] + row[4:]]]]]],
                    [['stocks', [['holdings', [row[:7] + ['HKD']]]]]], [['stocks', [['holdings', [['hk00700'] + row[1:]]]]]]):
            with self.assertRaises(ValueError):
                native.validate({**document, 'sections': bad})
        html = native.render_block(['holdings', rows], {}, DAY)
        self.assertIn('−¥103.00', html)  # A-share day total: +300 on Ping An, −403 on Moutai.
        self.assertIn('−¥12,503.00', html)
        self.assertIn('+$43.80', html)
        self.assertIn('Total gain/loss (1 with a cost)', html)
        self.assertLess(html.index('A-shares'), html.index('US stocks'))
        self.assertEqual(ui.text('Stocks', lang='zh-CN'), '持仓盈亏')


class EveningSectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)
        offline_provider_reads(self)
        request = patch.object(stocks, 'request', fake_tencent)
        request.start(); self.addCleanup(request.stop)
        clock = patch.object(stocks, 'datetime', type('Clock', (datetime,), {'now': staticmethod(lambda tz=None: NIGHT)}))
        clock.start(); self.addCleanup(clock.stop)
        (self.root / 'profile.md').write_text(
            'city: Shanghai, CN\ntimezone: Asia/Shanghai\nnews_country: CN\nsecretary_language: English\n'
            'stock_report: "true"\nstock_holdings: "sh600519:100:1450, usAAPL:30"\n')
        initialize(self.root)
        (self.root / 'daily').mkdir()

    def job(self):
        app = BrowserApp(self.root, now=lambda: NIGHT, preflight=True)
        job = {'id': 'c' * 32, 'date': DAY, 'kind': 'gn', 'state': 'preflight', 'session': 'ses_test'}
        app.jobs[DAY + '.gn'] = job; app.save_jobs()
        preflight(self.root, job)
        answer(self.root, job, {'details': 'No updates today'})
        job['state'] = 'running'; app.jobs[DAY + '.gn'] = job; app.save_jobs()
        return job

    def step(self, action, payload=None):
        return act(self.root, 'c' * 32, 'ses_test', action, payload)

    def test_section_is_last_copied_unchanged_and_never_skipped(self):
        self.job()
        self.step('init', {'greeting': 'Evening.', 'opening': 'Tonight’s review.'})
        plan = json.loads((self.root / 'browser-jobs' / ('c' * 32 + '.preview.json')).read_text())['plan']
        self.assertEqual(plan[-1], ['stocks', 'Stocks'])
        self.step('publish', {'position': 0, 'section': ['today', [['p', 'You shared no updates.']]]})
        self.step('publish', {'position': 1, 'section': ['schedule', [['p', 'No saved appointments tomorrow.']]]})
        self.step('skip', {'position': 2})
        result = self.step('skip', {'position': 3})
        self.assertEqual(result['next']['section'], ['stocks', 'Stocks'])
        read = result['next']['results'][0]
        self.assertEqual(read['exit'], 0)
        block = read['output']['block']
        self.assertEqual([row[2] for row in block[1]], [DAY, '2026-10-16'])
        with self.assertRaisesRegex(ValueError, 'do not skip'):
            self.step('skip', {'position': 4})
        edited = ['holdings', [block[1][0][:4] + [9999.0] + block[1][0][5:], block[1][1]]]
        with self.assertRaisesRegex(ValueError, 'copied unchanged'):
            self.step('publish', {'position': 4, 'section': ['stocks', [edited], 'Up!']})
        self.step('publish', {'position': 4, 'section': ['stocks', [block], 'A-shares dipped a little; Apple rose on Friday.']})
        self.assertEqual(self.step('finish', {})['saved'], True)

    def test_section_is_absent_unless_turned_on(self):
        (self.root / 'profile.md').write_text((self.root / 'profile.md').read_text().replace('stock_report: "true"', 'stock_report: "false"'))
        self.job()
        self.step('init', {'greeting': 'Evening.', 'opening': 'Tonight’s review.'})
        plan = json.loads((self.root / 'browser-jobs' / ('c' * 32 + '.preview.json')).read_text())['plan']
        self.assertNotIn('stocks', [tag for tag, _ in plan])


if __name__ == '__main__':
    unittest.main()
