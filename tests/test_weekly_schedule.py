"""Weekly schedule uses synthetic, account-local records and never dispatches work."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from support import TEMP_ROOT, start_server
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.web import language as ui
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web.schedule import saved_week, schedule_query, snapshot, week_offset
from goodmorning.records.inbox_store import InboxStore, initialize
from goodmorning.records.task_store import TaskStore

NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)


def make_runtime(root):
    (root / 'profile.md').write_text('timezone: Europe/London\nsecretary_language: English\ncity: London, GB\nnews_country: GB\n')
    (root / 'daily').mkdir()
    (root / 'daily/2026-10-12.md').write_text('# 2026-10-12\n\n## flexible\n- [x] Review the outline\n')
    (root / 'daily/2026-10-13.md').write_text('# 2026-10-13\n\n## must-do\n- [ ] Atlas: draft the methods\n\n## flexible\n- [ ] Pick up a parcel\n')
    (root / 'daily/2026-10-15.md').write_text('# 2026-10-15\n\n## nice-to-do\n- [ ] Atlas: try the new figure layout\n')
    store = CalendarStore(str(root / 'calendar.sqlite'))
    try:
        meeting = {'subject': 'Team check-in', 'start': '2026-10-13T09:30:00+01:00',
                   'end': '2026-10-13T10:00:00+01:00', 'location': 'Studio 2', 'notes': 'Bring the outline.'}
        store.add(meeting)
        store.add({'subject': 'Quiet working block', 'start': '2026-10-14T10:00:00+01:00', 'end': '2026-10-14T11:30:00+01:00'})
        store.add({'subject': 'Design review', 'start': '2026-10-16T14:00:00+01:00', 'end': '2026-10-16T15:00:00+01:00', 'location': 'Library'})
        store.add({'subject': 'A day away', 'start': '2026-10-17', 'end': '2026-10-18', 'all_day': True, 'timezone': 'Europe/London'})
        store.import_events('work', [{'external_id': 'imported-1', **meeting, 'subject': 'Imported invitation',
                                      'start': '2026-10-20T09:30:00+01:00', 'end': '2026-10-20T10:00:00+01:00'}])
    finally:
        store.close()
    return BrowserApp(root, now=lambda: NOW)


def canonical_records(root):
    initialize(root)
    inbox = InboxStore(root, write=True)
    tasks = TaskStore(inbox)
    receipts = {}
    try:
        for key, fields in {
            'outline': {'title': 'Review the outline', 'planned_date': '2026-10-12'},
            'methods': {'title': 'Draft the methods', 'project': 'Atlas', 'planned_date': '2026-10-13', 'due_date': '2026-10-16', 'detail': 'Compare the two baselines.'},
            'parcel': {'title': 'Pick up a parcel', 'planned_date': '2026-10-13'},
            'layout': {'title': 'Try the new figure layout', 'project': 'Atlas', 'optional': True, 'planned_date': '2026-10-15'},
            'blocked': {'title': 'Request the dataset', 'project': 'Atlas', 'planned_date': '2026-10-13'},
            'towels': {'title': 'Wash towels', 'timezone': 'Europe/London', 'repeat': {'weekdays': [5], 'start': '2026-10-13'}},
            'deadline': {'title': 'Deadline only, not a workday', 'due_date': '2026-10-16'},
        }.items():
            receipts[key] = inbox.mutate('add', {'kind': 'todo', 'raw': fields['title'], 'task': fields}, 'ses_synthetic', key, NOW.isoformat())
        tasks.mutate(receipts['outline']['task_id'], 1, {'status': 'done', 'confirmed_completion': True}, 'ses_synthetic', 'done', NOW.isoformat())
        tasks.mutate(receipts['methods']['task_id'], 1, {'status': 'partial', 'detail': 'First baseline compared.'}, 'ses_synthetic', 'partial', NOW.isoformat(), day='2026-10-13')
        tasks.mutate(receipts['blocked']['task_id'], 1, {'status': 'blocked', 'detail': 'Awaiting lab approval.'}, 'ses_synthetic', 'blocked-report', NOW.isoformat(), day='2026-10-13')
        receipts['dentist'] = inbox.mutate('add', {'kind': 'event_proposal', 'raw': 'Dentist Thursday, time unknown',
            'draft': {'title': 'Dentist', 'date': '2026-10-15', 'timezone': 'Europe/London', 'confirmed_day': True,
                      'location': 'Town Clinic', 'detail': 'Bring the referral.'}}, 'ses_synthetic', 'dentist', NOW.isoformat())
        return receipts
    finally:
        inbox.close()


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = make_runtime(self.root)
        self.token = ui.CURRENT.set('en')
        self.addCleanup(ui.CURRENT.reset, self.token)

    def data(self, offset=0):
        return saved_week(self.root, 'Europe/London', self.app.now(), offset)

    def test_canonical_week_shows_tbc_attributes_reports_and_only_agreed_workdays(self):
        canonical_records(self.root)
        days = {day['date']: day for day in self.data()['days']}
        tasks = {task['text']: task for day in days.values() for task in day['tasks']}
        self.assertEqual([(e['subject'], e.get('draft')) for e in days['2026-10-15']['events']], [('Dentist', True)])
        fields = ('status', 'project', 'due_date', 'report_detail')
        self.assertEqual([tasks[name][k] for name in ('Draft the methods', 'Request the dataset') for k in fields],
                         ['partial', 'Atlas', '2026-10-16', 'First baseline compared.',
                          'blocked', 'Atlas', '', 'Awaiting lab approval.'])
        deadline = tasks['Deadline only, not a workday']
        self.assertEqual((deadline['date'], deadline['marker'], deadline['occurrence_id']), ('2026-10-16', 'due', ''))
        self.assertEqual([r['text'] for r in days['2026-10-17']['tasks']], ['Wash towels'])
        self.assertFalse(any(r.get('draft') for r in days['2026-10-17']['events']))
        for language in ('en', 'zh-CN'):
            ui.CURRENT.set(language)
            markup = snapshot(self.app, 0)['view']
            self.assertIn(ui.text('Appointment time not yet confirmed'), markup)
            self.assertIn('Awaiting lab approval.', markup)

    def test_canonical_reads_ignore_legacy_failures_and_do_not_mutate_records(self):
        canonical_records(self.root)
        (self.root/'daily/2026-10-13.md').write_text('## flexible\n## flexible\n')
        before = {p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        first = snapshot(self.app, 0)
        self.assertIn('Draft the methods', first['view'])
        self.assertFalse(any(day['plan_error'] for day in self.data()['days']))
        self.assertEqual({p:p.read_bytes() for p in before}, before)
        # Canonical state, not legacy checkboxes, drives refresh.
        inbox = InboxStore(self.root, write=True)
        try:
            parcel = next(t for t in TaskStore(inbox).all() if t['title'] == 'Pick up a parcel')
            TaskStore(inbox).mutate(parcel['id'], parcel['revision'], {'status':'done', 'confirmed_completion':True}, 'ses_synthetic', 'parcel-done', NOW.isoformat())
        finally:
            inbox.close()
        self.assertNotEqual(first['revision'], snapshot(self.app, 0)['revision'])

    def test_tbc_conversion_and_pending_proposals_do_not_duplicate_or_reserve_days(self):
        receipts = canonical_records(self.root)
        inbox = InboxStore(self.root, write=True)
        try:
            inbox.mutate('add', {'kind':'event_proposal', 'raw':'Maybe meet Sam', 'draft':{'title':'Tentative Sam', 'date':'2026-10-15', 'timezone':'Europe/London', 'state':'tentative'}}, 'ses_synthetic', 'sam', NOW.isoformat())
            self.assertNotIn('Tentative Sam', snapshot(self.app, 0)['view'])
            draft = receipts['dentist']['draft_id']
            event = {'subject':'Dentist', 'start':'2026-10-15T14:00:00+01:00', 'end':'2026-10-15T15:00:00+01:00'}
            calendar = CalendarStore(str(self.root/'calendar.sqlite'))
            calendar.add(event, external_id=draft)  # Interrupted conversion after calendar commit.
            calendar.close()
            self.assertEqual(sum(e['subject']=='Dentist' for day in self.data()['days'] for e in day['events']), 1)
            TaskStore(inbox).convert(self.root, draft, 1, {'event':event}, 'ses_synthetic', 'convert', NOW.isoformat())
            self.assertEqual(sum(e['subject']=='Dentist' for day in self.data()['days'] for e in day['events']), 1)
        finally:
            inbox.close()

    def test_task_store_failure_is_not_reported_as_a_calendar_outage(self):
        canonical_records(self.root)
        def malformed():
            inbox = InboxStore(self.root, write=True)
            try:
                inbox.db.execute("UPDATE tasks SET data=? WHERE id=(SELECT id FROM tasks LIMIT 1)", ('{"title":"Incomplete record"}',))
            finally:
                inbox.close()
        for corrupt in (malformed, lambda: (self.root/'inbox.sqlite').write_bytes(b'not a task database')):
            corrupt()
            markup = snapshot(self.app, 0)['view']
            self.assertIn('Team check-in', markup)
            self.assertIn(ui.text('Task records unavailable'), markup)
            self.assertFalse(self.data().get('calendar_error'))
            self.assertNotIn('Atlas: draft the methods', markup)

    def test_interrupted_conversion_moved_to_another_week_hides_the_old_tbc_card(self):
        receipts=canonical_records(self.root)
        store=CalendarStore(str(self.root/'calendar.sqlite'))
        try:
            store.add({'subject':'Dentist','start':'2026-10-22T14:00:00+01:00','end':'2026-10-22T15:00:00+01:00'},
                      external_id=receipts['dentist']['draft_id'])
        finally:
            store.close()
        self.assertNotIn('Dentist',snapshot(self.app,0)['view'])
        self.assertIn('Dentist',snapshot(self.app,1)['view'])

    def test_current_week_uses_actual_midnight_not_briefing_cutoff(self):
        self.app.now = lambda: datetime(2026, 10, 11, 23, 30, tzinfo=timezone.utc)
        data = self.data()
        self.assertEqual(data['today'], '2026-10-12')
        self.assertEqual(data['start'], '2026-10-12')
        self.assertEqual(self.app.today(), '2026-10-11')
        self.assertEqual(len(data['days']), 7)
        self.assertEqual(data['days'][-1]['date'], '2026-10-18')

    def test_week_window_and_strict_query_validation(self):
        self.assertEqual(self.data(-3)['start'], '2026-09-21')
        self.assertEqual(self.data(3)['start'], '2026-11-02')
        for query in ({'week': ['4']}, {'week': ['-4']}, {'week': ['1', '2']},
                      {'week': ['']}, {'week': ['1.0']}, {'runtime': ['/other']}, {'week': ['+1']}):
            with self.subTest(query=query), self.assertRaises(ValueError):
                week_offset(query)
        for invalid in (-4, 4, True):
            with self.assertRaises(ValueError): self.data(invalid)
        self.assertEqual(week_offset({}), 0)
        self.assertEqual(week_offset({'week': ['-3']}), -3)
        self.assertNotIn('id="week-previous"', snapshot(self.app, -3)['view'])
        self.assertNotIn('id="week-next"', snapshot(self.app, 3)['view'])

    def test_view_query_validation(self):
        self.assertEqual(schedule_query({}), ('week', 0))
        self.assertEqual(schedule_query({'week': ['2']}), ('week', 2))
        self.assertEqual(schedule_query({'view': ['day']}), ('day', 0))
        self.assertEqual(schedule_query({'view': ['day'], 'day': ['-21']}), ('day', -21))
        for query in ({'view': ['week']}, {'view': ['day'], 'day': ['22']}, {'view': ['day'], 'day': ['+1']},
                      {'view': ['day'], 'day': ['01']}, {'view': ['day'], 'week': ['1']}, {'view': ['day', 'day']},
                      {'day': ['1']}):
            with self.subTest(query=query), self.assertRaises(ValueError):
                schedule_query(query)

    def test_day_view_shows_one_day_with_live_event_states(self):
        canonical_records(self.root)
        store = CalendarStore(str(self.root / 'calendar.sqlite'))
        store.add({'subject': 'Lunch with Mia', 'start': '2026-10-13T12:30:00+01:00', 'end': '2026-10-13T13:30:00+01:00'})
        store.add({'subject': 'Design sync', 'start': '2026-10-13T15:00:00+01:00', 'end': '2026-10-13T16:00:00+01:00'})
        store.close()
        today = snapshot(self.app, 0, 'day')
        markup = today['view']
        self.assertEqual(today['mode'], 'day')
        self.assertIn('Tuesday, October 13', markup)
        self.assertIn('Draft the methods', markup)
        self.assertNotIn('Quiet working block', markup)
        self.assertNotIn('Dentist', markup)
        self.assertEqual(markup.count('<li class="focus-event'), 3)
        self.assertLess(markup.index('Team check-in'), markup.index('Lunch with Mia'))
        self.assertIn('focus-event is-past', markup)
        self.assertIn('focus-event is-now', markup)
        self.assertRegex(markup, r'Next</bdi> · 15:00 <span data-content>Design sync')
        self.assertIn('href="/schedule?week=0"', markup)
        # The view changes only when an event's state does, not every minute.
        self.app.now = lambda: datetime(2026, 10, 13, 12, 1, tzinfo=timezone.utc)
        self.assertEqual(snapshot(self.app, 0, 'day')['revision'], today['revision'])
        self.app.now = lambda: datetime(2026, 10, 13, 12, 31, tzinfo=timezone.utc)
        self.assertNotEqual(snapshot(self.app, 0, 'day')['revision'], today['revision'])
        self.app.now = lambda: NOW
        later = snapshot(self.app, 2, 'day')['view']
        self.assertIn('Dentist', later)
        self.assertIn('In 2 days', later)
        self.assertNotIn('is-past', later)
        self.assertIn('id="day-next"', snapshot(self.app, 20, 'day')['view'])
        self.assertNotIn('id="day-next"', snapshot(self.app, 21, 'day')['view'])
        self.assertIn('href="/schedule?week=3"', snapshot(self.app, 21, 'day')['view'])
        self.assertNotIn('id="day-previous"', snapshot(self.app, -21, 'day')['view'])
        ui.CURRENT.set('zh-CN')
        translated = snapshot(self.app, 0, 'day')['view']
        self.assertIn('10月13日星期二', translated)
        self.assertIn('进行中', translated)

    def test_day_view_keeps_source_failures_visible(self):
        (self.root / 'calendar.sqlite').write_text('not SQLite')
        markup = snapshot(self.app, 0, 'day')['view']
        self.assertIn('Calendar records could not be read', markup)
        self.assertIn('Calendar unavailable', markup)
        self.assertIn('Atlas: draft the methods', markup)

    def test_imports_show_at_once_and_source_cancellations_remove_them(self):
        store = CalendarStore(str(self.root / 'calendar.sqlite'))
        self.addCleanup(store.close)
        self.assertIn('Imported invitation', snapshot(self.app, 1)['view'])
        store.import_events('work', [{'external_id': 'imported-1', 'status': 'cancelled'}])
        self.assertNotIn('Imported invitation', snapshot(self.app, 1)['view'])

    def test_overnight_exclusive_end_all_day_and_dst(self):
        store = CalendarStore(str(self.root / 'calendar.sqlite'))
        store.add({'subject': 'Overnight', 'start': '2026-10-12T23:30:00+01:00', 'end': '2026-10-13T01:00:00+01:00'})
        store.add({'subject': 'Ends at midnight', 'start': '2026-10-14T23:00:00+01:00', 'end': '2026-10-15T00:00:00+01:00'})
        store.add({'subject': 'DST all day', 'start': '2026-10-25', 'end': '2026-10-26', 'all_day': True, 'timezone': 'Europe/London'})
        store.close()
        data = self.data()
        subjects = [[event['subject'] for event in day['events']] for day in data['days']]
        self.assertIn('Overnight', subjects[0]); self.assertIn('Overnight', subjects[1])
        self.assertIn('Ends at midnight', subjects[2]); self.assertNotIn('Ends at midnight', subjects[3])
        self.assertIn('A day away', subjects[5]); self.assertNotIn('A day away', subjects[6])
        self.assertIn('DST all day', [event['subject'] for event in self.data(1)['days'][6]['events']])
        self.assertIn('Continues', snapshot(self.app, 0)['view'])

    def test_read_only_live_tasks_no_inbox_inference_or_rollover(self):
        (self.root / 'ideas.md').write_text('Make this idea happen today')
        (self.root / 'daily/2026-10-11.md').write_text('## flexible\n- [ ] Old unfinished task\n')
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        with patch.dict(os.environ, {'CALENDAR_DB_PATH': '/not-this-account.sqlite'}):
            first = snapshot(self.app, 0)
            markup = self.app.chat_page().decode() + self.app.page('2026-10-13', 'gm', False).decode()
        self.assertIn('href="/schedule"', markup)
        self.assertNotIn('Old unfinished task', first['view'])
        self.assertNotIn('Make this idea happen', first['view'])
        self.assertIn('Review the outline', first['view'])
        self.assertIn('is-done', first['view'])
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        # SQLite may create WAL lock companions while reading a live WAL database.
        added = {path.name for path in self.root.rglob('*') if path.is_file() and path not in before}
        self.assertLessEqual(added, {'calendar.sqlite-wal', 'calendar.sqlite-shm'})
        daily = self.root / 'daily/2026-10-13.md'
        daily.write_text(daily.read_text().replace('[ ] Pick up', '[x] Pick up'))
        self.assertNotEqual(first['revision'], snapshot(self.app, 0)['revision'])

    def test_missing_and_corrupt_sources_keep_other_plans_no_initialization(self):
        (self.root / 'calendar.sqlite').unlink()
        result = snapshot(self.app, 0)
        self.assertIn('Atlas: draft', result['view'])
        self.assertFalse((self.root / 'calendar.sqlite').exists())
        (self.root / 'calendar.sqlite').write_text('not SQLite')
        self.assertIn('Calendar records could not be read', snapshot(self.app, 0)['view'])
        (self.root / 'daily/2026-10-14.md').write_text('## flexible\n## flexible\n')
        self.assertTrue(self.data()['days'][2]['plan_error'])
        self.assertIn('Atlas: draft', snapshot(self.app, 0)['view'])

    def test_html_escaping_redaction_and_language_preserve_user_text(self):
        (self.root / 'daily/2026-10-13.md').write_text('## flexible\n- [ ] <img src=x onerror=alert(1)> Passcode: fictional-secret\n')
        markup = snapshot(self.app, 0)['view']
        self.assertNotIn('<img src=x', markup)
        self.assertIn('&lt;img', markup)
        self.assertNotIn('fictional-secret', markup)
        ui.CURRENT.set('zh-CN')
        markup = snapshot(self.app, 0)['view']
        self.assertIn('日程', markup)
        self.assertIn('Team check-in', markup)
        self.assertIn('data-ui-aria-label="Previous week"', markup)

    def test_calendar_does_not_stop_at_default_query_limit_and_converts_offsets(self):
        store = CalendarStore(str(self.root / 'calendar.sqlite'))
        try:
            for index in range(101):
                store.add({'subject': f'Appointment {index}', 'start': '2026-10-12T23:30:00Z',
                           'end': '2026-10-13T01:00:00Z'})
        finally:
            store.close()
        data = self.data()
        self.assertEqual(len(data['days'][0]['events']), 0)
        self.assertEqual(len(data['days'][1]['events']), 102)
        self.assertIn('00:30', snapshot(self.app, 0)['view'])
        self.assertIn('Appointment 100', snapshot(self.app, 0)['view'])

    def test_details_menu_keeps_metadata_and_checked_time_not_revision(self):
        from goodmorning.web.schedule import page
        markup = page(self.app, 0).decode()
        self.assertIn('id="schedule-info"', markup)
        self.assertIn('Europe/London', markup)
        self.assertIn(ui.text('Checked at {time}', time='13:00'), markup)
        self.assertEqual(markup.count('class="schedule-calendar"'), 7)
        self.assertEqual(markup.count('class="schedule-work"'), 7)
        before = snapshot(self.app, 0)
        self.app.now = lambda: datetime(2026, 10, 13, 12, 1, tzinfo=timezone.utc)
        after = snapshot(self.app, 0)
        self.assertEqual(before['revision'], after['revision'])
        self.assertNotEqual(before['checked'], after['checked'])

    def test_symlinks_cannot_select_other_calendar_or_daily_records(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
            outside = Path(temporary)
            other = make_runtime(outside)
            (outside / 'daily/2026-10-13.md').write_text('## flexible\n- [ ] Private other-account task\n')
            store = CalendarStore(str(outside / 'calendar.sqlite'))
            store.add({'subject': 'Private other-account event', 'start': '2026-10-13T10:00:00Z', 'end': '2026-10-13T11:00:00Z'})
            store.close()
            (self.root / 'calendar.sqlite').unlink()
            (self.root / 'calendar.sqlite').symlink_to(outside / 'calendar.sqlite')
            (self.root / 'daily/2026-10-13.md').unlink()
            (self.root / 'daily/2026-10-13.md').symlink_to(outside / 'daily/2026-10-13.md')
            result = snapshot(self.app, 0)
            self.assertNotIn('Private other-account', result['view'])
            self.assertIn('Calendar records could not be read', result['view'])
            self.assertIn('Daily plan unavailable', result['view'])
            self.assertIn('Private other-account', snapshot(other, 0)['view'])

    def test_http_route_security_assets_setup_and_no_mutation(self):
        server = start_server(self.app)
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'
        def get(path, headers=None, data=None):
            try:
                response = urlopen(Request(origin + path, headers=headers or {}, data=data), timeout=3)
            except HTTPError as error:
                response = error
            with response:
                return response.status, dict(response.headers), response.read()
        status, headers, body = get('/schedule?week=3')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn(b'aria-current="page"', body)
        status, _, body = get('/api/schedule?week=0')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['today'], '2026-10-13')
        self.assertEqual(get('/api/schedule?week=4')[0], 404)
        self.assertEqual(get('/api/schedule?runtime=other')[0], 404)
        status, _, body = get('/api/schedule?view=day&day=-1')
        self.assertEqual((status, json.loads(body)['mode']), (200, 'day'))
        self.assertEqual(get('/api/schedule?view=day&day=22')[0], 404)
        self.assertIn(b'/schedule-mode.js', get('/schedule?view=day')[2])
        self.assertEqual(get('/api/schedule', {'Origin': 'https://other.test'})[0], 403)
        self.assertEqual(get('/api/schedule', {'Origin': origin, 'X-Briefing-CSRF': self.app.csrf, 'Content-Type': 'application/json'}, b'{}')[0], 404)
        for name in ('schedule.js', 'schedule-mode.js', 'schedule.css'):
            self.assertEqual(get(self.app.resources.urls[name])[0], 200)
        (self.root / 'profile.md').write_text('')
        self.assertIn(b'Initialize my secretary', get('/schedule')[2])


if __name__ == '__main__':
    unittest.main()
