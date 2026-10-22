"""Isolated, per-device palettes. No models, real accounts or private records."""
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


def device(headers):
    """The device cookie a color choice set, ready to send back."""
    return re.search(r'GoodMorningAppearance=[^;]+', headers['Set-Cookie'])[0]


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
        self.assertEqual(colors.DEFAULT, {'style': 'soft', 'day': 'morning-sky', 'night': 'starry'})
        self.assertEqual(set(colors.OPTIONS['style']), {'soft', 'pixel'})
        self.assertEqual(set(colors.OPTIONS['day']), {'classic', 'warm', 'morning-sky', 'first-light', 'grass-block', 'picnic'})
        self.assertEqual(set(colors.OPTIONS['night']), {'classic', 'starry', 'city-lights', 'midnight-violet', 'grass-block', 'picnic'})
        # Choices saved before styles existed stay soft.
        self.assertEqual(colors.validate({'day': 'warm', 'night': 'starry'}), {'style': 'soft', 'day': 'warm', 'night': 'starry'})
        self.assertEqual(colors.validate({'style': 'pixel', 'day': 'picnic', 'night': 'grass-block'}),
                         {'style': 'pixel', 'day': 'picnic', 'night': 'grass-block'})
        for scheme in ('morning-sky', 'first-light'):
            self.assertEqual(colors.validate({'day': scheme, 'night': 'starry'})['day'], scheme)
        for value in (None, True, [], {}, {'day': 'warm'}, {'day': 'warm', 'night': 'warm'},
                      {'day': 'sunlit-garden', 'night': 'starry'},
                      {'day': {}, 'night': 'classic'}, {'day': 'warm', 'night': 'classic', 'user': 'other'},
                      {'style': 'retro', 'day': 'warm', 'night': 'classic'}, {'style': True, 'day': 'warm', 'night': 'classic'},
                      {'style': 'soft', 'day': 'warm', 'night': 'classic', 'pixel': True}):
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
        self.assertNotIn(b'#drift', css)
        self.assertEqual(resources.paths[resources.urls['morning-clouds.webp']].mime, 'image/webp')
        self.assertIn(resources.urls['morning-clouds.webp'].encode(), css)
        self.assertIn(resources.urls['morning-clouds-continuation.webp'].encode(), css)
        # First Light no longer repeats its scene down long pages.
        self.assertIn(b'--day-scene: url("' + resources.urls['first-light.svg'].encode() + b'"); --day-repeat: no-repeat;', css)

    def test_new_night_schemes_are_translated_and_city_lights_scene_is_served(self):
        resources = Resources(Path(__file__).resolve().parents[1] / 'assets/web')
        css = resources.paths[resources.urls['color-schemes.css']].data.decode()
        for scheme in ('city-lights', 'midnight-violet'):
            self.assertEqual(colors.validate({'day': 'warm', 'night': scheme})['night'], scheme)
            self.assertIn(colors.OPTIONS['night'][scheme], ui.CATALOG)
            self.assertIn(f'[data-night-scheme="{scheme}"]', css)
        scene = resources.paths[resources.urls['city-lights.svg']]
        self.assertEqual(scene.mime, 'image/svg+xml')
        root = ET.fromstring(scene.data)
        self.assertEqual(root.findall('.//' + SVG + 'filter'), [])
        self.assertIsNone(root.find(SVG + 'style'))
        self.assertIn(resources.urls['city-lights.svg'] + '"', css)

    def test_retired_day_preference_preserves_night_and_does_not_rewrite_records(self):
        retired = {'day': 'sunlit-garden', 'night': 'classic'}
        expected = {'day': colors.DEFAULT['day'], 'night': 'classic', 'style': 'soft'}
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
            classic = {'day': 'warm', 'night': 'classic', 'style': 'soft'}
            colors.write(runtime, classic)
            self.assertEqual(colors.read(runtime), classic)
        fixture = gateway(self); fixture.permanent()
        classic = {'day': 'classic', 'night': 'classic', 'style': 'soft'}
        status, headers, _ = fixture.request('/api/color-schemes', classic)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(fixture.request('/api/color-schemes', headers={'Cookie': fixture.cookie+'; '+device(headers)})[2]), classic)

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
        with palette({'day': 'warm', 'night': 'starry', 'style': 'pixel'}):
            page = ui.page(source, 'session-csrf', '/chat')
        self.assertIn('data-day-scheme="warm"', page)
        self.assertIn('data-night-scheme="starry"', page)
        self.assertIn('data-style="pixel" data-day-scheme="warm"', page)
        self.assertIn('name="style" value="pixel" checked', page)
        self.assertIn('name="day" value="warm" checked', page)
        self.assertIn('name="night" value="starry" checked', page)
        self.assertEqual(page.count(' checked'), 3)
        self.assertEqual(page.count('id="color-scheme-form"'), 1)
        self.assertEqual(page.count('src="/color-schemes.js"'), 1)
        self.assertIn('&quot;csrf&quot;: &quot;session-csrf&quot;', page)
        self.assertNotIn('backend-csrf', page)

    def test_choices_belong_to_the_device_and_start_from_the_account(self):
        fixture = gateway(self); fixture.permanent()
        self.assertEqual(json.loads(fixture.request('/api/color-schemes')[2]), colors.DEFAULT)
        earlier = {'day': 'classic', 'night': 'classic', 'style': 'soft'}
        fixture.store.website_color_schemes(fixture.id, earlier)
        self.assertEqual(json.loads(fixture.request('/api/color-schemes')[2]), earlier)
        choice = {'day': 'warm', 'night': 'starry', 'style': 'pixel'}
        original = fixture.cookie
        status, headers, raw = fixture.request('/api/color-schemes', choice)
        self.assertEqual((status, json.loads(raw)), (200, choice))
        self.assertIn('GoodMorningAppearance=pixel.warm.starry; Path=/; Secure; SameSite=Lax;', headers['Set-Cookie'])
        self.assertEqual(fixture.cookie, original)
        # The account keeps its earlier choice for devices that have not chosen; this device shares its choice across hosts.
        self.assertEqual(fixture.store.website_color_schemes(fixture.id), earlier)
        self.assertEqual(json.loads(fixture.request('/api/color-schemes')[2]), earlier)
        for host in HOSTS:
            _, _, raw = fixture.request('/api/color-schemes', headers={'Host': host, 'Cookie': session_cookie(fixture, fixture.id, host)+'; '+device(headers)})
            self.assertEqual(json.loads(raw), choice)
        _, _, raw = fixture.request('/api/color-schemes', headers={'Cookie': fixture.cookie+'; GoodMorningAppearance=pixel.warm.evil'})
        self.assertEqual(json.loads(raw), earlier)
        # Signed out, the device's choice still applies; before devices, only the day scheme was kept.
        self.assertEqual(json.loads(fixture.request('/api/color-schemes', headers={'Cookie': device(headers)})[2]), choice)
        _, _, raw = fixture.request('/api/color-schemes', headers={'Cookie': 'GoodMorningDayScheme=warm'})
        self.assertEqual(json.loads(raw), {**colors.DEFAULT, 'day': 'warm'})
        self.assertIsNone(fixture.store.website_color_schemes(fixture.other))

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
            self.assertEqual(device(headers), 'GoodMorningAppearance=soft.warm.starry')
        status, headers = form_post(fixture, '/api/color-schemes', {'style': 'pixel', 'day': 'picnic', 'night': 'starry', 'csrf': fixture.csrf, 'return_to': '/chat'})
        self.assertEqual(device(headers), 'GoodMorningAppearance=pixel.picnic.starry')
        status, headers = form_post(fixture, '/api/color-schemes', {'day': 'warm', 'night': 'starry', 'theme': 'x', 'csrf': fixture.csrf, 'return_to': '/chat'})
        self.assertEqual(status, 400)
        self.assertNotIn('GoodMorningAppearance', headers.get('Set-Cookie', ''))
        self.assertIsNone(fixture.store.website_color_schemes(fixture.id))

    def test_proxy_headers_and_html_cache_are_server_owned(self):
        fixture = gateway(self); fixture.permanent()
        classic = fixture.request('/')[2]
        chosen = device(fixture.request('/api/color-schemes', {'day': 'warm', 'night': 'starry', 'style': 'pixel'})[1])
        warm = fixture.request('/', headers={'X-GoodMorning-Day-Scheme': 'classic', 'X-GoodMorning-Night-Scheme': 'classic',
                                             'X-GoodMorning-Style': 'soft', 'Cookie': fixture.cookie+'; '+chosen})[2]
        headers = {key.lower(): value for key, value in fixture.received[-1][1].items()}
        self.assertEqual(headers['x-goodmorning-day-scheme'], 'warm')
        self.assertEqual(headers['x-goodmorning-night-scheme'], 'starry')
        self.assertEqual(headers['x-goodmorning-style'], 'pixel')
        self.assertIn(b'&quot;day&quot;: &quot;morning-sky&quot;', classic)
        self.assertIn(b'&quot;day&quot;: &quot;warm&quot;', warm)
        self.assertIn(b'&quot;night&quot;: &quot;starry&quot;', warm)
        self.assertIsNone(fixture.store.website_color_schemes(fixture.id))

    def test_runtime_restart_and_briefing_cache_do_not_rewrite_saved_content(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            runtime = Path(directory); (runtime/'daily').mkdir()
            (runtime/'profile.md').write_text('city: London\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n')
            path = runtime/'daily/2026-10-11.gm.json'
            path.write_text(encode({'v': 1, 'greeting': 'Original title', 'opening': 'Keep this.', 'sections': [['notes', [['p', 'Exact wording.']]]]}))
            before = path.read_bytes(), (runtime/'profile.md').read_bytes()
            colors.write(runtime, {'day': 'warm', 'night': 'starry'})
            self.assertEqual(colors.read(runtime), {'day': 'warm', 'night': 'starry', 'style': 'soft'})
            app = BrowserApp(runtime, now=lambda: datetime(2026, 10, 11, 12, tzinfo=timezone.utc))
            for value in (colors.DEFAULT, colors.read(runtime), {**colors.read(runtime), 'style': 'pixel'}):
                with palette(value):
                    page = app.page('2026-10-11', 'gm', True).decode()
                    self.assertIn('data-day-scheme="'+value['day']+'"', page)
                    self.assertIn('data-night-scheme="'+value['night']+'"', page)
            self.assertEqual(len(app.pages.items), 3)
            self.assertEqual((path.read_bytes(), (runtime/'profile.md').read_bytes()), before)
            unsafe = runtime/'unsafe'; unsafe.mkdir()
            (unsafe/'website-color-schemes.json').symlink_to(runtime/'website-color-schemes.json')
            with self.assertRaises(ValueError): colors.read(unsafe)
            with self.assertRaises(ValueError): colors.write(unsafe, colors.DEFAULT)

    def test_style_is_independent_of_color_schemes_and_editions(self):
        def attributes(edition, value):
            with palette(value):
                page = colors.page(f'<html lang="en" data-edition="{edition}"><head></head><body></body></html>', 'csrf', '/')
            return re.search(r'<html[^>]*>', page)[0]
        # Color schemes only change colors; only the style changes components, for every scheme and edition.
        for edition in ('gm', 'gn'):
            for scene in ('grass-block', 'picnic', 'warm'):
                night = scene if scene != 'warm' else 'starry'
                for style in colors.OPTIONS['style']:
                    self.assertIn(f'data-style="{style}"', attributes(edition, {'style': style, 'day': scene, 'night': night}))
        for theme, choices in colors.OPTIONS.items():
            self.assertIn(colors.LEGENDS[theme], ui.CATALOG)
            for label in choices.values():
                self.assertIn(label, ui.CATALOG)

    def test_pixel_fonts_and_scenes_are_immutable_assets(self):
        resources = Resources(Path(__file__).resolve().parents[1] / 'assets/web')
        pixel = resources.paths[resources.urls['pixel.css']].data.decode()
        schemes = resources.paths[resources.urls['color-schemes.css']].data.decode()
        for font in ('pixelify-sans', 'silkscreen', 'jersey-10', 'fusion-pixel-zh'):
            url = resources.urls[f'fonts/{font}.woff2']
            self.assertEqual(resources.paths[url].mime, 'font/woff2')
            self.assertIn(f'url("{url}")', pixel)
        for scene in ('grass-block-day', 'grass-block-night', 'grass-block-stone-day', 'grass-block-stone-night',
                      'grass-block-sun', 'pixel-sun', 'pixel-moon', 'picnic-day', 'picnic-night'):
            root = ET.fromstring(resources.paths[resources.urls[scene + '.svg']].data)
            self.assertEqual(root.findall('.//' + SVG + 'script'), [])
            self.assertIn(f'url("{resources.urls[scene + ".svg"]}")', schemes + pixel)
        self.assertIn(b'SIL Open Font License', resources.paths[resources.urls['fonts/pixel-fonts-OFL.txt']].data)


if __name__ == '__main__':
    unittest.main()
