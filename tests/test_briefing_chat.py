"""Synthetic, account-local website conversations. No real model or integrations."""
import json
import re
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from support import TEMP_ROOT, ImmediateThread, MockChamber
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web.briefing_chat import Chats, MODES, NEW_MODES
from goodmorning.web.briefing_server import BrowserApp, Chamber, serve_live


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'setup-consent.json').write_text('{}')  # Storage consent is covered in test_setup_flow.
        self.chamber = MockChamber(self.root)
        self.chats = Chats(self.root, self.chamber)
        patcher = patch('goodmorning.web.briefing_chat.threading.Thread', ImmediateThread)
        patcher.start(); self.addCleanup(patcher.stop)
        self.id = 'a' * 32

    def start(self, mode='secretary', text='Hello', chat=None):
        return self.chats.start({'id': chat or self.id, 'mode': mode, 'text': text})

    def begin(self, mode, text='Hello', chat=None):
        # Older To-do/Eureka chats can no longer be started; simulate a saved one.
        if mode in NEW_MODES:
            return self.start(mode, text, chat)
        result = self.start('secretary', text, chat)
        self.chats.items[chat or self.id]['mode'] = mode
        return result

    def test_modes_are_fixed_and_commands_are_not_accepted(self):
        for mode in ('gm', 'gn', 'shell'):
            with self.assertRaises(ValueError): self.start(mode)
        for text in ('/gm', ' /secretary other', 'x' * 8001):
            with self.assertRaises(ValueError): self.start(text=text)
        for mode in ('todo', 'eureka'):
            with self.assertRaises(ValueError): self.start(mode, 'Save this')
        self.assertEqual(self.chamber.calls, [])

    def test_secretary_opened_conversation_waits_unread_then_continues_with_the_secretary(self):
        note = 'Want me to remind you to passage the cells every two days? Just say the word.'
        self.assertEqual(self.chats.outreach({'id': self.id, 'text': note}), {'chat': self.id})
        self.assertEqual(self.chats.outreach({'id': self.id, 'text': note}), {'chat': self.id})  # A retried delivery is one conversation.
        with self.assertRaises(ValueError): self.chats.outreach({'id': self.id, 'text': 'Different words'})
        for bad in ({'id': 'b' * 32, 'text': '/secretary hi'}, {'id': 'b' * 32, 'text': ' '}, {'id': 'b' * 32},
                    {'id': 'b' * 32, 'text': 'Hi', 'mode': 'initialize'}):
            with self.assertRaises(ValueError): self.chats.outreach(bad)
        self.assertEqual(self.chamber.calls, [])  # No session and no model run until the user replies.
        listed, = self.chats.listing()
        self.assertEqual((listed['title'], listed['unread'], listed['mode']), ('A note from your secretary', True, 'secretary'))
        status = self.chats.status(self.id)
        self.assertEqual((status['state'], status['unread'], status['language']), ('idle', True, 'en'))
        self.assertEqual(status['messages'], [{'id': 'opening-' + self.id, 'role': 'assistant', 'text': note,
                                               'attachments': [], 'kind': 'outreach', 'language': 'en'}])
        self.assertEqual(self.chats.status(self.id, include_messages=False)['state'], 'idle')
        with self.assertRaises(ValueError): self.start(text=note)  # A browser start cannot take over the opening.
        self.chats.seen(self.id)
        self.assertNotIn('unread', self.chats.listing()[0])
        restarted = Chats(self.root, self.chamber)
        self.assertNotIn('unread', restarted.status(self.id))

        self.chats.send(self.id, {'id': 'c' * 32, 'text': 'Yes please!'})
        creates = [call for call in self.chamber.calls if call[0] == 'session.create']
        self.assertEqual(len(creates), 1)
        prompt = next(body['prompt'] for action, body in self.chamber.calls if action == 'session.send')
        self.assertTrue(prompt.startswith('/secretary\nBrowser chat: ' + self.id))
        self.assertIn('Secretary opening: ' + json.dumps(note), prompt)
        self.assertTrue(prompt.endswith('\n\nYes please!'))
        status = self.chats.status(self.id)
        self.assertEqual(status['state'], 'idle')
        self.assertEqual([(m['role'], m.get('kind'), m['text']) for m in status['messages']][:3],
                         [('assistant', 'outreach', note), ('user', None, 'Yes please!'),
                          ('assistant', None, 'Synthetic reply. Your text stays text: <img src=x onerror=alert(1)>')])
        self.assertEqual(self.chats.listing()[0]['title'], 'A note from your secretary')
        self.chats.send(self.id, {'id': 'd' * 32, 'text': 'Thanks'})
        later = [body['prompt'] for action, body in self.chamber.calls if action == 'session.send'][-1]
        self.assertNotIn('Secretary opening', later)
        self.assertEqual(len([call for call in self.chamber.calls if call[0] == 'session.create']), 1)

    def test_secretary_opened_conversation_keeps_its_title_and_language(self):
        from goodmorning.web import language as ui
        token = ui.CURRENT.set('zh-CN')
        try:
            self.chats.outreach({'id': self.id, 'text': '要不要每两天提醒你传代一次呀？', 'title': '  传代提醒  '})
            default = 'b' * 32
            self.chats.outreach({'id': default, 'text': '你好呀'})
        finally:
            ui.CURRENT.reset(token)
        titles = {item['id']: item['title'] for item in self.chats.listing()}
        self.assertEqual(titles, {self.id: '传代提醒', default: 'A note from your secretary'})
        token = ui.CURRENT.set('zh-CN')
        try:
            titles = {item['id']: item['title'] for item in self.chats.listing()}
        finally:
            ui.CURRENT.reset(token)
        self.assertEqual(titles, {self.id: '传代提醒', default: '你的秘书留了句话'})
        self.assertEqual(self.chats.status(self.id)['language'], 'zh-CN')

    def test_new_profile_opens_setup_without_inventing_timezone(self):
        app = BrowserApp(self.root, self.chamber)
        self.assertEqual(app.chat_settings()['defaultMode'], 'initialize')
        page = app.chat_page()
        self.assertNotIn(b'role="radiogroup"', page)
        self.assertNotIn(b'data-mode=', page)
        self.assertIn(b'data-guide="initialize">', page)
        self.assertIn(b'id="chat-starters" hidden', page)
        self.assertFalse((self.root / 'profile.md').exists())
        with self.assertRaises(ValueError): app.today()
        (self.root / 'setup-consent.json').unlink()
        self.start('initialize', '')
        status = self.chats.status(self.id)
        consent, = status['forms']
        self.assertEqual((status['state'], status['reservation_required'], consent['setup']), ('waiting', False, 'consent'))
        self.assertEqual([entry['text'] for entry in status['messages']], ['Start initialize'])
        self.assertEqual(self.chamber.calls, [])  # Nothing reaches a model before consent.
        self.chats.reply(self.id, 'form', consent['id'], {'answer': {'consent': 'decline'}})
        status = self.chats.status(self.id)
        self.assertEqual((status['state'], status['forms']), ('idle', []))
        self.assertEqual([entry.get('kind') for entry in status['messages']], [None, 'question', 'answer', 'note'])
        self.assertIn('haven’t saved anything', status['messages'][-1]['text'])
        self.assertFalse(any((self.root / name).exists() for name in ('profile.md', 'setup-consent.json', 'calendar.sqlite', 'inbox.sqlite')))
        self.chats.send(self.id, {'id': 'c' * 32, 'text': 'Set me up after all'})
        consent, = self.chats.status(self.id)['forms']
        self.assertEqual(self.chamber.calls, [])
        self.chats.reply(self.id, 'form', consent['id'], {'answer': {'consent': 'agree'}})
        self.assertTrue((self.root / 'profile.md').exists() and (self.root / 'setup-consent.json').exists())
        prompt = next(body['prompt'] for action, body in self.chamber.calls if action == 'session.send')
        self.assertTrue(prompt.startswith('/initialize\n'))
        self.assertIn('Set me up after all\n\nSetup step: {"setup":{"mode":"new","step":"secretary_name"', prompt)
        status = self.chats.status(self.id)
        self.assertEqual(status['forms'][0]['id'], 'form_city')
        self.assertEqual(status['messages'][0]['text'], 'Start initialize')
        self.assertNotIn(str(self.root), json.dumps(status['messages']))

    def test_blank_setup_start_asks_its_first_question_without_a_model(self):
        self.start('initialize', '')
        status = self.chats.status(self.id)
        question, = status['forms']
        self.assertEqual((question['setup'], question['title']), ('secretary_name', 'What would you like to call me?'))
        self.assertEqual(self.chamber.calls, [])
        self.chats.reply(self.id, 'form', question['id'], {'answer': {'secretary_name': 'skip'}})
        prompt = next(body['prompt'] for action, body in self.chamber.calls if action == 'session.send')
        self.assertTrue(prompt.startswith('/initialize\n'))
        self.assertIn('Setup already saved these answers.', prompt)
        self.assertIn('"step":"user_name"', prompt)
        self.assertIn('"contract"', prompt)
        self.assertEqual([entry.get('kind') for entry in self.chats.status(self.id)['messages']][:3], [None, 'question', 'answer'])

    def test_secretary_name_is_remembered_in_settings_page_and_status(self):
        app = BrowserApp(self.root, self.chamber)
        (self.root / 'profile.md').write_text('secretary_name: Aria\nsecretary_language: English\ncity: London\ntimezone: Europe/London\nnews_country: GB\n')
        self.assertEqual(app.chat_settings()['secretary_name'], 'Aria')
        page = app.chat_page().decode()
        self.assertEqual(re.search(r'id="secretary-heading"[^>]*>([^<]*)<', page)[1], 'Aria')
        self.assertNotIn('Aria.', page)
        self.start('secretary', 'Hello')
        self.assertEqual(self.chats.status(self.id)['secretary_name'], 'Aria')

    def test_saved_tone_is_available_before_each_turn_without_leaking_prompt_metadata(self):
        tone='Professional and reserved; use "clear" wording.'
        profile=self.root/'profile.md'
        profile.write_text('secretary_tone: '+tone+'\n')
        self.start('secretary','Record a task')
        prompts=[body['prompt'] for action,body in self.chamber.calls if action=='session.send']
        line=next(line for line in prompts[-1].splitlines() if line.startswith('Secretary tone at request start: '))
        self.assertEqual(json.loads(line.split(': ',1)[1]),{'value':tone,'source':'saved'})
        self.assertEqual(profile.read_text(),'secretary_tone: '+tone+'\n')
        profile.write_text('secretary_tone: Warm and lightly playful\n')
        self.chats.send(self.id,{'id':'b'*32,'text':'Follow up'})
        prompts=[body['prompt'] for action,body in self.chamber.calls if action=='session.send']
        self.assertIn('Warm and lightly playful',prompts[-1])
        self.assertIn(tone.replace('"','\\"'),prompts[0])
        user_texts=[message['text'] for message in self.chats.status(self.id)['messages'] if message['role']=='user']
        self.assertEqual(user_texts,['Record a task','Follow up'])

    def test_unsaved_tone_is_labeled_default_not_stored_as_a_preference(self):
        self.start('secretary','Record a task')
        prompt=next(body['prompt'] for action,body in self.chamber.calls if action=='session.send')
        line=next(line for line in prompt.splitlines() if line.startswith('Secretary tone at request start: '))
        self.assertEqual(json.loads(line.split(': ',1)[1]),{'value':'warm and helpful','source':'default'})
        self.assertFalse((self.root/'profile.md').exists())
        self.assertNotIn('Call the user:', prompt)

    def test_saved_user_name_is_supplied_each_turn(self):
        (self.root/'profile.md').write_text('user_name: 小王\n')
        self.start('secretary','Hello')
        prompt=[body['prompt'] for action,body in self.chamber.calls if action=='session.send'][-1]
        line=next(line for line in prompt.splitlines() if line.startswith('Call the user: '))
        self.assertEqual(json.loads(line.split(': ',1)[1]),'小王')
        self.assertTrue(prompt.endswith('\n\nHello'))

    def test_saved_profile_changes_default_without_restart_or_provider_verification(self):
        app = BrowserApp(self.root, self.chamber)
        (self.root / 'profile.md').write_text('secretary_language: English\ncity: London\ntimezone: Europe/London\nnews_country: GB\n')
        self.assertEqual(app.chat_settings()['defaultMode'], 'secretary')
        page = app.chat_page()
        self.assertNotIn(b'data-mode=', page)
        self.assertIn(b'data-guide="initialize" hidden', page)
        self.assertIn(b'data-guide="secretary">', page)
        self.assertNotIn(b'id="chat-starters" hidden', page)
        self.assertEqual(page.count(b'data-starter'), 3)
        self.assertRegex(app.today(), r'\d{4}-\d{2}-\d{2}')
        self.assertIn(b'href="/chat"', app.page(app.today(), 'gm', False))

    def test_incomplete_or_invalid_profile_keeps_only_initialization(self):
        app = BrowserApp(self.root, self.chamber)
        for fields in ('city: London\n', 'city: London\ntimezone: Invalid/Zone\nnews_country: GB\n'):
            (self.root / 'profile.md').write_text(fields)
            self.assertEqual(app.chat_settings()['defaultMode'], 'initialize')
            self.assertIn(b'data-guide="secretary" hidden', app.chat_page())
            self.assertEqual((self.root / 'profile.md').read_text(), fields)

    def test_duplicate_creation_and_turn_do_not_dispatch_twice(self):
        self.start()
        self.start()
        self.assertEqual(len(self.chamber.calls), 2)
        self.assertEqual(self.chats.status(self.id)['state'], 'idle')
        body = {'id': 'b' * 32, 'text': 'Follow up'}
        self.chats.send(self.id, body)
        self.chats.send(self.id, body)
        self.assertEqual(sum(action == 'session.send' for action, _ in self.chamber.calls), 2)
        with self.assertRaises(ValueError): self.start('initialize')
        with self.assertRaises(ValueError): self.chats.send(self.id, {**body, 'text': 'Changed'})

    def test_resumed_chat_moves_to_current_release_and_refreshes_rules_once(self):
        self.begin('todo', 'Claim salary every Friday')
        session = self.chats.get(self.id)['session']
        original = list(self.chamber.sessions[session]['messages'])
        self.chamber.sessions[session]['directory'] = '/opt/goodmorning/releases/old'
        self.chamber.sessions['ses_other'] = {'directory': '/opt/goodmorning/releases/old'}
        self.chats.status(self.id)
        self.chats.listing()
        self.assertFalse(any(path.endswith('/move') for path, _ in self.chamber.replies))
        text = 'Go into secretary mode and finish the setup for me.'
        self.chats.send(self.id, {'id': 'b'*32, 'text': text})
        self.assertEqual(self.chats.get(self.id)['session'], session)
        self.assertEqual(self.chamber.sessions[session]['directory'], self.chamber.directory)
        self.assertEqual(self.chamber.sessions['ses_other']['directory'], '/opt/goodmorning/releases/old')
        self.assertEqual(self.chamber.sessions[session]['messages'][:len(original)], original)
        prompt = [body['prompt'] for action, body in self.chamber.calls if action == 'session.send'][-1]
        self.assertIn(f'Browser chat: {self.id}', prompt)
        self.assertIn(f'Runtime: {self.root}', prompt)
        self.assertTrue(prompt.startswith('/secretary\n'), 'older To-do chats continue as Secretary')
        self.assertTrue(prompt.endswith(text))
        self.assertEqual(self.chats.status(self.id)['messages'][-2]['text'], text)
        self.chats.send(self.id, {'id': 'c'*32, 'text': 'Thanks'})
        moves = [body for path, body in self.chamber.replies if path.endswith('/move')]
        self.assertEqual(moves, [{'directory': self.chamber.directory}])
        prompt = [body['prompt'] for action, body in self.chamber.calls if action == 'session.send'][-1]
        self.assertNotIn('Workflow refresh', prompt)

    def test_every_text_turn_identifies_native_audit_owner_in_all_modes(self):
        for index, mode in enumerate(MODES):
            with self.subTest(mode=mode):
                chat = format(index, '032x')
                self.begin(mode, 'Synthetic request', chat=chat)
                session = self.chats.get(chat)['session']
                if mode == 'initialize':
                    self.chats.reply(chat, 'form', 'form_city', {'answer': {'city': 'London'}})
                    self.chats.reply(chat, 'permission', 'permission_setup', {'decision': 'reject'})
                self.chats.send(chat, {'id': 'e' * 32, 'text': 'Ordinary follow-up'})
                self.chamber.sessions[session]['directory'] = '/opt/goodmorning/releases/old'
                self.chats.send(chat, {'id': 'f' * 32, 'text': 'Resumed follow-up'})
                prompts = [body['prompt'] for action, body in self.chamber.calls
                           if action == 'session.send' and body['sessionId'] == session]
                # The setup answer is one more turn of the same session.
                self.assertEqual(len(prompts), 4 if mode == 'initialize' else 3)
                for prompt in prompts:
                    metadata = prompt.split('\n\n', 1)[0]
                    self.assertIn(f'Native session ID: {session}\n', metadata)
                    self.assertIn('--session and calendar --actor', metadata)
                    self.assertNotIn(f'Native session ID: {chat}', metadata)
                    self.assertIn('Website language: en', metadata)
                self.assertNotIn('Workflow refresh:', prompts[-2])
                self.assertIn('Workflow refresh: true', prompts[-1])
                self.assertTrue(prompts[-1].startswith('/' + (mode if mode in NEW_MODES else 'secretary') + '\n'))

    def test_failed_or_unconfirmed_release_move_never_dispatches_followup(self):
        for failure in ('failed', 'unconfirmed'):
            with self.subTest(failure=failure):
                chat = ('d' if failure == 'failed' else 'e')*32
                self.begin('eureka', 'Synthetic idea', chat=chat)
                session = self.chats.get(chat)['session']
                self.chamber.sessions[session]['directory'] = '/opt/goodmorning/releases/old'
                request = self.chamber.request
                def move(path, body=None):
                    if path.endswith('/move'):
                        if failure == 'failed': raise OSError('Synthetic move failure')
                        return {}
                    return request(path, body)
                before = len(self.chamber.sessions[session]['messages'])
                with patch.object(self.chamber, 'request', side_effect=move):
                    self.chats.send(chat, {'id': 'f'*32, 'text': 'Organize this idea'})
                self.assertEqual(self.chats.get(chat)['state'], 'uncertain')
                self.assertEqual(len(self.chamber.sessions[session]['messages']), before)

    def test_history_uses_engine_summary_not_clipped_user_text(self):
        raw = 'I think the priority setting for my project needs a careful correction.'
        self.start(text=raw)
        session = self.chats.get(self.id)['session']
        self.assertEqual(self.chats.listing()[0]['title'], 'Secretary')
        self.assertEqual(self.chats.listing()[0]['created'], self.chats.get(self.id)['created'])
        self.chamber.sessions[session]['title'] = 'Secretary Correct project priorities'
        self.assertEqual(self.chats.status(self.id)['state'], 'idle')
        before = self.chats.path.read_bytes()
        self.assertEqual(self.chats.listing()[0]['title'], 'Secretary Correct project priorities')
        self.assertEqual(self.chats.path.read_bytes(), before)
        self.assertEqual(self.chats.get(self.id)['turns'][0]['text'], raw)

    def test_all_chat_modes_leave_native_title_generation_enabled(self):
        for index, mode in enumerate(NEW_MODES):
            self.start(mode=mode, text='Synthetic request', chat=str(index)*32)
        creates = [body for action,body in self.chamber.calls if action=='session.create']
        self.assertEqual(len(creates), 2)
        self.assertTrue(all('title' not in body for body in creates))

    def test_every_turn_runs_on_the_secretary_agent(self):
        # OpenChamber drops session.create's agent when no prompt is sent with it, and
        # chats created before this fix already run as build: set it before every dispatch.
        order = []
        request, control = self.chamber.request, self.chamber.control
        def agent(path, body=None):
            if path.endswith('/agent'):
                order.append(body['agent'])
            return request(path, body)
        def send(action, **body):
            if action == 'session.send':
                order.append(action)
            return control(action, **body)
        self.chamber.request, self.chamber.control = agent, send
        self.start()
        session = self.chats.get(self.id)['session']
        self.chamber.sessions[session]['agent'] = 'build'
        self.chats.send(self.id, {'id': 'b'*32, 'text': 'Follow up'})
        self.assertEqual(order, ['secretary', 'session.send'] * 2)
        self.assertEqual(self.chamber.sessions[session]['agent'], 'secretary')

    def test_native_timestamp_placeholder_is_hidden_and_late_title_is_read(self):
        self.start()
        session = self.chats.get(self.id)['session']
        self.chamber.sessions[session]['title'] = 'New session - 2026-10-12T19:00:00.000Z'
        before = self.chats.path.read_bytes()
        with patch('goodmorning.web.briefing_chat.time.monotonic', return_value=10):
            listing = self.chats.listing()[0]
        self.assertEqual(listing['title'], 'Secretary')
        self.assertTrue(listing['title_pending'])
        self.chamber.sessions[session]['title'] = 'Review project priorities'
        with patch('goodmorning.web.briefing_chat.time.monotonic', return_value=14):
            listing = self.chats.listing()[0]
        self.assertEqual(listing['title'], 'Review project priorities')
        self.assertFalse(listing['title_pending'])
        self.assertEqual(self.chats.path.read_bytes(), before)

    def test_history_title_pages_are_bounded_cached_and_filtered_to_owned_sessions(self):
        self.start()
        session = self.chats.get(self.id)['session']
        self.chamber.sessions[session]['title'] = 'GoodMorning · Secretary · Review project plan'
        for index in range(120):
            self.chamber.sessions['ses_unregistered_'+str(index)] = {'title':'Unrelated session'}
        with patch.object(self.chamber, 'request', wraps=self.chamber.request) as request:
            self.assertEqual(self.chats.listing()[0]['title'], 'Secretary · Review project plan')
            reads = request.call_count
            self.assertEqual(reads, 2)
            self.assertEqual(len(self.chats.listing()), 1)
            self.assertEqual(request.call_count, reads)
            self.assertTrue(all('/api/session?' in call.args[0] and 'limit=100' in call.args[0]
                                for call in request.call_args_list))

    def test_history_preserves_cached_summary_during_engine_outage(self):
        self.start()
        session = self.chats.get(self.id)['session']
        self.chamber.sessions[session]['title'] = '秘书 调整项目优先级'
        self.assertEqual(self.chats.listing()[0]['title'], '秘书 调整项目优先级')
        self.chats.titles_checked = float('-inf')
        with patch.object(self.chamber, 'request', side_effect=OSError('Synthetic title outage')):
            self.assertEqual(self.chats.listing()[0]['title'], '秘书 调整项目优先级')

    def test_old_seeded_user_fragment_is_not_displayed_as_an_ai_title(self):
        from goodmorning.web.session_inventory import chat_session_title
        self.start()
        session = self.chats.get(self.id)['session']
        old = 'The original workflow involves me closing the calendar application'
        self.chats.items[self.id]['title'] = old
        self.chamber.sessions[session]['title'] = chat_session_title('Secretary', old)
        self.assertEqual(self.chats.listing()[0]['title'], 'Secretary')

    def test_question_closed_by_the_engine_shows_as_expired(self):
        self.start()
        session = self.chamber.sessions[self.chats.get(self.id)['session']]
        def interrupt(tool):
            session['messages'].append({'id': 'message_' + str(len(session['messages'])), 'role': 'assistant', 'text': '',
                'native': {'error': {'type': 'aborted'}, 'content': [{'type': 'tool', 'id': tool, 'name': 'question'}]}})
        ready = self.chats.status(self.id)['label']
        # Never seen while it waited: a plain note in the request language.
        interrupt('prt_unseen')
        status = self.chats.status(self.id)
        unseen = status['messages'][-1]
        self.assertEqual((unseen['kind'], unseen['language'], status['state']), ('expired', 'en', 'idle'))
        self.assertTrue(unseen['text'])
        self.assertNotIn('tools', unseen)
        self.assertNotEqual(status['label'], ready)
        self.chats.send(self.id, {'id': 'b' * 32, 'text': 'Just tonight'})
        self.assertEqual(self.chats.status(self.id)['label'], ready)

    def test_questions_and_permissions_are_bound_to_owning_conversation(self):
        self.start('secretary', 'Ask my city')
        with self.assertRaises(ValueError): self.chats.reply(self.id, 'form', 'foreign', {'answer': {}})
        self.chats.reply(self.id, 'form', 'form_city', {'answer': {'city': 'London'}})
        with self.assertRaises(ValueError): self.chats.reply(self.id, 'permission', 'permission_setup', {'decision': 'always'})
        self.chats.reply(self.id, 'permission', 'permission_setup', {'decision': 'once'})
        self.assertEqual(self.chats.status(self.id)['state'], 'idle')
        self.assertEqual(self.chamber.replies[-1][1], {'decision': 'once'})

    def test_question_is_saved_closed_and_answered_as_a_new_turn(self):
        self.start('secretary', 'Ask my city')
        session = self.chamber.sessions[self.chats.get(self.id)['session']]
        self.assertEqual(self.chats.status(self.id)['forms'][0]['id'], 'form_city')
        # The engine no longer holds the question, so nothing waits on it there.
        self.assertEqual((session['forms'], self.chats.status(self.id, include_messages=False)['state']), ([], 'waiting'))
        restored = Chats(self.root, self.chamber)
        status = restored.status(self.id)
        self.assertEqual((status['state'], status['forms'][0]['id']), ('waiting', 'form_city'))
        self.assertFalse(status['reservation_required'])
        restored.reply(self.id, 'form', 'form_city', {'answer': {'city': 'London'}})
        restored.reply(self.id, 'form', 'form_city', {'answer': {'city': 'Paris'}})
        prompts = [body['prompt'] for action, body in self.chamber.calls if action == 'session.send']
        self.assertEqual(len(prompts), 2)
        self.assertTrue(prompts[1].endswith('User has answered your questions: "City"="London". '
                                            "You can now continue with the user's answers in mind."))
        status = restored.status(self.id)
        self.assertEqual([(entry.get('kind'), entry['text']) for entry in status['messages'][-2:]],
                         [('question', 'Confirm your location\nCity\n• London'), ('answer', 'City: London')])
        # A permission still needs its decision before another message.
        self.assertEqual((status['state'], status['permissions'][0]['id']), ('waiting', 'permission_setup'))
        with self.assertRaises(ValueError): restored.send(self.id, {'id': 'b' * 32, 'text': 'Skip'})

    def test_new_message_skips_a_saved_question(self):
        self.start('secretary', 'Ask my city')
        self.chats.status(self.id)
        self.chats.send(self.id, {'id': 'b' * 32, 'text': 'Later, please'})
        status = self.chats.status(self.id)
        self.assertEqual(status['forms'], [])
        self.assertEqual([(entry.get('kind'), entry['text']) for entry in status['messages'][-3:-1]],
                         [('skipped', 'Confirm your location\nCity\n• London'), (None, 'Later, please')])
        with self.assertRaises(ValueError):
            self.chats.reply(self.id, 'form', 'form_city', {'answer': {'city': 'London'}})

    def test_questions_and_selected_answers_survive_refresh_and_restart_in_order(self):
        self.start('secretary', 'Ask my city')
        before = self.chats.status(self.id)
        self.chats.status(self.id)
        self.assertEqual(len(self.chats.get(self.id)['questions']), 1)
        self.assertNotIn('question:form_city', [entry['id'] for entry in before['messages']])
        session = self.chamber.sessions[self.chats.get(self.id)['session']]
        self.chamber.add(session, 'assistant', 'Take your time choosing.')
        self.chats.reply(self.id, 'form', 'form_city', {'answer': {'city': 'London'}})
        self.chats.reply(self.id, 'permission', 'permission_setup', {'decision': 'reject'})
        expected = ['Ask my city', 'Confirm your location; replies follow the website language.',
                    'Confirm your location\nCity\n• London', 'Take your time choosing.', 'City: London', 'Nothing saved.']
        self.assertEqual([entry['text'] for entry in self.chats.status(self.id)['messages']], expected)
        restored = Chats(self.root, self.chamber)
        self.assertEqual([entry['text'] for entry in restored.status(self.id)['messages']], expected)
        sent = len(self.chamber.calls)
        self.assertEqual(restored.reply(self.id, 'form', 'form_city', {'answer': {'city': 'Paris'}}), {'answered': True})
        self.assertEqual([entry['text'] for entry in restored.status(self.id)['messages']], expected)
        self.assertNotIn('session.send', [action for action, _ in self.chamber.calls[sent:]])
        self.assertEqual(len(restored.get(self.id)['questions']), 1)

    def test_answer_history_uses_labels_and_preserves_typed_and_multiple_values(self):
        self.start()
        session = self.chamber.sessions[self.chats.get(self.id)['session']]
        session['forms'] = [{'id': 'preferences', 'title': 'How should we plan?', 'metadata': {'tool': {'id': 'prt_plan'}}, 'fields': [
            {'key': 'calendar', 'title': 'Calendar', 'description': 'Choose a source.', 'type': 'string',
             'options': [{'value': 'ics', 'label': 'Calendar export', 'description': 'Upload a file.'}], 'custom': True},
            {'key': 'days', 'title': 'Days', 'type': 'multiselect',
             'options': [{'value': 'mon', 'label': 'Monday'}, {'value': 'tue', 'label': 'Tuesday'}], 'custom': True},
            {'key': 'notes', 'title': 'Notes', 'type': 'string'},
            {'key': 'count', 'title': 'Count', 'type': 'integer'},
            {'key': 'enabled', 'title': 'Enabled', 'type': 'boolean'}]}]
        answer = {'calendar': 'ics', 'days': ['mon', 'A custom day'], 'notes': '<img>\nKeep my wording.',
                  'count': 3, 'enabled': False}
        # Replies also persist the form when the browser has not polled it yet.
        self.chats.reply(self.id, 'form', 'preferences', {'answer': answer})
        messages = Chats(self.root, self.chamber).status(self.id)['messages']
        self.assertIn('Choose a source.\n• Calendar export: Upload a file.', messages[-3]['text'])
        self.assertEqual(messages[-2]['text'], 'Calendar: Calendar export\nDays: Monday, A custom day\n'
                         'Notes: <img>\nKeep my wording.\nCount: 3\nEnabled: No')
        self.assertEqual(self.chats.get(self.id)['questions'][0]['answer'], answer)
        prompt = [body['prompt'] for action, body in self.chamber.calls if action == 'session.send'][-1]
        self.assertIn('"Choose a source."="ics", "Days"="mon, A custom day", "Notes"="<img>\\nKeep my wording.", '
                      '"Count"="3", "Enabled"="No"', prompt)

    def test_failed_answer_is_not_displayed_as_accepted(self):
        self.start('initialize', 'Set me up')
        for answer in ({'town': 'London'}, {'city': {'nested': 'value'}}, {}):
            with self.assertRaises(ValueError):
                self.chats.reply(self.id, 'form', 'form_city', {'answer': answer})
        status = Chats(self.root, self.chamber).status(self.id)
        self.assertEqual(status['state'], 'waiting')
        self.assertFalse(any(entry.get('kind') == 'answer' for entry in status['messages']))
        self.assertNotIn('answer', self.chats.get(self.id)['questions'][0])

    def test_unsent_answer_reopens_its_question(self):
        self.start('initialize', 'Set me up')
        self.chats.status(self.id)
        session = self.chamber.sessions[self.chats.get(self.id)['session']]
        session['permissions'] = []
        self.chamber.fail = True
        self.chats.reply(self.id, 'form', 'form_city', {'answer': {'city': 'London'}})
        self.assertEqual(self.chats.status(self.id, include_messages=False)['state'], 'uncertain')
        self.chats.items[self.id]['uncertain_since'] = 0
        status = self.chats.status(self.id)
        self.assertEqual((status['state'], status['forms'][0]['id']), ('waiting', 'form_city'))
        self.assertEqual(status['label'], 'Your answer didn’t reach your secretary. Please answer again.')
        self.assertFalse(any(entry.get('kind') in ('answer', 'undelivered') for entry in status['messages']))
        self.chamber.fail = False
        self.chats.reply(self.id, 'form', 'form_city', {'answer': {'city': 'Paris'}})
        status = self.chats.status(self.id)
        self.assertEqual(status['forms'], [])
        self.assertEqual(status['messages'][-2:][1]['text'], 'City: Paris')

    def test_saved_questions_keep_their_request_language(self):
        from goodmorning.web import language as ui
        token = ui.CURRENT.set('zh-CN')
        try:
            self.start('initialize', 'Set me up')
            session = self.chamber.sessions[self.chats.get(self.id)['session']]
            session['forms'] = [{'id': 'confirm', 'metadata': {'tool': {'id': 'prt_confirm'}}, 'fields': [{'key': 'enabled', 'type': 'boolean'}]}]
            self.chats.status(self.id)
        finally:
            ui.CURRENT.reset(token)
        self.chats.reply(self.id, 'form', 'confirm', {'answer': {'enabled': True}})
        status = Chats(self.root, self.chamber).status(self.id)
        answer = ui.text('Your answer', lang='zh-CN')
        self.assertNotEqual(answer, 'Your answer')
        self.assertEqual(status['messages'][-3]['text'], ui.text('A question for you', lang='zh-CN') + '\n' + answer)
        self.assertEqual(status['messages'][-2]['text'], answer + ': ' + ui.text('Yes', lang='zh-CN'))
        self.assertEqual(status['messages'][-2]['language'], 'zh-CN')

    def test_question_history_stays_in_its_own_account(self):
        self.start('initialize', 'Set me up')
        self.chats.reply(self.id, 'form', 'form_city', {'answer': {'city': 'Private synthetic city'}})
        other = self.root / 'other'; other.mkdir()
        isolated = Chats(other, self.chamber)
        isolated.start({'id': self.id, 'mode': 'secretary', 'text': 'Other account'})
        status = isolated.status(self.id)
        self.assertFalse(any(entry.get('kind') for entry in status['messages']))
        self.assertNotIn('Private synthetic city', json.dumps(status))
        with self.assertRaises(ValueError):
            isolated.reply(self.id, 'form', 'form_city', {'answer': {'city': 'London'}})
        self.assertEqual(self.chats.get(self.id)['questions'][0]['answer']['city'], 'Private synthetic city')

    def test_old_question_exchanges_do_not_move_to_new_transcript_window(self):
        self.start('initialize', 'Set me up')
        self.chats.reply(self.id, 'form', 'form_city', {'answer': {'city': 'London'}})
        session = self.chamber.sessions[self.chats.get(self.id)['session']]
        for index in range(120):
            self.chamber.add(session, 'assistant', f'Later reply {index}')
        status = self.chats.status(self.id)
        self.assertEqual(len(status['messages']), 100)
        self.assertTrue(status['history_limited'])
        self.assertFalse(any(entry.get('kind') for entry in status['messages']))
        self.assertEqual(len(self.chats.get(self.id)['questions']), 1)

    def test_long_conversation_loads_earlier_messages_on_request(self):
        self.start()
        session = self.chamber.sessions[self.chats.get(self.id)['session']]
        for index in range(150):
            self.chamber.add(session, 'assistant', f'Later reply {index}')
        status = self.chats.status(self.id)
        self.assertEqual((len(status['messages']), status['history_limited']), (100, True))
        status = self.chats.status(self.id, limit=200)
        self.assertEqual((len(status['messages']), status['history_limited']), (152, False))
        self.assertEqual(status['messages'][0]['text'], 'Hello')
        for limit in (99, 1001, '200'):
            with self.assertRaises(ValueError): self.chats.status(self.id, limit=limit)

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
        self.start()
        restored = Chats(self.root, self.chamber)
        self.assertEqual(restored.status(self.id)['state'], 'uncertain')
        with self.assertRaises(ValueError): restored.send(self.id, {'id': 'b' * 32, 'text': 'Again'})
        self.assertEqual(sum(action == 'session.send' for action, _ in self.chamber.calls), 1)

    def test_uncertain_delivery_seen_by_the_engine_continues_without_replay(self):
        self.start()
        self.chats.send(self.id, {'id': 'b' * 32, 'text': 'Yes'})
        # The prompt arrived, but its receipt was lost before the restart.
        self.chats.items[self.id].update(state='starting')
        self.chats.save()
        restored = Chats(self.root, self.chamber)
        sends = sum(action == 'session.send' for action, _ in self.chamber.calls)
        status = restored.status(self.id, include_messages=False)
        self.assertEqual(status['state'], 'idle')
        self.assertEqual(restored.get(self.id)['state'], 'running')
        self.assertNotIn('uncertain_since', restored.get(self.id))
        self.assertEqual(sum(action == 'session.send' for action, _ in self.chamber.calls), sends)
        self.assertFalse(any(entry.get('kind') == 'undelivered' for entry in restored.status(self.id)['messages']))

    def test_identical_replies_each_need_their_own_acknowledgment(self):
        self.start()
        self.chats.send(self.id, {'id': 'b' * 32, 'text': 'Yes'})
        self.chamber.fail = True
        self.chats.send(self.id, {'id': 'c' * 32, 'text': 'Yes'})
        self.chats.items[self.id]['uncertain_since'] = 0
        status = self.chats.status(self.id)
        self.assertEqual(status['state'], 'idle')
        self.assertEqual([(entry['role'], entry.get('kind'), entry['text']) for entry in status['messages'][-2:]],
                         [('assistant', None, 'Synthetic reply. Your text stays text: <img src=x onerror=alert(1)>'),
                          ('user', 'undelivered', 'Yes')])

    def test_undelivered_message_waits_for_the_engine_then_can_be_sent_again(self):
        self.start()
        self.chamber.fail = True
        self.chats.send(self.id, {'id': 'b' * 32, 'text': 'Save the dentist call'})
        status = self.chats.status(self.id)
        self.assertEqual(status['state'], 'uncertain')
        self.assertIn('Checking whether your last message reached your secretary', status['label'])
        with self.assertRaisesRegex(ValueError, 'Try again in a moment'):
            self.chats.send(self.id, {'id': 'c' * 32, 'text': 'Again'})
        # A busy engine may still be accepting the prompt.
        self.chats.items[self.id]['uncertain_since'] = 0
        session = self.chamber.sessions[self.chats.get(self.id)['session']]
        session['permissions'] = [{'id': 'permission_busy'}]
        with patch.object(self.chamber, 'pending', return_value=([], [])):
            self.assertEqual(self.chats.status(self.id)['state'], 'uncertain')
        session['permissions'] = []
        status = self.chats.status(self.id)
        self.assertEqual(status['state'], 'idle')
        self.assertEqual(status['label'], 'Your last message wasn’t sent. Send it again or write a new one.')
        self.assertEqual(status['messages'][-1], {'id': 'undelivered:' + 'b' * 32, 'role': 'user', 'kind': 'undelivered',
                                                  'text': 'Save the dentist call', 'attachments': [], 'turn': 'b' * 32})
        self.assertEqual(self.chats.status(self.id, include_messages=False)['state'], 'idle')
        sends = sum(action == 'session.send' for action, _ in self.chamber.calls)
        self.chamber.fail = False
        self.chats.send(self.id, {'id': 'd' * 32, 'text': 'Save the dentist call'})
        self.assertEqual(sum(action == 'session.send' for action, _ in self.chamber.calls), sends + 1)
        status = self.chats.status(self.id)
        self.assertEqual(status['state'], 'idle')
        self.assertFalse(any(entry.get('kind') == 'undelivered' for entry in status['messages']))
        self.assertEqual([entry['text'] for entry in status['messages'] if entry['role'] == 'user'],
                         ['Hello', 'Save the dentist call'])

    def test_unsent_first_message_opens_the_conversation_when_sent_again(self):
        control, request = self.chamber.control, self.chamber.request
        def no_session(action, **body):
            if action == 'session.create':
                raise OSError('Synthetic engine outage')
            return control(action, **body)
        def no_agent(path, body=None):
            if path.endswith('/agent'):
                raise OSError('Synthetic engine outage')
            return request(path, body)
        for failure, chat in (('control', 'b' * 32), ('request', 'c' * 32)):
            with self.subTest(failure=failure):
                with patch.object(self.chamber, failure, side_effect=no_session if failure == 'control' else no_agent):
                    self.start(text='Plan my week', chat=chat)
                # The prompt was never sent, so there is nothing to wait for.
                status = self.chats.status(chat)
                self.assertEqual(status['state'], 'idle')
                self.assertEqual([entry['kind'] for entry in status['messages']], ['undelivered'])
                self.chats.send(chat, {'id': 'd' * 32, 'text': 'Plan my week'})
                prompt = [body['prompt'] for action, body in self.chamber.calls if action == 'session.send'][-1]
                self.assertTrue(prompt.startswith('/secretary\nBrowser chat: ' + chat))
                status = self.chats.status(chat)
                self.assertEqual(status['state'], 'idle')
                self.assertEqual([entry['text'] for entry in status['messages'] if entry['role'] == 'user'], ['Plan my week'])

    def test_engine_retry_is_still_working(self):
        self.start()
        request = self.chamber.request
        def retrying(path, body=None):
            if path == '/api/openchamber/control':
                return {'sessionStatus': {'type': 'retry'}}
            return request(path, body)
        self.chamber.sessions[self.chats.get(self.id)['session']]['messages'].pop()
        self.chamber.sessions[self.chats.get(self.id)['session']]['messages'].pop()
        with patch.object(self.chamber, 'request', side_effect=retrying):
            self.assertEqual(self.chats.status(self.id)['state'], 'running')

    def test_interrupted_start_without_a_session_settles_without_engine_calls(self):
        self.chats.items[self.id] = {'id': self.id, 'mode': 'secretary', 'state': 'starting', 'title': 'Hello', 'turns': []}
        self.chats.save()
        restored = Chats(self.root, self.chamber)
        self.assertEqual(restored.get(self.id)['state'], 'uncertain')
        self.assertEqual(restored.status(self.id)['state'], 'idle')
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

    def test_queue_status_does_not_read_transcript_and_confirms_latest_user_turn(self):
        self.start()
        control = self.chamber.control
        def without_transcript(action, **body):
            if action == 'session.messages':
                raise ValueError('Upstream response exceeds limit')
            return control(action, **body)
        with patch.object(self.chamber, 'control', side_effect=without_transcript):
            self.assertEqual(self.chats.status(self.id)['state'], 'unavailable')
            status = self.chats.status(self.id, include_messages=False)
            self.assertEqual(status['state'], 'idle')
            self.assertNotIn('messages', status)
            self.chats.items[self.id]['turns'][0]['attachments'] = [{'id': 'f' * 32, 'name': 'old.txt', 'size': 1}]
            with patch.object(self.chats.uploads, 'get', side_effect=OSError('Synthetic unavailable preview')) as preview:
                self.assertEqual(self.chats.status(self.id, include_messages=False)['state'], 'idle')
                preview.assert_not_called()
            self.chamber.sessions[self.chats.get(self.id)['session']]['messages'] = []
            self.assertEqual(self.chats.status(self.id, include_messages=False)['state'], 'running')

    def test_queue_status_keeps_pending_and_uncertain_work_and_saves_questions(self):
        self.start('initialize', 'Set me up')
        status = self.chats.status(self.id, include_messages=False)
        self.assertEqual(status['state'], 'waiting')
        self.assertFalse(status['reservation_required'])
        self.assertTrue(Chats(self.root, self.chamber).get(self.id)['questions'][0]['parked'])
        self.chats.items[self.id].update(state='uncertain', uncertain_since=time.time())
        self.chamber.sessions[self.chats.get(self.id)['session']]['messages'].clear()
        self.assertEqual(self.chats.status(self.id, include_messages=False)['state'], 'uncertain')
        with self.assertRaises(ValueError):
            self.chats.status('b' * 32, include_messages=False)

    def test_native_message_read_preserves_100_messages_without_400_record_prefetch(self):
        self.start()
        session = self.chamber.sessions[self.chats.get(self.id)['session']]
        for index in range(120):self.chamber.add(session, 'assistant', f'Reply {index}')
        with patch.object(self.chamber, 'request', wraps=self.chamber.request) as request:
            result = self.chamber.control('session.messages', sessionId=self.chats.get(self.id)['session'], limit=100)
        reads = [call.args[0] for call in request.call_args_list if '/message?' in call.args[0]]
        self.assertEqual(len(reads), 1)
        self.assertIn('limit=200', reads[0])
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
