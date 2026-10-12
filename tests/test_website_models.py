"""User-selected website model beside the language setting, pinned per job/turn."""
import json
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.request import Request
from urllib.error import HTTPError

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web import models as site_models
from goodmorning.web import language as ui
from goodmorning.web.briefing_chat import Chats
from goodmorning.web.briefing_server import BrowserApp
from test_briefing_chat import MockChamber, ImmediateThread
from test_briefing_server import FakeChamber
import test_briefing_gateway as gateway_tests


@contextmanager
def selected_model(value):
    token = site_models.CURRENT.set(value)
    try:
        yield
    finally:
        site_models.CURRENT.reset(token)


@contextmanager
def selected_language(value):
    token = ui.CURRENT.set(value)
    try:
        yield
    finally:
        ui.CURRENT.reset(token)


class ModelCatalogTests(unittest.TestCase):
    def test_two_options_with_exact_engine_payloads(self):
        self.assertEqual(set(site_models.MODELS), {'muse-spark', 'deepseek-flash'})
        self.assertEqual(site_models.DEFAULT, 'muse-spark')
        self.assertEqual(site_models.session_payload('muse-spark'),
                         {'providerID': 'opencode-go', 'id': 'muse-spark-1.3-contributor', 'variant': 'xhigh'})
        self.assertEqual(site_models.session_payload('deepseek-flash'),
                         {'providerID': 'opencode-go', 'id': 'deepseek-v4.1-flash', 'variant': 'high'})

    def test_invalid_choices_rejected(self):
        for bad in ('gpt-4', '', None, {}, True, 'MUSE-SPARK', 'muse-spark-1.3-contributor', 'opencode-go/muse-spark-1.3-contributor'):
            with self.assertRaises(ValueError):
                site_models.model(bad)


class ModelSettingTests(unittest.TestCase):
    def gateway(self):
        fixture = gateway_tests.GatewayTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.gateway.hosts['sec.example.test'] = 'sec'
        return fixture

    def test_model_defaults_then_syncs_account_wide(self):
        fixture = self.gateway()
        fixture.permanent()
        status, _, body = fixture.request('/api/model')
        self.assertEqual((status, json.loads(body)['model']), (200, 'muse-spark'))
        self.assertIsNone(fixture.store.website_model(fixture.id))
        for bad in ('gpt-4', 'zh-CN', None, {}):
            self.assertEqual(fixture.request('/api/model', {'model': bad})[0], 400)
        self.assertIsNone(fixture.gateway.ticket())
        status, _, body = fixture.request('/api/model', {'model': 'deepseek-flash'})
        self.assertEqual((status, json.loads(body)['model']), (200, 'deepseek-flash'))
        self.assertEqual(fixture.store.website_model(fixture.id), 'deepseek-flash')
        for host in ('gm.example.test', 'gn.example.test', 'sec.example.test'):
            with fixture.store.db() as db:
                row = db.execute('SELECT * FROM users WHERE id=?', (fixture.id,)).fetchone()
                token, _ = fixture.store.issue(db, host, row)
            status, _, body = fixture.request('/api/model', headers={'Host': host, 'Cookie': '__Host-GoodMorning=' + token})
            self.assertEqual((status, json.loads(body)['model']), (200, 'deepseek-flash'))
        fixture.store.administer('alice', new_name='alice-new')
        self.assertEqual(fixture.store.website_model(fixture.id), 'deepseek-flash')

    def test_model_header_is_server_owned_not_client_chosen(self):
        fixture = self.gateway()
        fixture.permanent()
        fixture.store.website_model(fixture.id, 'deepseek-flash')
        fixture.request('/', headers={'X-GoodMorning-Model': 'muse-spark'})
        headers = {key.lower(): value for key, value in fixture.received[-1][1].items()}
        self.assertEqual(headers['x-goodmorning-model'], 'deepseek-flash')

    def test_non_javascript_model_switch_has_csrf_and_safe_redirect(self):
        fixture = self.gateway()
        fixture.permanent()
        raw = urlencode({'model': 'deepseek-flash', 'csrf': fixture.csrf, 'return_to': '/chat'}).encode()
        headers = {'Host': 'gm.example.test', 'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1',
                   'Cookie': fixture.cookie, 'Origin': 'https://gm.example.test',
                   'Content-Type': 'application/x-www-form-urlencoded'}
        try:
            response = fixture.opener.open(Request(f'http://127.0.0.1:{fixture.server.server_port}/api/model', data=raw, headers=headers))
        except HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, 303)
            self.assertEqual(response.headers['Location'], '/chat')
        self.assertEqual(fixture.store.website_model(fixture.id), 'deepseek-flash')


class DispatchModelTests(unittest.TestCase):
    def root(self):
        temporary = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'profile.md').write_text('secretary_language: English\ntimezone: Europe/London\ncity: London, GB\nnews_country: GB\n')
        (root / 'daily').mkdir()
        return root

    def test_briefing_pins_selected_model_and_switches_before_send(self):
        from datetime import datetime, timezone
        root = self.root()
        chamber = FakeChamber()
        app = BrowserApp(root, chamber, now=lambda: datetime(2026, 10, 10, 12, tzinfo=timezone.utc))
        with selected_language('en'), selected_model('deepseek-flash'):
            with patch('goodmorning.web.briefing_server.threading.Thread', ImmediateThread):
                job = app.start('2026-10-10', 'gm')['job']
        self.assertTrue(chamber.sent.wait(2))
        self.assertEqual(app.jobs['2026-10-10.gm']['model'], 'deepseek-flash')
        self.assertEqual([call[0] for call in chamber.calls],
                         ['session.create', '/api/session/ses_fixture/model', 'session.send'])
        self.assertEqual(chamber.calls[1], ('/api/session/ses_fixture/model',
                                            {'model': site_models.session_payload('deepseek-flash')}))

    def test_chat_turns_pin_model_and_switch_on_every_send(self):
        root = self.root()
        chamber = MockChamber(root)
        chats = Chats(root, chamber)
        with patch('goodmorning.web.briefing_chat.threading.Thread', ImmediateThread):
            with selected_language('en'), selected_model('deepseek-flash'):
                chats.start({'id': 'a' * 32, 'mode': 'secretary', 'text': 'Hello'})
            with selected_language('en'), selected_model('muse-spark'):
                chats.send('a' * 32, {'id': 'b' * 32, 'text': 'Follow up'})
        session = chamber.sessions[chats.get('a' * 32)['session']]
        self.assertEqual(session['model'], site_models.session_payload('muse-spark'))
        self.assertEqual(chats.get('a' * 32)['turns'][0]['model'], 'deepseek-flash')
        self.assertEqual(chats.get('a' * 32)['turns'][1]['model'], 'muse-spark')

    def test_model_switch_failure_leaves_dispatch_uncertain(self):
        from datetime import datetime, timezone
        root = self.root()
        chamber = FakeChamber()
        real_request = chamber.request

        def fail(path, body=None):
            if path.endswith('/model'):
                raise OSError('Synthetic model switch interruption')
            return real_request(path, body)

        chamber.request = fail
        app = BrowserApp(root, chamber, now=lambda: datetime(2026, 10, 10, 12, tzinfo=timezone.utc))
        record = {'id': 'a' * 32, 'date': '2026-10-10', 'kind': 'gm', 'state': 'starting',
                  'language': 'en', 'model': 'deepseek-flash'}
        with selected_language('en'), selected_model('deepseek-flash'):
            app.dispatch(record)
        self.assertEqual(record['state'], 'uncertain')
        self.assertFalse(chamber.sent.is_set())


if __name__ == '__main__':
    unittest.main()
