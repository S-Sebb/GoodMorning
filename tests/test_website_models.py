"""Automatic language/model routing and preservation of pinned jobs/turns."""
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from support import TEMP_ROOT, HOSTS, FakeChamber, MockChamber, ImmediateThread, complete_profile, gateway, selected, session_cookie, start_server
from goodmorning.web import models as site_models
from goodmorning.web import language as ui
from goodmorning.web.briefing_chat import Chats
from goodmorning.web.briefing_server import BrowserApp


def selected_model(value): return selected(site_models.CURRENT, value)
def selected_language(value): return selected(ui.CURRENT, value)


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

    def test_automatic_language_mapping(self):
        with selected_model(None):
            for language,model in (('en','muse-spark'),('zh-CN','deepseek-flash')):
                with selected_language(language):
                    self.assertEqual(site_models.current(),model)
                    self.assertEqual(site_models.for_language(language),model)
            with self.assertRaises(ValueError):
                site_models.for_language('fr')


class ModelSettingTests(unittest.TestCase):
    def test_model_routes_from_account_language_ignoring_legacy_preference(self):
        fixture = gateway(self)
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
        for host in HOSTS:
            status, _, body = fixture.request('/api/model', headers={'Host': host, 'Cookie': session_cookie(fixture, fixture.id, host)})
            self.assertEqual((status, json.loads(body)['model']), (200, 'deepseek-flash'))
        fixture.store.administer('alice', new_name='alice-new')
        self.assertEqual(fixture.store.website_model(fixture.id), 'muse-spark')

    def test_client_and_legacy_model_are_not_forwarded(self):
        fixture = gateway(self)
        fixture.permanent()
        fixture.store.website_model(fixture.id, 'deepseek-flash')
        fixture.request('/', headers={'X-GoodMorning-Model': 'muse-spark'})
        headers = {key.lower(): value for key, value in fixture.received[-1][1].items()}
        self.assertNotIn('x-goodmorning-model',headers)
        self.assertEqual(headers['x-goodmorning-language'],'en')
        self.assertEqual(json.loads(fixture.request('/api/model')[2])['model'],'muse-spark')

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
        complete_profile(root)
        (root / 'daily').mkdir()
        return root

    def test_new_briefings_pin_routed_or_override_model_and_switch_before_send(self):
        for language,override,model in (('en',None,'muse-spark'),('zh-CN',None,'deepseek-flash'),('en','deepseek-flash','deepseek-flash')):
            with self.subTest(language=language,override=override):
                chamber=FakeChamber()
                app=BrowserApp(self.root(),chamber,now=lambda:datetime(2026,10,10,12,tzinfo=timezone.utc))
                with selected_model(override),selected_language(language),patch('goodmorning.web.briefing_server.threading.Thread',ImmediateThread):
                    app.start('2026-10-10','gm')
                self.assertTrue(chamber.sent.is_set())
                job=app.jobs['2026-10-10.gm']
                self.assertEqual((job['language'],job['model']),(language,model))
                self.assertEqual(chamber.calls,[('session.create',chamber.calls[0][1]),
                                                ('/api/session/ses_fixture/model',{'model':site_models.session_payload(model)}),
                                                ('session.send',chamber.calls[2][1])])

    def test_chat_turns_pin_language_and_model_and_keep_request_idempotence(self):
        root=self.root()
        chamber=MockChamber(root)
        chats=Chats(root,chamber)
        with selected_model(None),patch('goodmorning.web.briefing_chat.threading.Thread',ImmediateThread):
            with selected_language('zh-CN'):
                chats.start({'id':'a'*32,'mode':'secretary','text':'Keep original wording.'})
            with selected_language('en'):
                chats.start({'id':'a'*32,'mode':'secretary','text':'Keep original wording.'})
                with selected_model('deepseek-flash'):
                    chats.send('a'*32,{'id':'b'*32,'text':'Explicit override.'})
                chats.send('a'*32,{'id':'c'*32,'text':'Routed again.'})
        prompts=[body['prompt'] for action,body in chamber.calls if action=='session.send']
        self.assertEqual(len(prompts),3)
        for prompt,language in zip(prompts,('zh-CN','en','en')):
            self.assertIn('Website language: '+language,prompt)
        self.assertEqual([(turn['language'],turn['model']) for turn in chats.get('a'*32)['turns']],
                         [('zh-CN','deepseek-flash'),('en','deepseek-flash'),('en','muse-spark')])
        self.assertEqual(chamber.sessions[chats.get('a'*32)['session']]['model'],site_models.session_payload('muse-spark'))
        self.assertEqual(chats.status('a'*32)['messages'][0]['text'],'Keep original wording.')

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

    def test_legacy_job_without_model_keeps_previous_default(self):
        chamber=FakeChamber()
        app=BrowserApp(self.root(),chamber)
        job={'id':'a'*32,'date':'2026-10-10','kind':'gm','state':'starting','language':'zh-CN'}
        with selected_model(None),selected_language('zh-CN'):
            app.dispatch(job)
        self.assertEqual(chamber.calls[1][1],{'model':site_models.session_payload(site_models.DEFAULT)})

    def test_local_http_routing_ignores_model_file_and_header(self):
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
