"""Public holidays come from bundled data on display; synthetic accounts, no network."""
import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.briefings import briefing_document as native
from goodmorning.calendar import public_holidays
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.records import routing
from goodmorning.records.inbox_store import initialize
from goodmorning.setup_check import profile_status
from goodmorning.web import language as ui
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web.schedule import saved_week, snapshot

NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)


class DataTests(unittest.TestCase):
    def kinds(self, code, start, end):
        return {day: [entry['kind'] for entry in entries] for day, entries in public_holidays.days([code], start, end, 'en').items()}

    def test_china_follows_the_announced_runs_and_make_up_workdays(self):
        # 2026: Mid-Autumn 25–27 September; National Day 1–7 October with 20 September and 10 October worked;
        # Spring Festival 15–23 February.
        october = self.kinds('CN', '2026-09-19', '2026-10-12')
        self.assertEqual(october, {'2026-09-20': ['workday'], **{f'2026-09-{day}': ['holiday'] for day in range(25, 28)},
                                   **{f'2026-10-0{day}': ['holiday'] for day in range(1, 8)},
                                   '2026-10-10': ['workday']})
        february = [day for day, kinds in self.kinds('CN', '2026-02-01', '2026-03-01').items() if kinds == ['holiday']]
        self.assertEqual(february, [f'2026-02-{day}' for day in range(15, 24)])
        new_year = public_holidays.days(['CN'], '2026-01-01', '2026-01-05', 'zh-CN')
        self.assertEqual([(day, entry['kind']) for day, (entry,) in new_year.items()],
                         [('2026-01-01', 'holiday'), ('2026-01-02', 'holiday'), ('2026-01-03', 'holiday'), ('2026-01-04', 'workday')])
        self.assertEqual(new_year['2026-01-01'][0]['name'], '元旦')
        workday, = public_holidays.days(['CN'], '2026-10-10', '2026-10-11', 'en')['2026-10-10']
        self.assertEqual(workday['name'], 'National Day make-up workday')

    def test_china_shows_nothing_for_an_unannounced_year(self):
        self.assertEqual(public_holidays.days(['CN'], '2027-01-01', '2028-01-01', 'en'), {})
        self.assertEqual(public_holidays.unlisted(['CN', 'GB-SCT'], '2026-12-28', '2027-01-03'), [('CN', 2027)])

    def test_regions_differ_and_every_name_has_chinese_wording(self):
        self.assertIn('2026-11-30', public_holidays.days(['GB-SCT'], '2026-11-01', '2026-12-01', 'en'))
        self.assertNotIn('2026-11-30', public_holidays.days(['GB-ENG'], '2026-11-01', '2026-12-01', 'en'))
        for region in public_holidays.REGIONS.values():
            for name in (region['country'], region['label'], *region['days'].values(), *region['workdays'].values()):
                self.assertTrue(public_holidays.DATA['names'][name].strip(), name)

    def test_setting_values_and_helper(self):
        self.assertEqual(public_holidays.regions(''), [])
        self.assertEqual(public_holidays.regions('None'), [])
        self.assertEqual(public_holidays.regions(' cn; gb-sct, CN '), ['CN', 'GB-SCT'])
        for bad in ('GB', 'XX', 'CN, Mars'):
            with self.assertRaises(ValueError): public_holidays.regions(bad)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(public_holidays.main(['--check', 'cn, gb-sct', '--website-language', 'zh-CN']), 0)
        self.assertEqual(json.loads(output.getvalue()), {'save': 'CN, GB-SCT', 'regions': [
            {'code': 'CN', 'name': '中国'}, {'code': 'GB-SCT', 'name': '英国 — 苏格兰'}]})
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(public_holidays.main(['--check', 'GB']), 1)
        self.assertEqual(json.loads(output.getvalue())['error'], 'unknown_region')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            public_holidays.main(['--list'])
        names = {row['code']: row['name'] for row in json.loads(output.getvalue())['regions']}
        self.assertEqual((names['US'], names['AU-NSW']), ('United States', 'Australia — New South Wales'))


class DisplayTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.profile('CN')
        CalendarStore(str(self.root / 'calendar.sqlite')).close()
        token = ui.CURRENT.set('en')
        self.addCleanup(ui.CURRENT.reset, token)

    def profile(self, holidays):
        (self.root / 'profile.md').write_text('city: Shanghai, CN\ntimezone: Asia/Shanghai\nnews_country: CN\n'
                                              'secretary_language: English\nholiday_countries: ' + holidays + '\n')

    def test_schedule_heads_each_day_without_counting_holidays_as_events(self):
        week = saved_week(self.root, 'Asia/Shanghai', NOW, -2)  # 28 September – 4 October 2026.
        self.assertEqual([day['holidays'] for day in week['days'][:4]],
                         [[], [], [], [{'kind': 'holiday', 'title': 'National Day'}]])
        self.assertEqual(sum(len(day['events']) for day in week['days']), 0)
        app = BrowserApp(self.root, now=lambda: NOW)
        markup = snapshot(app, -2)['view']
        self.assertIn('<p class="schedule-holiday is-holiday" data-content>National Day</p>', markup)
        self.assertIn('<dt><bdi lang="en" data-ui-text="Events">Events</bdi></dt><dd>0</dd>', markup)
        ui.CURRENT.set('zh-CN')
        self.assertIn('国庆节', snapshot(app, -2)['view'])
        self.assertIn('国庆调休上班', snapshot(app, -1)['view'])  # 10 October.

    def test_several_regions_name_theirs_and_a_bad_setting_shows_a_notice(self):
        self.profile('CN, US')
        week = saved_week(self.root, 'Asia/Shanghai', NOW, 0)
        self.assertEqual(week['days'][0]['holidays'], [{'kind': 'holiday', 'title': 'Columbus Day · United States'}])
        # A holiday shared by every followed region appears once; one some lack names who has it.
        self.profile('GB-ENG, GB-WLS, GB-SCT')
        week = saved_week(self.root, 'Asia/Shanghai', datetime(2026, 11, 30, 12, tzinfo=timezone.utc), 0)
        self.assertEqual(week['days'][0]['holidays'], [{'kind': 'holiday', 'title': "Saint Andrew's Day · Scotland"}])
        week = saved_week(self.root, 'Asia/Shanghai', datetime(2026, 12, 23, 12, tzinfo=timezone.utc), 0)
        self.assertEqual(week['days'][4]['holidays'], [{'kind': 'holiday', 'title': 'Christmas Day'}])
        token = ui.CURRENT.set('zh-CN')
        try:
            self.profile('GB-ENG, GB-SCT, US')
            self.assertIn({'kind': 'holiday', 'title': '节礼日 · 英格兰、苏格兰'}, saved_week(self.root, 'Asia/Shanghai', datetime(2026, 12, 23, 12, tzinfo=timezone.utc), 0)['days'][5]['holidays'])
        finally:
            ui.CURRENT.reset(token)
        self.profile('Narnia')
        week = saved_week(self.root, 'Asia/Shanghai', NOW, 0)
        self.assertEqual([day['holidays'] for day in week['days']], [[]] * 7)
        self.assertIn('Your public holiday choice could not be read, so no holidays are shown.', week['warnings'])
        self.assertEqual(profile_status(self.root, {'holiday_countries': 'Narnia'})['holiday_countries'], 'invalid')
        self.assertEqual(profile_status(self.root, {'holiday_countries': 'none'})['holiday_countries'], 'declined')
        self.assertIsNone(profile_status(self.root, {})['holiday_countries'])

    def test_briefings_show_the_focus_day_as_a_source_linked_card(self):
        initialize(self.root)
        morning = routing.prepare(self.root, '2026-10-01', 'gm')
        block = morning['blocks']['schedule']
        identifier = block[1][0][0]
        self.assertRegex(identifier, '^hd_[0-9a-f]{16}$')
        self.assertEqual(block[1], [[identifier, 1, '2026-10-01', 'Public holiday', 'National Day', '', '']])
        document = {'v': 2, 'greeting': 'Hello.', 'opening': 'Synthetic.', 'sections': [['schedule', [block]]]}
        native.parse(json.dumps(document))
        routing.validate_sources(self.root, document, '2026-10-01', 'gm')
        evening = routing.prepare(self.root, '2026-10-09', 'gn')['blocks']['schedule']
        self.assertEqual(evening[1][0][2:5], ['2026-10-10', 'Workday', 'National Day make-up workday'])
        self.assertEqual(routing.prepare(self.root, '2026-10-12', 'gm')['blocks']['schedule'][1], [])
        token = ui.CURRENT.set('zh-CN')
        try:
            chinese = routing.prepare(self.root, '2026-10-01', 'gm')['blocks']['schedule'][1][0]
        finally:
            ui.CURRENT.reset(token)
        self.assertEqual(chinese[0], identifier)
        self.assertEqual(chinese[4], '国庆节')


if __name__ == '__main__':
    unittest.main()
