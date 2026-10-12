"""Isolated, account-wide palettes. No models, real accounts or private records."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web import color_schemes as colors, language as ui
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.briefings.briefing_document import encode
import test_briefing_gateway as gateway_tests


@contextmanager
def selected(value):
    token = colors.CURRENT.set(value)
    try:
        yield
    finally:
        colors.CURRENT.reset(token)


class ColorSchemeTests(unittest.TestCase):
    def gateway(self):
        fixture = gateway_tests.GatewayTests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.gateway.hosts['sec.example.test'] = 'sec'
        return fixture

    def test_catalog_and_invalid_requests(self):
        self.assertEqual(set(colors.OPTIONS['day']), {'classic', 'warm'})
        self.assertEqual(set(colors.OPTIONS['night']), {'classic'})
        for value in (None, True, [], {}, {'day': 'warm'}, {'day': 'warm', 'night': 'warm'},
                      {'day': {}, 'night': 'classic'}, {'day': 'warm', 'night': 'classic', 'user': 'other'}):
            with self.assertRaises(ValueError): colors.validate(value)

    def test_server_markup_and_gateway_rewrapping_use_current_palette_and_csrf(self):
        source = '<html lang="en"><head></head><body><header>Desk</header></body></html>'
        with selected(colors.DEFAULT):
            source = ui.page(source, 'backend-csrf', '/chat')
        with selected({'day': 'warm', 'night': 'classic'}):
            page = ui.page(source, 'session-csrf', '/chat')
        self.assertIn('data-day-scheme="warm"', page)
        self.assertIn('data-night-scheme="classic"', page)
        self.assertIn('value="warm" data-ui-text="Warm" selected', page)
        self.assertEqual(page.count('id="color-scheme-form"'), 1)
        self.assertEqual(page.count('src="/color-schemes.js"'), 1)
        self.assertIn('&quot;csrf&quot;: &quot;session-csrf&quot;', page)
        self.assertNotIn('backend-csrf', page)

    def test_account_choices_sync_across_hosts_but_not_accounts(self):
        fixture = self.gateway(); fixture.permanent()
        self.assertEqual(json.loads(fixture.request('/api/color-schemes')[2]), colors.DEFAULT)
        choice = {'day': 'warm', 'night': 'classic'}
        original = fixture.cookie
        status, headers, raw = fixture.request('/api/color-schemes', choice)
        self.assertEqual((status, json.loads(raw)), (200, choice))
        self.assertIn('GoodMorningDayScheme=warm', headers['Set-Cookie'])
        self.assertEqual(fixture.cookie, original)
        for host in ('gm.example.test', 'gn.example.test', 'sec.example.test'):
            with fixture.store.db() as db:
                row = db.execute('SELECT * FROM users WHERE id=?', (fixture.id,)).fetchone()
                token, _ = fixture.store.issue(db, host, row)
            _, _, raw = fixture.request('/api/color-schemes', headers={'Host': host, 'Cookie': '__Host-GoodMorning='+token})
            self.assertEqual(json.loads(raw), choice)
        with fixture.store.db() as db:
            row = db.execute('SELECT * FROM users WHERE id=?', (fixture.other,)).fetchone()
            token, _ = fixture.store.issue(db, 'gm.example.test', row)
        _, _, raw = fixture.request('/api/color-schemes', headers={'Cookie': '__Host-GoodMorning='+token+'; GoodMorningDayScheme=warm'})
        self.assertEqual(json.loads(raw), colors.DEFAULT)
        self.assertIsNone(fixture.store.website_color_schemes(fixture.other))
        fixture.store.administer('alice', new_name='alice-renamed')
        self.assertEqual(fixture.store.website_color_schemes(fixture.id), choice)

    def test_csrf_origin_and_unoffered_night_choices_are_rejected(self):
        fixture = self.gateway(); fixture.permanent()
        choice = {'day': 'warm', 'night': 'classic'}
        self.assertEqual(fixture.request('/api/color-schemes', choice, headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(fixture.request('/api/color-schemes', choice, headers={'X-Briefing-CSRF': 'wrong'})[0], 403)
        for bad in ({'day': 'classic', 'night': 'warm'}, {'day': '<script>', 'night': 'classic'},
                    {'day': 'warm'}, {'day': 'warm', 'night': 'classic', 'user': fixture.other}):
            self.assertEqual(fixture.request('/api/color-schemes', bad)[0], 400)
        self.assertIsNone(fixture.store.website_color_schemes(fixture.id))
        self.assertIsNone(fixture.gateway.ticket())

    def test_non_javascript_form_and_redirect(self):
        fixture = self.gateway(); fixture.permanent()
        for target in ('/chat', '//evil.example'):
            raw = urlencode({'day': 'warm', 'night': 'classic', 'csrf': fixture.csrf, 'return_to': target}).encode()
            headers = {'Host': 'gm.example.test', 'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1',
                       'Cookie': fixture.cookie, 'Origin': 'https://gm.example.test', 'Content-Type': 'application/x-www-form-urlencoded'}
            try: response = fixture.opener.open(Request(f'http://127.0.0.1:{fixture.server.server_port}/api/color-schemes', data=raw, headers=headers))
            except HTTPError as error: response = error
            with response:
                self.assertEqual(response.status, 303)
                self.assertEqual(response.headers['Location'], '/chat' if target == '/chat' else '/')
        self.assertEqual(fixture.store.website_color_schemes(fixture.id), {'day': 'warm', 'night': 'classic'})

    def test_proxy_headers_and_html_cache_are_server_owned(self):
        fixture = self.gateway(); fixture.permanent()
        classic = fixture.request('/')[2]
        fixture.request('/api/color-schemes', {'day': 'warm', 'night': 'classic'})
        warm = fixture.request('/', headers={'X-GoodMorning-Day-Scheme': 'classic', 'X-GoodMorning-Night-Scheme': 'warm'})[2]
        headers = {key.lower(): value for key, value in fixture.received[-1][1].items()}
        self.assertEqual(headers['x-goodmorning-day-scheme'], 'warm')
        self.assertEqual(headers['x-goodmorning-night-scheme'], 'classic')
        self.assertIn(b'&quot;day&quot;: &quot;classic&quot;', classic)
        self.assertIn(b'&quot;day&quot;: &quot;warm&quot;', warm)
        fixture.request('/api/auth/logout', {})
        self.assertEqual(fixture.store.website_color_schemes(fixture.id), {'day': 'warm', 'night': 'classic'})

    def test_runtime_restart_and_briefing_cache_do_not_rewrite_saved_content(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            runtime = Path(directory); (runtime/'daily').mkdir()
            (runtime/'profile.md').write_text('city: London\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n')
            path = runtime/'daily/2026-10-11.gm.json'
            path.write_text(encode({'v': 1, 'greeting': 'Original title', 'opening': 'Keep this.', 'sections': [['notes', [['p', 'Exact wording.']]]]}))
            before = path.read_bytes(), (runtime/'profile.md').read_bytes()
            colors.write(runtime, {'day': 'warm', 'night': 'classic'})
            self.assertEqual(colors.read(runtime), {'day': 'warm', 'night': 'classic'})
            app = BrowserApp(runtime, now=lambda: datetime(2026, 10, 11, 12, tzinfo=timezone.utc))
            for value in (colors.DEFAULT, colors.read(runtime)):
                with selected(value):
                    page = app.page('2026-10-11', 'gm', True).decode()
                    self.assertIn('data-day-scheme="'+value['day']+'"', page)
            self.assertEqual(len(app.pages.items), 2)
            self.assertEqual((path.read_bytes(), (runtime/'profile.md').read_bytes()), before)
            unsafe = runtime/'unsafe'; unsafe.mkdir()
            (unsafe/'website-color-schemes.json').symlink_to(runtime/'website-color-schemes.json')
            with self.assertRaises(ValueError): colors.read(unsafe)
            with self.assertRaises(ValueError): colors.write(unsafe, colors.DEFAULT)


if __name__ == '__main__':
    unittest.main()
