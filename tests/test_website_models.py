"""Automatic language/model routing and preservation of pinned jobs/turns."""
import json
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from urllib.request import Request, urlopen
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
                         {'providerID': 'opencode', 'id': 'deepseek-v4.1-flash-free', 'variant': 'high'})

    def test_invalid_choices_rejected(self):
        for bad in ('gpt-4', '', None, {}, True, 'MUSE-SPARK', 'muse-spark-1.3-contributor', 'opencode-go/muse-spark-1.3-contributor'):
            with self.assertRaises(ValueError):
                site_models.model(bad)

    def test_automatic_language_mapping(self):
        with selected_model(None):
            for language,model in (('en','muse-spark'),('zh-CN','deepseek-flash')):
                with selected_language(language):
                    self.assertEqual(site_models.current(),model)
                    self.assertEqual(site_models.for_language(language),model)
            with self.assertRaises(ValueError):
                site_models.for_language('fr')


class ModelSettingTests(unittest.TestCase):
    def gateway(self):
        fixture = gateway_tests.GatewayTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.gateway.hosts['sec.example.test'] = 'sec'
        return fixture

    def test_model_routes_from_account_language_ignoring_legacy_preference(self):
        fixture = self.gateway()
        fixture.permanent()
        status, _, body = fixture.request('/api/model')
        self.assertEqual((status, json.loads(body)['model']), (200, 'muse-spark'))
        self.assertIsNone(fixture.store.website_model(fixture.id))
        for bad in ('gpt-4', 'zh-CN', None, {},'deepseek-flash'):
            self.assertEqual(fixture.request('/api/model', {'model': bad})[0], 405)
        self.assertIsNone(fixture.gateway.ticket())
        fixture.store.website_model(fixture.id,'muse-spark')
        status, _, _ = fixture.request('/api/language', {'language':'zh-CN'})
        self.assertEqual(status,200)
        status, _, body = fixture.request('/api/model')
        self.assertEqual((status, json.loads(body)['model']), (200, 'deepseek-flash'))
        self.assertEqual(fixture.store.website_model(fixture.id), 'muse-spark')
        for host in ('gm.example.test', 'gn.example.test', 'sec.example.test'):
            with fixture.store.db() as db:
                row = db.execute('SELECT * FROM users WHERE id=?', (fixture.id,)).fetchone()
                token, _ = fixture.store.issue(db, host, row)
            status, _, body = fixture.request('/api/model', headers={'Host': host, 'Cookie': '__Host-GoodMorning=' + token})
            self.assertEqual((status, json.loads(body)['model']), (200, 'deepseek-flash'))
        fixture.store.administer('alice', new_name='alice-new')
        self.assertEqual(fixture.store.website_model(fixture.id), 'muse-spark')

    def test_client_and_legacy_model_are_not_forwarded(self):
        fixture = self.gateway()
        fixture.permanent()
        fixture.store.website_model(fixture.id, 'deepseek-flash')
        fixture.request('/', headers={'X-GoodMorning-Model': 'muse-spark'})
        headers = {key.lower(): value for key, value in fixture.received[-1][1].items()}
        self.assertNotIn('x-goodmorning-model',headers)
        self.assertEqual(headers['x-goodmorning-language'],'en')
        self.assertEqual(json.loads(fixture.request('/api/model')[2])['model'],'muse-spark')

    def test_old_model_form_cannot_change_preference(self):
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
            self.assertEqual(response.status, 405)
        self.assertIsNone(fixture.store.website_model(fixture.id))

    def test_settings_has_language_but_no_model_selector(self):
        for language in ('en','zh-CN'):
            with selected_language(language):
                page=ui.page('<html><head></head><body></body></html>',None)
            self.assertIn('id="website-language"',page)
            self.assertNotIn('model-form',page)
            self.assertNotIn('website-model',page)
            self.assertNotIn('/model.js',page)


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

    def test_new_chat_turns_route_on_language_change(self):
        root=self.root()
        chamber=MockChamber(root)
        chats=Chats(root,chamber)
        with selected_model(None),patch('goodmorning.web.briefing_chat.threading.Thread',ImmediateThread):
            with selected_language('en'):
                chats.start({'id':'a'*32,'mode':'secretary','text':'Hello'})
            with selected_language('zh-CN'):
                chats.send('a'*32,{'id':'b'*32,'text':'你好'})
        turns=chats.get('a'*32)['turns']
        self.assertEqual([(turn['language'],turn['model']) for turn in turns],
                         [('en','muse-spark'),('zh-CN','deepseek-flash')])
        self.assertEqual(chamber.sessions[chats.get('a'*32)['session']]['model'],
                         site_models.session_payload('deepseek-flash'))

    def test_queued_legacy_briefing_keeps_original_model_and_language(self):
        root=self.root()
        chamber=FakeChamber()
        app=BrowserApp(root,chamber)
        job={'id':'a'*32,'date':'2026-10-10','kind':'gm','state':'starting',
             'language':'en','model':'deepseek-flash'}
        with selected_language('zh-CN'),selected_model(None):
            app.dispatch(job)
        self.assertIn('Website language: en',chamber.calls[-1][1]['prompt'])
        self.assertEqual(chamber.calls[1][1],{'model':site_models.session_payload('deepseek-flash')})

    def test_new_briefings_use_language_route(self):
        from datetime import datetime,timezone
        for language,model in (('en','muse-spark'),('zh-CN','deepseek-flash')):
            with self.subTest(language=language):
                chamber=FakeChamber()
                app=BrowserApp(self.root(),chamber,now=lambda:datetime(2026,10,10,12,tzinfo=timezone.utc))
                with selected_model(None),selected_language(language),patch('goodmorning.web.briefing_server.threading.Thread',ImmediateThread):
                    app.start('2026-10-10','gm')
                job=app.jobs['2026-10-10.gm']
                self.assertEqual((job['language'],job['model']),(language,model))
                self.assertEqual(chamber.calls[1][1],{'model':site_models.session_payload(model)})

    def test_legacy_job_without_model_keeps_previous_default(self):
        chamber=FakeChamber()
        app=BrowserApp(self.root(),chamber)
        job={'id':'a'*32,'date':'2026-10-10','kind':'gm','state':'starting','language':'zh-CN'}
        with selected_model(None),selected_language('zh-CN'):
            app.dispatch(job)
        self.assertEqual(chamber.calls[1][1],{'model':site_models.session_payload(site_models.DEFAULT)})

    def test_local_http_routing_ignores_model_file_and_header(self):
        from test_weekly_schedule import start_server
        root=self.root()
        legacy=root/'website-model.json'
        legacy.write_text('{"model":"muse-spark"}\n')
        original=legacy.read_bytes()
        (root/'website-language.json').write_text('{"language":"zh-CN"}')
        app=BrowserApp(root)
        server=start_server(app)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        origin=f'http://127.0.0.1:{server.server_port}'
        with urlopen(Request(origin+'/api/model',headers={'X-GoodMorning-Model':'muse-spark'})) as response:
            self.assertEqual(json.load(response)['model'],'deepseek-flash')
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(origin+'/api/model',data=b'{"model":"muse-spark"}',headers={
                'Content-Type':'application/json','Origin':origin,'X-Briefing-CSRF':app.csrf}))
        self.assertEqual(error.exception.code,405)
        error.exception.close()
        self.assertEqual(legacy.read_bytes(),original)

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
