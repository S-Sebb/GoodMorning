"""Briefing reminder lines: written once per saved tone and language, built-in lines meanwhile."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web import briefing_reminders
from goodmorning.web.briefing_reminders import FALLBACK, ReminderLines, Unknown, line, written

LINES = {'gm': ['Morning. Your briefing awaits preparation.', 'Good morning. Open it to prepare today.', 'Morning. Shall we begin?'],
         'gn': ['Evening. Your briefing awaits preparation.', 'Good evening. Open it to review today.', 'Evening. Time to close the day.']}


class Chamber:
    def __init__(self):
        self.busy, self.reply, self.forms, self.prompts, self.agents = True, json.dumps(LINES), [], [], []

    def control(self, action, **body):
        if action == 'session.create':
            return {'sessionId': 'ses_lines'}
        if action == 'session.send':
            self.prompts.append(body['prompt'])
            return {'promptDispatched': True}
        if action == 'session.status':
            return {'sessionStatus': {'type': 'busy' if self.busy else 'idle'}}
        if action == 'session.messages':
            return {'messages': [{'role': 'user', 'text': self.prompts[-1]}, {'role': 'assistant', 'text': self.reply}]}
        raise AssertionError(action)

    def request(self, path, body=None):
        if path.endswith('/agent'):
            self.agents.append(body['agent'])
        return {}

    def pending(self, session):
        return self.forms, []


class ReminderLineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.runtime = Path(temp.name)
        self.profile('dry and formal')
        self.chamber = Chamber()
        self.lines = ReminderLines(self.runtime, self.chamber)

    def profile(self, tone):
        (self.runtime / 'profile.md').write_text('timezone: Europe/London\nsecretary_name: Nora\n' + (f'secretary_tone: {tone}\n' if tone else ''))

    def start(self, identifier):
        result = self.lines.start({'id': identifier})
        for _ in range(100):
            if self.lines.state['attempt']['state'] != 'starting':
                return result
            time.sleep(0.01)
        raise AssertionError('Dispatch did not finish')

    def test_secretary_lines_replace_built_in_ones_until_the_tone_changes(self):
        self.assertEqual(self.lines.current('en'), {'lines': FALLBACK['en'], 'write': True})
        self.assertEqual(self.start('a' * 32), {'lines': 'a' * 32})
        self.assertEqual(self.start('a' * 32), {'lines': 'a' * 32})  # The same request never dispatches twice.
        self.assertEqual(len(self.chamber.prompts), 1)
        self.assertIn('dry and formal', self.chamber.prompts[0])
        self.assertEqual(self.chamber.agents, ['secretary'])
        self.assertFalse(self.lines.current('en')['write'])  # Being written.
        with self.assertRaises(ValueError):
            self.lines.start({'id': 'b' * 32})
        self.assertEqual(self.lines.status('a' * 32), {'state': 'running'})
        self.chamber.busy = False
        self.assertEqual(self.lines.status('a' * 32), {'state': 'ready'})
        self.assertEqual(self.lines.current('en'), {'lines': LINES, 'write': False})
        self.assertEqual(ReminderLines(self.runtime, self.chamber).current('en')['lines'], LINES)  # Kept across restarts.
        # Another website language or tone needs its own lines; built-in ones remind meanwhile.
        self.assertEqual(self.lines.current('zh-CN'), {'lines': FALLBACK['zh-CN'], 'write': True})
        self.profile('playful')
        self.assertEqual(self.lines.current('en'), {'lines': FALLBACK['en'], 'write': True})

    def test_an_unusable_reply_keeps_built_in_lines_and_waits_before_asking_again(self):
        self.chamber.busy, self.chamber.reply = False, 'Here you go: Morning! Evening!'
        self.start('a' * 32)
        self.assertEqual(self.lines.status('a' * 32), {'state': 'stopped'})
        self.assertEqual(self.lines.current('en'), {'lines': FALLBACK['en'], 'write': False})
        later = time.time() + briefing_reminders.RETRY + 1
        with patch('goodmorning.web.briefing_reminders.time.time', lambda: later):
            self.assertTrue(self.lines.current('en')['write'])
        self.profile('')  # A changed tone may ask at once.
        self.assertTrue(self.lines.current('en')['write'])

    def test_a_question_instead_of_lines_is_left_unanswered(self):
        self.chamber.forms = [{'id': 'form_1'}]
        self.start('a' * 32)
        self.assertEqual(self.lines.status('a' * 32), {'state': 'stopped'})
        self.assertEqual(self.lines.current('en')['lines'], FALLBACK['en'])

    def test_unknown_and_interrupted_requests(self):
        with self.assertRaises(Unknown):
            self.lines.status('c' * 32)
        for bad in ({'id': 'short'}, {'id': 'a' * 32, 'extra': 1}, {}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.lines.start(bad)
        self.lines.state['attempt'] = {'id': 'a' * 32, 'wording': self.lines.wording('en'), 'state': 'starting', 'created': time.time()}
        self.lines.save()
        restarted = ReminderLines(self.runtime, self.chamber)
        self.assertEqual(restarted.status('a' * 32), {'state': 'stopped'})  # Never replayed.
        self.assertFalse(restarted.current('en')['write'])
        self.assertFalse(ReminderLines(self.runtime, None).current('zh-CN')['write'])  # No secretary connected.

    def test_only_the_requested_json_becomes_lines(self):
        self.assertEqual(written('```json\n' + json.dumps(LINES) + '\n```', 'en'), LINES)
        self.assertEqual(written(json.dumps({key: ['  ' + item.replace(' ', '\n ') for item in value] for key, value in LINES.items()}), 'en'), LINES)
        for bad in ({'gm': LINES['gm']}, {**LINES, 'gn': LINES['gn'][:2]}, {**LINES, 'gm': ['**Bold**'] + LINES['gm'][1:]},
                    {**LINES, 'gm': ['x' * 101] + LINES['gm'][1:]}, {**LINES, 'gm': [''] + LINES['gm'][1:]}, {**LINES, 'gn': [1, 2, 3]}):
            with self.subTest(bad=bad):
                self.assertIsNone(written(json.dumps(bad), 'en'))
        self.assertIsNone(written('早上好 ' + json.dumps(LINES), 'en'))
        self.assertIsNone(written(json.dumps({**LINES, 'gm': ['早' * 41] + LINES['gm'][1:]}), 'zh-CN'))

    def test_the_backend_reports_todays_editions_with_the_lines(self):
        from datetime import datetime, timezone
        from goodmorning.web.briefing_server import BrowserApp
        app = BrowserApp(self.runtime, self.chamber, now=lambda: datetime(2026, 10, 26, 9, tzinfo=timezone.utc))
        state = app.reminder_state()
        self.assertEqual(state, {'date': '2026-10-26', 'timezone': 'Europe/London', 'editions': {'gm': 'missing', 'gn': 'missing'},
                                 'lines': FALLBACK['en'], 'write': True})
        app.source('2026-10-26', 'gm').parent.mkdir(parents=True, exist_ok=True)
        app.source('2026-10-26', 'gm').write_text('{}')
        self.assertEqual(app.reminder_state()['editions'], {'gm': 'ready', 'gn': 'missing'})

    def test_consecutive_days_use_different_lines(self):
        days = {line(LINES, 'gm', day) for day in ('2026-10-26', '2026-10-27', '2026-10-28')}
        self.assertEqual(days, set(LINES['gm']))


if __name__ == '__main__':
    unittest.main()
