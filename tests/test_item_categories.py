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

    def test_todays_rows_stay_visible_and_earlier_open_work_is_labelled(self):
        row = lambda title, day, project='': ['task_' + '0' * 16, 1, '', day, 'open', title, f'Project: {project}' if project else '']
        today = [row(f'Step {n}', DAY, project) for n, project in enumerate(('A', 'B', 'C', '', '', ''))]
        html = native.render_block(['actions', today + [row('Old', '2026-10-12'), *[row(f'Later {n}', '', p) for n, p in enumerate('DEFGH')]]],
                                   {}, DAY)
        before_backlog = html.split('To be scheduled')[0]
        self.assertNotIn('<details', before_backlog)  # Nothing due today is folded away.
        self.assertIn('data-ui-text="Still open"', before_backlog)
        self.assertIn('<details', html.split('To be scheduled')[-1])  # The undated backlog may fold.
        note = native.render_block(['tasks', [['open', 'Chair price', ui.text('Heads-up only; nothing to tick off', lang='zh-CN')]]], {})
        self.assertIn('check is-note', note)  # A heads-up announces no completion status.

    def test_notice_is_only_for_dated_actions_and_well_formed(self):
        for task, message in (({'title': 'Read', 'notice': {'morning': 2}}, 'dated action'),
                              ({'title': 'Chair', 'kind': 'nudge', 'notice': {'morning': 2}}, 'dated action'),
                              ({'title': 'Form', 'due_date': '2026-10-20', 'notice': {'morning': 61}}, '0..60'),
                              ({'title': 'Form', 'due_date': '2026-10-20', 'notice': {'soon': 1}}, 'notice is')):
            with self.assertRaisesRegex(ValueError, message):
                self.capture(**task)
        with self.assertRaisesRegex(ValueError, 'notice is'):
            self.draft(title='Class', date='2026-10-17', timezone=ZONE, confirmed_day=True, notice={'early': True})

    def test_notice_shows_an_only_on_the_day_deadline_as_a_heads_up(self):
        self.capture(title='Claim the pay', due_date='2026-10-16', notice={'morning': 2, 'evening': 1, 'early': False})
        self.assertNotIn('Claim the pay', self.items('gm', '2026-10-13'))  # Three days before: not yet.
        row = self.items('gm', '2026-10-14')['Claim the pay']
        self.assertEqual((row['group'], row['date'], row['preview']), ('coming', '2026-10-16', True))
        self.assertEqual(routing.action_cells(row)[6].split(' · ')[0], 'Heads-up: this can only be done on its day')
        self.assertNotIn('Claim the pay', self.items('gn', '2026-10-14'))  # Evening: only the night before.
        self.assertTrue(self.items('gn', '2026-10-15')['Claim the pay']['preview'])
        self.assertEqual(self.items('gm', '2026-10-16')['Claim the pay']['group'], 'deadline')  # Its day: a real action.
        # Seen in a morning ahead of its day, it is never offered as done early that evening.
        cells = routing.action_cells(row)
        (self.root/'daily').mkdir(exist_ok=True)
        (self.root/'daily'/'2026-10-14.gm.json').write_text(native.encode(
            {'v': 2, 'greeting': 'Hello.', 'opening': 'Synthetic.', 'sections': [['tasks', [['actions', [cells]]]]]}))
        self.assertNotIn('Claim the pay', [r['title'] for r in routing.feedback_day(self.tasks, '2026-10-14')])

    def test_notice_lets_early_work_and_routines_appear_ahead(self):
        self.capture(title='Pack for the trip', planned_date='2026-10-17', notice={'morning': 3, 'early': True})
        self.capture(title='Remove hair', timezone=ZONE, repeat={'weekdays': [5], 'start': DAY}, notice={'evening': 0})
        self.capture(title='Council form', due_date='2026-10-22', notice={'morning': 2})
        row = self.items('gm', '2026-10-14')['Pack for the trip']
        self.assertEqual((row['group'], row['date'], row['preview']), ('coming', '2026-10-17', False))
        self.assertNotIn('Pack for the trip', self.items('gm', '2026-10-13'))
        self.assertNotIn('Remove hair', self.items('gn', '2026-10-16'))  # Asked never to hear the night before.
        self.assertIn('Remove hair', self.items('gm', '2026-10-17'))
        self.assertNotIn('Council form', self.items('gm', '2026-10-19'))  # Notice replaces the seven-day default.
        self.assertIn('Council form', self.items('gm', '2026-10-20'))

    def test_notice_brings_occasions_and_tbc_classes_ahead(self):
        calendar = CalendarStore(str(self.root/'calendar.sqlite'))
        try:
            calendar.add({'subject': "Mum's birthday", 'start': '2026-10-17', 'end': '2026-10-18', 'all_day': True,
                          'timezone': ZONE, 'repeat': {'yearly': True, 'start': '2026-10-17'}, 'notice': {'morning': 3}})
            calendar.add({'subject': 'Dentist', 'start': '2026-10-16T10:00:00+01:00', 'end': '2026-10-16T11:00:00+01:00', 'timezone': ZONE})
        finally:
            calendar.close()
        self.draft(title='Archery class', date='2026-10-17', timezone=ZONE, confirmed_day=True,
                   repeat={'weekdays': [5], 'start': '2026-10-17', 'until': '2026-10-31'}, notice={'morning': 2, 'evening': 2})
        subjects = lambda kind, day: [i['subject'] for i in routing.prepare(self.root, day, kind)['schedule']['items']]
        self.assertEqual(subjects('gm', '2026-10-13'), [])
        self.assertEqual(subjects('gm', '2026-10-14'), ["Mum's birthday"])
        self.assertEqual(subjects('gm', '2026-10-15'), ["Mum's birthday", 'Archery class'])
        self.assertEqual(subjects('gn', '2026-10-15'), ['Dentist', 'Archery class'])  # The birthday's notice is morning-only.
        self.assertEqual(subjects('gn', '2026-10-16'), ["Mum's birthday", 'Archery class'])  # Default: the night before.
        view = routing.prepare(self.root, '2026-10-15', 'gm')
        doc = native.parse(native.encode({'v': 2, 'greeting': 'Hello.', 'opening': 'Synthetic.',
                                          'sections': [['schedule', [view['blocks']['schedule']]]]}))
        routing.validate_sources(self.root, doc, '2026-10-15', 'gm')
        self.assertIn('data-ui-text="Coming up"', native.render_block(['agenda', [r[2:] for r in view['blocks']['schedule'][1]]], {}, '2026-10-15'))

    def test_habits_appear_in_briefings_on_their_days(self):
        self.habit()  # Every two days from Tuesday 13th.
        row = self.items()['Strength training']
        self.assertEqual((row['category'], row['date'], row['group']), ('habit', DAY, 'planned'))
        self.assertEqual(routing.action_cells(row)[:5], [row['id'], row['revision'], row['occurrence_id'], DAY, 'open'])
        doc = native.parse(native.encode({'v': 2, 'greeting': 'Hello.', 'opening': 'Synthetic.',
                                          'sections': [['tasks', [['actions', [routing.action_cells(row)]]]]]}))
        routing.validate_sources(self.root, doc, DAY, 'gm')  # A published edition may carry the habit row.
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

    def test_errand_is_done_by_the_secretary_each_morning_and_shown_only_as_a_finding(self):
        daily = self.capture(title='Check the black SIHOO M18 price on Amazon UK', kind='errand',
                             detail='Tell me only when it is under £120.')
        self.capture(title='Look up the library opening hours', kind='errand', timezone=ZONE,
                     repeat={'weekdays': [2], 'start': DAY})
        self.assertEqual(self.tasks.show(daily)['category'], 'errand')
        view = routing.prepare(self.root, DAY, 'gm')
        self.assertEqual(view['tasks']['items'], [])  # Never a card to tick off.
        self.assertEqual(view['tasks']['errands'], [{'id': daily, 'revision': 1, 'title': 'Check the black SIHOO M18 price on Amazon UK', 'worded': False,
                                                     'instruction': 'Tell me only when it is under £120.', 'extra': '', 'last': None}])
        self.assertEqual([e['title'] for e in routing.prepare(self.root, '2026-10-14', 'gm')['tasks']['errands']],
                         ['Check the black SIHOO M18 price on Amazon UK', 'Look up the library opening hours'])
        self.assertEqual(routing.prepare(self.root, DAY, 'gn')['tasks']['errands'], [])
        self.assertEqual(routing.planned_day(self.tasks, '2026-10-14'), [])
        self.assertFalse(any(day['tasks'] for day in self.week().values()))
        with self.assertRaisesRegex(ValueError, 'never completed'):
            self.tasks.mutate(daily, 1, {'status': 'done', 'confirmed_completion': True}, 'ses_test', 'done', NOW)
        with self.assertRaisesRegex(ValueError, 'no deadline'):
            self.capture(title='Bad', kind='errand', due_date='2026-10-20')
        finding = ['errands', [[daily, 1, 'Check the black SIHOO M18 price on Amazon UK', '£114.99 today, under your £120 limit.',
                                [['Amazon UK', 'https://www.amazon.co.uk/dp/B0EXAMPLE']], '2026-10-13: £114.99 on the product page']]]
        document = lambda block, section='tasks': native.parse(native.encode(
            {'v': 2, 'greeting': 'Hello.', 'opening': 'Synthetic.', 'sections': [[section, [block]]]}))
        routing.validate_sources(self.root, document(finding), DAY, 'gm')
        routing.validate_sources(self.root, document(['errands', [[*finding[1][0][:4], [], 'Blocked (503).']]]), DAY, 'gm')  # Could not check.
        quiet = ['errands', [[daily, 1, 'Check the black SIHOO M18 price on Amazon UK', '', [], '2026-10-13: £139.99, above £120']]]
        self.assertEqual(native.render_block(quiet, {}), '')  # Checked, nothing to tell: hidden, yet remembered.
        (self.root/'daily').mkdir(exist_ok=True)
        (self.root/'daily'/(DAY + '.gm.json')).write_text(native.encode(document(quiet)))
        self.assertEqual(routing.prepare(self.root, '2026-10-14', 'gm')['tasks']['errands'][0]['last'],
                         {'date': DAY, 'note': '2026-10-13: £139.99, above £120'})
        self.assertIsNone(routing.prepare(self.root, DAY, 'gm')['tasks']['errands'][0]['last'])  # Only earlier mornings.
        routing.validate_sources(self.root, document(['errands', [[daily, 1, 'Chair price check', 'x', [], 'n']]]), DAY, 'gm')  # Display title.
        with self.assertRaisesRegex(ValueError, 'source_conflict'):
            routing.validate_sources(self.root, document(['errands', [[daily, 2, 'Chair price check', 'x', [], 'n']]]), DAY, 'gm')
        with self.assertRaisesRegex(ValueError, 'wrong section owner'):
            document(finding, 'attention')
        html = native.render_block(finding, {})
        self.assertIn('data-ui-text="Checked for you this morning"', html)
        self.assertIn('check is-note', html)
        self.assertIn('href="https://www.amazon.co.uk/dp/B0EXAMPLE"', html)
        self.tasks.mutate(daily, 1, {'status': 'cancelled'}, 'ses_test', 'retire', NOW)
        self.assertEqual(routing.prepare(self.root, DAY, 'gm')['tasks']['errands'], [])
        with self.assertRaisesRegex(ValueError, 'source_conflict'):
            routing.validate_sources(self.root, document(finding), DAY, 'gm')

    def test_briefing_may_reword_titles_and_details_without_touching_the_item(self):
        identifier = self.capture(title='Dentist', detail='checkup before May. Reminder date: tomorrow.')
        cells = routing.action_cells(self.items()['Dentist'])
        shown = lambda **change: native.parse(native.encode({'v': 2, 'greeting': 'Hello.', 'opening': 'Synthetic.',
            'sections': [['tasks', [['actions', [[*cells[:4], change.get('status', cells[4]), 'Book a dentist checkup', 'Before May.']]]]]]}))
        routing.validate_sources(self.root, shown(), DAY, 'gm')
        self.assertEqual((self.tasks.show(identifier)['title'], self.tasks.show(identifier)['revision']), ('Dentist', 1))
        with self.assertRaisesRegex(ValueError, 'source_conflict'):
            routing.validate_sources(self.root, shown(status='done'), DAY, 'gm')  # Status still comes from the item.

    def test_extra_keeps_the_secretarys_notes_without_showing_them(self):
        errand = self.capture(title='Check the chair price', kind='errand', detail='Tell me only when it is under £120.',
                              extra='2026-10-12: £139.99 on the Amazon UK product page')
        self.tasks.mutate(errand, 1, {'extra': '2026-10-13: Amazon UK refused automatic reads (503)\n2026-10-12: £139.99'},
                          'ses_test', 'errand:job:1', NOW)
        self.assertEqual(routing.prepare(self.root, DAY, 'gm')['tasks']['errands'][0]['extra'][:10], '2026-10-13')
        action = self.capture(title='Send the report', extra='The user prefers PDF.')
        row = self.items()['Send the report']
        self.assertEqual(row['extra'], 'The user prefers PDF.')  # The secretary reads it ...
        self.assertNotIn('PDF', routing.action_cells(row)[6])  # ... the page never shows it.
        draft = self.draft(title='Archery class', date=DAY, timezone=ZONE, confirmed_day=True, extra='Bring the arm guard.')
        self.assertEqual(self.tasks.show(draft, draft=True)['extra'], 'Bring the arm guard.')
        with self.assertRaisesRegex(ValueError, 'task field'):
            self.tasks.mutate(action, 1, {'extra': 'x' * 2001}, 'ses_test', 'long', NOW)

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
        view = routing.prepare(self.root, '2026-10-17', 'gm')
        self.assertEqual([e['date'] for e in view['schedule']['items']], ['2026-10-17'])
        doc = native.parse(native.encode({'v': 2, 'greeting': 'Hello.', 'opening': 'Synthetic.',
                                          'sections': [['schedule', [view['blocks']['schedule']]]]}))
        routing.validate_sources(self.root, doc, '2026-10-17', 'gm')  # The series card can be published.
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

    def test_event_capture_cannot_close_while_its_tbc_draft_is_open(self):
        identifier = self.draft(title='Translate for mom', date=DAY, timezone=ZONE, confirmed_day=True)
        entry = self.tasks.show(identifier, True)['source_entry_id']
        self.assertEqual(self.inbox.show(entry)['draft_ids'], [identifier])
        # Closing the capture after a separate calendar add would leave a TBC duplicate.
        with self.assertRaisesRegex(ValueError, f'organization_required: event draft {identifier} is still open'):
            self.inbox.mutate('update', {'status': 'confirmed'}, 'ses_test', 'close-1', NOW, entry, 1)
        event = {'subject': 'Translate for mom', 'start': DAY + 'T09:00:00+01:00', 'end': DAY + 'T10:00:00+01:00', 'timezone': ZONE}
        self.tasks.convert(self.root, identifier, 1, {'event': event}, 'ses_test', 'convert', NOW)
        self.assertTrue(self.inbox.mutate('update', {'status': 'confirmed'}, 'ses_test', 'close-2', NOW, entry, 1)['saved'])
        self.assertEqual([i.get('time') for i in routing.prepare(self.root, DAY, 'gm')['schedule']['items']], [None])

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

    def test_due_deadline_is_a_required_night_check_and_steps_are_early_choices(self):
        due = self.capture(title='Submit council form', due_date=DAY)
        later = self.capture(title='Book flights', due_date='2026-10-30')
        step = self.capture(title='Fix blur correction', project='MRHarmon', due_date='2026-12-31', due_soft=True)
        block = routing.prepare(self.root, DAY, 'gm', limit=200)['blocks']['tasks']
        (self.root/'daily').mkdir(exist_ok=True)
        (self.root/'daily'/f'{DAY}.gm.json').write_text(native.encode(
            {'v': 2, 'greeting': 'Hello.', 'opening': 'Synthetic.', 'sections': [['tasks', [block]]]}))
        job = {'id': 'c'*32, 'date': DAY, 'kind': 'gn', 'state': 'preflight'}
        context = preflight(self.root, job)
        self.assertTrue(context['form']['checkin'])
        fields = {f['key']: f for f in context['form']['fields']}
        self.assertEqual(set(fields), {'completed', 'completed_longterm', 'details'})
        today = {o['value']: o for o in fields['completed']['options']}
        self.assertEqual((today[occurrence_id(due, DAY)]['label'], today[occurrence_id(due, DAY)]['description']),
                         ('Submit council form', ui.text('Due: {date}', date=ui.day_text(DAY))))
        future = {o['value']: o for o in fields['completed_longterm']['options']}
        self.assertEqual(set(future), {occurrence_id(later, DAY), occurrence_id(step, DAY)})
        self.assertEqual((future[occurrence_id(step, DAY)]['label'], future[occurrence_id(step, DAY)]['group']),
                         ('Fix blur correction', 'MRHarmon'))
        result = answer(self.root, job, {'completed': [occurrence_id(due, DAY)], 'completed_longterm': [occurrence_id(step, DAY)],
                                         'details': 'No other updates'})
        self.assertEqual(result['feedback']['completed'], ['Submit council form', 'Fix blur correction'])
        self.assertEqual(self.tasks.show(due)['status'], 'done')
        self.assertEqual(self.tasks.show(step)['status'], 'done')
        self.assertEqual(self.tasks.show(later)['status'], 'open')

    def test_weekly_evening_tidy_up_asks_about_the_oldest_stale_items_and_applies_only_answers(self):
        night = '2026-11-13'  # Everything below was saved on 13 October.
        garage = self.capture(title='Tidy the garage')
        dentist = self.capture(title='Book the dentist', planned_date='2026-11-04')
        passport = self.capture(title='Renew passport', due_date='2026-11-05')
        plants = self.capture(title='Water plants', planned_date='2026-11-06')
        bank = self.capture(title='Call the bank', planned_date='2026-11-10')  # Only three days past its day.
        bill = self.capture(title='Pay the bill', due_date='2026-11-07')  # Six days overdue.
        self.capture(title='Bring water', kind='nudge')
        self.capture(title='Stretch', timezone=ZONE, repeat={'interval_days': 1, 'start': DAY})
        stale = routing.stale_tasks(self.tasks, night)
        self.assertEqual([r['id'] for r in stale], [garage, dentist, passport])  # Oldest first, at most three.

        job = {'id': 'd'*32, 'date': night, 'kind': 'gn', 'state': 'preflight'}
        fields = {f['key']: f for f in preflight(self.root, job)['form']['fields']}
        self.assertEqual(set(fields), {'completed', 'details', 'tidy_' + garage, 'tidy_' + dentist, 'tidy_' + passport})
        # Asked about once: the overdue passport left the finish list, the less stale bill did not.
        self.assertEqual({o['label'] for o in fields['completed']['options']}, {'None of these today.', 'Pay the bill', 'Stretch'})
        self.assertEqual(fields['tidy_' + dentist]['description'],
                         ui.text('Planned for {date}', date=ui.day_text('2026-11-04', reference=night)))
        self.assertEqual([o['value'] for o in fields['tidy_' + garage]['options']], ['snooze', 'done', 'drop', 'keep', 'later'])
        with self.assertRaisesRegex(ValueError, 'tidy-up answers'):
            answer(self.root, job, {'completed': ['none'], 'details': 'No other updates', 'tidy_' + garage: 'delete'})
        with patch('goodmorning.records.inbox_store.stamp', return_value=night + 'T21:00:00+00:00'):
            result = answer(self.root, job, {'completed': ['none'], 'details': 'No other updates', 'tidy_' + garage: 'drop',
                                             'tidy_' + dentist: 'snooze', 'tidy_' + passport: 'done'})
        self.assertEqual(result['feedback']['completed'], ['Renew passport'])
        self.assertEqual(self.tasks.show(garage)['status'], 'cancelled')
        self.assertEqual((self.tasks.show(dentist)['status'], self.tasks.show(dentist)['defer_until']), ('open', '2026-11-20'))
        self.assertEqual(self.tasks.show(passport)['status'], 'done')
        self.assertEqual(self.tasks.show(bill)['status'], 'open')

        self.assertEqual(routing.stale_tasks(self.tasks, '2026-11-19'), [])  # At most once a week.
        self.assertNotIn('Book the dentist', self.items('gm', '2026-11-19'))  # Snoozed off the morning list.
        rows = routing.stale_tasks(self.tasks, '2026-11-20')
        self.assertEqual([r['id'] for r in rows], [plants, bill, bank])
        self.tasks.tidy(rows, {plants: 'later', bill: 'keep'}, '2026-11-20', 'ses_test', 'tidy-later', NOW)
        # "Not sure yet", "Keep it" and no answer change nothing.
        self.assertEqual([self.tasks.show(r['id'])['revision'] for r in rows], [r['revision'] for r in rows])
        self.assertEqual(routing.stale_tasks(self.tasks, '2026-11-26'), [])
        self.assertEqual(routing.stale_tasks(self.tasks, '2026-11-27'), [])  # Everything still stale was asked about recently.
        # Four weeks on, they can be asked about again; the kept bill never is.
        self.assertEqual([r['id'] for r in routing.stale_tasks(self.tasks, '2026-12-18')], [plants, bank, dentist])

    def test_a_tidy_up_shown_but_never_saved_still_counts_as_asked(self):
        garage = self.capture(title='Tidy the garage')
        job = {'id': 'e'*32, 'date': '2026-11-13', 'kind': 'gn', 'state': 'preflight'}
        self.assertIn('tidy_' + garage, {f['key'] for f in preflight(self.root, job)['form']['fields']})
        self.tasks.mutate(garage, self.tasks.show(garage)['revision'], {'title': 'Tidy the garage and shed'}, 'ses_chat', 'edit', NOW)
        # Preparing the same night again asks about the same items, as they are now.
        self.assertEqual([(r['id'], r['revision']) for r in preflight(self.root, {**job, 'preflight_revision': 1})['tidy']],
                         [(garage, self.tasks.show(garage)['revision'])])
        self.assertEqual(routing.stale_tasks(self.tasks, '2026-11-14'), [])
        self.assertEqual(routing.stale_tasks(self.tasks, '2026-12-10'), [])
        self.assertEqual([r['id'] for r in routing.stale_tasks(self.tasks, '2026-12-11')], [garage])

    def test_tidy_up_answers_skip_items_changed_after_they_were_shown(self):
        night = '2026-11-13'
        garage = self.capture(title='Tidy the garage')
        attic = self.capture(title='Clear the attic')
        job = {'id': 'f'*32, 'date': night, 'kind': 'gn', 'state': 'preflight'}
        preflight(self.root, job)
        self.tasks.mutate(garage, self.tasks.show(garage)['revision'], {'title': 'Tidy the garage and shed'}, 'ses_chat', 'edit', NOW)
        with patch('goodmorning.records.inbox_store.stamp', return_value=night + 'T21:00:00+00:00'):
            result = answer(self.root, job, {'details': 'No other updates', 'tidy_' + garage: 'done', 'tidy_' + attic: 'done'})
        self.assertEqual(result['feedback']['completed'], ['Clear the attic'])
        self.assertEqual((self.tasks.show(garage)['status'], self.tasks.show(attic)['status']), ('open', 'done'))
        self.assertIn('Changed since this check-in started, so left as is: Tidy the garage', (self.root/'daily'/(night + '.md')).read_text())

if __name__ == '__main__':
    unittest.main()
