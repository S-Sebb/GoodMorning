"""Secretary memory: the note's revision-checked store, its chat marker, chat preparation, briefings and the About me page."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from support import TEMP_ROOT, offline_provider_reads
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.briefings import briefing_guides
from goodmorning.briefings.briefing_job import act
from goodmorning.briefings.briefing_preflight import answer, initialize as preflight
from goodmorning.records import memory, workflow
from goodmorning.records.inbox_store import initialize
from goodmorning.web import about_me
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web.chat_actions import read_changes

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
        greeting = self.step('prepare')['next']
        self.assertEqual((greeting['action'], greeting['memory']), ('init', {'lately': 'Training for the Shanghai marathon in March.'}))
        self.assertIn('`memory`', greeting['guide'])
        section = self.step('init', {'greeting': 'Evening.', 'opening': 'Tonight’s review.'})['next']
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
        self.assertTrue(saved['next'].startswith('Before the handoff, tidy your memory'))
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
        self.assertIn('Last updated', section)
        self.assertIn('data-switch="memory"', section)
        self.assertEqual(section.count('data-multiline'), 3)

    def test_edit_forget_and_switch_off_from_the_page(self):
        self.assertEqual(self.save('memory:life', ' You have two dogs.\nBoth are loud. '),
                         {'field': 'memory:life', 'value': 'You have two dogs.\nBoth are loud.'})
        self.assertEqual(self.save('memory:lately', ''), {'field': 'memory:lately', 'value': ''})
        with self.assertRaisesRegex(about_me.Invalid, 'Shorten it'):
            self.save('memory:likes', 'x' * memory.LENGTH)
        with self.assertRaises(ValueError):
            self.save('memory:mood', 'Tired.')
        self.save('memory', 'false')
        self.assertFalse(memory.load(self.root)['enabled'])
        with self.assertRaisesRegex(about_me.Invalid, 'Turn memory on'):
            self.save('memory:life', 'You have a cat.')
        self.save('memory', 'true')
        self.save('forget', 'all')
        self.assertFalse(any(memory.load(self.root)['note'].values()))
        self.assertIn('Nothing yet. Chat with your secretary', about_me.page(self.app).decode())


if __name__ == '__main__':
    unittest.main()
