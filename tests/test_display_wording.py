"""Display wording: saved once with the item, read by the briefings and the Schedule tab."""
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.records.inbox_store import InboxStore, initialize
from goodmorning.records.task_store import TaskStore
from goodmorning.records import routing
from goodmorning.records.display import check, fingerprint
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.web.schedule import saved_week
from goodmorning.web import language as ui

DAY = '2026-10-13'  # Tuesday
NOW = DAY + 'T12:00:00+01:00'
ZONE = 'Europe/London'
HELPDESK = {'en': {'morning': {'title': 'Call extension 4471 about the receipt upload error', 'detail': ''},
                   'evening': {'title': 'IT helpdesk call', 'detail': 'Have a screenshot of the upload error ready.'},
                   'schedule': 'IT helpdesk call'},
            'zh': {'morning': {'title': '拨打分机 4471 处理报销上传报错', 'detail': ''},
                   'evening': {'title': 'IT 服务台电话', 'detail': '准备好上传报错的截图。'},
                   'schedule': 'IT 服务台电话'}}


def words(title, schedule=None, detail=''):
    return {language: {'morning': {'title': title, 'detail': detail}, 'schedule': schedule or title} for language in ('en', 'zh')}


class DisplayWordingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)
        (self.root/'profile.md').write_text('city: London, GB\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n')
        initialize(self.root)
        CalendarStore(str(self.root/'calendar.sqlite')).close()
        self.inbox = InboxStore(self.root, write=True)
        self.addCleanup(self.inbox.close)
        self.tasks = TaskStore(self.inbox)
        self.n = 0

    def capture(self, **task):
        self.n += 1
        return self.inbox.mutate('add', {'kind': 'todo', 'raw': task['title'], 'task': task}, 'ses_test', str(self.n), NOW)['task_id']

    def cells(self, kind='gm', day=DAY, lang='en'):
        token = ui.CURRENT.set(lang)
        try:
            view = routing.prepare(self.root, day, kind, limit=200)
        finally:
            ui.CURRENT.reset(token)
        return {row[0]: row for row in view['blocks']['tasks'][1]}, view['tasks']['fallback'], view

    def test_wording_needs_both_languages_and_no_relative_time(self):
        for bad, message in (({'en': HELPDESK['en']}, 'en and zh'),
                             ({**HELPDESK, 'en': {**HELPDESK['en'], 'schedule': 'Helpdesk call tomorrow'}}, 'relative time'),
                             ({**HELPDESK, 'zh': {**HELPDESK['zh'], 'schedule': '明天打电话'}}, 'relative time'),
                             ({**HELPDESK, 'en': {'schedule': 'IT helpdesk call'}}, 'morning and schedule'),
                             ({**HELPDESK, 'source': 'not-a-fingerprint'}, 'code-owned')):
            with self.assertRaisesRegex(ValueError, message):
                self.capture(title='Call the IT helpdesk', display=bad)
        identifier = self.capture(title='Call the IT helpdesk', display={**HELPDESK})
        saved = self.tasks.show(identifier)['display']
        self.assertEqual(saved['source'], fingerprint('task', self.tasks.show(identifier)))  # Stamped by code.

    def test_briefings_show_morning_and_evening_wording_in_the_page_language(self):
        identifier = self.capture(title='Call the IT helpdesk', detail='Ext. 4471. Reminder date: tomorrow.', planned_date='2026-10-14',
                                  display=HELPDESK)
        morning, fallback, _ = self.cells('gm', '2026-10-14')
        self.assertEqual(morning[identifier][5:], ['Call extension 4471 about the receipt upload error', ''])
        self.assertNotIn(identifier, fallback)
        evening, _, _ = self.cells('gn', DAY)
        self.assertEqual(evening[identifier][5:], ['IT helpdesk call', 'Have a screenshot of the upload error ready.'])
        chinese, _, _ = self.cells('gn', DAY, 'zh-CN')
        self.assertEqual(chinese[identifier][5], 'IT 服务台电话')
        plain = self.capture(title='Review the venue contract', display=words('Review the venue contract', 'Venue contract'))
        self.assertEqual(self.cells()[0][plain][5], 'Review the venue contract')  # No evening wording: morning is reused.

    def test_outside_changes_fall_back_to_saved_fields_but_status_does_not(self):
        identifier = self.capture(title='Call the IT helpdesk', display=HELPDESK)
        self.tasks.mutate(identifier, 1, {'status': 'partial', 'detail': ''}, 'ses_test', 'progress', NOW)
        self.assertNotIn(identifier, self.cells()[1])  # Status and empty detail change nothing the wording describes...
        self.tasks.mutate(identifier, 2, {'title': 'Call the finance helpdesk'}, 'ses_test', 'rename', NOW)
        row, fallback, _ = self.cells()
        self.assertEqual(row[identifier][5], 'Call the finance helpdesk')  # ...a rename without new wording falls back.
        self.assertIn(identifier, fallback)
        self.tasks.mutate(identifier, 3, {'display': {**HELPDESK, 'source': '0' * 16}}, 'ses_test', 'reword', NOW)
        self.assertNotIn(identifier, self.cells()[1])  # New wording is fingerprinted afresh, whatever source was sent.

    def test_calendar_events_and_tbc_appointments_use_their_wording(self):
        calendar = CalendarStore(str(self.root/'calendar.sqlite'))
        try:
            calendar.stage('outlook', [{'external_id': 'sync', 'subject': 'FW: Weekly sync (updated invite)',
                                        'start': DAY + 'T10:00:00+01:00', 'end': DAY + 'T11:00:00+01:00', 'timezone': ZONE}])
            pending = calendar.pending()[0]
            calendar.change(pending['id'], 'approve', pending['revision'], {'display': words('Weekly sync', detail='Bring the slides.')})
            with self.assertRaisesRegex(ValueError, 'unsupported import fields'):
                calendar.stage('outlook', [{'external_id': 'x', 'subject': 'X', 'start': DAY + 'T12:00:00+01:00',
                                            'end': DAY + 'T13:00:00+01:00', 'display': words('X')}])
        finally:
            calendar.close()
        self.inbox.mutate('add', {'kind': 'event_proposal', 'raw': 'Archery', 'draft': {
            'title': 'Archery class at Hongqiao', 'date': DAY, 'timezone': ZONE, 'confirmed_day': True,
            'display': words('Archery class', 'Archery')}}, 'ses_test', 'draft', NOW)
        _, _, view = self.cells()
        shown = {row[4]: row for row in view['blocks']['schedule'][1]}
        self.assertEqual(shown['Weekly sync'][6], 'Bring the slides.')
        self.assertIn('Archery class', shown)
        week = saved_week(self.root, ZONE, datetime(2026, 10, 13, 9, tzinfo=timezone.utc), 0)['days'][1]
        self.assertEqual(sorted(e.get('subject') for e in week['events']), ['Archery', 'Weekly sync'])

    def test_schedule_tab_uses_the_label_in_each_language(self):
        self.capture(title='Call the IT helpdesk', planned_date=DAY, display=HELPDESK)
        for lang, label in (('en', 'IT helpdesk call'), ('zh-CN', 'IT 服务台电话')):
            token = ui.CURRENT.set(lang)
            try:
                tasks = saved_week(self.root, ZONE, datetime(2026, 10, 13, 9, tzinfo=timezone.utc), 0)['days'][1]['tasks']
            finally:
                ui.CURRENT.reset(token)
            self.assertEqual([t['text'] for t in tasks], [label])

    def test_check_rejects_overlong_labels(self):
        with self.assertRaisesRegex(ValueError, 'at most 40'):
            check({**HELPDESK, 'en': {**HELPDESK['en'], 'schedule': 'x' * 41}}, 'task', {'title': 'x'})


if __name__ == '__main__':
    unittest.main()
