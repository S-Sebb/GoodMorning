"""Synthetic, account-local website conversations. No real model or integrations."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web.briefing_chat import Chats, MODES
from goodmorning.web.briefing_server import BrowserApp, Chamber, serve_live
from urllib.parse import urlsplit, parse_qs


class MockChamber(Chamber):
    def __init__(self, runtime):
        self.runtime = runtime
        self.directory = str(runtime)
        self.sessions = {}
        self.calls = []
        self.replies = []
        self.fail = False

    def control(self, action, **body):
        self.calls.append((action, body))
        if action == 'session.create':
            session = 'ses_chat_' + str(len(self.sessions))
            self.sessions[session] = {'messages': [], 'forms': [], 'permissions': []}
            return {'sessionId': session}
        session = self.sessions[body['sessionId']]
        if action == 'session.send':
            if self.fail:
                raise OSError('Synthetic dispatch interruption')
            self.add(session, 'user', body['prompt'])
            if body['prompt'].startswith('/initialize'):
                self.add(session, 'assistant', 'Confirm your location; replies follow the website language.')
                session['forms'] = [{'id': 'form_city', 'title': 'Confirm your location', 'fields': [
                    {'key': 'city', 'title': 'City', 'type': 'string', 'required': True,
                     'options': [{'value': 'London', 'label': 'London'}], 'custom': True}]}]
            else:
                self.add(session, 'assistant', 'Synthetic reply. Your text stays text: <img src=x onerror=alert(1)>')
            return {'promptDispatched': True}
        if action == 'session.messages':
            return super().control(action, **body)
        raise ValueError('Unexpected control action')

    def add(self, session, role, text):
        session['messages'].append({'id': 'message_' + str(len(session['messages'])), 'role': role, 'text': text})

    def pending(self, session):
        entry = self.sessions[session]
        return entry['forms'], entry['permissions']

    def request(self, path, body=None):
        if path == '/api/openchamber/control':
            session = self.sessions[body['input']['sessionId']]
            return {'sessionStatus': {'type': 'busy' if session['forms'] or session['permissions'] else 'idle'}}
        if path.endswith('/model'):
            session = self.sessions[path.split('/')[3]]
            session['model'] = body['model']
            return {}
        if body is None:
            parsed = urlsplit(path);query = parse_qs(parsed.query)
            limit = int(query['limit'][0])
            if limit > 200:raise ValueError('Expected a value less than or equal to 200')
            session = self.sessions[parsed.path.split('/')[3]]
            offset = int(query.get('cursor', ['0'])[0])
            rows = list(reversed(session['messages']))[offset:offset+limit]
            return {'data': [{'id': row['id'], 'type': row['role'], **({'text': row['text']} if row['role']=='user'
                    else {'content':[{'type':'text','text':row['text']}]})} for row in rows],
                    'cursor': {'next': str(offset+limit) if len(session['messages'])>offset+limit else None}}
        self.replies.append((path, body))
        session_id = path.split('/')[3]
        session = self.sessions[session_id]
        if '/form/' in path:
            session['forms'] = []
            session['permissions'] = [{'id': 'permission_setup', 'action': 'Save confirmed synthetic profile', 'resources': ['Synthetic profile only']}]
        else:
            session['permissions'] = []
            if body['decision'] == 'once':
                (self.runtime / 'profile.md').write_text('city: London\ntimezone: Europe/London\nnews_country: GB\n')
                self.add(session, 'assistant', 'Synthetic setup saved. Provider verification was not performed.')
            else:
                self.add(session, 'assistant', 'Nothing saved.')
        return {}


class ImmediateThread:
    def __init__(self, target, args, **_):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.chamber = MockChamber(self.root)
        self.chats = Chats(self.root, self.chamber)
        patcher = patch('goodmorning.web.briefing_chat.threading.Thread', ImmediateThread)
        patcher.start(); self.addCleanup(patcher.stop)
        self.id = 'a' * 32

    def start(self, mode='secretary', text='Hello', chat=None):
        return self.chats.start({'id': chat or self.id, 'mode': mode, 'text': text})

    def test_modes_are_fixed_and_commands_are_not_accepted(self):
        self.assertEqual(set(MODES), {'initialize', 'secretary', 'todo', 'eureka'})
        for mode in ('gm', 'gn', 'shell'):
            with self.assertRaises(ValueError): self.start(mode)
        for text in ('/gm', ' /secretary other', 'x' * 8001):
            with self.assertRaises(ValueError): self.start(text=text)
        for mode in ('todo', 'eureka'):
            with self.assertRaises(ValueError): self.start(mode, '')
        self.assertEqual(self.chamber.calls, [])

    def test_new_profile_opens_setup_without_inventing_timezone(self):
        app = BrowserApp(self.root, self.chamber)
        self.assertEqual(app.chat_settings()['defaultMode'], 'initialize')
        self.assertIn(b'role="radiogroup"', app.chat_page())
        self.assertFalse((self.root / 'profile.md').exists())
        with self.assertRaises(ValueError): app.today()
        self.start('initialize', '')
        status = self.chats.status(self.id)
        self.assertEqual(status['state'], 'waiting')
        self.assertEqual(status['forms'][0]['id'], 'form_city')
        self.assertEqual(status['messages'][0]['text'], 'Start initialize')
        self.assertNotIn(str(self.root), json.dumps(status['messages']))

    def test_secretary_name_is_remembered_in_settings_page_and_status(self):
        app = BrowserApp(self.root, self.chamber)
        (self.root / 'profile.md').write_text('secretary_name: Aria\nsecretary_language: English\ncity: London\ntimezone: Europe/London\nnews_country: GB\n')
        self.assertEqual(app.chat_settings()['secretary_name'], 'Aria')
        page = app.chat_page().decode()
        self.assertIn('Aria.', page)
        self.assertIn('id="secretary-heading"', page)
        with patch('goodmorning.web.briefing_chat.threading.Thread', ImmediateThread):
            self.start('secretary', 'Hello')
        self.assertEqual(self.chats.status(self.id)['secretary_name'], 'Aria')

    def test_saved_profile_changes_default_without_restart_or_provider_verification(self):
        app = BrowserApp(self.root, self.chamber)
        (self.root / 'profile.md').write_text('secretary_language: English\ncity: London\ntimezone: Europe/London\nnews_country: GB\n')
        self.assertEqual(app.chat_settings()['defaultMode'], 'secretary')
        self.assertRegex(app.today(), r'\d{4}-\d{2}-\d{2}')
        self.assertIn(b'href="/chat"', app.page(app.today(), 'gm', False))

    def test_duplicate_creation_and_turn_do_not_dispatch_twice(self):
        self.start()
        self.start()
        self.assertEqual(len(self.chamber.calls), 2)
        self.assertEqual(self.chats.status(self.id)['state'], 'idle')
        body = {'id': 'b' * 32, 'text': 'Follow up'}
        self.chats.send(self.id, body)
        self.chats.send(self.id, body)
        self.assertEqual(sum(action == 'session.send' for action, _ in self.chamber.calls), 2)
        with self.assertRaises(ValueError): self.start('todo')
        with self.assertRaises(ValueError): self.chats.send(self.id, {**body, 'text': 'Changed'})

    def test_questions_and_permissions_are_bound_to_owning_conversation(self):
        self.start('initialize', '')
        with self.assertRaises(ValueError): self.chats.reply(self.id, 'form', 'foreign', {'answer': {}})
        self.chats.reply(self.id, 'form', 'form_city', {'answer': {'city': 'London'}})
        with self.assertRaises(ValueError): self.chats.reply(self.id, 'permission', 'permission_setup', {'decision': 'always'})
        self.chats.reply(self.id, 'permission', 'permission_setup', {'decision': 'once'})
        self.assertEqual(self.chats.status(self.id)['state'], 'idle')
        self.assertEqual(self.chamber.replies[-1][1], {'decision': 'once'})

    def test_waiting_session_cannot_receive_free_text_turn(self):
        self.start('initialize', '')
        with self.assertRaises(ValueError): self.chats.send(self.id, {'id': 'b' * 32, 'text': 'Skip'})

    def test_restart_preserves_conversation_without_replaying(self):
        self.start()
        count = len(self.chamber.calls)
        restored = Chats(self.root, self.chamber)
        self.assertEqual(restored.status(self.id)['state'], 'idle')
        self.assertEqual(len(self.chamber.calls), count + 1)  # Read-only transcript request.
        self.assertEqual(restored.listing()[0]['id'], self.id)

    def test_uncertain_send_never_becomes_idle_or_replays(self):
        self.chamber.fail = True
        self.start()
        count = len(self.chamber.calls)
        self.start()
        restored = Chats(self.root, self.chamber)
        self.assertEqual(restored.status(self.id)['state'], 'uncertain')
        with self.assertRaises(ValueError): restored.send(self.id, {'id': 'b' * 32, 'text': 'Again'})
        self.assertEqual(sum(action == 'session.send' for action, _ in self.chamber.calls), 1)
        self.assertGreaterEqual(len(self.chamber.calls), count)

    def test_interrupted_start_is_uncertain_after_restart(self):
        self.chats.items[self.id] = {'id': self.id, 'mode': 'secretary', 'state': 'starting', 'title': 'Hello', 'turns': []}
        self.chats.save()
        restored = Chats(self.root, self.chamber)
        self.assertEqual(restored.status(self.id)['state'], 'uncertain')
        self.assertEqual(self.chamber.calls, [])

    def test_missing_account_chat_cannot_be_read(self):
        with self.assertRaises(ValueError): self.chats.status('b' * 32)
        self.start()
        other = self.root / 'other'; other.mkdir()
        isolated = Chats(other, self.chamber)
        with self.assertRaises(ValueError): isolated.status(self.id)

    def test_idle_without_acknowledged_user_message_does_not_release_turn(self):
        self.start()
        session = self.chamber.sessions[self.chats.get(self.id)['session']]
        session['messages'] = []
        self.assertEqual(self.chats.status(self.id)['state'], 'running')

    def test_native_message_read_preserves_100_messages_without_400_record_prefetch(self):
        self.start()
        session = self.chamber.sessions[self.chats.get(self.id)['session']]
        for index in range(120):self.chamber.add(session, 'assistant', f'Reply {index}')
        result = self.chamber.control('session.messages', sessionId=self.chats.get(self.id)['session'], limit=100)
        self.assertEqual(len(result['messages']), 100)
        self.assertEqual(result['messages'][0]['text'], 'Reply 20')
        self.assertEqual(result['messages'][-1]['text'], 'Reply 119')

    def test_native_message_read_pages_past_non_text_records(self):
        from unittest.mock import Mock
        chamber = Chamber('http://127.0.0.1:1234', '/synthetic')
        chamber.request = Mock(side_effect=[
            {'data':[{'id':'idle','type':'idle'} for _ in range(200)], 'cursor':{'next':'opaque /+'}},
            {'data':[{'id':'a','type':'assistant','content':[{'type':'text','text':'Answer'}]},
                     {'id':'u','type':'user','text':'Prompt'}], 'cursor':{'next':None}},
            {'sessionStatus':{'type':'idle'}}])
        result=chamber.control('session.messages',sessionId='ses_test',limit=100)
        self.assertEqual([entry['text'] for entry in result['messages']],['Prompt','Answer'])
        self.assertIn('limit=200', chamber.request.call_args_list[0].args[0])
        self.assertIn('cursor=opaque+%2F%2B', chamber.request.call_args_list[1].args[0])
        self.assertEqual(result['sessionStatus']['type'],'idle')

    def test_symlink_storage_is_rejected(self):
        root = self.root / 'unsafe'; root.mkdir()
        (root / 'browser-chats').symlink_to(self.chats.directory, target_is_directory=True)
        with self.assertRaises(ValueError): Chats(root, self.chamber)

    def test_registry_capacity_is_checked_before_an_agent_dispatch(self):
        self.chats.items['b'*32]={'padding':'x'*7_500_000}
        with self.assertRaises(ValueError): self.start()
        self.assertNotIn(self.id,self.chats.items)
        self.assertEqual(self.chamber.calls,[])


if __name__ == '__main__':
    if '--serve-fixture' in sys.argv:
        runtime = Path(sys.argv[-1])
        if '--unseen-release' not in sys.argv:
            from support import returning_viewer
            returning_viewer(runtime)
        serve_live(BrowserApp(runtime, MockChamber(runtime)), 0)
    else:
        unittest.main()
