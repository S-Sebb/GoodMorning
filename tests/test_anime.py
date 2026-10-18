"""New anime episodes: source reads, the code-owned block and its evening section."""
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
from goodmorning import anime
from goodmorning.briefings import briefing_document as native
from goodmorning.briefings.briefing_job import act
from goodmorning.briefings.briefing_preflight import answer, initialize as preflight
from goodmorning.records.inbox_store import initialize
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import language as ui

DAY = '2026-10-18'
NOW = datetime(2026, 10, 18, 13, tzinfo=timezone.utc)
LAST = datetime(2026, 10, 16, 13, 30, tzinfo=timezone.utc).timestamp()  # Previous night briefing: 21:30 in Shanghai.
COVER = 'https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx195516.jpg'
MEDIA = {195516: {'id': 195516, 'title': {'romaji': 'Kusuriya no Hitorigoto 3rd Season', 'english': 'The Apothecary Diaries Season 3',
                                          'native': '薬屋のひとりごと 第3期'}, 'coverImage': {'large': COVER}},
         235: {'id': 235, 'title': {'romaji': 'Meitantei Conan', 'english': 'Detective Conan', 'native': '名探偵コナン'},
               'coverImage': {'large': 'https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx235.jpg'}}}
AIRED = [(195516, 3, datetime(2026, 10, 16, 14, tzinfo=timezone.utc)), (235, 1217, datetime(2026, 10, 17, 9, tzinfo=timezone.utc)),
         (235, 1216, datetime(2026, 10, 10, 9, tzinfo=timezone.utc))]


def fake_anilist(url, body=None, cache=None, headers=None):
    variables = body['variables']
    if 'u' in variables:
        if variables['u'] != 'maomao':
            return {'errors': [{'status': 404, 'message': 'User not found'}], 'data': None}
        return {'data': {'MediaListCollection': {'lists': [{'entries': [{'media': MEDIA[195516]}]}]}}}
    rows = [{'episode': episode, 'airingAt': int(when.timestamp()), 'media': MEDIA[identifier]} for identifier, episode, when in AIRED
            if identifier in variables['ids'] and variables['a'] < when.timestamp() < variables['b']]
    return {'data': {'Page': {'pageInfo': {'hasNextPage': False}, 'airingSchedules': rows}}}


def fake_anilist_any_time(url, body=None, cache=None, headers=None):
    """Job reads use the real clock; pretend every fixture episode aired inside its window."""
    if 'ids' in body['variables']:
        body = {**body, 'variables': {**body['variables'], 'a': 0, 'b': 2 ** 31}}
    return fake_anilist(url, body, cache)


SUBJECT = {'id': 568244, 'name': '薬屋のひとりごと 第3期', 'name_cn': '药屋少女的呢喃 第三季',
           'images': {'common': 'https://lain.bgm.tv/r/400/pic/cover/l/55/e2/568244.jpg'}}


def fake_bangumi(url, body=None, cache=None, headers=None):
    if '/collections' in url:
        return {'total': 1, 'data': [{'subject_id': 568244, 'subject': SUBJECT}]}
    episodes = [{'ep': n, 'name': name, 'name_cn': cn, 'airdate': day} for n, name, cn, day in (
        (2, '火鼠の皮衣', '火鼠的皮衣', '2026-10-09'), (3, '麺麭がなければ', '何不食肉糜', '2026-10-16'),
        (4, '最後の一冊', '', '2026-10-23'))]
    return {'total': len(episodes), 'data': episodes}


class AnimeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)
        (self.root / 'daily').mkdir()
        previous = self.root / 'daily' / '2026-10-16.gn.json'
        previous.write_text('{}')
        os.utime(previous, (LAST, LAST))

    def profile(self, source='anilist', account='', titles='235', updates='true'):
        (self.root / 'profile.md').write_text(
            'city: Shanghai, CN\ntimezone: Asia/Shanghai\nnews_country: CN\nsecretary_language: English\n'
            f'anime_updates: "{updates}"\nanime_source: "{source}"\nanime_account: "{account}"\nanime_titles: "{titles}"\n')

    def read(self, language='en', fake=fake_anilist):
        with patch.object(anime, 'request', fake):
            return anime.episodes(self.root, DAY, 'Asia/Shanghai', language, now=NOW)

    def test_anilist_lists_episodes_since_the_previous_night_briefing(self):
        self.profile(account='maomao')
        result = self.read()
        self.assertEqual(result['since'], '2026-10-16T21:30+08:00')
        self.assertEqual(result['titles_checked'], 2)
        self.assertEqual(result['block'], ['episodes', [
            ['anilist:195516', '薬屋のひとりごと 第3期', 'The Apothecary Diaries Season 3', '3', '', '', '2026-10-16T22:00', COVER],
            ['anilist:235', '名探偵コナン', 'Detective Conan', '1217', '', '', '2026-10-17T17:00',
             'https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx235.jpg']]])
        # Without a Bangumi match, Chinese pages show the original alone rather than an English one.
        nothing = lambda url, body=None, cache=None, headers=None: {'data': []} if url.startswith(anime.BANGUMI) else fake_anilist(url, body, cache)
        self.assertEqual({row[2] for row in self.read('zh-CN', nothing)['block'][1]}, {''})

    def test_nothing_new_and_unknown_account_are_distinct(self):
        self.profile(titles='')
        self.assertIsNone(self.read()['block'])
        self.profile(account='nobody', titles='')
        with self.assertRaisesRegex(anime.AnimeError, 'not_found'):
            self.read()
        self.profile(titles='235,abc')
        with self.assertRaisesRegex(anime.AnimeError, 'invalid_settings'):
            self.read()

    def test_bangumi_uses_broadcast_days_and_drops_what_the_last_briefing_showed(self):
        self.profile('bangumi', 'maomao', '')
        result = self.read('zh-CN', fake_bangumi)
        self.assertEqual(result['block'][1], [['bangumi:568244', '薬屋のひとりごと 第3期', '药屋少女的呢喃 第三季', '3',
                                               '麺麭がなければ', '何不食肉糜', '2026-10-16', SUBJECT['images']['common']]])
        # English pages get no Chinese notation.
        self.assertEqual(self.read('en', fake_bangumi)['block'][1][0][2::3], ['', ''])
        anime.save(self.root, '2026-10-16', result)
        self.assertIsNone(self.read('zh-CN', fake_bangumi)['block'])

    def test_watching_lists_are_read_fresh_for_every_briefing(self):
        self.profile(account='maomao')
        calls = []
        def recording(url, body=None, cache=None, headers=None):
            calls.append(('u' in body['variables'], cache))
            return fake_anilist(url, body, cache)
        with patch.object(anime, 'request', recording):
            anime.episodes(self.root, DAY, 'Asia/Shanghai', 'en', cache=self.root / 'cache', now=NOW)
        self.assertEqual(calls, [(True, None), (False, self.root / 'cache')])

    def test_myanimelist_lists_use_anilist_schedules(self):
        self.profile('myanimelist', 'maomao', '235')
        mapped = {59000: 195516, 235: 235}
        seen = []
        def fake(url, body=None, cache=None, headers=None):
            if url.startswith(anime.MAL):
                seen.append((url, headers))
                return {'data': [{'node': {'id': 59000, 'title': 'Kusuriya no Hitorigoto 3rd Season'}}]}
            if 'idMal_in' in body['query']:
                return {'data': {'Page': {'media': [MEDIA[mapped[i]] for i in body['variables']['ids']]}}}
            return fake_anilist(url, body, cache)
        with self.assertRaisesRegex(anime.AnimeError, 'mal_unconfigured'):
            self.read(fake=fake)
        with patch.dict(os.environ, {'MAL_CLIENT_ID': 'synthetic-client'}):
            rows = self.read(fake=fake)['block'][1]
        self.assertEqual([row[:4] for row in rows], [['anilist:195516', '薬屋のひとりごと 第3期', 'The Apothecary Diaries Season 3', '3'],
                                                     ['anilist:235', '名探偵コナン', 'Detective Conan', '1217']])
        self.assertIn('/users/maomao/animelist?status=watching', seen[0][0])
        self.assertEqual(seen[0][1], {'X-MAL-CLIENT-ID': 'synthetic-client'})

    def test_profile_links_name_their_source_and_user(self):
        for link, expected in (('https://myanimelist.net/animelist/S-Sebb', ('myanimelist', 'S-Sebb')),
                               ('myanimelist.net/profile/S-Sebb?view=1', ('myanimelist', 'S-Sebb')),
                               ('https://anilist.co/user/maomao/animelist', ('anilist', 'maomao')),
                               ('https://bgm.tv/user/sai', ('bangumi', 'sai')), ('bangumi.tv/anime/list/sai/do', ('bangumi', 'sai')),
                               ('maomao', (None, 'maomao')), ('https://example.com/user/maomao', (None, 'https://example.com/user/maomao'))):
            self.assertEqual(anime.account_link(link), expected)
        self.profile(account='https://anilist.co/user/maomao')
        self.assertEqual(anime.settings(self.root)['account'], 'maomao')

    def test_chinese_titles_come_only_from_an_exact_bangumi_match(self):
        self.profile(titles='235, 195516')
        def fake(url, body=None, cache=None, headers=None):
            if url.startswith(anime.BANGUMI):
                return {'data': {'名探偵コナン': [{'name': '名探偵コナン', 'name_cn': '名侦探柯南'},
                                                   {'name': '名探偵コナン 瞳の中の暗殺者', 'name_cn': '名侦探柯南 瞳孔中的暗杀者'}],
                                 '薬屋のひとりごと 第3期': [{'name': '薬屋のひとりごと', 'name_cn': '药屋少女的呢喃'}]}[body['keyword']]}
            return fake_anilist(url, body, cache)
        rows = self.read('zh-CN', fake)['block'][1]
        self.assertEqual({row[1]: row[2] for row in rows}, {'名探偵コナン': '名侦探柯南', '薬屋のひとりごと 第3期': ''})
        self.assertEqual({row[2] for row in self.read('en', fake)['block'][1]}, {'The Apothecary Diaries Season 3', 'Detective Conan'})

    def test_episode_blocks_stay_in_their_section_and_render_original_title_first(self):
        row = ['anilist:235', '名探偵コナン', 'Detective Conan', '1217', '', '', '2026-10-17T17:00', 'https://s4.anilist.co/c.jpg']
        document = {'v': 2, 'greeting': 'Hi.', 'opening': 'Tonight.', 'sections': [['anime', [['episodes', [row]]], 'Enjoy!']]}
        native.validate(document)
        for bad in ([['tasks', [['episodes', [row]]]]], [['anime', [['list', ['x']]]]],
                    [['anime', [['episodes', [row[:6] + ['tonight', row[7]]]]]]],
                    [['anime', [['episodes', [row[:7] + ['http://s4.anilist.co/c.jpg']]]]]]):
            with self.assertRaises(ValueError):
                native.validate({**document, 'sections': bad})
        html = native.render_block(['episodes', [row]], {}, DAY)
        self.assertLess(html.index('名探偵コナン'), html.index('Detective Conan'))
        self.assertIn('class="episode-show-local"', html)
        self.assertIn('Episode 1217', html)
        self.assertNotIn('<img', html)  # Uncached covers are never hotlinked.
        cached = native.render_block(['episodes', [row]], {row[7]: {'src': '/media/' + 'a' * 64 + '.webp'}}, DAY)
        self.assertIn('src="/media/' + 'a' * 64 + '.webp"', cached)
        self.assertEqual(native.image_urls(document), [row[7]])
        self.assertEqual(ui.text('Episode {number}', lang='zh-CN', number='3'), '第 3 集')


class EveningSectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)
        offline_provider_reads(self)
        request = patch.object(anime, 'request', fake_anilist_any_time)
        request.start(); self.addCleanup(request.stop)
        (self.root / 'profile.md').write_text(
            'city: Shanghai, CN\ntimezone: Asia/Shanghai\nnews_country: CN\nsecretary_language: English\n'
            'anime_updates: "true"\nanime_source: "anilist"\nanime_account: ""\nanime_titles: "235"\n')
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
        result = self.step('init', {'greeting': 'Evening.', 'opening': 'Tonight’s review.'})
        plan = json.loads((self.root / 'browser-jobs' / ('c' * 32 + '.preview.json')).read_text())['plan']
        self.assertEqual(plan[-1], ['anime', 'New episodes'])
        self.step('publish', {'position': 0, 'section': ['today', [['p', 'You shared no updates.']]]})
        self.step('publish', {'position': 1, 'section': ['schedule', [['p', 'No saved appointments tomorrow.']]]})
        self.step('skip', {'position': 2})
        result = self.step('skip', {'position': 3})
        self.assertEqual(result['next']['section'], ['anime', 'New episodes'])
        read = result['next']['results'][0]
        self.assertEqual(read['exit'], 0)
        block = read['output']['block']
        self.assertEqual([row[3] for row in block[1]], ['1216', '1217'])
        self.assertIn('lively', result['next']['guide'])
        with self.assertRaisesRegex(ValueError, 'do not skip'):
            self.step('skip', {'position': 4})
        edited = ['episodes', [block[1][0][:2] + ['Conan!'] + block[1][0][3:]]]
        with self.assertRaisesRegex(ValueError, 'copied unchanged'):
            self.step('publish', {'position': 4, 'section': ['anime', [edited], 'Cosy night!']})
        with patch('goodmorning.briefings.briefing_images.cache_previews', return_value={}) as covers:
            self.step('publish', {'position': 4, 'section': ['anime', [block], 'A new case for a cosy night!']})
        self.assertTrue(covers.call_args.kwargs['direct'])
        self.assertEqual(self.step('finish', {})['saved'], True)

    def test_section_is_absent_unless_turned_on(self):
        (self.root / 'profile.md').write_text((self.root / 'profile.md').read_text().replace('anime_updates: "true"', 'anime_updates: "false"'))
        self.job()
        self.step('init', {'greeting': 'Evening.', 'opening': 'Tonight’s review.'})
        plan = json.loads((self.root / 'browser-jobs' / ('c' * 32 + '.preview.json')).read_text())['plan']
        self.assertNotIn('anime', [tag for tag, _ in plan])


if __name__ == '__main__':
    unittest.main()
