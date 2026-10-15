"""Item categories: what each kind of saved item does in gm, gn and the Schedule tab."""
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
from goodmorning.records.task_store import TaskStore, category, occurrence_id
from goodmorning.records.custom_store import CustomStore
from goodmorning.records import routing
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.briefings import briefing_document as native
from goodmorning.briefings.briefing_preflight import initialize as preflight, answer
from goodmorning.web.schedule import saved_week, snapshot
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import language as ui

DAY = '2026-10-13'  # Tuesday
NOW = DAY + 'T12:00:00+01:00'
ZONE = 'Europe/London'


class CategoryTests(unittest.TestCase):
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
        return self.inbox.mutate('add', {'kind': 'todo', 'raw': task.get('title', 'Item'), 'task': task},
                                 'ses_test', str(self.n), NOW)['task_id']

    def draft(self, **draft):
        self.n += 1
        return self.inbox.mutate('add', {'kind': 'event_proposal', 'raw': draft['title'], 'draft': draft},
                                 'ses_test', str(self.n), NOW)['draft_id']

    def items(self, kind='gm', day=DAY):
        return {r['title']: r for r in routing.prepare(self.root, day, kind, limit=200)['tasks']['items']}

    def week(self, offset=0):
        days = saved_week(self.root, ZONE, datetime(2026, 10, 13, 9, tzinfo=timezone.utc), offset)['days']
        return {day['date']: day for day in days}

    def habit(self, title='Strength training', start=DAY):
        store = CustomStore(self.root, write=True)
        try:
            return store.add({'title': title, 'timezone': ZONE, 'policy': {
                'base': 'interval_days', 'interval_days': 2, 'start': start, 'anchor': 'fixed',
                'miss_policy': 'fixed', 'nightly': 'due_only'}}, 'ses_test', 'habit-' + title, NOW)['id']
        finally:
            store.close()

    def meeting(self, day, subject='Lab meeting'):
        calendar = CalendarStore(str(self.root/'calendar.sqlite'))
        try:
            return calendar.add({'subject': subject, 'start': day + 'T10:00:00+01:00', 'end': day + 'T11:00:00+01:00', 'timezone': ZONE})
        finally:
            calendar.close()

    def test_category_comes_from_kind_and_timing_fields(self):
        cases = {
            'day': {'planned_date': DAY},
            'deadline': {'due_date': '2026-10-20'},
            'routine': {'timezone': ZONE, 'repeat': {'weekdays': [4], 'start': DAY}},
            'project': {'project': 'Atlas', 'due_date': '2026-12-31', 'due_soft': True},
            'anytime': {},
            'nudge': {'kind': 'nudge'},
            'reference': {'kind': 'reference', 'trigger': 'Protein powder runs out'},
        }
        for expected, fields in cases.items():
            identifier = self.capture(title=expected, **fields)
            self.assertEqual(self.tasks.show(identifier)['category'], expected)
            self.assertEqual(category(self.tasks.show(identifier)), expected)
        self.assertNotIn('category', self.inbox.db.execute('SELECT data FROM tasks LIMIT 1').fetchone()[0])

    def test_morning_is_about_today_and_evening_previews_only_tomorrow(self):
        self.capture(title='Remove hair', timezone=ZONE, repeat={'weekdays': [5], 'start': DAY})  # Saturdays
        self.capture(title='Council form', due_date='2026-10-17')
        calendar = CalendarStore(str(self.root/'calendar.sqlite'))
        try:
            calendar.add({'subject': "Mum's birthday", 'start': '2026-10-17', 'end': '2026-10-18', 'all_day': True, 'timezone': ZONE})
        finally:
            calendar.close()
        self.draft(title='Archery class', date='2026-10-17', timezone=ZONE, confirmed_day=True)
        shown = lambda kind, day: (set(self.items(kind, day)),
                                   {i['subject'] for i in routing.prepare(self.root, day, kind)['schedule']['items']})
        for day in ('2026-10-14', '2026-10-15'):  # Wednesday and Thursday: nothing of Saturday's.
            for kind in ('gm', 'gn'):
                self.assertNotIn('Remove hair', shown(kind, day)[0], (kind, day))
                self.assertEqual(shown(kind, day)[1], set(), (kind, day))
        self.assertIn('Council form', shown('gm', '2026-10-14')[0])  # A hard deadline is the exception.
        self.assertNotIn('Council form', shown('gn', '2026-10-14')[0])  # Evenings: only due tomorrow.
        self.assertEqual(shown('gn', '2026-10-16'), ({'Remove hair', 'Council form'}, {"Mum's birthday", 'Archery class'}))
        self.assertEqual(shown('gm', '2026-10-17'), ({'Remove hair', 'Council form'}, {"Mum's birthday", 'Archery class'}))

    def test_habits_appear_in_briefings_on_their_days(self):
        self.habit()  # Every two days from Tuesday 13th.
        row = self.items()['Strength training']
        self.assertEqual((row['category'], row['date'], row['group']), ('habit', DAY, 'planned'))
        self.assertEqual(routing.action_cells(row)[:5], [row['id'], row['revision'], row['occurrence_id'], DAY, 'open'])
        self.assertNotIn('Strength training', self.items('gn'))  # Wednesday is an off day.
        self.assertIn('Strength training', self.items('gn', '2026-10-14'))  # Preview of Thursday.

    def test_nudge_is_morning_only_and_never_ticked_off(self):
        anytime = self.capture(title='Check the chair price', kind='nudge')
        weekly = self.capture(title='Bring gym clothes', kind='nudge', timezone=ZONE, repeat={'weekdays': [2], 'start': DAY})
        gm = self.items()
        self.assertEqual(gm['Check the chair price']['group'], 'nudge')
        self.assertNotIn('Bring gym clothes', gm)  # Wednesday only; no lookahead for heads-ups.
        tomorrow = self.items(day='2026-10-14')
        self.assertEqual((tomorrow['Bring gym clothes']['date'], tomorrow['Bring gym clothes']['group']), ('2026-10-14', 'nudge'))
        self.assertIn(ui.text('Heads-up only; nothing to tick off'), routing.action_cells(tomorrow['Bring gym clothes'])[6])
        self.assertEqual(self.items('gn'), {})
        self.assertEqual(routing.planned_day(self.tasks, '2026-10-14'), [])
        self.assertFalse(any(day['tasks'] for day in self.week().values()))
        with self.assertRaisesRegex(ValueError, 'never completed'):
            self.tasks.mutate(anytime, 1, {'status': 'done', 'confirmed_completion': True}, 'ses_test', 'done', NOW)
        with self.assertRaisesRegex(ValueError, 'no occurrence reports'):
            self.tasks.mutate(weekly, 1, {'status': 'done', 'confirmed_completion': True}, 'ses_test', 'r', NOW, day='2026-10-14')
        with self.assertRaisesRegex(ValueError, 'no deadline'):
            self.capture(title='Bad', kind='nudge', due_date='2026-10-20')
        self.tasks.mutate(anytime, 1, {'status': 'cancelled'}, 'ses_test', 'retire', NOW)
        self.assertNotIn('Check the chair price', self.items())

    def test_reference_note_never_appears_and_has_no_timing(self):
        identifier = self.capture(title='Rebuy supplements', kind='reference', trigger='A supplement runs out',
                                  detail='Protein: brand X, 1 scoop daily.')
        self.assertEqual(self.tasks.show(identifier)['trigger'], 'A supplement runs out')
        for kind in ('gm', 'gn'):
            self.assertEqual(self.items(kind), {})
        self.assertFalse(any(day['tasks'] for day in self.week().values()))
        with self.assertRaisesRegex(ValueError, 'needs a trigger'):
            self.capture(title='No trigger', kind='reference')
        with self.assertRaisesRegex(ValueError, 'needs a trigger and no dates'):
            self.capture(title='Dated', kind='reference', trigger='x', planned_date=DAY)
        with self.assertRaisesRegex(ValueError, 'only reference notes'):
            self.capture(title='Action', trigger='x')

    def test_one_capture_can_save_sibling_items_and_unchecked_items_are_not_pending(self):
        receipt = self.inbox.mutate('add', {'kind': 'todo', 'raw': 'Watch the chair price, buy below £130',
            'task': {'title': 'Check the chair price', 'kind': 'nudge'},
            'also': [{'title': 'Buy the chair below £130'}]}, 'ses_test', 'pair', NOW)
        nudge, purchase = receipt['task_ids']
        self.assertEqual(receipt['task_id'], nudge)
        self.assertEqual([self.tasks.show(i)['category'] for i in receipt['task_ids']], ['nudge', 'anytime'])
        entry = self.tasks.show(nudge)['source_entry_id']
        self.assertEqual(self.inbox.show(entry)['status'], 'pending')
        self.tasks.mutate(purchase, 1, {'status': 'done', 'confirmed_completion': True}, 'ses_test', 'bought', NOW)
        self.assertEqual(self.inbox.show(entry)['status'], 'done')
        reference = self.capture(title='Rebuy supplements', kind='reference', trigger='A supplement runs out')
        self.assertEqual(self.inbox.show(self.tasks.show(reference)['source_entry_id'])['status'], 'confirmed')
        with self.assertRaisesRegex(ValueError, 'own title'):
            self.inbox.mutate('add', {'kind': 'todo', 'raw': 'x', 'also': [{}]}, 'ses_test', 'bad', NOW)

    def test_secretary_preparation_lists_reference_triggers_and_habits(self):
        from goodmorning.records.workflow import prepare
        reference = self.capture(title='Rebuy supplements', kind='reference', trigger='A supplement runs out')
        self.capture(title='Ordinary action')
        rule = self.habit()
        context = prepare(self.root, 'secretary', DAY)
        self.assertEqual(context['references'], [{'id': reference, 'title': 'Rebuy supplements', 'trigger': 'A supplement runs out'}])
        self.assertEqual(context['habits'], [{'id': rule, 'title': 'Strength training'}])
        self.assertNotIn('references', prepare(self.root, 'gm', DAY))

    def test_until_done_follows_up_daily_and_one_tick_closes_it(self):
        identifier = self.capture(title='Decide the trip dates', defer_until='2026-10-14', follow_up='until-done')
        self.assertNotIn('Decide the trip dates', self.items())
        for day in ('2026-10-14', '2026-10-15'):
            row = self.items(day=day)['Decide the trip dates']
            self.assertEqual((row['group'], row['date']), ('follow-up', day))
            self.assertEqual([r['id'] for r in routing.feedback_day(self.tasks, day)], [identifier])
        self.assertNotIn('Decide the trip dates', self.items('gn', '2026-10-15'))  # The evening form asks instead.
        self.assertFalse(any(day['tasks'] for day in self.week().values()))  # A chase reserves no workday.
        task = self.tasks.show(identifier)
        self.tasks.complete_day([{'id': occurrence_id(identifier, '2026-10-15'), 'task_id': identifier, 'revision': task['revision']}],
                                '2026-10-15', 'ses_test', 'fb', '2026-10-15T20:00:00+01:00', '')
        self.assertEqual(self.tasks.show(identifier)['status'], 'done')
        self.assertNotIn('Decide the trip dates', self.items(day='2026-10-16'))
        with self.assertRaisesRegex(ValueError, 'one-off'):
            self.capture(title='Bad', follow_up='until-done', timezone=ZONE, repeat={'weekdays': [1], 'start': DAY})

    def test_until_done_day_task_shows_once_on_schedule_then_chases(self):
        identifier = self.capture(title='Buy ointment', planned_date='2026-10-14', follow_up='until-done')
        week = self.week()
        self.assertEqual([d for d, day in week.items() if day['tasks']], ['2026-10-14'])
        self.assertEqual(self.items('gn')['Buy ointment']['date'], '2026-10-14')  # Tomorrow's plan, shown once.
        self.assertEqual(self.items(day='2026-10-16')['Buy ointment']['group'], 'follow-up')
        self.assertEqual(self.tasks.occurrence(self.tasks.show(identifier), '2026-10-16')['status'], 'open')

    def test_step_waits_for_the_task_it_depends_on(self):
        first = self.capture(title='Plate the bacteria', project='HL60')
        self.capture(title='Send plates for sequencing', project='HL60', after=first)
        self.assertNotIn('Send plates for sequencing', self.items())
        self.tasks.mutate(first, 1, {'status': 'done', 'confirmed_completion': True}, 'ses_test', 'done', NOW)
        self.assertIn('Send plates for sequencing', self.items())
        with self.assertRaisesRegex(ValueError, 'another saved task'):
            self.capture(title='Orphan', after='task_0123456789abcdef')
        with self.assertRaisesRegex(ValueError, 'undated step'):
            self.capture(title='Dated', after=first, planned_date=DAY)

    def test_morning_offers_at_most_three_steps_per_project(self):
        for n in range(5):
            self.capture(title=f'Atlas step {n}', project='Atlas')
        self.capture(title='Other step', project='Beacon')
        view = routing.prepare(self.root, DAY, 'gm', limit=200)['tasks']
        projects = [row['project'] for row in view['items']]
        self.assertEqual((projects.count('Atlas'), projects.count('Beacon'), view['total']), (3, 1, 4))

    def test_preparation_follows_the_named_appointment_when_it_moves(self):
        self.meeting('2026-10-15')
        moved = self.meeting('2026-10-22')
        self.meeting('2026-10-14', 'Other meeting')
        identifier = self.capture(title='Prepare lab update', project='Atlas', timezone=ZONE,
                                  repeat={'event_subject': 'lab meeting', 'start': DAY, 'offset_days': -1})
        self.assertEqual(self.tasks.show(identifier)['category'], 'routine')
        row = self.items(day='2026-10-14')['Prepare lab update']
        self.assertEqual(row['date'], '2026-10-14')
        self.assertIn(ui.text('Preparation for {subject}, {count} day(s) before', subject='lab meeting', count=1), routing.action_cells(row)[6])
        self.assertEqual([d for d, day in self.week(1).items() if day['tasks']], ['2026-10-21'])
        calendar = CalendarStore(str(self.root/'calendar.sqlite'))
        try:
            calendar.change(moved, 'update', 1, {'start': '2026-10-23T10:00:00+01:00', 'end': '2026-10-23T11:00:00+01:00'})
        finally:
            calendar.close()
        self.tasks = TaskStore(self.inbox)
        self.assertEqual([d for d, day in self.week(1).items() if day['tasks']], ['2026-10-22'])
        with self.assertRaisesRegex(ValueError, 'offset_days'):
            self.capture(title='Bad', timezone=ZONE, repeat={'event_subject': 'x', 'start': DAY, 'offset_days': 2})

    def test_habit_nudge_and_schedule_show_flexible_habit_days(self):
        rule = self.habit()
        self.capture(title='Bring gym clothes', kind='nudge', timezone=ZONE, when={'custom_rule_id': rule})
        self.assertIn('Bring gym clothes', self.items())
        self.assertNotIn('Bring gym clothes', self.items(day='2026-10-14'))
        week = self.week()
        habit_days = [d for d, day in week.items() for t in day['tasks'] if t.get('marker') == 'flexible']
        self.assertEqual(habit_days, ['2026-10-13', '2026-10-15', '2026-10-17'])
        markup = snapshot(BrowserApp(self.root, now=lambda: datetime(2026, 10, 13, 9, tzinfo=timezone.utc)), 0)['view']
        self.assertIn(ui.text('Flexible habit · moves with what you actually do'), markup)

    def test_weekly_tbc_series_shows_each_date_and_converts_once(self):
        identifier = self.draft(title='Archery class', date='2026-10-17', timezone=ZONE, confirmed_day=True,
                                location='Sports park', repeat={'weekdays': [5], 'start': '2026-10-17', 'until': '2026-10-31'})
        cards = [(e['id'], e['date']) for day in self.week(1).values() for e in day['events']]
        self.assertEqual(cards, [(identifier + '@2026-10-24', '2026-10-24')])
        self.assertEqual([e['date'] for e in routing.prepare(self.root, '2026-10-17', 'gm')['schedule']['items']], ['2026-10-17'])
        with self.assertRaisesRegex(ValueError, 'start equal to date'):
            self.draft(title='Bad', date='2026-10-17', timezone=ZONE, confirmed_day=True, repeat={'weekdays': [5], 'start': '2026-10-18'})
        event = {'subject': 'Archery class', 'start': '2026-10-17T19:00:00+01:00', 'end': '2026-10-17T20:30:00+01:00',
                 'timezone': ZONE, 'location': 'Sports park'}
        result = self.tasks.convert(self.root, identifier, 1, {'event': event}, 'ses_test', 'convert', NOW)
        self.assertTrue(result['saved'])
        calendar = CalendarStore(str(self.root/'calendar.sqlite'), readonly=True)
        try:
            starts = [e['start'] for e in calendar.query(datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 11, 30, tzinfo=timezone.utc), limit=-1)]
        finally:
            calendar.close()
        # Wall-clock 19:00 survives the end of British Summer Time on 25 October.
        self.assertEqual(starts, ['2026-10-17T18:00:00+00:00', '2026-10-24T18:00:00+00:00', '2026-10-31T19:00:00+00:00'])
        events = [e for day in self.week(1).values() for e in day['events']]
        self.assertEqual([e.get('draft') for e in events], [None])

    def test_all_day_events_are_occasions_and_timed_events_appointments(self):
        calendar = CalendarStore(str(self.root/'calendar.sqlite'))
        try:
            calendar.add({'subject': "Mum's birthday", 'start': DAY, 'end': '2026-10-14', 'all_day': True, 'timezone': ZONE,
                          'repeat': {'yearly': True, 'start': DAY}})
        finally:
            calendar.close()
        self.meeting(DAY)
        items = {i['subject']: i['category'] for i in routing.prepare(self.root, DAY, 'gm')['schedule']['items']}
        self.assertEqual(items, {"Mum's birthday": 'occasion', 'Lab meeting': 'appointment'})
        nextyear = routing.prepare(self.root, '2027-10-13', 'gm')['schedule']['items']
        self.assertEqual([i['subject'] for i in nextyear], ["Mum's birthday"])

    def test_due_deadline_is_a_required_night_check_and_steps_get_progress_notes(self):
        due = self.capture(title='Submit council form', due_date=DAY)
        later = self.capture(title='Book flights', due_date='2026-10-30')
        step = self.capture(title='Fix blur correction', project='MRHarmon', due_date='2026-12-31', due_soft=True)
        block = routing.prepare(self.root, DAY, 'gm', limit=200)['blocks']['tasks']
        (self.root/'daily').mkdir(exist_ok=True)
        (self.root/'daily'/f'{DAY}.gm.json').write_text(native.encode(
            {'v': 2, 'greeting': 'Hello.', 'opening': 'Synthetic.', 'sections': [['tasks', [block]]]}))
        job = {'id': 'c'*32, 'date': DAY, 'kind': 'gn', 'state': 'preflight'}
        context = preflight(self.root, job)
        fields = {f['key']: f for f in context['form']['fields']}
        today = {o['value']: o['label'] for o in fields['completed']['options']}
        self.assertEqual(today[occurrence_id(due, DAY)], 'Submit council form · ' + ui.text('Due: {date}', date=ui.day_text(DAY)))
        future = [o['value'] for o in fields['completed_longterm']['options']]
        self.assertEqual(set(future), {occurrence_id(later, DAY), occurrence_id(step, DAY)})
        self.assertEqual((fields['progress_1']['project'], fields['progress_1']['required']), ('MRHarmon', False))
        result = answer(self.root, job, {'completed': [occurrence_id(due, DAY)], 'completed_longterm': [],
                                         'progress_1': 'Tested two kernels.', 'details': 'No other updates'})
        self.assertEqual(result['feedback']['progress'], ['Progress on MRHarmon: Tested two kernels.'])
        self.assertEqual(self.tasks.show(due)['status'], 'done')
        self.assertEqual(self.tasks.show(step)['status'], 'open')
        self.assertIn('Progress on MRHarmon: Tested two kernels.', (self.root/'daily'/f'{DAY}.md').read_text())


if __name__ == '__main__':
    unittest.main()
