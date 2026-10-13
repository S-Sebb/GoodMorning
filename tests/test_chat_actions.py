"""Confirmed change cards use read-only, bounded, session-owned audit projections."""
from datetime import datetime
import json
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
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.web.chat_actions import read_changes, action_history, LIMIT
from goodmorning.web.briefing_chat import Chats
from test_briefing_chat import MockChamber, ImmediateThread

NOW = '2026-10-13T12:00:00+01:00'
SESSION = 'ses_chat_0'


class ActionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)
        initialize(self.root)
        self.inbox = InboxStore(self.root, write=True)
        self.addCleanup(self.inbox.close)
        self.calendar = CalendarStore(str(self.root / 'calendar.sqlite'))
        self.addCleanup(self.calendar.close)

    def capture(self, key='capture', session=SESSION, **extra):
        return self.inbox.mutate('add', {'kind': 'todo', 'raw': 'Prepare the slides', **extra}, session, key, NOW)

    def test_capture_update_cancel_and_completion_have_distinct_receipts(self):
        receipt = self.capture(task={'title': 'Prepare slides'})
        tasks = TaskStore(self.inbox)
        tasks.mutate(receipt['task_id'], 1, {'title': 'Prepare final slides'}, SESSION, 'edit', NOW)
        tasks.mutate(receipt['task_id'], 2, {'status': 'cancelled'}, SESSION, 'cancel', NOW)
        done = self.capture('other', task={'title': 'Buy tea'})
        tasks.mutate(done['task_id'], 1, {'status': 'done', 'confirmed_completion': True}, SESSION, 'done', NOW)
        changes, unavailable = read_changes(self.root, SESSION)
        self.assertFalse(unavailable)
        self.assertEqual([entry['action']['operation'] for entry in changes], ['added', 'added', 'updated', 'cancelled', 'completed'])
        self.assertEqual(changes[0]['text'], 'Prepare slides')  # Original title, not mutable current state.
        self.assertEqual(changes[2]['text'], 'Prepare final slides')

    def test_calendar_operations_and_conversion_are_not_duplicated(self):
        event = {'subject': 'Tea with Sam', 'start': '2026-10-14T14:00:00+01:00', 'end': '2026-10-14T15:00:00+01:00'}
        identifier = self.calendar.add(event, actor=SESSION)
        self.calendar.change(identifier, 'update', 1, {'subject': 'Tea with Alex'}, SESSION)
        self.calendar.change(identifier, 'cancel', 2, actor=SESSION)
        draft = self.inbox.mutate('add', {'kind': 'event_proposal', 'raw': 'Plan lunch'}, SESSION, 'draft', NOW)
        TaskStore(self.inbox).convert(self.root, draft['draft_id'], 1, {'event': {**event, 'subject': 'Lunch'}}, SESSION, 'convert', NOW)
        changes, unavailable = read_changes(self.root, SESSION)
        self.assertFalse(unavailable)
        events = [entry for entry in changes if entry['action']['target'] == 'event']
        self.assertEqual([entry['action']['operation'] for entry in events], ['added', 'updated', 'cancelled', 'added'])
        self.assertEqual([entry['text'] for entry in events], ['Tea with Sam', 'Tea with Alex', 'Tea with Alex', 'Lunch'])

    def test_isolation_retry_failures_and_private_fields(self):
        self.capture('other-session', session='ses_other', context='PRIVATE other account context')
        receipt = self.capture(context='PRIVATE context', task={'title': '<img src=x onerror=alert(1)>'})
        self.capture(context='PRIVATE context', task={'title': '<img src=x onerror=alert(1)>'})
        with self.assertRaises(ValueError):
            TaskStore(self.inbox).mutate(receipt['task_id'], 99, {'title': 'Never saved'}, SESSION, 'failed', NOW)
        self.inbox.db.execute("INSERT INTO task_events(item_id,action,at,session,snapshot,request_key,fingerprint,receipt) VALUES (?,?,?,?,?,?,?,?)",
            ('draft', 'convert-pending', NOW, SESSION, '{}', 'pending', 'x', '{"saved":false}'))
        changes, unavailable = read_changes(self.root, SESSION)
        self.assertFalse(unavailable)
        self.assertEqual(len(changes), 1)
        self.assertNotIn('PRIVATE', json.dumps(changes))
        self.assertNotIn('Never saved', json.dumps(changes))
        self.assertEqual(set(changes[0]), {'id', 'role', 'kind', 'text', 'action', 'at'})

    def test_import_review_cards_describe_the_reviewed_revision(self):
        event = {'external_id': 'lunch', 'subject': 'Team lunch', 'start': '2026-10-14T14:00:00+01:00',
                 'end': '2026-10-14T15:00:00+01:00'}
        self.calendar.stage('work', [event], SESSION)
        identifier = self.calendar.pending()[0]['id']
        self.calendar.change(identifier, 'approve', 1, actor=SESSION)
        self.calendar.stage('work', [{**event, 'subject': 'Moved team lunch'}], SESSION)
        self.calendar.change(identifier, 'reject', 3, actor=SESSION)
        changes, unavailable = read_changes(self.root, SESSION)
        self.assertFalse(unavailable)
        self.assertEqual([(entry['action']['operation'], entry['text']) for entry in changes],
                         [('approved', 'Team lunch'), ('declined', 'Moved team lunch')])

    def test_bounded_titles_and_no_read_side_effects(self):
        for index in range(LIMIT + 5):
            self.capture(str(index), raw='x' * 500)
        before = {path.name: path.read_bytes() for path in self.root.glob('*.sqlite')}
        changes, unavailable = read_changes(self.root, SESSION)
        self.assertFalse(unavailable)
        self.assertEqual(len(changes), LIMIT)
        self.assertTrue(all(len(entry['text']) == 160 for entry in changes))
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.root.glob('*.sqlite')})

    def test_missing_corrupt_and_symlink_stores_preserve_chat(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            self.assertEqual(read_changes(root, SESSION), ([], False))
            self.assertEqual(list(root.iterdir()), [])
            (root / 'inbox.sqlite').write_bytes(b'not a database')
            self.assertEqual(read_changes(root, SESSION), ([], True))
            (root / 'inbox.sqlite').unlink()
            (root / 'inbox.sqlite').symlink_to(self.root / 'inbox.sqlite')
            self.assertEqual(read_changes(root, SESSION), ([], True))

    def test_turn_order_offsets_and_bounded_history(self):
        start = datetime.fromisoformat(NOW).timestamp()
        turns = [{'id': 'one'}, {'id': 'two', 'created': start + 60}]
        changes = [{'id': 'saved-one', 'at': NOW}, {'id': 'saved-two', 'at': '2026-10-13T19:02:00+08:00'}]
        messages = [{'id': 'u1', '_turn': 'one'}, {'id': 'a1'}, {'id': 'u2', '_turn': 'two'}, {'id': 'a2'}]
        result = action_history(messages, changes, turns, start - 10)
        self.assertEqual([entry['id'] for entry in result], ['u1', 'a1', 'saved-one', 'u2', 'a2', 'saved-two'])
        self.assertTrue(all('_turn' not in entry for entry in result))
        self.assertEqual([entry['id'] for entry in action_history(messages[2:], changes, turns, start - 10)], ['u2', 'a2', 'saved-two'])
        legacy = [{'id': 'one'}, {'id': 'two'}]
        self.assertEqual([entry['id'] for entry in action_history(messages, changes, legacy, start - 10)], ['u1', 'a1', 'u2', 'a2'])
        self.assertEqual([entry['id'] for entry in action_history(messages[:2], changes[:1], [{'id': 'one'}], start + .5)],
                         ['u1', 'a1', 'saved-one'])

    def test_real_chat_status_includes_changes_but_queue_status_never_reads_them(self):
        chamber = MockChamber(self.root)
        chats = Chats(self.root, chamber)
        chat = 'a' * 32
        with patch('goodmorning.web.briefing_chat.threading.Thread', ImmediateThread), patch('time.time', return_value=0):
            chats.start({'id': chat, 'mode': 'secretary', 'text': 'Save a task'})
        self.capture()
        status = chats.status(chat)
        self.assertEqual(status['messages'][-1]['kind'], 'action')
        self.assertFalse(status['action_history_unavailable'])
        self.assertEqual(status['state'], 'idle')
        with patch('goodmorning.web.chat_actions.read_changes', side_effect=AssertionError('Queue must not scan audits')):
            self.assertEqual(chats.status(chat, include_messages=False)['state'], 'idle')

    def test_repeated_user_text_keeps_changes_in_distinct_turns(self):
        chamber = MockChamber(self.root)
        chats = Chats(self.root, chamber)
        chat = 'a' * 32
        start = datetime.fromisoformat(NOW).timestamp()
        with patch('goodmorning.web.briefing_chat.threading.Thread', ImmediateThread):
            with patch('time.time', return_value=start - 1):
                chats.start({'id': chat, 'mode': 'secretary', 'text': 'Hello'})
            with patch('time.time', return_value=start + 60):
                chats.send(chat, {'id': 'b' * 32, 'text': 'Yes'})
            self.inbox.mutate('add', {'kind': 'idea', 'raw': 'First yes'}, SESSION, 'yes-one', '2026-10-13T12:01:01+01:00')
            with patch('time.time', return_value=start + 120):
                chats.send(chat, {'id': 'c' * 32, 'text': 'Yes'})
            self.inbox.mutate('add', {'kind': 'idea', 'raw': 'Second yes'}, SESSION, 'yes-two', '2026-10-13T12:02:01+01:00')
        messages = chats.status(chat)['messages']
        self.assertEqual([entry['text'] for entry in messages if entry.get('kind') == 'action'], ['First yes', 'Second yes'])
        first = next(index for index, entry in enumerate(messages) if entry['text'] == 'First yes')
        self.assertEqual(messages[first + 1]['text'], 'Yes')
        # A clipped transcript must not pull the first receipt into the latest turn.
        chamber.sessions[SESSION]['messages'] = chamber.sessions[SESSION]['messages'][-2:]
        self.assertEqual([entry['text'] for entry in chats.status(chat)['messages']],
                         ['Yes', 'Synthetic reply. Your text stays text: <img src=x onerror=alert(1)>', 'Second yes'])


if __name__ == '__main__':
    unittest.main()
