"""Deploy pause flag: gateway full takeover, queue pump pause, admin CLI."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.security.briefing_accounts import Accounts
from goodmorning.security import maintenance as deploy_pause
from goodmorning.security.briefing_gateway import Gateway


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
        self.assertEqual(self.gateway.pause_state()['enabled'], True)
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
        from unittest.mock import patch
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

    def test_html_and_json_copies_share_wording(self):
        html = deploy_pause.html_page()
        self.assertIn(b'maintenance-status', html)
        self.assertIn(b'Please come back later', html)
        self.assertIn('请稍后再来'.encode(), html)
        self.assertIn(b'\xef\xbc\xbe', html)  # fullwidth ＾ in (＾▽＾)
        static = Path(__file__).resolve().parents[1] / 'assets' / 'web' / 'maintenance.html'
        self.assertTrue(static.is_file())
        text = static.read_bytes()
        self.assertIn(b'maintenance-status', text)
        self.assertIn(b'desk-secretary.png', text)
        self.assertIn(b'<style>', text)
        # Gateway file copy and module copy must agree on the core wording.
        self.assertIn(b'Please come back later', text + html)
        self.assertIn('请稍后再来'.encode(), text + html)
        css = Path(__file__).resolve().parents[1] / 'assets' / 'web' / 'maintenance.css'
        self.assertTrue(css.is_file())
        self.assertIn(b'.maintenance-status', css.read_bytes())

    def test_inline_style_matches_maintenance_css(self):
        import re
        static = Path(__file__).resolve().parents[1] / 'assets' / 'web' / 'maintenance.html'
        css = (Path(__file__).resolve().parents[1] / 'assets' / 'web' / 'maintenance.css').read_bytes()
        text = static.read_bytes()
        match = re.search(rb'<style>(.*?)</style>', text, re.S)
        self.assertIsNotNone(match, 'maintenance.html must carry its styles inline')
        self.assertEqual(match[1].decode().strip(), css.decode().strip())

    def test_translation_catalog_covers_json_error(self):
        import json as js
        catalog = js.loads((Path(__file__).resolve().parents[1] / 'assets' / 'web' / 'translations.json').read_text(encoding='utf-8'))
        self.assertIn(deploy_pause.MESSAGE_EN, catalog)
        self.assertTrue(catalog[deploy_pause.MESSAGE_EN].strip())


class MaintenanceHttpTests(unittest.TestCase):
    """Full-takeover HTTP behavior: pages 503 HTML, APIs 503 JSON, assets exempt."""

    def setUp(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Accounts(self.root, testing=True, n=1024)
        from goodmorning.security.briefing_gateway import handler_for
        self.gateway = Gateway(self.store, {'gm.example.test': 'gm'}, testing=True)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.gateway))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        from urllib.request import Request, build_opener, HTTPRedirectHandler

        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None
        self.opener = build_opener(NoRedirect())

    def request(self, path='/', body=None):
        import json as js
        from urllib.request import Request
        from urllib.error import HTTPError
        headers = {'Host': 'gm.example.test', 'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1'}
        if body is not None:
            headers.update({'Origin': 'https://gm.example.test', 'Content-Type': 'application/json'})
        raw = js.dumps(body).encode() if body is not None else None
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
            self.assertIn(b'maintenance-status', body)
            self.assertIn('请稍后再来'.encode(), body)
            status, _, body = self.request('/login')
            self.assertEqual(status, 503)
            self.assertIn(b'maintenance-status', body)
            status, _, body = self.request('/api/queue')
            self.assertEqual(status, 503)
            self.assertIn(b'maintained', body)
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


if __name__ == '__main__':
    unittest.main()
