"""Isolated, account-wide palettes. No models, real accounts or private records."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web import color_schemes as colors, language as ui
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web.briefing_resources import Resources
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
        self.assertEqual(colors.DEFAULT, {'day': 'classic', 'night': 'starry'})
        self.assertEqual(set(colors.OPTIONS['day']), {'classic', 'warm', 'morning-sky', 'first-light'})
        self.assertEqual(set(colors.OPTIONS['night']), {'classic', 'starry'})
        self.assertEqual(colors.validate({'day': 'warm', 'night': 'starry'}), {'day': 'warm', 'night': 'starry'})
        for scheme in ('morning-sky', 'first-light'):
            self.assertEqual(colors.validate({'day': scheme, 'night': 'starry'})['day'], scheme)
        for value in (None, True, [], {}, {'day': 'warm'}, {'day': 'warm', 'night': 'warm'},
                      {'day': 'sunlit-garden', 'night': 'starry'},
                      {'day': {}, 'night': 'classic'}, {'day': 'warm', 'night': 'classic', 'user': 'other'}):
            with self.assertRaises(ValueError): colors.validate(value)

    def test_day_scenes_are_immutable_and_translated(self):
        resources = Resources(Path(__file__).resolve().parents[1] / 'assets/web')
        css = resources.paths[resources.urls['color-schemes.css']].data
        for scheme in ('morning-sky', 'first-light'):
            scene = resources.paths[resources.urls[scheme + '.svg']]
            self.assertEqual(scene.mime, 'image/svg+xml')
            root = ET.fromstring(scene.data)
            self.assertEqual(root.findall('{http://www.w3.org/2000/svg}filter'), [])
            if scheme == 'first-light':
                self.assertEqual(root.findall('{http://www.w3.org/2000/svg}circle'), [])
                self.assertEqual(root.findall('{http://www.w3.org/2000/svg}ellipse'), [])
            self.assertIn(resources.urls[scheme + '.svg'].encode(), css)
            self.assertIn(colors.OPTIONS['day'][scheme], ui.CATALOG)
        self.assertIn((resources.urls['morning-sky.svg'] + '#drift').encode(), css)
        self.assertEqual(resources.paths[resources.urls['morning-clouds.webp']].mime, 'image/webp')
        self.assertIn(resources.urls['morning-clouds.webp'].encode(), css)
        first_light = ET.fromstring(resources.paths[resources.urls['first-light.svg']].data)
        self.assertEqual(first_light.attrib['viewBox'], '0 0 1600 1800')
        for name in ('first-light-continuation.svg', 'morning-sky-continuation.svg', 'morning-clouds-continuation.webp'):
            self.assertIn(resources.urls[name].encode(), css)
        self.assertIn(b'--day-repeat: no-repeat, repeat-y', css)

    def test_retired_day_preference_preserves_night_and_does_not_rewrite_records(self):
        retired = {'day': 'sunlit-garden', 'night': 'classic'}
        expected = {'day': colors.DEFAULT['day'], 'night': 'classic'}
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            runtime = Path(directory)
            path = runtime / 'website-color-schemes.json'
            path.write_text(json.dumps(retired))
            original = path.read_bytes()
            self.assertEqual(colors.read(runtime), expected)
            self.assertEqual(path.read_bytes(), original)
        fixture = self.gateway(); fixture.permanent()
        key = 'website-color-schemes:' + fixture.id
        with fixture.store.db() as db:
            db.execute('INSERT INTO metadata VALUES (?,?)', (key, json.dumps(retired)))
        self.assertEqual(fixture.store.website_color_schemes(fixture.id), expected)
        self.assertEqual(json.loads(fixture.request('/api/color-schemes')[2]), expected)
        self.assertEqual(fixture.request('/api/color-schemes', retired)[0], 400)
        with fixture.store.db() as db:
            self.assertEqual(json.loads(db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()[0]), retired)

    def test_default_applies_only_without_a_saved_preference(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            runtime = Path(directory)
            self.assertEqual(colors.read(runtime), colors.DEFAULT)
            classic = {'day': 'warm', 'night': 'classic'}
            colors.write(runtime, classic)
            self.assertEqual(colors.read(runtime), classic)
        fixture = self.gateway(); fixture.permanent()
        classic = {'day': 'classic', 'night': 'classic'}
        self.assertEqual(fixture.request('/api/color-schemes', classic)[0], 200)
        self.assertEqual(json.loads(fixture.request('/api/color-schemes')[2]), classic)

    def test_star_field_is_irregular_and_served_as_an_immutable_asset(self):
        resources = Resources(Path(__file__).resolve().parents[1] / 'assets/web')
        sky = resources.paths[resources.urls['starry-sky.svg']]
        self.assertEqual(sky.mime, 'image/svg+xml')
        paths = ET.fromstring(sky.data).findall('{http://www.w3.org/2000/svg}path')
        points = [point for path in paths for point in re.findall(r'M([\d.]+) ([\d.]+)h', path.attrib['d'])]
        self.assertEqual(len(points), 540)
        self.assertEqual(len(set(points)), len(points))
        for axis in (0, 1):
            self.assertGreater(len({point[axis] for point in points}), len(points) * .9)
        self.assertEqual(len({path.attrib['stroke-width'] for path in paths}), 4)
        css = resources.paths[resources.urls['color-schemes.css']].data
        self.assertIn(resources.urls['starry-sky.svg'].encode(), css)
        self.assertIn(b'background-repeat: no-repeat', css)

    def test_twinkle_only_dims_highlights_and_keeps_the_static_sky(self):
        resources = Resources(Path(__file__).resolve().parents[1] / 'assets/web')
        root = ET.fromstring(resources.paths[resources.urls['starry-sky.svg']].data)
        self.assertEqual(root.attrib['id'], 'twinkle')
        paths = root.findall('{http://www.w3.org/2000/svg}path')
        self.assertEqual([path.attrib['stroke-width'] for path in paths],
            ['0.9', '1.3', '1.8', '2.3', '0.9', '1.3', '1.8', '2.3'])
        self.assertEqual([path.attrib['stroke-opacity'] for path in paths],
            ['0.28', '0.45', '0.65', '0.82', '0.28', '0.45', '0.65', '0.82'])
        self.assertEqual(len(root.findall('{http://www.w3.org/2000/svg}circle')), 8)
        style = root.find('{http://www.w3.org/2000/svg}style').text
        self.assertIn(':root:target path[stroke-width="1.8"]', style)
        self.assertIn(':root:target path[stroke-width="2.3"]', style)
        self.assertIn(':root:target circle', style)
        self.assertIn('0%, 20%, 100% { opacity: 1; } 55%, 65% { opacity: .12; }', style)
        self.assertIn('animation: twinkle 3.2s ease-in-out infinite', style)
        self.assertNotIn('transform', style)
        css = resources.paths[resources.urls['color-schemes.css']].data
        self.assertIn(b'@media (prefers-reduced-motion: no-preference)', css)
        self.assertIn((resources.urls['starry-sky.svg'] + '#twinkle').encode(), css)

    def test_server_markup_and_gateway_rewrapping_use_current_palette_and_csrf(self):
        source = '<html lang="en"><head></head><body><header>Desk</header></body></html>'
        with selected(colors.DEFAULT):
            source = ui.page(source, 'backend-csrf', '/chat')
        with selected({'day': 'warm', 'night': 'starry'}):
            page = ui.page(source, 'session-csrf', '/chat')
        self.assertIn('data-day-scheme="warm"', page)
        self.assertIn('data-night-scheme="starry"', page)
        self.assertIn('value="warm" data-ui-text="Warm" selected', page)
        self.assertIn('value="starry" data-ui-text="Starry" selected', page)
        self.assertEqual(page.count('id="color-scheme-form"'), 1)
        self.assertEqual(page.count('src="/color-schemes.js"'), 1)
        self.assertIn('&quot;csrf&quot;: &quot;session-csrf&quot;', page)
        self.assertNotIn('backend-csrf', page)

    def test_account_choices_sync_across_hosts_but_not_accounts(self):
        fixture = self.gateway(); fixture.permanent()
        self.assertEqual(json.loads(fixture.request('/api/color-schemes')[2]), colors.DEFAULT)
        choice = {'day': 'warm', 'night': 'starry'}
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
            raw = urlencode({'day': 'warm', 'night': 'starry', 'csrf': fixture.csrf, 'return_to': target}).encode()
            headers = {'Host': 'gm.example.test', 'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1',
                       'Cookie': fixture.cookie, 'Origin': 'https://gm.example.test', 'Content-Type': 'application/x-www-form-urlencoded'}
            try: response = fixture.opener.open(Request(f'http://127.0.0.1:{fixture.server.server_port}/api/color-schemes', data=raw, headers=headers))
            except HTTPError as error: response = error
            with response:
                self.assertEqual(response.status, 303)
                self.assertEqual(response.headers['Location'], '/chat' if target == '/chat' else '/')
        self.assertEqual(fixture.store.website_color_schemes(fixture.id), {'day': 'warm', 'night': 'starry'})

    def test_proxy_headers_and_html_cache_are_server_owned(self):
        fixture = self.gateway(); fixture.permanent()
        classic = fixture.request('/')[2]
        fixture.request('/api/color-schemes', {'day': 'warm', 'night': 'starry'})
        warm = fixture.request('/', headers={'X-GoodMorning-Day-Scheme': 'classic', 'X-GoodMorning-Night-Scheme': 'classic'})[2]
        headers = {key.lower(): value for key, value in fixture.received[-1][1].items()}
        self.assertEqual(headers['x-goodmorning-day-scheme'], 'warm')
        self.assertEqual(headers['x-goodmorning-night-scheme'], 'starry')
        self.assertIn(b'&quot;day&quot;: &quot;classic&quot;', classic)
        self.assertIn(b'&quot;day&quot;: &quot;warm&quot;', warm)
        self.assertIn(b'&quot;night&quot;: &quot;starry&quot;', warm)
        fixture.request('/api/auth/logout', {})
        self.assertEqual(fixture.store.website_color_schemes(fixture.id), {'day': 'warm', 'night': 'starry'})

    def test_runtime_restart_and_briefing_cache_do_not_rewrite_saved_content(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            runtime = Path(directory); (runtime/'daily').mkdir()
            (runtime/'profile.md').write_text('city: London\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n')
            path = runtime/'daily/2026-10-11.gm.json'
            path.write_text(encode({'v': 1, 'greeting': 'Original title', 'opening': 'Keep this.', 'sections': [['notes', [['p', 'Exact wording.']]]]}))
            before = path.read_bytes(), (runtime/'profile.md').read_bytes()
            colors.write(runtime, {'day': 'warm', 'night': 'starry'})
            self.assertEqual(colors.read(runtime), {'day': 'warm', 'night': 'starry'})
            app = BrowserApp(runtime, now=lambda: datetime(2026, 10, 11, 12, tzinfo=timezone.utc))
            for value in (colors.DEFAULT, colors.read(runtime)):
                with selected(value):
                    page = app.page('2026-10-11', 'gm', True).decode()
                    self.assertIn('data-day-scheme="'+value['day']+'"', page)
                    self.assertIn('data-night-scheme="'+value['night']+'"', page)
            self.assertEqual(len(app.pages.items), 2)
            self.assertEqual((path.read_bytes(), (runtime/'profile.md').read_bytes()), before)
            unsafe = runtime/'unsafe'; unsafe.mkdir()
            (unsafe/'website-color-schemes.json').symlink_to(runtime/'website-color-schemes.json')
            with self.assertRaises(ValueError): colors.read(unsafe)
            with self.assertRaises(ValueError): colors.write(unsafe, colors.DEFAULT)


if __name__ == '__main__':
    unittest.main()
