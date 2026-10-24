"""Deploy pause flag: gateway full takeover, queue pump pause, admin CLI."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from urllib.error import HTTPError
from urllib.request import Request, build_opener

from support import TEMP_ROOT, NoRedirect, QuickServer, gateway, serve
from goodmorning.paths import WEB_ASSETS
from goodmorning.security.briefing_accounts import Accounts, Denied
from goodmorning.security import maintenance as deploy_pause
from goodmorning.security.briefing_gateway import POLICY, Gateway, handler_for


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Accounts(self.root, testing=True, n=1024)
        self.gateway = Gateway(self.store, {'gm.example.test': 'gm'}, testing=True)

    def test_flag_defaults_off_and_toggles(self):
        self.assertIsNone(deploy_pause.get_state(self.store))
        self.assertFalse(deploy_pause.is_paused(self.store))
        self.assertFalse(self.gateway.paused())
        deploy_pause.set_state(self.store, True, reason='deploy test', by='test')
        self.assertTrue(deploy_pause.is_paused(self.store))
        self.assertTrue(self.gateway.paused())
        self.assertEqual(deploy_pause.get_state(self.store)['enabled'], True)
        deploy_pause.set_state(self.store, False)
        self.assertFalse(self.gateway.paused())

    def test_reserve_is_blocked_while_paused(self):
        deploy_pause.set_state(self.store, True)
        with self.assertRaises(deploy_pause.MaintenancePaused):
            self.gateway._reserve_or_queue('chat', {'user': 'u', 'host': 'gm.example.test'},
                                           '/api/chats', {}, 'en')
        with self.assertRaises(deploy_pause.MaintenancePaused):
            self.gateway.chat_message('u', 'gm.example.test', '/api/chats',
                                      json.dumps({'id': 'a' * 32, 'mode': 'secretary', 'text': 'hi'}), {})
        with self.assertRaises(deploy_pause.MaintenancePaused):
            self.gateway.generate('u', 'gm.example.test',
                                  json.dumps({'date': '2026-10-14', 'kind': 'gm'}), {})

    def test_pump_reconciles_but_never_dispatches_while_paused(self):
        with self.store.db() as db:
            db.execute('INSERT INTO metadata VALUES (?,?)', ('generation_queue', json.dumps([
                {'kind': 'chat', 'candidate': {'user': 'u', 'host': 'gm.example.test', 'chat': 'a' * 32},
                 'user': 'u', 'host': 'gm.example.test', 'path': '/api/chats',
                 'body': {'id': 'a' * 32}, 'language': 'en', 'enqueued': 0}]))),
        deploy_pause.set_state(self.store, True)
        with patch.object(self.gateway, '_dispatch_queued') as dispatch, \
             patch.object(self.gateway, 'reconcile_ticket') as reconcile:
            self.gateway.pump_queue()
            reconcile.assert_called_once_with()
            dispatch.assert_not_called()
        with self.store.db() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='generation'").fetchone()
            self.assertIsNone(row)

    def test_static_page_is_served_and_styled_under_the_gateway_csp(self):
        static = (WEB_ASSETS / 'maintenance.html').read_bytes()
        self.assertEqual(deploy_pause.html_page(), static)
        text = static.decode()
        # style-src 'self' ignores inline styles, so the paused page must link its stylesheet.
        self.assertIn("style-src 'self'", POLICY)
        self.assertIn('<link rel="stylesheet" href="/maintenance.css">', text)
        for referenced in re.findall(r'(?:href|src)="/([^"]+)"', text):
            self.assertTrue((WEB_ASSETS / referenced).is_file(), referenced)
        self.assertEqual([re.search(r'lang="([^"]+)"', section)[1] for section in re.findall(r'<section [^>]*>', text)], ['en', 'zh-CN'])
        self.assertEqual(text.count('role="status"'), 2)

    def test_translation_catalog_covers_json_error(self):
        catalog = json.loads((WEB_ASSETS / 'translations.json').read_text(encoding='utf-8'))
        self.assertIn(deploy_pause.MESSAGE_EN, catalog)
        self.assertTrue(catalog[deploy_pause.MESSAGE_EN].strip())


class MaintenanceHttpTests(unittest.TestCase):
    """Full-takeover HTTP behavior: pages 503 HTML, APIs 503 JSON, assets exempt."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Accounts(self.root, testing=True, n=1024)
        self.gateway = Gateway(self.store, {'gm.example.test': 'gm'}, testing=True)
        self.server = serve(QuickServer(('127.0.0.1', 0), handler_for(self.gateway)))
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.opener = build_opener(NoRedirect())

    def request(self, path='/', body=None):
        headers = {'Host': 'gm.example.test', 'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1'}
        if body is not None:
            headers.update({'Origin': 'https://gm.example.test', 'Content-Type': 'application/json'})
        raw = json.dumps(body).encode() if body is not None else None
        try:
            response = self.opener.open(
                Request(f'http://127.0.0.1:{self.server.server_port}' + path, data=raw, headers=headers), timeout=3)
        except HTTPError as error:
            response = error
        with response:
            return response.status, dict(response.headers), response.read()

    def test_paused_takeover_and_release_exemptions(self):
        # Live first: unauthenticated root redirects to login.
        status, _, _ = self.request('/')
        self.assertEqual(status, 302)
        deploy_pause.set_state(self.store, True, reason='test', by='test')
        try:
            status, headers, body = self.request('/')
            self.assertEqual(status, 503)
            self.assertEqual(headers.get('Retry-After'), '60')
            self.assertIn('no-store', headers.get('Cache-Control', ''))
            self.assertEqual(body, deploy_pause.html_page())
            status, _, body = self.request('/login')
            self.assertEqual(status, 503)
            self.assertIn(b'maintenance-status', body)
            status, _, body = self.request('/api/queue')
            self.assertEqual((status, json.loads(body)), (503, deploy_pause.json_error()))
            status, _, _ = self.request('/api/chats', {'id': 'a' * 32, 'mode': 'secretary', 'text': 'hi'})
            self.assertEqual(status, 503)
            # Exemptions still serve while paused.
            status, _, _ = self.request('/api/release')
            self.assertEqual(status, 200)
            status, _, body = self.request('/maintenance.css')
            self.assertEqual(status, 200)
            self.assertIn(b'.maintenance-status', body)
            status, _, _ = self.request('/desk-secretary.png')
            self.assertEqual(status, 200)
        finally:
            deploy_pause.set_state(self.store, False)
        status, _, _ = self.request('/')
        self.assertEqual(status, 302)

    def test_built_in_page_is_served_when_the_static_file_is_missing(self):
        deploy_pause.set_state(self.store, True)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as empty, patch('goodmorning.paths.WEB_ASSETS', Path(empty)):
            status, headers, body = self.request('/')
        self.assertEqual((status, headers.get('Retry-After')), (503, '60'))
        text = body.decode()
        self.assertIn(deploy_pause.MESSAGE_EN, text)
        self.assertIn(deploy_pause.MESSAGE_ZH, text)
        self.assertIn('lang="zh-CN"', text)
        self.assertEqual(text.count('role="status"'), 2)


class MaintenanceSessionTests(unittest.TestCase):
    def test_paused_posts_keep_session_and_queue_but_logout_still_revokes(self):
        fixture = gateway(self)
        session = fixture.login()
        fixture.csrf = session['csrf']
        queue = json.dumps([{'kind': 'chat', 'candidate': {'user': fixture.id, 'host': 'gm.example.test', 'chat': 'a' * 32},
                             'user': fixture.id, 'host': 'gm.example.test', 'path': '/api/chats',
                             'body': {'id': 'a' * 32}, 'language': 'en', 'enqueued': 0}])
        with fixture.store.db() as db:
            db.execute('INSERT INTO metadata VALUES (?,?)', ('generation_queue', queue))
        language = fixture.store.website_language(fixture.id)
        deploy_pause.set_state(fixture.store, True)
        for path, body in (('/api/chats', {'id': 'b' * 32, 'mode': 'secretary', 'text': 'hi'}),
                           ('/api/generate', {'date': '2026-10-14', 'kind': 'gm'}),
                           ('/api/language', {'language': 'zh-CN'}),
                           ('/api/auth/password', {'current': 'temporary-alice-secret1', 'replacement': 'permanent-alice-secret1'})):
            status, _, raw = fixture.request(path, body)
            self.assertEqual((status, json.loads(raw)), (503, deploy_pause.json_error()), path)
        token = fixture.cookie.split('=', 1)[1]
        self.assertEqual(fixture.store.session(token, 'gm.example.test')['user_id'], fixture.id)
        self.assertEqual(fixture.store.website_language(fixture.id), language)
        with fixture.store.db() as db:
            self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='generation_queue'").fetchone()[0], queue)
        self.assertEqual(fixture.received, [])
        self.assertEqual(fixture.request('/api/auth/logout', {})[0], 200)
        with self.assertRaises(Denied):
            fixture.store.session(token, 'gm.example.test')


if __name__ == '__main__':
    unittest.main()
