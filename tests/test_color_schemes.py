"""Isolated, account-wide palettes. No models, real accounts or private records."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET

from support import TEMP_ROOT, HOSTS, form_post, gateway, selected, session_cookie
from goodmorning.web import color_schemes as colors, language as ui
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web.briefing_resources import Resources
from goodmorning.briefings.briefing_document import encode
SVG = '{http://www.w3.org/2000/svg}'


def palette(value): return selected(colors.CURRENT, value)


def motion_only(css, fragment):
    """Every use of an animated scene fragment sits inside a no-preference reduced-motion block."""
    found, stack, start = 0, [], 0
    for index, char in enumerate(css):
        if char == '{':
            stack.append(css[start:index]); start = index + 1
        elif char == '}':
            stack.pop(); start = index + 1
        elif char == ';':
            start = index + 1
        if css.startswith(fragment, index):
            found += 1
            if not any('prefers-reduced-motion: no-preference' in prelude for prelude in stack):
                return False
    return found > 0


class ColorSchemeTests(unittest.TestCase):

    def test_catalog_and_invalid_requests(self):
        self.assertEqual(colors.DEFAULT, {'day': 'morning-sky', 'night': 'starry'})
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
            self.assertEqual(root.findall(SVG + 'filter'), [])
            if scheme == 'first-light':
                self.assertEqual(root.findall(SVG + 'circle'), [])
                self.assertEqual(root.findall(SVG + 'ellipse'), [])
            self.assertIn(resources.urls[scheme + '.svg'].encode(), css)
            self.assertIn(colors.OPTIONS['day'][scheme], ui.CATALOG)
        self.assertTrue(motion_only(css.decode(), resources.urls['morning-sky.svg'] + '#drift'))
        self.assertEqual(resources.paths[resources.urls['morning-clouds.webp']].mime, 'image/webp')
        self.assertIn(resources.urls['morning-clouds.webp'].encode(), css)
        for name in ('first-light-continuation.svg', 'morning-sky-continuation.svg', 'morning-clouds-continuation.webp'):
            self.assertIn(resources.urls[name].encode(), css)

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
        fixture = gateway(self); fixture.permanent()
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
        fixture = gateway(self); fixture.permanent()
        classic = {'day': 'classic', 'night': 'classic'}
        self.assertEqual(fixture.request('/api/color-schemes', classic)[0], 200)
        self.assertEqual(json.loads(fixture.request('/api/color-schemes')[2]), classic)

    def test_star_field_is_irregular_and_twinkles_only_when_motion_is_allowed(self):
        resources = Resources(Path(__file__).resolve().parents[1] / 'assets/web')
        sky = resources.paths[resources.urls['starry-sky.svg']]
        self.assertEqual(sky.mime, 'image/svg+xml')
        root = ET.fromstring(sky.data)
        points = [point for path in root.findall(SVG + 'path') for point in re.findall(r'M([\d.]+) ([\d.]+)h', path.attrib['d'])]
        self.assertGreater(len(points), 100)
        self.assertEqual(len(set(points)), len(points))
        for axis in (0, 1):
            self.assertGreater(len({point[axis] for point in points}), len(points) * .9)
        # The plain URL is a static sky; animation applies only when the page targets #twinkle.
        self.assertEqual(root.attrib['id'], 'twinkle')
        style = re.sub(r'/\*.*?\*/', '', root.find(SVG + 'style').text, flags=re.S)
        style = re.sub(r'@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}', '', style)
        animated = [selector for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', style) if 'animation' in body]
        self.assertTrue(animated)
        for selector in animated:
            self.assertTrue(all(part.strip().startswith(':root:target') for part in selector.split(',')), selector)
        self.assertNotIn('transform', style)
        css = resources.paths[resources.urls['color-schemes.css']].data.decode()
        self.assertIn(resources.urls['starry-sky.svg'] + '"', css)
        self.assertTrue(motion_only(css, resources.urls['starry-sky.svg'] + '#twinkle'))

    def test_server_markup_and_gateway_rewrapping_use_current_palette_and_csrf(self):
        source = '<html lang="en"><head></head><body><header>Desk</header></body></html>'
        with palette(colors.DEFAULT):
            source = ui.page(source, 'backend-csrf', '/chat')
        with palette({'day': 'warm', 'night': 'starry'}):
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
        fixture = gateway(self); fixture.permanent()
        self.assertEqual(json.loads(fixture.request('/api/color-schemes')[2]), colors.DEFAULT)
        choice = {'day': 'warm', 'night': 'starry'}
        original = fixture.cookie
        status, headers, raw = fixture.request('/api/color-schemes', choice)
        self.assertEqual((status, json.loads(raw)), (200, choice))
        self.assertIn('GoodMorningDayScheme=warm', headers['Set-Cookie'])
        self.assertEqual(fixture.cookie, original)
        for host in HOSTS:
            _, _, raw = fixture.request('/api/color-schemes', headers={'Host': host, 'Cookie': session_cookie(fixture, fixture.id, host)})
            self.assertEqual(json.loads(raw), choice)
        _, _, raw = fixture.request('/api/color-schemes', headers={'Cookie': session_cookie(fixture, fixture.other)+'; GoodMorningDayScheme=warm'})
        self.assertEqual(json.loads(raw), colors.DEFAULT)
        self.assertIsNone(fixture.store.website_color_schemes(fixture.other))
        fixture.store.administer('alice', new_name='alice-renamed')
        self.assertEqual(fixture.store.website_color_schemes(fixture.id), choice)

    def test_csrf_origin_and_unoffered_night_choices_are_rejected(self):
        fixture = gateway(self); fixture.permanent()
        choice = {'day': 'warm', 'night': 'classic'}
        self.assertEqual(fixture.request('/api/color-schemes', choice, headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(fixture.request('/api/color-schemes', choice, headers={'X-Briefing-CSRF': 'wrong'})[0], 403)
        for bad in ({'day': 'classic', 'night': 'warm'}, {'day': '<script>', 'night': 'classic'},
                    {'day': 'warm'}, {'day': 'warm', 'night': 'classic', 'user': fixture.other}):
            self.assertEqual(fixture.request('/api/color-schemes', bad)[0], 400)
        self.assertIsNone(fixture.store.website_color_schemes(fixture.id))
        self.assertIsNone(fixture.gateway.ticket())

    def test_non_javascript_form_and_redirect(self):
        fixture = gateway(self); fixture.permanent()
        for target in ('/chat', '//evil.example'):
            status, headers = form_post(fixture, '/api/color-schemes', {'day': 'warm', 'night': 'starry', 'csrf': fixture.csrf, 'return_to': target})
            self.assertEqual((status, headers['Location']), (303, '/chat' if target == '/chat' else '/'))
        self.assertEqual(fixture.store.website_color_schemes(fixture.id), {'day': 'warm', 'night': 'starry'})

    def test_proxy_headers_and_html_cache_are_server_owned(self):
        fixture = gateway(self); fixture.permanent()
        classic = fixture.request('/')[2]
        fixture.request('/api/color-schemes', {'day': 'warm', 'night': 'starry'})
        warm = fixture.request('/', headers={'X-GoodMorning-Day-Scheme': 'classic', 'X-GoodMorning-Night-Scheme': 'classic'})[2]
        headers = {key.lower(): value for key, value in fixture.received[-1][1].items()}
        self.assertEqual(headers['x-goodmorning-day-scheme'], 'warm')
        self.assertEqual(headers['x-goodmorning-night-scheme'], 'starry')
        self.assertIn(b'&quot;day&quot;: &quot;morning-sky&quot;', classic)
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
                with palette(value):
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
