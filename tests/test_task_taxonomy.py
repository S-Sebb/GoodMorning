"""Canonical identities, temporal intent, routing and recovery on synthetic runtimes."""
import copy
import contextlib
import io
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT, offline_provider_reads
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.records.inbox_store import InboxStore, initialize
from goodmorning.records.task_store import TaskStore, migrate, occurrence_id
from goodmorning.records import routing, daily
from goodmorning.records import task as task_cli, workflow
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.briefings import briefing_document as native, briefing_guides
from goodmorning.briefings.briefing_preflight import initialize as preflight, answer
from goodmorning.briefings.briefing_job import act
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web.schedule import saved_week
from goodmorning.web import language as ui

DAY = '2026-10-13'
NOW = DAY + 'T12:00:00+01:00'


class TaxonomyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)
        offline_provider_reads(self)
        (self.root/'profile.md').write_text('city: London, GB\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n')
        initialize(self.root)
        CalendarStore(str(self.root/'calendar.sqlite')).close()
        self.inbox = InboxStore(self.root, write=True)
        self.addCleanup(self.inbox.close)
        self.tasks = TaskStore(self.inbox)
        self.n = 0

    def capture(self, raw='Buy milk', kind='todo', **fields):
        self.n += 1
        return self.inbox.mutate('add', {'kind': kind, 'raw': raw, **fields}, 'ses_test', str(self.n), NOW)

    def view(self, kind='gm', day=DAY):
        return routing.prepare(self.root, day, kind)

    def document(self, block, section='tasks'):
        return {'v': 2, 'greeting': 'Hello.', 'opening': 'Synthetic.', 'sections': [[section, [block]]]}

    def browser_job(self, letter, kind='gn', state='preflight', **fields):
        app = BrowserApp(self.root, now=lambda: datetime(2026, 10, 13, 12, tzinfo=timezone.utc), preflight=True)
        job = {'id': letter*32, 'date': DAY, 'kind': kind, 'state': state, **fields}
        app.jobs[DAY+'.'+kind] = job; app.save_jobs()
        return job

    def assertLocalized(self, chinese, english):
        self.assertEqual(chinese, ui.text(english, lang='zh-CN'))
        self.assertNotEqual(chinese, english)

    def test_capture_is_atomic_and_retry_safe_and_idea_creates_no_work(self):
        first = self.capture('Send report by Friday', task={'title': 'Send report', 'due_date': '2026-10-16'})
        replay = self.inbox.mutate('add', {'kind': 'todo', 'raw': 'Send report by Friday', 'task': {'title': 'Send report', 'due_date': '2026-10-16'}}, 'ses_test', '1', NOW)
        self.assertEqual(first['task_id'], replay['task_id'])
        idea = self.capture('Research caching and deploy Friday', 'idea')
        self.assertNotIn('task_id', idea)
        self.assertEqual(len(list(self.tasks.all())), 1)
        self.inbox.db.execute("CREATE TRIGGER reject_task BEFORE INSERT ON tasks BEGIN SELECT RAISE(FAIL,'synthetic'); END")
        with self.assertRaises(sqlite3.Error):
            self.capture('Must roll back raw input too')
        self.assertEqual(self.inbox.stats()['total'], 2)

    def test_ambiguous_task_or_event_is_not_even_a_pending_capture(self):
        before = (self.root/'inbox.sqlite').read_bytes()
        for kind in ('todo', 'event_proposal'):
            with self.assertRaisesRegex(ValueError, 'clarification_required'):
                self.capture('Next Friday, or perhaps Saturday?', kind, questions=['Which date?'])
        self.assertEqual(self.inbox.stats()['total'], 0)
        self.assertEqual(self.inbox.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)
        self.assertEqual((self.root/'inbox.sqlite').read_bytes(), before)
        receipt=self.capture('Friday is confirmed', task={'title':'Buy milk','planned_date':'2026-10-16'})
        self.assertTrue(receipt['saved'])
        with self.assertRaisesRegex(ValueError,'clarification_required'):
            self.inbox.mutate('update',{'questions':['Change to Saturday?']},'ses_test','unanswered-change',NOW,receipt['id'],1)
        self.assertEqual(self.inbox.show(receipt['id'])['revision'],1)

    def test_interval_and_explicit_date_recurrence_are_not_weekday_approximations(self):
        first = self.capture(task={'title':'Training','timezone':'Asia/Shanghai',
            'repeat':{'interval_days':2,'start':'2026-10-12'}})['task_id']
        task = self.tasks.show(first)
        self.tasks.occurrence(task,'2026-10-14')
        self.tasks.occurrence(task,'2026-10-18')
        with self.assertRaisesRegex(ValueError,'unknown_occurrence'):
            self.tasks.occurrence(task,'2026-10-15')
        second = self.capture(task={'title':'Rebalance reminder','timezone':'Asia/Shanghai',
            'repeat':{'dates':['2026-11-12','2026-12-14'],'start':'2026-10-12'}})['task_id']
        self.tasks.occurrence(self.tasks.show(second),'2026-12-14')
        with self.assertRaisesRegex(ValueError,'unknown_occurrence'):
            self.tasks.occurrence(self.tasks.show(second),'2026-12-12')

    def test_moved_meeting_preparation_is_one_series_with_explicit_exception(self):
        receipt=self.capture(task={'title':'Prepare presentation','timezone':'Europe/London',
            'repeat':{'weekdays':[3],'start':'2026-10-12','include':['2026-10-12'],'exclude':['2026-10-15']}})
        task=self.tasks.show(receipt['task_id'])
        self.tasks.occurrence(task,'2026-10-12')
        self.tasks.occurrence(task,'2026-10-22')
        with self.assertRaisesRegex(ValueError,'unknown_occurrence'):
            self.tasks.occurrence(task,'2026-10-15')

    def test_morning_condition_uses_account_date_and_original_request_not_finish_or_wake(self):
        identifier = self.capture(task={'title':'Craft reminder','timezone':'Asia/Shanghai',
            'repeat':{'weekdays':[0,1,2,3,4],'start':'2026-10-12'}, 'when':{'morning_before':'10:00'}})['task_id']
        directory=self.root/'browser-jobs';directory.mkdir()
        path=directory/'jobs.json'
        def at(day, clock):
            started=datetime.fromisoformat(day+'T'+clock+':00+08:00').timestamp()
            path.write_text(json.dumps({day+'.gm':{'generation_started_at':started}}))
        self.assertEqual(self.view()['tasks']['total'],0)
        at(DAY,'09:59')
        self.assertEqual(self.view()['tasks']['items'][0]['id'],identifier)
        self.assertEqual(self.view('gn')['tasks']['items'][0]['group'],'still-open')
        self.assertEqual(routing.planned_day(self.tasks,'2026-10-14'),[])
        at(DAY,'10:00')
        self.assertEqual(self.view()['tasks']['total'],0)
        at('2026-10-17','09:00')
        self.assertEqual(self.view(day='2026-10-17')['tasks']['total'],0)
        self.tasks.mutate(identifier,1,{'status':'done','confirmed_completion':True},'ses_test','craft-done',NOW,day=DAY)
        self.assertEqual(self.view('gn')['today'][0]['status'],'done')

    def test_future_defer_date_hides_an_undated_reminder_until_its_confirmed_start(self):
        self.capture(task={'title':'Confirm trip','defer_until':'2026-11-01'})
        self.assertEqual(self.view()['tasks']['total'],0)
        self.assertEqual(self.view(day='2026-11-01')['tasks']['items'][0]['date'],'')

    def test_one_outstanding_reminder_keeps_actual_completion_and_original_cadence(self):
        identifier=self.capture(task={'title':'Training','timezone':'Asia/Shanghai',
            'repeat':{'interval_days':2,'start':'2026-10-12'},'follow_up':'one-outstanding'})['task_id']
        self.tasks.mutate(identifier,1,{'status':'done','confirmed_completion':True},'ses_test','first-session',NOW,day='2026-10-12')
        pending=self.view(day='2026-10-15')['tasks']['items']
        self.assertEqual([r['date'] for r in pending if r['group']=='still-open'],['2026-10-14'])
        overdue=next(r['detail'] for r in pending if r['date']=='2026-10-14')
        overlapping=self.view(day='2026-10-16')['tasks']['items']
        self.assertEqual(next(r['detail'] for r in overlapping if r['date']=='2026-10-16'),overdue)
        self.assertNotIn('2026-10-14',[r['date'] for r in overlapping])
        self.tasks.mutate(identifier,2,{'status':'done','confirmed_completion':True},'ses_test','actual-session',
                          '2026-10-15T12:00:00+08:00',day='2026-10-15',actual=True)
        self.assertEqual([r['date'] for r in self.view(day='2026-10-15')['tasks']['items']],[])  # No lookahead to the 16th.
        current=self.view(day='2026-10-16')['tasks']['items'][0]['detail']
        self.assertTrue(overdue.startswith(current+'\n'))  # The firmer follow-up applies only while overdue.
        self.assertEqual(self.view('gn',day='2026-10-15')['today'][0]['date'],'2026-10-15')
        self.assertIsNone(self.inbox.db.execute('SELECT * FROM task_occurrences WHERE task_id=? AND date=?',(identifier,'2026-10-14')).fetchone())
        later=self.view(day='2026-10-19')['tasks']['items']
        self.assertEqual([r['date'] for r in later if r['group']=='still-open'],['2026-10-18'])
        self.assertEqual(self.tasks.show(identifier)['repeat']['start'],'2026-10-12')

    def test_actual_completion_closes_an_undated_action_but_cannot_claim_future_work(self):
        identifier=self.capture(task={'title':'Send receipt'})['task_id']
        with self.assertRaisesRegex(ValueError,'future work'):
            self.tasks.mutate(identifier,1,{'status':'done','confirmed_completion':True},'ses_test','future',NOW,day='2026-10-20',actual=True)
        self.tasks.mutate(identifier,1,{'status':'done','confirmed_completion':True},'ses_test','actual',NOW,day=DAY,actual=True)
        self.assertEqual(self.tasks.show(identifier)['status'],'done')
        self.assertEqual(self.view('gn')['today'][0]['date'],DAY)
        self.assertEqual(self.view()['tasks']['total'],0)

    def test_experiment_condition_uses_concrete_plans_not_generic_mentions(self):
        reminder=self.capture(task={'title':'Use expiring tokens','timezone':'Europe/London',
            'repeat':{'weekdays':list(range(7)),'start':DAY,'until':'2026-10-19'},
            'when':{'unless_experiment_plan':True}})['task_id']
        self.capture(task={'title':'Maybe advance a little experiment work','planned_date':DAY})
        self.assertIn(reminder,[r['id'] for r in self.view()['tasks']['items']])
        self.capture(task={'title':'Run the confirmed culture experiment','planned_date':DAY,'work_kind':'experiment'})
        self.assertNotIn(reminder,[r['id'] for r in self.view()['tasks']['items'] if r['date']==DAY])

    def test_craft_suppression_uses_fixed_plans_not_all_day_observances(self):
        identifier=self.capture(task={'title':'Craft reminder','timezone':'Asia/Shanghai',
            'repeat':{'weekdays':[0,1,2,3,4],'start':'2026-10-12'},
            'when':{'morning_before':'10:00','unless_timed_plan':True,'unless_experiment_plan':True}})['task_id']
        directory=self.root/'browser-jobs';directory.mkdir()
        (directory/'jobs.json').write_text(json.dumps({DAY+'.gm':{'generation_started_at':datetime.fromisoformat(DAY+'T09:00:00+08:00').timestamp()}}))
        calendar=CalendarStore(str(self.root/'calendar.sqlite'))
        try:
            calendar.add({'subject':'A birthday','all_day':True,'timezone':'Asia/Shanghai','start':DAY,'end':'2026-10-14'})
            self.assertIn(identifier,[r['id'] for r in self.view()['tasks']['items']])
            event=calendar.add({'subject':'Evening appointment','start':DAY+'T18:00:00+08:00','end':DAY+'T19:00:00+08:00'})
            self.assertNotIn(identifier,[r['id'] for r in self.view()['tasks']['items']])
            calendar.change(event,'cancel',1)
            self.assertIn(identifier,[r['id'] for r in self.view()['tasks']['items']])
        finally:
            calendar.close()

    def test_clothing_reminder_follows_the_canonical_training_plan_not_makeup_days(self):
        parent=self.capture(task={'title':'Training','timezone':'Asia/Shanghai',
            'repeat':{'interval_days':2,'start':'2026-10-12'}})['task_id']
        child=self.capture(task={'title':'Bring clothing','timezone':'Asia/Shanghai',
            'when':{'planned_task_id':parent}})['task_id']
        self.tasks.occurrence(self.tasks.show(child),'2026-10-14')
        self.tasks.mutate(parent,1,{'status':'done','confirmed_completion':True},'ses_test','off-plan-session',
            '2026-10-15T12:00:00+08:00',day='2026-10-15',actual=True)
        with self.assertRaisesRegex(ValueError,'unknown_occurrence'):
            self.tasks.occurrence(self.tasks.show(child),'2026-10-15')
        self.tasks.mutate(parent,2,{'repeat':{'interval_days':2,'start':'2026-10-13'}},'ses_test','change-plan',NOW)
        self.tasks.occurrence(self.tasks.show(child),'2026-10-15')
        with self.assertRaisesRegex(ValueError,'unknown_occurrence'):
            self.tasks.occurrence(self.tasks.show(child),'2026-10-14')
        self.tasks.mutate(parent,3,{'status':'cancelled'},'ses_test','stop-plan',NOW)
        with self.assertRaisesRegex(ValueError,'unknown_occurrence'):
            self.tasks.occurrence(self.tasks.show(child),'2026-10-15')

    def test_soft_target_remains_explicitly_soft_in_source_linked_presentation(self):
        self.capture(task={'title':'Write paper','due_date':DAY,'due_soft':True})
        self.capture(task={'title':'Write paper','due_date':DAY})
        view=self.view()
        cells={row[0]:row[-1] for row in view['blocks']['tasks'][1]}
        soft,hard=(cells[r['id']] for r in sorted(view['tasks']['items'],key=lambda r:not r.get('due_soft')))
        self.assertEqual(sum(bool(r.get('due_soft')) for r in view['tasks']['items']),1)
        self.assertIn(DAY,soft)
        self.assertNotEqual(soft,hard)

    def test_annual_observance_projects_from_approved_source_without_materializing(self):
        (self.root/'profile.md').write_text((self.root/'profile.md').read_text().replace('Europe/London','Asia/Shanghai'))
        calendar=CalendarStore(str(self.root/'calendar.sqlite'))
        try:
            identifier=calendar.add({'subject':'Synthetic birthday','all_day':True,'timezone':'Asia/Shanghai',
                'start':'2027-01-06','end':'2027-01-07','repeat':{'yearly':True,'start':'2026-10-11'}})
            start=datetime.fromisoformat('2028-01-06T00:00:00+08:00')
            end=datetime.fromisoformat('2028-01-07T00:00:00+08:00')
            rows=calendar.query(start,end)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['series_event_id'],identifier)
            self.assertEqual(calendar.get(rows[0]['id'])['approved']['start'],'2028-01-06')
            self.assertEqual(calendar.stats()['total'],1)
            with self.assertRaisesRegex(ValueError,'clarification_required'):
                calendar.change(rows[0]['id'],'cancel',1)
            self.assertEqual(calendar.stats()['total'],1)
            self.assertEqual(len(calendar.history(identifier)),1)
        finally:
            calendar.close()
        view=self.view(day='2028-01-06')
        document=self.document(view['blocks']['schedule'],'schedule')
        routing.validate_sources(self.root,document,'2028-01-06','gm')

    def test_deadline_is_not_workday_and_undated_tasks_are_not_dated_on_publication(self):
        receipt = self.capture(task={'title': 'Send report', 'due_date': '2026-10-16', 'detail': 'Attach signed figures.', 'project': 'Atlas'})
        row = self.view()['tasks']['items'][0]
        self.assertEqual(row['group'], 'deadline')
        self.assertEqual(row['date'], '')
        self.assertEqual(row['detail'], 'Attach signed figures.')
        doc = self.document(self.view()['blocks']['tasks'])
        self.assertEqual(daily.planned_tasks(doc, DAY), {})
        routing.validate_sources(self.root, doc, DAY, 'gm')
        self.assertEqual(self.tasks.show(receipt['task_id'])['planned_date'], '')
        week = saved_week(self.root, 'Europe/London', datetime(2026, 10, 13, tzinfo=timezone.utc), 0)
        # Only a deadline marker on the due date; no workday occurrence anywhere.
        marked = [(day['date'], task['marker'], task['occurrence_id']) for day in week['days'] for task in day['tasks']]
        self.assertEqual(marked, [('2026-10-16', 'due', '')])

    def test_planned_tasks_keep_identity_after_rewording_and_have_one_owner(self):
        capture = self.capture(task={'title': 'Atlas: prepare review', 'planned_date': DAY})
        identifier = capture['task_id']
        before = self.view()['tasks']['items'][0]
        self.tasks.mutate(identifier, 1, {'title': 'Atlas: draft the review outline'}, 'ses_test', 'rename', NOW)
        after = self.view()['tasks']['items'][0]
        self.assertEqual(before['id'], after['id'])
        self.assertEqual(before['occurrence_id'], after['occurrence_id'])
        block = self.view()['blocks']['tasks']
        doc = self.document(block)
        doc['sections'][0][1].append(copy.deepcopy(block))
        with self.assertRaisesRegex(ValueError, 'duplicate source'):
            native.validate_task_ownership(doc)

    def test_several_actions_share_one_capture_without_subtask_collapse(self):
        entry = self.capture('Organize these project actions', 'idea')['id']
        payload = {'tasks': [{'title': 'Compare baselines'}, {'title': 'Improve plot colors', 'optional': True}]}
        result = self.tasks.adopt(entry, 1, payload, 'ses_test', 'adopt', NOW)
        again = self.tasks.adopt(entry, 1, payload, 'ses_test', 'adopt', NOW)
        self.assertEqual(result['task_ids'], again['task_ids'])
        self.assertEqual(self.view()['tasks']['total'], 2)
        self.assertEqual(len(self.inbox.show(entry)['task_ids']), 2)

    def test_requested_todo_split_is_atomic_exact_scope_and_preserves_the_source(self):
        receipt = self.capture('Buy milk and return the book')
        payload = {'tasks': [{'title': 'Buy milk'}, {'title': 'Return the book'}],
                   'replace': [{'id': receipt['task_id'], 'revision': 1}]}
        result = self.tasks.adopt(receipt['id'], 1, payload, 'ses_test', 'split', NOW)
        self.assertEqual(self.tasks.show(receipt['task_id'])['status'], 'cancelled')
        self.assertEqual(self.view()['tasks']['total'], 2)
        self.assertEqual(self.inbox.text(receipt['id'])['text'], 'Buy milk and return the book')
        self.assertEqual(self.tasks.adopt(receipt['id'], 1, payload, 'ses_test', 'split', NOW)['task_ids'], result['task_ids'])

    def test_partial_work_does_not_roll_over_or_infer_completion(self):
        identifier = self.capture(task={'title': 'Draft report', 'planned_date': DAY})['task_id']
        self.tasks.mutate(identifier, 1, {'status': 'blocked', 'detail': 'Awaiting data.'}, 'ses_test', 'blocked', NOW, day=DAY)
        row = self.view('gn')['tasks']['items'][0]
        self.assertEqual((row['group'], row['date'], row['status']), ('still-open', DAY, 'blocked'))
        self.assertEqual(self.tasks.show(identifier)['planned_date'], DAY)
        with self.assertRaisesRegex(ValueError, 'confirmation_required'):
            self.tasks.mutate(identifier, 2, {'status': 'done'}, 'ses_test', 'bad-completion', NOW)

    def test_reported_outcome_survives_an_explicit_reschedule(self):
        identifier = self.capture(task={'title': 'Draft report', 'planned_date': DAY})['task_id']
        self.tasks.mutate(identifier, 1, {'status': 'partial', 'detail': 'Outline drafted.'}, 'ses_test', 'progress', NOW, day=DAY)
        self.tasks.mutate(identifier, 2, {'planned_date': '2026-10-14'}, 'ses_test', 'agreed-move', NOW)
        view = self.view('gn')
        self.assertEqual(view['today'][0]['status'], 'partial')
        self.assertEqual(view['today'][0]['date'], DAY)
        self.assertEqual(view['tasks']['items'][0]['date'], '2026-10-14')

    def test_global_completion_does_not_rewrite_a_previous_days_partial_outcome(self):
        identifier = self.capture(task={'title': 'Draft report', 'planned_date': DAY})['task_id']
        self.tasks.mutate(identifier, 1, {'status': 'partial', 'detail': 'Outline only.'}, 'ses_test', 'partial', NOW, day=DAY)
        self.tasks.mutate(identifier, 2, {'status': 'done', 'confirmed_completion': True}, 'ses_test', 'later-completion', '2026-10-14T12:00:00+01:00')
        self.assertEqual(self.view('gn')['today'][0]['status'], 'partial')
        other = self.capture(task={'title': 'Unreported outcome', 'planned_date': DAY})['task_id']
        self.tasks.mutate(other, 1, {'status': 'done', 'confirmed_completion': True}, 'ses_test', 'global-only', NOW)
        self.assertEqual([r['id'] for r in self.view('gn')['today']], [identifier])

    def test_recurring_completion_is_one_occurrence_and_reads_do_not_materialize(self):
        identifier = self.capture(task={'title': 'Wash towels', 'timezone': 'Europe/London',
                                       'repeat': {'weekdays': [5], 'start': DAY}})['task_id']
        self.assertEqual(self.inbox.db.execute('SELECT COUNT(*) FROM task_occurrences').fetchone()[0], 0)
        self.assertEqual(self.view(day='2026-10-17')['tasks']['total'], 1)
        self.assertEqual(self.inbox.db.execute('SELECT COUNT(*) FROM task_occurrences').fetchone()[0], 0)
        self.tasks.mutate(identifier, 1, {'status': 'done', 'confirmed_completion': True}, 'ses_test', 'saturday', NOW, day='2026-10-17')
        self.assertEqual(self.view(day='2026-10-17')['tasks']['total'], 0)
        self.assertEqual(self.view(day='2026-10-24')['tasks']['items'][0]['status'], 'open')
        self.assertEqual(self.tasks.show(identifier)['status'], 'open')

    def test_tbc_event_is_persistent_not_an_all_day_or_flexible_task(self):
        receipt = self.capture('Dentist Thursday; time unknown', 'event_proposal', draft={
            'title': 'Dentist', 'date': '2026-10-15', 'timezone': 'Europe/London', 'confirmed_day': True})
        self.assertEqual(self.view()['schedule']['items'], [])  # A morning shows its own day only.
        view = self.view(day='2026-10-15')
        self.assertEqual(view['tasks']['total'], 0)
        self.assertEqual(view['schedule']['items'][0]['time'], 'TBC')
        self.assertFalse(view['schedule']['items'][0].get('all_day', False))
        self.assertEqual(view['blocks']['schedule'][1][0][0], receipt['draft_id'])

    def test_tentative_proposal_does_not_reserve_schedule_and_clear_ideas_are_quiet(self):
        self.capture('Maybe meet Sam next week', 'event_proposal', draft={'title': 'Meet Sam', 'state': 'tentative'})
        self.capture('Maybe build a dashboard', 'idea')
        self.capture('Which scope?', 'project_update', questions=['Which scope?'], review_after='2026-10-20')
        self.assertEqual(self.view()['schedule']['items'], [])
        self.assertEqual(self.view()['attention']['items'], [])
        self.assertEqual(self.view(day='2026-10-20')['attention']['total'], 1)

    def test_complete_event_request_is_saved_before_confirmation_but_not_approved(self):
        payload = {'subject': 'Dentist', 'start': '2026-10-15T14:00:00+01:00', 'end': '2026-10-15T15:00:00+01:00', 'location': 'Town Clinic'}
        self.capture('Add dentist Thursday 14:00-15:00 at Town Clinic', 'event_proposal',
                     draft={'title': 'Dentist', 'state': 'ready-for-confirmation', 'event': payload})
        view = self.view()
        self.assertEqual(view['schedule']['items'], [])
        self.assertEqual(view['attention']['total'], 1)
        self.assertEqual(view['attention']['items'][0]['event']['subject'], 'Dentist')
        self.assertEqual(self.inbox.stats()['total'], 1)
        doc = self.document(view['blocks']['attention'], 'attention')
        routing.validate_sources(self.root, doc, DAY, 'gm')
        draft = view['attention']['items'][0]['draft_id']
        self.tasks.mutate(draft, 1, {'title': 'Updated dentist'}, 'ses_test', 'update-draft', NOW, draft=True)
        with self.assertRaisesRegex(ValueError, 'source_conflict'):
            routing.validate_sources(self.root, doc, DAY, 'gm')

    def test_conversion_retry_does_not_duplicate_calendar_after_partial_commit(self):
        identifier = self.capture('Dentist Thursday', 'event_proposal')['draft_id']
        payload = {'event': {'subject': 'Dentist', 'start': '2026-10-15T14:00:00+01:00', 'end': '2026-10-15T15:00:00+01:00'}}
        original = CalendarStore.add
        def crash_after_commit(calendar, *args, **kwargs):
            original(calendar, *args, **kwargs)
            raise OSError('synthetic crash after calendar commit')
        with patch.object(CalendarStore, 'add', crash_after_commit), self.assertRaises(OSError):
            self.tasks.convert(self.root, identifier, 1, payload, 'ses_test', 'convert', NOW)
        with self.assertRaisesRegex(ValueError, 'outcome_unknown'):
            self.tasks.mutate(identifier, 1, {'title': 'Changed'}, 'ses_test', 'edit', NOW, draft=True)
        result = self.tasks.convert(self.root, identifier, 1, payload, 'ses_test', 'convert', NOW)
        self.assertTrue(self.tasks.convert(self.root, identifier, 1, payload, 'ses_test', 'convert', NOW)['replayed'])
        calendar = CalendarStore(str(self.root/'calendar.sqlite'), readonly=True)
        try:
            self.assertEqual(calendar.stats()['total'], 1)
        finally:
            calendar.close()
        self.assertEqual(self.tasks.show(identifier, True)['calendar_event_id'], result['calendar_event_id'])

    def test_imports_apply_and_the_next_edition_reports_them_once(self):
        calendar = CalendarStore(str(self.root/'calendar.sqlite'))
        self.addCleanup(calendar.close)
        event = {'external_id': 'provider-id', 'subject': 'Meeting', 'start': DAY+'T10:00:00+01:00', 'end': DAY+'T11:00:00+01:00'}
        stamp = lambda: datetime.now(timezone.utc).isoformat()
        calendar.mark('2026-10-12.gn', stamp())
        started = stamp()
        calendar.import_events('work', [event, {**event, 'external_id': 'other', 'subject': 'Lunch',
                                                'start': DAY+'T12:30:00+01:00', 'end': DAY+'T13:30:00+01:00'}])
        calendar.mark(DAY + '.gm', started)
        view = self.view()
        self.assertEqual([r['subject'] for r in view['schedule']['items']], ['Meeting', 'Lunch'])
        self.assertEqual([r[2] for r in view['blocks']['attention'][1]], ['New: Meeting', 'New: Lunch'])
        routing.validate_sources(self.root, self.document(view['blocks']['attention'], 'attention'), DAY, 'gm')
        started = stamp()
        calendar.import_events('work', [{**event, 'start': DAY+'T12:00:00+01:00', 'end': DAY+'T13:00:00+01:00'}])
        calendar.mark(DAY + '.gn', started)
        view = self.view('gn')
        self.assertEqual(view['blocks']['attention'][1][0][2:], [
            'Changed: Meeting', 'Tue, Oct 13 10:00–11:00 → 12:00–13:00 · Overlaps Lunch (Tue, Oct 13 12:30–13:30)'])
        morning = self.view()
        self.assertIn('12:00', routing.event_cells(morning['schedule']['items'][0], 'Europe/London')[1])
        self.assertEqual(morning['attention']['total'], 2)  # A regenerated edition keeps its own report.

    def test_event_cells_preserve_overnight_and_exclusive_all_day_end_dates(self):
        event = {'subject': 'Overnight', 'start': DAY+'T23:00:00+01:00',
                 'end': '2026-10-14T01:00:00+01:00', 'all_day': False}
        self.assertIn('2026-10-14 01:00', routing.event_cells(event, 'Europe/London')[1])
        event.update(all_day=True, start=DAY, end='2026-10-16', timezone='Europe/London')
        self.assertIn('2026-10-15', routing.event_cells(event, 'Europe/London')[1])

    def test_source_validation_rejects_invented_dates_status_revisions_and_wrong_owner(self):
        self.capture(task={'title': 'Report'})
        doc = self.document(self.view()['blocks']['tasks'])
        for column, value in ((1, 99), (3, DAY), (4, 'done')):  # Title and detail are display wording.
            changed = copy.deepcopy(doc)
            changed['sections'][0][1][0][1][0][column] = value
            with self.assertRaisesRegex(ValueError, 'source_conflict'):
                routing.validate_sources(self.root, changed, DAY, 'gm')
        doc['sections'][0][0] = 'schedule'
        with self.assertRaisesRegex(ValueError, 'wrong section owner'):
            native.validate(doc)

    def test_paging_keeps_stable_action_ids_and_no_silent_later_page_loss(self):
        ids = {self.capture(f'Task {n}')['task_id'] for n in range(12)}
        first = self.view()['tasks']
        second = routing.prepare(self.root, DAY, 'gm', offset=first['next_offset'])['tasks']
        self.assertEqual(first['total'], 12)
        self.assertEqual({r['id'] for r in first['items'] + second['items']}, ids)
        self.assertIsNone(second['next_offset'])

    def test_browser_v2_save_does_not_create_daily_tasks_and_keeps_archives_readable(self):
        self.capture(task={'title': 'Undated action'})
        job = self.browser_job('a', 'gm', 'running', session='ses_test'); preflight(self.root, job)
        act(self.root, job['id'], 'ses_test', 'init', {'greeting': 'Morning.', 'opening': 'Plan.'})
        act(self.root, job['id'], 'ses_test', 'publish', {'position': 0, 'section': ['weather', [['p', 'Weather unavailable; check before travelling.']]]})
        act(self.root, job['id'], 'ses_test', 'publish', {'position': 1, 'section': ['news', [['p', 'News unavailable.']]]})
        act(self.root, job['id'], 'ses_test', 'publish', {'position': 2, 'section': ['schedule', [['p', 'No appointments.']]]})
        act(self.root, job['id'], 'ses_test', 'publish', {'position': 3, 'section': ['tasks', [self.view()['blocks']['tasks']]]})
        act(self.root, job['id'], 'ses_test', 'skip', {'position': 4})
        act(self.root, job['id'], 'ses_test', 'finish', {})
        doc = native.parse((self.root/'daily'/f'{DAY}.gm.json').read_text())
        self.assertEqual(doc['v'], 2)
        self.assertEqual(daily.show(self.root, DAY)['tasks_total'], 0)
        old = {'v': 1, 'greeting': 'Old.', 'opening': 'Archive.', 'sections': [['must-do', [['tasks', [['open', 'Historical', '']]]]]]}
        self.assertEqual(native.parse(native.encode(old)), old)

    def test_evening_questions_only_cover_agreed_day_not_undated_backlog(self):
        self.capture('Undated backlog')
        task = self.capture(task={'title': 'Today task', 'planned_date': DAY})['task_id']
        job = self.browser_job('b', session='ses_test')
        context = preflight(self.root, job)
        completed = next(f for f in context['form']['fields'] if f['key'] == 'completed')
        self.assertEqual([o['value'] for o in completed['options']], ['none', occurrence_id(task, DAY)])
        result = answer(self.root, job, {'completed': [occurrence_id(task, DAY)], 'details': 'No other updates'})
        self.assertTrue(result['feedback']['saved'])
        self.assertEqual(self.tasks.show(task)['status'], 'done')
        self.assertEqual(self.inbox.show(self.tasks.show(task)['source_entry_id'])['status'], 'done')
        self.assertEqual(answer(self.root, job, {'completed': [occurrence_id(task, DAY)], 'details': 'No other updates'}), result)

    def test_evening_includes_saved_morning_tasks_with_current_identity_and_actual_day(self):
        undated = self.capture(task={'title':'Morning choice'})['task_id']
        old = self.capture(task={'title':'Older work','planned_date':'2026-10-11'})['task_id']
        planned = self.capture(task={'title':'Today work','planned_date':DAY})['task_id']
        recurring = self.capture(task={'title':'Recurring work','timezone':'Europe/London',
            'repeat':{'weekdays':[1], 'start':DAY}})['task_id']
        closed = self.capture(task={'title':'Later cancelled'})['task_id']
        block = routing.prepare(self.root, DAY, 'gm', limit=200)['blocks']['tasks']
        (self.root/'daily').mkdir(exist_ok=True)
        (self.root/'daily'/f'{DAY}.gm.json').write_text(native.encode(self.document(block)))
        self.capture('Not shown this morning')
        future = self.capture(task={'title':'Future only','planned_date':'2026-11-11'})['task_id']
        self.tasks.mutate(closed,1,{'status':'cancelled'},'ses_test','cancel',NOW)
        self.tasks.mutate(undated,1,{'title':'Revised morning choice'},'ses_test','rename',NOW)
        job = {'id':'e'*32,'date':DAY,'kind':'gn','state':'preflight'}
        context = preflight(self.root,job)
        known = {t['task_id']:t for t in context['feedback_tasks'] if not t['done']}
        self.assertEqual(set(known),{undated,old,planned,recurring})
        self.assertEqual(known[undated]['text'],'Revised morning choice')
        self.assertEqual(known[undated]['revision'],2)
        self.assertNotIn(future,known)
        selected = [known[id]['id'] for id in (undated,old,recurring)]
        payload = {'completed':selected,'details':'Today work is partial.'}
        result = answer(self.root,job,payload)
        self.assertEqual(answer(self.root,job,payload),result)
        for id in (undated,old,recurring):
            self.assertEqual(self.tasks.occurrence(self.tasks.show(id),DAY)['status'],'done')
        self.assertEqual(self.tasks.show(undated)['planned_date'],'')
        self.assertEqual(self.tasks.show(old)['planned_date'],'2026-10-11')
        self.assertEqual(self.tasks.show(old)['status'],'done')
        self.assertEqual(self.tasks.show(recurring)['status'],'open')
        self.assertEqual(self.tasks.occurrence(self.tasks.show(recurring),'2026-10-20')['status'],'open')
        self.assertEqual(self.tasks.show(planned)['status'],'open')
        self.assertEqual({r['id'] for r in routing.reported_day(self.tasks,DAY)}, {undated,old,recurring})

    def test_empty_evening_asks_about_actual_work_without_completion_checkbox(self):
        self.capture('Undated work not shown in a morning briefing')
        job = {'id':'f'*32,'date':DAY,'kind':'gn','state':'preflight'}
        context = preflight(self.root,job)
        fields = {f['key']:f for f in context['form']['fields']}
        self.assertEqual(set(fields),{'details'})
        self.assertTrue(fields['details']['customFirst'])
        self.assertEqual([o['value'] for o in fields['details']['options']],['No updates today'])
        with self.assertRaisesRegex(ValueError,'Give actual details'):
            answer(self.root,job,{'details':'   '})
        result = answer(self.root,job,{'details':'Read a paper and made progress.'})
        self.assertEqual(result['feedback']['completed'],[])
        text = (self.root/'daily'/f'{DAY}.md').read_text()
        self.assertIn('Read a paper and made progress.',text)
        self.assertNotIn('No listed tasks were fully completed.',text)
        self.assertEqual(len(routing.reported_day(self.tasks,DAY)),0)

    def test_empty_evening_question_is_localized(self):
        english = preflight(self.root,{'id':'8'*32,'date':DAY,'kind':'gn','state':'preflight'})['form']
        job = {'id':'9'*32,'date':DAY,'kind':'gn','state':'preflight','language':'zh-CN'}
        context = preflight(self.root,job)
        self.assertLocalized(context['form']['title'],english['title'])
        field,source = context['form']['fields'][0],english['fields'][0]
        for key in ('title','placeholder','description'):
            self.assertLocalized(field[key],source[key])
        self.assertLocalized(field['options'][0]['label'],source['options'][0]['label'])
        self.assertEqual(field['options'][0]['value'],source['options'][0]['value'])
        result = answer(self.root,job,{'details':'No updates today'})
        self.assertTrue(result['feedback']['saved'])

    def test_morning_recurring_completion_does_not_reappear_as_actual_choice(self):
        id = self.capture(task={'title':'Weekly','timezone':'Europe/London',
            'repeat':{'weekdays':[1],'start':DAY}})['task_id']
        block = self.view()['blocks']['tasks']
        (self.root/'daily').mkdir(exist_ok=True)
        (self.root/'daily'/f'{DAY}.gm.json').write_text(native.encode(self.document(block)))
        self.tasks.mutate(id,1,{'status':'done','confirmed_completion':True},'ses_test','report',NOW,day=DAY,actual=True)
        context = preflight(self.root,{'id':'8'*32,'date':DAY,'kind':'gn','state':'preflight'})
        self.assertNotIn('completed',{f['key'] for f in context['form']['fields']})

    def test_actual_feedback_conflict_rolls_back_all_selected_completions(self):
        first = self.capture(task={'title':'First'})['task_id']
        second = self.capture(task={'title':'Second'})['task_id']
        selections = [{'task_id':id,'id':occurrence_id(id,DAY),'revision':1,'actual':True}
                      for id in (first,second)]
        self.tasks.mutate(second,1,{'title':'Changed'},'ses_test','changed',NOW)
        with self.assertRaisesRegex(ValueError,'write_conflict'):
            self.tasks.complete_day(selections,DAY,'ses_test','feedback',NOW,'No other updates')
        self.assertEqual(self.tasks.show(first)['status'],'open')
        self.assertEqual(routing.reported_day(self.tasks,DAY),[])
        self.assertIsNone(self.inbox.db.execute("SELECT 1 FROM task_events WHERE request_key='feedback'").fetchone())

    def test_actual_feedback_rejects_future_completion_and_foreign_occurrence(self):
        id = self.capture(task={'title':'Undated'})['task_id']
        selection = {'task_id':id,'id':occurrence_id(id,'2026-10-14'),'revision':1,'actual':True}
        with self.assertRaisesRegex(ValueError,'future work'):
            self.tasks.complete_day([selection],'2026-10-14','ses_test','future',NOW,'No other updates')
        with self.assertRaisesRegex(ValueError,'unknown_occurrence'):
            self.tasks.complete_day([selection],DAY,'ses_test','foreign',NOW,'No other updates')
        self.assertEqual(self.tasks.show(id)['status'],'open')

    def test_morning_choices_keep_distinct_ids_and_deduplicate_multiple_days(self):
        first = self.capture(task={'title':'Same title','timezone':'Europe/London',
            'repeat':{'interval_days':1,'start':DAY}})['task_id']
        second = self.capture(task={'title':'Same title'})['task_id']
        (self.root/'daily').mkdir(exist_ok=True)
        block = routing.prepare(self.root,DAY,'gm',limit=200)['blocks']['tasks']
        (self.root/'daily'/f'{DAY}.gm.json').write_text(native.encode(self.document(block)))
        rows = routing.feedback_day(self.tasks,DAY)
        self.assertEqual({r['id'] for r in rows},{first,second})
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r['occurrence_id']==occurrence_id(r['id'],DAY) for r in rows))

    def test_account_isolation_and_readonly_missing_store(self):
        self.capture(task={'title': 'Private task'})
        other = self.root/'other'; other.mkdir()
        (other/'profile.md').write_text((self.root/'profile.md').read_text())
        initialize(other)
        self.assertEqual(routing.prepare(other, DAY, 'gm')['tasks']['total'], 0)
        missing = self.root/'missing'; missing.mkdir()
        (missing/'profile.md').write_text((self.root/'profile.md').read_text())
        self.assertTrue(routing.prepare(missing, DAY, 'gm')['warnings'])
        self.assertFalse((missing/'inbox.sqlite').exists())

    def test_preflight_completion_before_agent_session_exists(self):
        task = self.capture(task={'title':'Today task', 'planned_date':DAY})['task_id']
        job = self.browser_job('c'); preflight(self.root, job)
        result = answer(self.root, job, {'completed':[occurrence_id(task,DAY)], 'details':'No other updates'})
        self.assertTrue(result['feedback']['saved'])
        self.assertEqual(self.tasks.show(task)['status'],'done')
        self.assertEqual(self.inbox.db.execute("SELECT session FROM task_events WHERE action='feedback'").fetchone()[0], 'browser:'+job['id'])

    def test_stale_daily_feedback_cannot_complete_canonical_tasks(self):
        task = self.capture(task={'title':'Today task', 'planned_date':DAY})['task_id']
        job = self.browser_job('d'); preflight(self.root, job)
        (self.root/'daily').mkdir(exist_ok=True)
        (self.root/'daily'/f'{DAY}.md').write_text('## feedback\n- An unrelated new report\n')
        with self.assertRaisesRegex(ValueError,'daily plan changed'):
            answer(self.root, job, {'completed':[occurrence_id(task,DAY)], 'details':'No other updates'})
        self.assertEqual(self.tasks.show(task)['status'],'open')

    def test_regeneration_with_reused_feedback_does_not_ask_about_archive_gaps(self):
        (self.root/'daily').mkdir(exist_ok=True)
        (self.root/'daily'/'2026-10-12.md').write_text('# 2026-10-12\n- gn: yes (session ses_old)\n')
        job = self.browser_job('e')
        previous = {'feedback':{'completed':[], 'details':'No other updates', 'saved':True}}
        context = preflight(self.root,job,previous=previous)
        self.assertIsNone(context['form'])
        self.assertFalse(context['awaiting'])
        self.assertEqual(context['feedback'],previous['feedback'])
        self.assertFalse((self.root/'daily'/f'{DAY}.md').exists())

    def test_evening_options_keep_current_project_context_and_unassigned_group(self):
        first=self.capture(task={'title':'Review results','project':'Atlas','planned_date':DAY})['task_id']
        second=self.capture(task={'title':'Review results','project':'Paper','planned_date':DAY})['task_id']
        other=self.capture(task={'title':'Personal work','planned_date':DAY})['task_id']
        self.tasks.mutate(first,1,{'project':'Atlas revised'},'ses_test','project-rename',NOW)
        (self.root/'daily').mkdir(exist_ok=True)
        historical=self.root/'daily/2026-10-12.md'
        historical.write_text('# 2026-10-12\n- gn: yes (session ses_old)\n')
        context=preflight(self.root,{'id':'7'*32,'date':DAY,'kind':'gn','state':'preflight'})
        fields={f['key']:f for f in context['form']['fields']}
        self.assertEqual(set(fields),{'completed','details'})
        options=fields['completed']['options']
        self.assertNotIn('group',options[0])
        self.assertEqual([o['group'] for o in options[1:]],['Atlas revised','Paper','Other tasks'])
        self.assertTrue(fields['details']['customFirst'])
        self.assertEqual([o['value'] for o in fields['details']['options']],['No other updates'])
        self.assertEqual({o['value']:o['group'] for o in options[1:]},
            {occurrence_id(first,DAY):'Atlas revised',occurrence_id(second,DAY):'Paper',occurrence_id(other,DAY):'Other tasks'})
        self.assertEqual(historical.read_text(),'# 2026-10-12\n- gn: yes (session ses_old)\n')
        result=answer(self.root,{'id':'7'*32,'date':DAY,'kind':'gn'},
            {'completed':[occurrence_id(second,DAY)],'details':'No other updates'})
        self.assertTrue(result['feedback']['saved'])
        self.assertEqual(self.tasks.show(first)['status'],'open')
        self.assertEqual(self.tasks.show(second)['status'],'done')

    def test_unassigned_group_uses_website_language_without_translating_project_names(self):
        self.capture(task={'title':'Task','planned_date':DAY})
        self.capture(task={'title':'Project task','project':'Atlas','planned_date':DAY})
        english=preflight(self.root,{'id':'5'*32,'date':DAY,'kind':'gn','state':'preflight'})['form']['fields']
        context=preflight(self.root,{'id':'6'*32,'date':DAY,'kind':'gn','state':'preflight','language':'zh-CN'})
        options=next(f for f in context['form']['fields'] if f['key']=='completed')['options']
        self.assertEqual([o.get('group') for o in options[:2]],[None,'Atlas'])
        self.assertLocalized(options[2]['group'],'Other tasks')
        for field,source in zip(context['form']['fields'],english,strict=True):
            self.assertLocalized(field['title'],source['title'])
            self.assertLocalized(field['options'][0]['label'],source['options'][0]['label'])

    def test_section_recipe_returns_identical_sources_without_unrelated_payload(self):
        for n in range(9):
            self.capture(f'Task {n}')
        expected = self.view()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = task_cli.main(['--secretary-dir',str(self.root),'--briefing','gm','--date',DAY,'--section','tasks'])
        actual = json.loads(output.getvalue())
        self.assertEqual(code,0)
        self.assertEqual(actual['block'],expected['blocks']['tasks'])
        self.assertEqual(actual['next_offset'],7)
        self.assertNotIn('schedule',actual)
        self.assertLess(len(output.getvalue()),len(json.dumps(expected)))

    def test_secretary_preparation_does_not_collect_an_unrequested_agenda(self):
        with patch.object(routing,'prepare',side_effect=AssertionError('unrequested agenda scan')):
            result = workflow.prepare(self.root,'secretary',DAY)
        self.assertTrue(result['ready'])
        self.assertNotIn('items',result)

    def test_legacy_checklists_neither_block_v2_preflight_nor_enter_the_agent_plan(self):
        (self.root/'daily').mkdir(exist_ok=True)
        (self.root/'daily'/f'{DAY}.md').write_text('## flexible\n'+''.join(f'- [ ] Legacy {n}\n' for n in range(201)))
        job = self.browser_job('f', 'gm', 'running', session='ses_test'); preflight(self.root,job)
        result = act(self.root,job['id'],'ses_test','prepare')
        self.assertNotIn('tasks',result['daily'])
        self.assertNotIn('items',result)
        self.assertNotIn('feedback_tasks',result)
        self.assertEqual(result['next']['action'],'init')

    def test_v2_receipts_carry_one_localized_step_guide_at_a_time(self):
        app = BrowserApp(self.root, now=lambda:datetime(2026,10,13,12,tzinfo=timezone.utc), preflight=True)
        for language, contract, title in (('en','ESCAPE HATCH','Weather'), ('zh-CN','例外通道','天气')):
            identifier = ('e' if language == 'en' else 'c')*32
            job = {'id':identifier,'date':DAY,'kind':'gm','state':'running','session':'ses_test','language':language}
            app.jobs[DAY+'.gm']=job; app.save_jobs(); preflight(self.root,job)
            result = act(self.root,identifier,'ses_test','prepare')
            self.assertIn(contract,result['contract'])
            self.assertIn('docs/core-rules.md',result['contract'])
            self.assertEqual(result['next']['input'],{'greeting':'…','opening':'…'})
            self.assertIn(title,result['next']['guide'])
            self.assertNotIn('instruction',result['next'])
            result = act(self.root,identifier,'ses_test','init',{'greeting':'Hi.','opening':'Weather first.'})
            guide = result['next']['guide']
            self.assertEqual(result['next']['input'],{'position':0,'section':['weather','BLOCKS','NOTE',title]})
            self.assertIn('`input`',guide)
            self.assertIn('temperature',guide)
            self.assertNotIn('polish:',guide)
            self.assertNotIn('instruction',result['next'])
            activity = self.root/'browser-jobs'/(identifier+'.activity.json')
            self.assertEqual(json.loads(activity.read_text()),{'step':'write','position':0,'section':'weather','count':None})
            result = act(self.root,identifier,'ses_test','publish',{'position':0,'section':['weather',[['p','Unavailable.']],'',title]})
            self.assertEqual(json.loads(activity.read_text())['section'],'news')
            self.assertEqual(result['next']['input']['position'],1)
            self.assertEqual(result['next']['input']['section'][0],'news')
        guide = briefing_guides.guide({'date':DAY}, {'action':'publish','section':['tasks','Tasks']}, [],
                                      runtime=self.root, job='j'*32, session='ses_test')
        self.assertNotIn('--update', guide)  # Briefings present saved items; they never rewrite them.
        guide = briefing_guides.guide({'date':DAY}, {'action':'publish','section':['today','Today']}, [],
                                      runtime=self.root, job='j'*32, session='ses_test')
        self.assertIn('--secretary-dir '+str(self.root),guide)
        self.assertNotIn('RUNTIME',guide)
        self.assertIn('gn-plan:'+'j'*32, guide)  # Dated plans in progress notes are scheduled, not only mentioned.

    def test_receipts_carry_the_next_sections_reads_after_publication(self):
        self.capture('Buy milk', task={'title': 'Buy milk', 'planned_date': DAY})
        job = self.browser_job('d', kind='gm', state='running', session='ses_test', language='en')
        preflight(self.root, job)
        result = act(self.root, job['id'], 'ses_test', 'init', {'greeting': 'Hi.', 'opening': 'Weather first.'})
        self.assertNotIn('read', result['next'])
        self.assertEqual([r['command'].split()[2] for r in result['next']['results']], ['weather'])
        for position, tag in ((0, 'weather'), (1, 'news')):
            result = act(self.root, job['id'], 'ses_test', 'publish', {'position': position, 'section': [tag, [['p', 'Unavailable.']]]})
        schedule, = result['next']['results']
        self.assertEqual((schedule['exit'], schedule['output']['block'][0]), (0, 'p'))
        result = act(self.root, job['id'], 'ses_test', 'publish', {'position': 2, 'section': ['schedule', [schedule['output']['block']]]})
        tasks, = result['next']['results']
        self.assertEqual(tasks['exit'], 0)  # Ran in turn: an out-of-turn read is refused.
        self.assertEqual([row[5] for row in tasks['output']['block'][1]], ['Buy milk'])

    def test_account_schedule_ignores_process_calendar_override(self):
        other = self.root/'other-calendar.sqlite'
        calendar = CalendarStore(str(other))
        calendar.add({'subject': 'Other account', 'start': DAY+'T09:00:00+01:00', 'end': DAY+'T10:00:00+01:00'})
        calendar.close()
        with patch.dict(os.environ, {'CALENDAR_DB_PATH': str(other)}):
            self.assertEqual(self.view()['schedule']['items'], [])

    def test_linked_reserved_block_owns_action_without_duplicate_task_card(self):
        calendar = CalendarStore(str(self.root/'calendar.sqlite'))
        event_id = calendar.add({'subject': 'Atlas work block', 'start': DAY+'T14:00:00+01:00', 'end': DAY+'T15:00:00+01:00'})
        calendar.close()
        self.capture(task={'title': 'Compare baselines', 'planned_date': DAY, 'calendar_event_id': event_id})
        view = self.view()
        self.assertEqual(view['tasks']['total'], 0)
        self.assertIn('Compare baselines', view['blocks']['schedule'][1][0][-1])
        routing.validate_sources(self.root, self.document(view['blocks']['schedule'], 'schedule'), DAY, 'gm')

    def legacy_runtime(self):
        old = self.root/'legacy'; old.mkdir()
        path = old/'inbox.sqlite'
        with contextlib.closing(sqlite3.connect(path)) as db, db:
            db.executescript("""
                CREATE TABLE entries (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,revision INTEGER NOT NULL,
                    kind TEXT CHECK(kind IN ('idea','todo','project_update')),status TEXT,
                    project TEXT,created_at TEXT,updated_at TEXT,raw TEXT,summary TEXT,context TEXT,
                    questions TEXT,needs_review INTEGER DEFAULT 0,reviewed_event INTEGER DEFAULT 0);
                CREATE INDEX active_entries ON entries(status,seq);
                CREATE INDEX review_entries ON entries(needs_review,seq);
                CREATE INDEX project_entries ON entries(project,seq);
                CREATE TABLE events (seq INTEGER PRIMARY KEY,entry_id TEXT REFERENCES entries(id),
                    revision INTEGER,action TEXT,created_at TEXT,session TEXT,detail TEXT,changes TEXT,
                    request_key TEXT UNIQUE,fingerprint TEXT,receipt TEXT);
                PRAGMA user_version=1;
            """)
            db.execute('INSERT INTO entries(id,revision,kind,status,project,created_at,updated_at,raw,summary,context,questions) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       ('ib_'+'a'*16, 1, 'todo', 'pending', '', NOW, NOW, 'Send report by Friday', 'Send report', 'Important constraint', '[]'))
            db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)', (1, 'ib_'+'a'*16, 1, 'add', NOW, 'ses_old', '', 'original bytes', 'old-key', 'hash', 'receipt'))
        return old

    def test_migration_is_explicit_backed_up_and_preserves_raw_history_without_dates(self):
        old=self.legacy_runtime()
        path=old/'inbox.sqlite'
        before = path.read_bytes()
        report = migrate(old)
        self.assertTrue(report['dry_run'])
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'migration_required'):
            InboxStore(old, write=True)
        upgraded = migrate(old, True)
        self.assertTrue((old/upgraded['backup']).exists())
        inbox = InboxStore(old, write=True)
        try:
            task = list(TaskStore(inbox).all())[0]
            self.assertEqual((task['planned_date'], task['due_date']), ('', ''))
            self.assertEqual(inbox.text('ib_'+'a'*16)['text'], 'Send report by Friday')
            self.assertEqual(inbox.db.execute('SELECT changes FROM events').fetchone()[0], 'original bytes')
            self.assertEqual(inbox.db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertIn('draft_id', inbox.mutate('add', {'kind': 'event_proposal', 'raw': 'Unknown time'}, 'ses_test', 'draft', NOW))
        finally:
            inbox.close()

    def test_reviewed_migration_preserves_capture_and_audit_bytes_without_fake_completion(self):
        old=self.legacy_runtime()
        source='ib_'+'a'*16
        with contextlib.closing(sqlite3.connect(old/'inbox.sqlite')) as db, db:
            db.execute("UPDATE entries SET status='done',context='Cancelled, not completed'")
            db.execute("INSERT INTO entries(id,revision,kind,status,project,created_at,updated_at,raw,summary,context,questions) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ('ib_'+'b'*16,1,'todo','pending','',NOW,NOW,'Reference when asked','Reference','No current action','[]'))
            originals=db.execute('SELECT * FROM entries').fetchall()
            events=db.execute('SELECT * FROM events').fetchall()
        plan={source:[{'title':'Cancelled request','status':'cancelled'}], 'ib_'+'b'*16:[]}
        before=(old/'inbox.sqlite').read_bytes()
        with self.assertRaisesRegex(ValueError,'scope_required'):
            migrate(old,True,reviewed_tasks={source:plan[source]},session='ses_test',now=NOW)
        self.assertEqual((old/'inbox.sqlite').read_bytes(),before)
        self.assertFalse((old/'inbox.v1.backup.sqlite').exists())
        preview=migrate(old,reviewed_tasks=plan,session='ses_test',now=NOW)
        self.assertEqual(preview['reviewed_tasks'],1)
        self.assertEqual((old/'inbox.sqlite').read_bytes(),before)
        result=migrate(old,True,reviewed_tasks=plan,session='ses_test',now=NOW)
        self.assertTrue(result['saved'])
        inbox=InboxStore(old,write=True)
        try:
            self.assertEqual([tuple(r)[:-1] for r in inbox.db.execute('SELECT * FROM entries')],originals)
            self.assertEqual([tuple(r) for r in inbox.db.execute('SELECT * FROM events')],events)
            tasks=list(TaskStore(inbox).all())
            self.assertEqual([t['status'] for t in tasks],['cancelled'])
            self.assertEqual(inbox.db.execute('SELECT COUNT(*) FROM task_occurrences').fetchone()[0],0)
            receipt=json.loads(inbox.db.execute('SELECT receipt FROM task_events').fetchone()[0])
            self.assertTrue(receipt['source_records_preserved'])
        finally:
            inbox.close()
        with self.assertRaisesRegex(ValueError,'migration_conflict'):
            migrate(old,True,reviewed_tasks=plan,session='ses_test',now=NOW)

    def test_reviewed_migration_can_import_an_authorized_action_from_an_idea(self):
        old=self.legacy_runtime()
        with contextlib.closing(sqlite3.connect(old/'inbox.sqlite')) as db, db:
            db.execute("UPDATE entries SET kind='idea'")
        plan={'ib_'+'a'*16:[{'title':'Monitor price manually','detail':'No automatic purchase or scheduler'}]}
        result=migrate(old,True,reviewed_tasks=plan,session='ses_test',now=NOW)
        self.assertTrue(result['saved'])
        inbox=InboxStore(old)
        try:
            self.assertEqual(len(list(TaskStore(inbox).all())),1)
            self.assertEqual(inbox.show('ib_'+'a'*16)['kind'],'idea')
        finally:
            inbox.close()

    def test_update_revision_and_secret_validation_precede_any_change(self):
        identifier = self.capture()['task_id']
        for payload in ({'detail': 'token=secret'}, {'unknown': 'field'}, {'repeat': {'weekdays': [9], 'start': DAY}}):
            with self.assertRaises(ValueError):
                self.tasks.mutate(identifier, 1, payload, 'ses_test', 'invalid', NOW)
        self.assertEqual(self.tasks.show(identifier)['revision'], 1)
        self.tasks.mutate(identifier, 1, {'detail': 'Keep this detail'}, 'ses_test', 'valid', NOW)
        with self.assertRaisesRegex(ValueError, 'write_conflict'):
            self.tasks.mutate(identifier, 1, {'title': 'Stale'}, 'ses_test', 'stale', NOW)

    def test_deadline_timestamp_is_not_a_booking_and_dst_recurrence_uses_local_day(self):
        task = self.capture(task={'title': 'Submit report', 'timezone': 'Europe/London',
                                 'due_at': '2026-10-25T17:00:00+00:00'})['task_id']
        self.assertEqual(self.tasks.show(task)['due_date'], '2026-10-25')
        self.assertEqual(self.view()['schedule']['items'], [])
        repeat = self.capture(task={'title': 'Sunday review', 'timezone': 'Europe/London',
                                   'repeat': {'weekdays': [6], 'start': DAY}})['task_id']
        before = self.tasks.occurrence(self.tasks.show(repeat), '2026-10-18')
        after = self.tasks.occurrence(self.tasks.show(repeat), '2026-10-25')
        self.assertNotEqual(before['id'], after['id'])
