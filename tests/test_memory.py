"""Secretary memory: the note's revision-checked store, its chat marker, chat preparation, briefings and the About me page."""
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from support import TEMP_ROOT, offline_provider_reads
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.briefings import briefing_guides
from goodmorning.briefings.briefing_job import act
from goodmorning.briefings.briefing_preflight import answer, initialize as preflight
from goodmorning.records import memory, workflow
from goodmorning.records.inbox_store import InboxStore, initialize, stamp
from goodmorning.records.task_store import TaskStore
from goodmorning.runtime_files import runtime_lock
from goodmorning.web import about_me
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web.chat_actions import read_changes
from test_letters import records

DAY = '2026-10-26'
MOCHI = {'life': 'You have a dog, Mochi.'}


def runtime(test, profile='city: "London, GB"\ntimezone: "Europe/London"\nnews_country: "GB"\nsecretary_language: "English"\n'):
    temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
    test.addCleanup(temp.cleanup)
    root = Path(temp.name)
    (root / 'profile.md').write_text(profile)
    return root


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.root = runtime(self)

    def test_writes_rewrite_only_the_parts_sent_and_are_revision_checked(self):
        self.assertEqual(memory.change(self.root, 0, note=MOCHI), {'saved': True, 'revision': 1})
        with self.assertRaisesRegex(ValueError, 'revision_conflict'):
            memory.change(self.root, 0, note={'lately': 'Night shifts all week.'})
        memory.change(self.root, 1, note={'lately': ' Night shifts all week.\nTired of them. '})
        self.assertEqual(memory.context(self.root)['note'],
                         {'life': 'You have a dog, Mochi.', 'likes': '', 'lately': 'Night shifts all week.\nTired of them.'})
        self.assertEqual(memory.change(self.root, 2, note=MOCHI), {'saved': False, 'revision': 2}, 'an unchanged note is not a change')
        for note in ({}, {'mood': 'Seems tired.'}, {'life': 3}, {'life': 'Tab\there'}, ['life']):
            with self.subTest(note), self.assertRaisesRegex(ValueError, 'invalid_input'):
                memory.change(self.root, 2, note=note)
        with self.assertRaisesRegex(ValueError, 'memory_too_long'):
            memory.change(self.root, 2, note={'likes': 'x' * (memory.LENGTH - 30)})
        memory.change(self.root, 2, note=dict.fromkeys(memory.PARTS, ''))
        self.assertNotIn('Mochi', memory.path(self.root).read_text(), 'forgetting deletes the text')

    def test_projects_are_entries_named_like_their_to_dos(self):
        memory.path(self.root).write_text(json.dumps({'changes': [], 'enabled': True, 'note': {**dict.fromkeys(memory.PARTS, ''), **MOCHI},
                                                      'revision': 4}))
        self.assertEqual(memory.context(self.root)['projects'], [], 'a note saved before projects keeps none')
        memory.change(self.root, 4, note={'projects': {' Atlas ': 'Your comparison study; the methods come next.', 'Boreal': ''}})
        memory.change(self.root, 5, note={'projects': {'ATLAS': 'The methods are written; the figure comes next.'}})
        self.assertEqual([(entry['name'], entry['note']) for entry in memory.context(self.root)['projects']],
                         [('Atlas', 'The methods are written; the figure comes next.'), ('Boreal', '')])
        self.assertEqual(memory.change(self.root, 6, note={'projects': {'Boreal': None}})['revision'], 7)
        self.assertEqual([entry['name'] for entry in memory.load(self.root)['projects']], ['Atlas'])
        with self.assertRaisesRegex(ValueError, 'project_too_long'):
            memory.change(self.root, 7, note={'projects': {'Atlas': 'x' * (memory.PROJECT + 1)}})
        full = {f'P{n}': '' for n in range(memory.PROJECTS - 1)}
        memory.change(self.root, 7, note={'projects': full})
        with self.assertRaisesRegex(ValueError, 'memory_projects_full'):
            memory.change(self.root, 8, note={'projects': {'Ninth': ''}})
        memory.change(self.root, 8, note={'projects': {'Ninth': '', 'P0': None}})  # A finished project makes room.
        with self.assertRaisesRegex(ValueError, 'memory_too_long'):
            memory.change(self.root, 9, note={'life': 'x' * 3000, 'projects': {'P1': 'y' * 500, 'P2': 'z' * 500}})
        for note in ({'projects': {}}, {'projects': ['Atlas']}, {'projects': {'Two\nlines': ''}}, {'projects': {'Atlas': 3}},
                     {'projects': {'Atlas': '', 'atlas': ''}}):
            with self.subTest(note), self.assertRaisesRegex(ValueError, 'invalid_input'):
                memory.change(self.root, 9, note=note)

    def test_the_first_to_do_with_a_label_starts_its_project_and_a_rename_moves_both(self):
        initialize(self.root)
        def store():
            inbox = InboxStore(self.root, write=True)
            self.addCleanup(inbox.close)
            return inbox
        def add(raw, project, key):
            store().mutate('add', {'kind': 'todo', 'raw': raw, 'project': project}, 'ses_a', key, stamp(self.root))
        add('Draft the methods', 'Atlas', 'k1')
        memory.change(self.root, 1, note={'projects': {'Atlas': 'Your comparison study.'}})
        add('Make the figure', 'atlas', 'k2')
        add('Buy milk', '', 'k3')
        self.assertEqual([(entry['name'], entry['note']) for entry in memory.load(self.root)['projects']], [('Atlas', 'Your comparison study.')])
        memory.change(self.root, 2, note={'projects': {'Atlas': None}})
        add('Check the baselines', 'Atlas', 'k4')
        self.assertEqual(memory.load(self.root)['projects'], [], 'forgetting a project keeps its label on to-dos but does not restart it')
        add('Book the van', 'Boreal', 'k5')
        self.assertEqual([entry['name'] for entry in memory.load(self.root)['projects']], ['Boreal'])
        tasks = TaskStore(store())
        receipt = tasks.rename_project({'from': 'boreal', 'to': 'Northern station'}, 'ses_a', 'k6', stamp(self.root))
        self.assertEqual(receipt, {'saved': True, 'project': 'Northern station', 'tasks': 1})
        self.assertEqual({task['title']: task['project'] for task in tasks.all()}['Book the van'], 'Northern station')
        self.assertTrue(tasks.rename_project({'from': 'boreal', 'to': 'Northern station'}, 'ses_a', 'k6', stamp(self.root))['replayed'])
        self.assertEqual([entry['name'] for entry in memory.load(self.root)['projects']], ['Northern station'])
        memory.change(self.root, memory.load(self.root)['revision'], enabled=False)
        add('Ship the figure', 'Comet', 'k7')
        self.assertEqual(len(memory.load(self.root)['projects']), 1, 'nothing is written while memory is off')

    def test_a_rename_moves_only_an_existing_entry_after_the_to_dos_and_keeps_their_dates(self):
        initialize(self.root)
        inbox = InboxStore(self.root, write=True)
        self.addCleanup(inbox.close)
        for key, project in (('k1', 'Atlas'), ('k2', 'Boreal')):
            inbox.mutate('add', {'kind': 'todo', 'raw': 'Step', 'project': project}, 'ses_a', key, '2026-10-01T09:00:00+00:00')
        tasks = TaskStore(inbox)
        memory.change(self.root, 2, note={'projects': {'Atlas': None}})
        tasks.rename_project({'from': 'Atlas', 'to': 'Atlas Paper'}, 'ses_a', 'k3', stamp(self.root))
        self.assertEqual([entry['name'] for entry in memory.load(self.root)['projects']], ['Boreal'],
                         'a rename never brings back a forgotten project')
        self.assertEqual({task['project']: task['updated_at'] for task in tasks.all()},
                         {'Atlas Paper': '2026-10-01T09:00:00+00:00', 'Boreal': '2026-10-01T09:00:00+00:00'},
                         'a rename is not activity, so tidy and stale checks keep their dates')
        memory.change(self.root, memory.load(self.root)['revision'], enabled=False)
        tasks.rename_project({'from': 'Boreal', 'to': 'Northern station'}, 'ses_a', 'k4', stamp(self.root))
        self.assertEqual([entry['name'] for entry in memory.load(self.root)['projects']], ['Northern station'],
                         "the user's entry follows its to-dos while memory is off")
        memory.change(self.root, memory.load(self.root)['revision'], enabled=True)
        memory.change(self.root, memory.load(self.root)['revision'], note={'projects': {'Comet': 'A survey.'}})
        with self.assertRaisesRegex(ValueError, 'project_exists: .*ask the user'):
            tasks.rename_project({'from': 'Northern station', 'to': 'comet'}, 'ses_a', 'k5', stamp(self.root))
        self.assertEqual({task['project'] for task in tasks.all()}, {'Atlas Paper', 'Northern station'}, 'nothing was renamed')

    def test_a_busy_memory_lock_still_starts_the_project(self):
        initialize(self.root)
        inbox = InboxStore(self.root, write=True)
        self.addCleanup(inbox.close)
        held, release = threading.Event(), threading.Event()
        def hold():
            with runtime_lock(self.root, 'memory.lock'):
                held.set(); release.wait(5)
        thread = threading.Thread(target=hold); thread.start()
        held.wait(5)
        threading.Timer(0.3, release.set).start()
        inbox.mutate('add', {'kind': 'todo', 'raw': 'Step', 'project': 'Atlas'}, 'ses_a', 'k1', stamp(self.root))
        thread.join()
        self.assertEqual([entry['name'] for entry in memory.load(self.root)['projects']], ['Atlas'])

    def test_off_hides_the_note_and_refuses_writes(self):
        memory.change(self.root, 0, note=MOCHI)
        memory.change(self.root, 1, enabled=False)
        self.assertEqual(memory.context(self.root), {'enabled': False, 'revision': 2})
        with self.assertRaisesRegex(ValueError, 'memory_off'):
            memory.change(self.root, 2, note={'life': 'You have a cat.'})

    def test_only_the_writing_chat_shows_that_memory_changed(self):
        memory.change(self.root, 0, note=MOCHI, session='ses_a')
        memory.change(self.root, 1, note={'likes': 'Short replies.'})  # The About me page has no session.
        changes, unavailable = read_changes(self.root, 'ses_a')
        self.assertFalse(unavailable)
        self.assertEqual([(entry['text'], entry['action']) for entry in changes], [('', {'operation': 'updated', 'target': 'memory'})])
        self.assertEqual(read_changes(self.root, 'ses_b'), ([], False))

    def test_setup_chats_write_no_memory_and_chinese_chats_write_chinese(self):
        (self.root / 'browser-chats').mkdir()
        chats = {'a': {'mode': 'initialize', 'session': 'ses_a', 'turns': [{'language': 'en'}]},
                 'b': {'mode': 'secretary', 'session': 'ses_b', 'turns': [{'language': 'zh-CN'}]}}
        (self.root / 'browser-chats' / 'chats.json').write_text(json.dumps(chats))
        with self.assertRaisesRegex(ValueError, 'memory_setup'):
            memory.change(self.root, 0, note=MOCHI, session='ses_a')
        with self.assertRaisesRegex(ValueError, 'memory_language'):
            memory.change(self.root, 0, note=MOCHI, session='ses_b')
        self.assertTrue(memory.change(self.root, 0, note={'life': '你养了一只狗，叫 Mochi。'}, session='ses_b')['saved'])
        self.assertTrue(memory.change(self.root, 1, note=MOCHI)['saved'])  # The About me page keeps the user's own words.
        self.assertEqual(memory.load(self.root)['revision'], 2)

    def test_secretary_preparation_carries_the_note(self):
        memory.change(self.root, 0, note=MOCHI)
        prepared = workflow.prepare(self.root, 'secretary', today=DAY)['memory']
        self.assertEqual((prepared['revision'], prepared['note']['life']), (1, 'You have a dog, Mochi.'))
        self.assertNotIn('memory', workflow.prepare(self.root, 'todo', today=DAY))

    def test_the_tidy_rereads_only_new_user_messages(self):
        now = time.time()
        chats = {'a': {'mode': 'secretary', 'created': now - 7200, 'turns': [
                     {'id': 'a', 'text': 'Mochi chewed my shoes'}, {'id': 't2', 'text': 'x' * 900, 'created': now - 3600},
                     {'id': 't5', 'text': 'Held before consent', 'local': True, 'created': now - 60}]},
                 'b': {'mode': 'secretary', 'created': now - 3 * 86400, 'turns': [{'id': 'b', 'text': 'Old news'}, {'id': 't3', 'text': '', 'created': now - 60}]},
                 'c': {'mode': 'initialize', 'created': now - 60, 'turns': [{'id': 'c', 'text': 'I live in Edinburgh'}]}}
        (self.root / 'browser-chats').mkdir()
        (self.root / 'browser-chats' / 'chats.json').write_text(json.dumps(chats))
        found = memory.tidy(self.root)
        self.assertEqual([entry['text'] for entry in found], ['Mochi chewed my shoes', 'x' * memory.MESSAGE])
        self.assertEqual(memory.tidy(self.root), [], 'each message is reread once')
        chats['b']['turns'].append({'id': 't4', 'text': 'Starting a pottery class', 'created': time.time()})
        (self.root / 'browser-chats' / 'chats.json').write_text(json.dumps(chats))
        self.assertEqual([entry['text'] for entry in memory.tidy(self.root)], ['Starting a pottery class'])
        self.assertEqual(memory.load(self.root)['revision'], 0, 'marking a tidy is not a change to the note')


    def test_the_tidy_reads_two_weeks_of_check_ins_and_records_as_dated_lines(self):
        root = runtime(self, 'timezone: Asia/Shanghai\n')
        records(root)
        (root / 'daily').mkdir()
        (root / 'daily' / '2026-10-25.md').write_text('# 2026-10-25\n\n## feedback\n- Other updates: Long run with Mia\n')
        lines = memory.activity(root, DAY)
        for line in ('Tue 2026-10-13 habit done: Stretching', 'Wed 2026-10-14 to-do done: Water the plants',
                     'Mon 2026-10-19 to-do done: Water the plants', 'Wed 2026-10-21 10:00 idea saved: Try a weekly review with Mia',
                     'Thu 2026-10-22 10:00 to-do done: Renew passport photo [project: Home]', 'Sun 2026-10-25 check-in: Other updates: Long run with Mia'):
            self.assertIn(line, lines)
        self.assertEqual(lines, sorted(lines, key=lambda line: line.split()[1]), 'oldest first')
        self.assertFalse([line for line in lines if '2026-10-06' in line or '2026-10-12' in line], 'only the last 14 days')
        self.assertEqual(sum('Draft chapter 2 outline' in line for line in lines), 1, "a day's Done is listed once")
        self.assertEqual(memory.activity(runtime(self), DAY), [], 'an account with no records yet')


class BriefingMemoryTests(unittest.TestCase):
    def setUp(self):
        self.root = runtime(self, 'city: Shanghai, CN\ntimezone: Asia/Shanghai\nnews_country: CN\nsecretary_language: English\n')
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)
        offline_provider_reads(self)
        (self.root / 'daily').mkdir()
        self.app = BrowserApp(self.root, now=lambda: datetime(2026, 10, 26, 13, tzinfo=timezone.utc), preflight=True)

    def start(self, version=2):
        if version == 2:
            initialize(self.root)  # Without the version 2 store, the job takes a free plan.
        self.job = {'id': 'c' * 32, 'date': DAY, 'kind': 'gn', 'state': 'preflight', 'session': 'ses_test'}
        self.app.jobs[DAY + '.gn'] = self.job; self.app.save_jobs()
        fields = preflight(self.root, self.job)['form']['fields']
        answer(self.root, self.job, {field['key']: {'completed': ['none'], 'details': 'No updates today'}.get(field['key'], [])
                                     for field in fields})
        self.job['state'] = 'running'; self.app.jobs[DAY + '.gn'] = self.job; self.app.save_jobs()

    def step(self, action, payload=None):
        return act(self.root, self.job['id'], 'ses_test', action, payload)

    def test_only_the_greeting_closing_and_letter_see_the_note(self):
        self.start()
        self.assertNotIn('memory', self.step('prepare')['next'], 'an empty note adds nothing')
        memory.change(self.root, 0, note={'lately': 'Training for the Shanghai marathon in March.'})
        init = self.step('prepare')['next']
        self.assertEqual(init['action'], 'init')
        self.assertNotIn('memory', init, 'the evening greeting is written at finish')
        evening = briefing_guides.guide({'date': DAY, 'workflow': 'gn'}, {'action': 'finish', 'memory': MOCHI},
                                        [], runtime=self.root, job='c' * 32, session='ses_test')
        self.assertIn('only when the note dates it today or tomorrow (today is ' + DAY, evening)  # Not the same item every day (#227).
        for language, cap, outside in (('en', 'at most 60 characters', 'It never goes in the headline'), ('zh-CN', '不超过 30 个字', '标题里不要用它')):
            morning = briefing_guides.guide({'date': DAY, 'workflow': 'gm', 'website_language': language}, {'action': 'finish', 'memory': MOCHI},
                                            [], runtime=self.root, job='c' * 32, session='ses_test')
            self.assertIn(cap, morning)
            self.assertIn(outside, morning)
        section = self.step('init', {})['next']
        self.assertNotIn('memory', section)
        self.assertNotIn('`memory`', section['guide'])
        letter = briefing_guides.guide({'date': DAY, 'workflow': 'gn'}, {'action': 'publish', 'section': ['letter'], 'memory': MOCHI},
                                       [], runtime=self.root, job='c' * 32, session='ses_test')
        self.assertIn('The sign-off\'s wish may lightly reflect one thing', letter)
        memory.change(self.root, 1, enabled=False)
        self.assertNotIn('memory', self.step('prepare')['next'], 'memory turned off leaves briefings without it')

    def test_the_evening_save_hands_over_the_note_and_new_messages_to_tidy(self):
        self.start(version=1)
        memory.change(self.root, 0, note=MOCHI)
        (self.root / 'browser-chats' / 'chats.json').write_text(json.dumps(
            {'a': {'mode': 'secretary', 'created': time.time() - 60, 'turns': [{'id': 'a', 'text': 'Night shifts all week, ugh'}]}}))
        self.step('init', {'greeting': 'Evening.', 'opening': 'Tonight’s review.', 'plan': [['must-do', 'Project steps']]})
        self.step('publish', {'position': 0, 'section': ['must-do', [['p', 'Nothing open.']]]})
        saved = self.step('finish', {})
        self.assertEqual((saved['memory']['revision'], saved['memory']['note']['life']), (1, 'You have a dog, Mochi.'))
        self.assertEqual([entry['text'] for entry in saved['memory']['messages']], ['Night shifts all week, ugh'])
        self.assertTrue([line for line in saved['memory']['activity'] if line.startswith('Mon 2026-10-26 check-in: ')],
                        "tonight's saved check-in is part of the activity")
        self.assertIn('patterns, meaning the same kind of thing on at least two different days', saved['next'])
        self.assertTrue(saved['next'].startswith('Before the handoff, tidy your memory'))
        self.assertIn('something coming up keeps its calendar date', saved['next'])
        self.assertIn('Hand over the relative link', saved['next'])


class AboutMeMemoryTests(unittest.TestCase):
    def setUp(self):
        self.root = runtime(self)
        self.app = BrowserApp(self.root)
        memory.change(self.root, 0, note={**MOCHI, 'lately': 'Training for a marathon.'})

    def save(self, field, value):
        return about_me.save(self.app, {'field': field, 'value': value})

    def test_the_page_shows_the_note_part_by_part(self):
        page = about_me.page(self.app).decode()
        section = page[page.index('id="about-memory"'):page.index('id="about-news"')]
        self.assertLess(section.index('You have a dog, Mochi.'), section.index('Training for a marathon.'))
        self.assertIn('What I remember about you', section)
        self.assertIn('has learned from your chats, check-ins and plans', section)
        self.assertNotIn('Forget everything', section)
        self.assertIn('data-switch="memory"', section)
        self.assertEqual(section.count('data-multiline'), 3)

    def test_edit_forget_and_switch_off_from_the_page(self):
        self.assertEqual(self.save('memory:life', ' You have two dogs.\nBoth are loud. '),
                         {'field': 'memory:life', 'value': 'You have two dogs.\nBoth are loud.', 'revision': 2})
        self.assertEqual(self.save('memory:lately', '')['value'], '')
        with self.assertRaisesRegex(about_me.Invalid, 'Shorten it'):
            self.save('memory:likes', 'x' * memory.LENGTH)
        with self.assertRaises(ValueError):
            self.save('memory:mood', 'Tired.')
        self.save('memory', 'false')
        self.assertFalse(memory.load(self.root)['enabled'])
        with self.assertRaisesRegex(about_me.Invalid, 'Turn memory on'):
            self.save('memory:life', 'You have a cat.')
        self.save('memory', 'true')
        for part in memory.PARTS:
            self.save('memory:' + part, '')
        self.assertFalse(any(memory.load(self.root)['note'].values()))
        with self.assertRaisesRegex(ValueError, 'Invalid change'):
            self.save('forget', 'all')

    def test_projects_show_as_entries_that_are_edited_or_forgotten_one_by_one(self):
        initialize(self.root)
        inbox = InboxStore(self.root, write=True)
        self.addCleanup(inbox.close)
        for key, project in (('k1', 'Atlas'), ('k2', 'atlas'), ('k3', 'Boreal')):
            inbox.mutate('add', {'kind': 'todo', 'raw': 'Step', 'project': project}, 'ses_a', key, stamp(self.root))
        memory.change(self.root, 3, note={'projects': {'Atlas': 'Your comparison study.'}})
        page = html.unescape(about_me.page(self.app).decode())
        section = page[page.index('id="about-memory"'):page.index('id="about-news"')]
        self.assertIn('data-revision="4"', section)
        self.assertLess(section.index('Training for a marathon.'), section.index('Project: Atlas'))
        self.assertLess(section.index('Project: Atlas'), section.index('Project: Boreal'))
        self.assertLess(section.index('Project: Boreal'), section.index('New project'))
        self.assertIn('2 open to-dos', section)
        self.assertIn('Tell your secretary about it, or save a to-do for it.', section)
        self.assertEqual(section.count('class="about-forget"'), 2)
        work = page[page.index('id="about-work"'):page.index('id="about-memory"')]
        self.assertIn('Project areas', work)
        self.assertNotIn('Linked projects', page)
        with self.assertRaisesRegex(about_me.Invalid, 'just changed this'):
            about_me.save(self.app, {'field': 'project:Atlas', 'value': 'Old tab.', 'revision': 3})
        with self.assertRaisesRegex(about_me.Invalid, 'just changed this'):
            about_me.save(self.app, {'field': 'project:Gone', 'value': 'Old tab.', 'revision': 3})
        self.assertEqual(about_me.save(self.app, {'field': 'project:atlas', 'value': ' The figure is next. ', 'revision': 4}),
                         {'field': 'project:atlas', 'value': 'The figure is next.', 'revision': 5})
        with self.assertRaisesRegex(about_me.Invalid, 'A project fits 500'):
            self.save('project:Atlas', 'x' * 501)
        with self.assertRaisesRegex(ValueError, 'only be changed in chat'):
            self.save('project:Comet', 'A new project.')
        self.save('forget', 'project:Boreal')
        self.assertEqual([entry['name'] for entry in memory.load(self.root)['projects']], ['Atlas'])
        self.assertEqual(len(list(TaskStore(inbox).all())), 3, 'forgetting keeps the to-dos')


if __name__ == '__main__':
    unittest.main()
