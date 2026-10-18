"""Steam game sales: store reads, thresholds, the code-owned block and its evening section."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from support import TEMP_ROOT, offline_provider_reads
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning import games
from goodmorning.briefings import briefing_document as native
from goodmorning.briefings.briefing_job import act
from goodmorning.briefings.briefing_preflight import answer, initialize as preflight
from goodmorning.records.inbox_store import initialize
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import language as ui

DAY = '2026-10-18'
NOW = datetime(2026, 10, 18, 13, tzinfo=timezone.utc)
ENDS = int(datetime(2026, 10, 22, 17, tzinfo=timezone.utc).timestamp())
ACCOUNT = '76561198000000001'
# appid: (English name, Chinese name, discount, final, original)
STORE = {292030: ('The Witcher 3: Wild Hunt', '巫师3：狂猎', 80, '£7.99', '£39.99'),
         582010: ('Monster Hunter: World', '怪物猎人：世界', 67, '£8.24', '£24.98'),
         1245620: ('ELDEN RING', '艾尔登法环', 40, '£29.99', '£49.99'),
         1091500: ('Cyberpunk 2077', '赛博朋克 2077', 0, '£49.99', '')}


def fake_steam(url, cache=None, raw=False):
    if 'steamcommunity.com/id/' in url:
        return f'<profile><steamID64>{ACCOUNT}</steamID64></profile>' if '/id/geralt/' in url else '<response><error>none</error></response>'
    if 'GetWishlist' in url:
        return {'response': {'items': [{'appid': 1245620, 'priority': 2}, {'appid': 292030, 'priority': 1}]}
                if ACCOUNT in url else {}}
    query = json.loads(parse_qs(urlsplit(url).query)['input_json'][0])
    chinese = query['context']['language'] == 'schinese'
    items = []
    for entry in query['ids']:
        english, local, discount, final, original = STORE[entry['appid']]
        price = {'formatted_final_price': final}
        if discount:
            price.update(discount_pct=discount, formatted_original_price=original,
                         active_discounts=[{'discount_end_date': ENDS}])
        items.append({'appid': entry['appid'], 'success': 1, 'name': local if chinese else english, 'best_purchase_option': price,
                      'assets': {'asset_url_format': f'steam/apps/{entry["appid"]}/${{FILENAME}}?t=1', 'header': 'abc/header.jpg'}})
    return {'response': {'store_items': items}}


def cover(appid):
    return f'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/abc/header.jpg?t=1'


class GameTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)

    def profile(self, account=ACCOUNT, threshold='50', titles='582010'):
        (self.root / 'profile.md').write_text(
            'city: London, GB\ntimezone: Europe/London\n'
            f'game_sales: "true"\ngame_country: "gb"\ngame_account: "{account}"\ngame_threshold: "{threshold}"\ngame_titles: "{titles}"\n')

    def read(self, language='en'):
        with patch.object(games, 'request', fake_steam):
            return games.deals(self.root, 'Europe/London', language)

    def test_wishlist_and_added_games_at_or_above_their_threshold(self):
        self.profile()
        result = self.read()
        self.assertEqual(result['games_checked'], 3)
        self.assertEqual(result['block'], ['deals', [
            ['steam:292030', 'The Witcher 3: Wild Hunt', 80, '£7.99', '£39.99', '2026-10-22T18:00', cover(292030)],
            ['steam:582010', 'Monster Hunter: World', 67, '£8.24', '£24.98', '2026-10-22T18:00', cover(582010)]]])
        self.assertEqual([row[1] for row in self.read('zh-CN')['block'][1]], ['巫师3：狂猎', '怪物猎人：世界'])

    def test_a_game_override_beats_the_threshold_both_ways(self):
        # Elden Ring (wishlisted, 40%) qualifies with its own 30%; Witcher (80%) is held back by its own 90%.
        self.profile(titles='582010, 1245620:30, 292030:90')
        self.assertEqual([row[0] for row in self.read()['block'][1]], ['steam:582010', 'steam:1245620'])

    def test_nothing_on_sale_and_bad_settings_are_distinct(self):
        self.profile(account='', threshold='90', titles='582010,1091500')
        self.assertIsNone(self.read()['block'])
        self.profile(titles='582010:0')
        with self.assertRaisesRegex(games.GameError, 'invalid_settings'):
            self.read()
        self.profile(threshold='')
        with self.assertRaisesRegex(games.GameError, 'invalid_settings'):
            self.read()

    def test_account_check_accepts_names_links_and_ids(self):
        with patch.object(games, 'request', fake_steam):
            for given in ('geralt', 'https://steamcommunity.com/id/geralt/', ACCOUNT, f'https://steamcommunity.com/profiles/{ACCOUNT}'):
                self.assertEqual(games.steam_id(given), ACCOUNT)
            with self.assertRaisesRegex(games.GameError, 'not_found'):
                games.steam_id('nobody')
            self.assertEqual(games.wishlist(ACCOUNT), [292030, 1245620])

    def test_deal_blocks_stay_in_their_section_and_render_prices(self):
        row = ['steam:292030', 'The Witcher 3: Wild Hunt', 80, '£7.99', '£39.99', '2026-10-22T18:00', cover(292030)]
        document = {'v': 2, 'greeting': 'Hi.', 'opening': 'Tonight.', 'sections': [['games', [['deals', [row]]], 'Bargains!']]}
        native.validate(document)
        for bad in ([['anime', [['deals', [row]]]]], [['games', [['list', ['x']]]]], [['games', [['deals', [row[:2] + ['80'] + row[3:]]]]]],
                    [['games', [['deals', [row[:5] + ['soon', row[6]]]]]]], [['games', [['deals', [row[:6] + ['http://x/c.jpg']]]]]]):
            with self.assertRaises(ValueError):
                native.validate({**document, 'sections': bad})
        html = native.render_block(['deals', [row]], {}, DAY)
        self.assertIn('−80%', html)
        self.assertIn('<s class="deal-original">£39.99</s>', html)
        self.assertIn('Sale ends', html)
        self.assertNotIn('<img', html)  # Uncached covers are never hotlinked.
        self.assertEqual(native.image_urls(document), [row[6]])
        self.assertEqual(ui.text('Game sales', lang='zh-CN'), '游戏特惠')


class EveningSectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)
        offline_provider_reads(self)
        request = patch.object(games, 'request', fake_steam)
        request.start(); self.addCleanup(request.stop)
        (self.root / 'profile.md').write_text(
            'city: London, GB\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n'
            'game_sales: "true"\ngame_country: "GB"\ngame_account: ""\ngame_threshold: "50"\ngame_titles: "292030, 582010"\n')
        initialize(self.root)
        (self.root / 'daily').mkdir()

    def job(self):
        app = BrowserApp(self.root, now=lambda: NOW, preflight=True)
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
        self.assertEqual(plan[-1], ['games', 'Game sales'])
        self.step('publish', {'position': 0, 'section': ['today', [['p', 'You shared no updates.']]]})
        self.step('publish', {'position': 1, 'section': ['schedule', [['p', 'No saved appointments tomorrow.']]]})
        self.step('skip', {'position': 2})
        result = self.step('skip', {'position': 3})
        self.assertEqual(result['next']['section'], ['games', 'Game sales'])
        read = result['next']['results'][0]
        self.assertEqual(read['exit'], 0)
        block = read['output']['block']
        self.assertEqual([row[2] for row in block[1]], [80, 67])
        self.assertIn('lively', result['next']['guide'])
        with self.assertRaisesRegex(ValueError, 'do not skip'):
            self.step('skip', {'position': 4})
        edited = ['deals', [block[1][0][:3] + ['£1.00'] + block[1][0][4:]]]
        with self.assertRaisesRegex(ValueError, 'copied unchanged'):
            self.step('publish', {'position': 4, 'section': ['games', [edited], 'Bargains!']})
        with patch('goodmorning.briefings.briefing_images.cache_previews', return_value={}) as covers:
            self.step('publish', {'position': 4, 'section': ['games', [block], 'Two hunts on sale tonight!']})
        self.assertTrue(covers.call_args.kwargs['direct'])
        self.assertEqual(self.step('finish', {})['saved'], True)

    def test_section_is_absent_unless_turned_on(self):
        (self.root / 'profile.md').write_text((self.root / 'profile.md').read_text().replace('game_sales: "true"', 'game_sales: "false"'))
        self.job()
        self.step('init', {'greeting': 'Evening.', 'opening': 'Tonight’s review.'})
        plan = json.loads((self.root / 'browser-jobs' / ('c' * 32 + '.preview.json')).read_text())['plan']
        self.assertNotIn('games', [tag for tag, _ in plan])


if __name__ == '__main__':
    unittest.main()
