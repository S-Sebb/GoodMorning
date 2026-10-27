"""Celebrations: birthdays, festivals, GoodMorning anniversaries and task milestones, found by code and shown on one card."""
from datetime import date as Date, datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT, offline_provider_reads
from test_letters import records
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.briefings import briefing_document as native
from goodmorning.briefings.briefing_job import act
from goodmorning.briefings.briefing_preflight import initialize as preflight
from goodmorning.records import celebrations
from goodmorning.web import app_briefings
from goodmorning.web import language as ui
from goodmorning.web.briefing_server import BrowserApp

DAY = '2026-10-26'
MORNING = datetime(2026, 10, 25, 23, tzinfo=timezone.utc)  # 07:00 in Shanghai


def visible(markup):
    return ' '.join(re.sub(r'<[^>]+>', ' ', markup).split())


class CelebrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)
        offline_provider_reads(self)
        self.profile('')
        (self.root / 'daily').mkdir()
        records(self.root)

    def profile(self, extra):
        (self.root / 'profile.md').write_text('secretary_name: "Mochi"\ncity: Shanghai, CN\ntimezone: Asia/Shanghai\n'
                                              'news_country: CN\nsecretary_language: English\n' + extra)

    def saved(self, day, kind='gm'):
        (self.root / 'daily' / f'{day}.{kind}.json').write_text('{}')

    def job(self, identifier='c' * 32, day=DAY):
        app = BrowserApp(self.root, now=lambda: MORNING, preflight=True)
        job = {'id': identifier, 'date': day, 'kind': 'gm', 'state': 'preflight', 'session': 'ses_test',
               'created': MORNING.timestamp()}
        app.jobs[day + '.gm'] = job; app.save_jobs()
        preflight(self.root, job)
        job['state'] = 'running'; app.jobs[day + '.gm'] = job; app.save_jobs()
        return identifier

    def step(self, action, payload=None, identifier='c' * 32):
        return act(self.root, identifier, 'ses_test', action, payload)

    def test_birthdays_are_a_month_and_day_and_29_february_moves_to_the_28th(self):
        self.assertEqual([celebrations.birthday(value) for value in ('02-13', ' 02-29 ', '')], ['02-13', '02-29', ''])
        for wrong in ('2-13', '13-01', '02-30', '2000-02-13'):
            with self.assertRaisesRegex(ValueError, 'MM-DD'):
                celebrations.birthday(wrong)
        self.assertTrue(celebrations.yearly(Date(2027, 2, 28), '02-29'))
        self.assertFalse(celebrations.yearly(Date(2028, 2, 28), '02-29'))
        self.assertTrue(celebrations.yearly(Date(2028, 2, 29), '02-29'))

    def test_birthday_anniversaries_and_the_first_briefing_come_from_saved_records(self):
        self.assertEqual(celebrations.found(self.root, DAY, 'gm'), [])
        self.profile('birthday: "10-26"\n')
        self.assertEqual(celebrations.found(self.root, DAY, 'gm'), [['birthday']])
        self.profile('birthday: "Oct 26"\n')  # Unreadable: no card, no error.
        self.assertEqual(celebrations.found(self.root, DAY, 'gm'), [])
        self.saved('2025-10-26', 'gn'); self.saved('2026-07-18')
        (self.root / 'daily' / '2024-01-01.md').write_text('')  # Daily notes are not briefings.
        self.assertEqual(celebrations.first_briefing(self.root), '2025-10-26')
        self.assertEqual(celebrations.found(self.root, DAY, 'gm'), [['years', 1, '2025-10-26']])
        (self.root / 'daily' / '2025-10-26.gn.json').unlink()
        self.assertEqual(celebrations.found(self.root, DAY, 'gm'), [['days', 100, '2026-07-18']])
        # Evening shows the card only when no morning briefing was saved that day.
        self.assertEqual(celebrations.found(self.root, DAY, 'gn'), [['days', 100, '2026-07-18']])
        self.saved(DAY)
        self.assertEqual(celebrations.found(self.root, DAY, 'gn'), [])

    def test_festivals_greet_on_their_first_day_in_the_followed_regions(self):
        self.profile('birthday: "10-01"\nholiday_countries: "CN, GB-SCT"\n')
        self.assertEqual(celebrations.found(self.root, '2026-10-01', 'gm'), [['birthday'], ['holiday', 'National Day', ['China']]])
        self.assertEqual(celebrations.found(self.root, '2026-10-02', 'gm'), [])  # Still National Day, already greeted.
        self.assertEqual(celebrations.found(self.root, '2026-04-05', 'gm'), [])  # Tomb-Sweeping Day is not festive.
        self.assertEqual(celebrations.found(self.root, '2026-12-25', 'gm'), [['holiday', 'Christmas Day', ['United Kingdom']]])
        self.profile('holiday_countries: "GB"\n')  # Unreadable: no holidays anywhere.
        self.assertEqual(celebrations.found(self.root, '2026-12-25', 'gm'), [])
        item = ['holiday', 'Christmas Day', ['United Kingdom', 'China']]
        self.assertEqual(celebrations.words(item, ui.text, 'en'), ('Merry Christmas! 🎄', 'Today is a public holiday in the United Kingdom and China.'))
        token = ui.CURRENT.set('zh-CN')
        try:
            self.assertEqual(celebrations.words(item, ui.text, 'zh-CN'), ('圣诞快乐！🎄', '今天是英国、中国的公共假期。'))
        finally:
            ui.CURRENT.reset(token)
        native.block(['celebration', [item], 'Merry, merry!', ''], 'celebration')
        for wrong in (['holiday', 'Tomb-Sweeping Day', ['China']], ['holiday', 'Christmas Day', ['Atlantis']]):
            with self.assertRaises(ValueError):
                native.block(['celebration', [wrong], 'Hi', ''], 'celebration')

    def test_a_milestone_shows_once_and_counts_only_confirmed_tasks(self):
        self.assertEqual(celebrations.tasks_done(self.root, 'Asia/Shanghai'), 7)  # As the weekly letter counts them.
        self.assertEqual(celebrations.milestones(2400), [100, 250, 500, 1000, 2000])
        with patch.object(celebrations, 'tasks_done', return_value=312):
            items = celebrations.found(self.root, DAY, 'gm')
            self.assertEqual(items, [['tasks', 250, 312]])  # The highest one reached; 100 is never shown later.
            celebrations.remember(self.root, DAY, items)
            self.assertEqual(celebrations.found(self.root, DAY, 'gm'), items)  # A regenerated briefing keeps it.
            self.assertEqual(celebrations.found(self.root, '2026-10-27', 'gm'), [])
        with patch.object(celebrations, 'tasks_done', return_value=500):
            self.assertEqual(celebrations.found(self.root, '2026-10-28', 'gm'), [['tasks', 500, 500]])
        self.assertEqual(json.loads((self.root / 'celebrations.json').read_text()), {'tasks': {'100': DAY, '250': DAY}})

    def test_the_card_opens_the_briefing_with_code_facts_and_the_secretarys_wish(self):
        self.profile('birthday: "10-26"\n')
        self.saved('2026-07-18')
        with patch.object(celebrations, 'tasks_done', return_value=100):
            self.job()
        result = self.step('init', {'greeting': 'Good morning.', 'opening': 'Weather, news and your day.'})
        self.assertEqual(result['next']['section'], ['celebration', 'Something to celebrate'])
        self.assertEqual(result['next']['input'], {'position': 0, 'celebration': {'wish': '…'}})
        self.assertEqual([entry['headline'] for entry in result['next']['celebrations']],
                         ['Happy birthday! 🎂', '100 days of GoodMorning! 🌱', '100 tasks done! ✨'])
        self.assertEqual(result['next']['celebrations'][1]['line'], 'Your very first briefing was on July 18, 2026, 100 days ago today.')
        self.assertIn('never "we"', result['next']['guide'])
        with self.assertRaisesRegex(ValueError, 'do not skip'):
            self.step('skip', {'position': 0})
        for wrong in ({'position': 0}, {'position': 0, 'celebration': {'wish': ''}},
                      {'position': 0, 'section': ['celebration', [['celebration', [['birthday']], 'Hi', '']]]}):
            with self.assertRaises(ValueError):
                self.step('publish', wrong)
        self.assertFalse((self.root / 'celebrations.json').exists())
        wish = 'Wishing you a sparkly, happy day!'
        result = self.step('publish', {'position': 0, 'celebration': {'wish': wish}})
        self.assertEqual(result['next']['section'][0], 'weather')
        self.assertTrue(self.step('publish', {'position': 0, 'celebration': {'wish': wish}})['reused'])
        preview = json.loads((self.root / 'browser-jobs' / ('c' * 32 + '.preview.json')).read_text())
        block = ['celebration', [['birthday'], ['days', 100, '2026-07-18'], ['tasks', 100, 100]], wish, 'Mochi']
        self.assertEqual(preview['document']['sections'][0], ['celebration', [block]])
        self.assertEqual(json.loads((self.root / 'celebrations.json').read_text()), {'tasks': {'100': DAY}})
        self.assertEqual(visible(native.render_block(block, {})),
                         'Happy birthday! 🎂 100 days of GoodMorning! 🌱 Your very first briefing was on July 18, 2026, 100 days ago today. '
                         '100 tasks done! ✨ You’ve ticked off 100 tasks in GoodMorning so far. ' + wish + ' — Mochi')
        token = ui.CURRENT.set('zh-CN')
        try:
            self.assertIn('你的第一份简报是 2026年7月18日，到今天正好 100 天。', visible(native.render_block(block, {})))
            rows = app_briefings.document({'greeting': '', 'opening': '', 'sections': [['celebration', [block]]]}, DAY)['sections'][0]['rows']
        finally:
            ui.CURRENT.reset(token)
        self.assertEqual([(row['title'], row['text']) for row in rows],
                         [('生日快乐呀！🎂', ''), ('GoodMorning 100 天啦！🌱', '你的第一份简报是 2026年7月18日，到今天正好 100 天。'),
                          ('100 件待办搞定！✨', '你已经在 GoodMorning 里勾掉了 100 件待办。'), ('', wish)])

    def test_an_ordinary_day_has_no_celebration_section(self):
        self.job()
        result = self.step('init', {'greeting': 'Good morning.', 'opening': 'Weather, news and your day.'})
        self.assertEqual(result['next']['section'][0], 'weather')


if __name__ == '__main__':
    unittest.main()
