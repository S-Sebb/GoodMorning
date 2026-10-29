"""Secretary avatar choice: validation, server persistence, Account menu picker and routes."""
from pathlib import Path
import tempfile
import unittest

from support import TEMP_ROOT, FakeChamber, selected
from goodmorning.paths import WEB_ASSETS
from goodmorning.web import language as ui
from goodmorning.web.briefing_chat import AVATAR_FILES, AVATAR_IDS, avatar_id, page, read_avatar, write_avatar
from goodmorning.web.briefing_resources import Resources
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.security.briefing_gateway import GET_ROUTES, POST_ROUTES
from goodmorning.briefings.briefing_document import encode
from goodmorning.briefings.briefing_layout import celestial


class AvatarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'profile.md').write_text(
            'secretary_language: English\ntimezone: Europe/London\ncity: London, GB\nnews_country: GB\n')

    def test_ids_cover_two_female_and_two_male_scenes(self):
        self.assertEqual(AVATAR_IDS, ('f1', 'f2', 'm1', 'm2'))
        for bad in ('', 'F1', 'male-1', '../desk-secretary.png', None, 1):
            with self.assertRaises(ValueError):
                avatar_id(bad)

    def test_storage_defaults_and_rejects_symlinks(self):
        self.assertEqual(read_avatar(self.root), 'f1')
        self.assertEqual(write_avatar(self.root, 'm1'), 'm1')
        self.assertEqual(read_avatar(self.root), 'm1')
        (self.root / 'website-avatar.json').write_text('not json')
        self.assertEqual(read_avatar(self.root), 'f1')
        with self.assertRaises(ValueError):
            write_avatar(self.root, 'unknown')
        target = self.root / 'real.json'
        target.write_text('{"avatar": "f2"}')
        (self.root / 'website-avatar.json').unlink()
        (self.root / 'website-avatar.json').symlink_to(target)
        with self.assertRaises(ValueError):
            read_avatar(self.root)
        with self.assertRaises(ValueError):
            write_avatar(self.root, 'f1')

    def test_portrait_only_shows_the_avatar(self):
        html = page('csrf', True, True, None)
        self.assertIn('href="/avatar.css"', html)
        self.assertIn('src="/avatar.js"', html)
        self.assertNotIn('<button', html.split('avatar-display', 1)[1].split('</figure>', 1)[0])
        self.assertIn('data-avatar="f1"', html)
        self.assertLess(html.index('desk-figure'), html.index('<p class="eyebrow">' + ui.text('Your desk')))
        html = page('csrf', True, True, None, 'm2', {'m2': {'day': '/hashed/m2-day.png', 'night': '/hashed/m2.png', 'profile': '/hashed/m2-profile.png'}})
        self.assertIn('class="avatar-image" src="/hashed/m2-day.png"', html)
        self.assertIn('data-profile="/hashed/m2-profile.png"', html)
        self.assertIn('data-avatar="m2"', html)
        self.assertIn('class="avatar-image" src="/desk-secretary-m1.png"', page('csrf', True, True, None, 'm1', theme='gn'))
        self.assertIn('data-avatar="f1"', page('csrf', True, True, None, 'evil'))

    def test_account_menu_holds_the_avatar_picker(self):
        source = '<html><head></head><body><main></main></body></html>'
        signed_in = ui.page(source.replace('</body>', '<nav class="account-tools" aria-label="Account"></nav></body>'), 'csrf')
        account = signed_in.split('id="account-menu"', 1)[1]
        self.assertIn('id="avatar-settings"', account)
        self.assertNotIn('id="avatar-settings"', signed_in.split('id="account-menu"', 1)[0])
        self.assertIn('src="/avatar.js"', signed_in)
        # Without an account, viewer pages keep it in Settings; the sign-in page has none.
        self.assertIn('id="avatar-settings"', ui.page(source, 'csrf', avatars=True).split('id="prefs-menu"', 1)[1])
        sign_in = ui.page(source, 'csrf')
        self.assertNotIn('id="avatar-settings"', sign_in)
        self.assertNotIn('/avatar.js', sign_in)
        # A page that already loads the script does not load it twice.
        self.assertEqual(ui.page(source.replace('</body>', '<script src="/avatar.js" defer></script></body>'), 'csrf', avatars=True).count('/avatar.js'), 1)

    def test_settings_and_page_follow_saved_avatar(self):
        app = BrowserApp(self.root, FakeChamber())
        settings = app.chat_settings()
        self.assertEqual(settings['avatar'], 'f1')
        self.assertEqual([item['id'] for item in settings['avatars']], list(AVATAR_IDS))
        self.assertTrue(all(item[variant].startswith('/assets/') for item in settings['avatars'] for variant in ('day', 'night', 'profile')))
        self.assertIn('data-avatar="f1"', app.chat_page().decode())
        self.assertEqual(app.set_avatar('f2'), 'f2')
        self.assertEqual(app.chat_settings()['avatar'], 'f2')
        rendered = app.chat_page().decode()
        self.assertIn('data-avatar="f2"', rendered)
        self.assertIn('id="avatar-settings"', rendered)
        with self.assertRaises(ValueError):
            app.set_avatar('unknown')

    def test_resources_and_gateway_serve_every_scene_and_profile(self):
        resources = Resources(WEB_ASSETS)
        filenames = [name for files in AVATAR_FILES.values() for name in files.values()]
        self.assertEqual(len(set(filenames)), 20)
        for filename in filenames:
            self.assertIn(filename, resources.urls)
            self.assertTrue(GET_ROUTES.fullmatch('/' + filename), filename)
        self.assertTrue(GET_ROUTES.fullmatch('/api/avatar'))
        self.assertTrue(POST_ROUTES.fullmatch('/api/avatar'))
        for variant in ('day', 'night', 'profile'):
            self.assertTrue(POST_ROUTES.fullmatch('/api/avatar/upload/' + variant))
        self.assertFalse(POST_ROUTES.fullmatch('/api/avatar/upload'))
        hashed = '/assets/' + 'a' * 64 + '/desk-secretary-m1.png'
        self.assertTrue(GET_ROUTES.fullmatch(hashed))
        self.assertFalse(GET_ROUTES.fullmatch('/desk-secretary-evil.png'))
        self.assertFalse(GET_ROUTES.fullmatch('/desk-secretary-profile-animated.png'))

    def test_built_in_portraits_animate_only_without_reduced_motion(self):
        from PIL import Image
        for files in AVATAR_FILES.values():
            for still, moving in (('day', 'dayAnimated'), ('night', 'nightAnimated')):
                with Image.open(WEB_ASSETS / files[still]) as base, Image.open(WEB_ASSETS / files[moving]) as image:
                    self.assertTrue(image.is_animated, files[moving])
                    self.assertEqual(image.size, base.size)
                    self.assertEqual(image.convert('RGBA').getextrema()[3][0], 0, 'Background stays transparent')
        source = '<source media="(prefers-reduced-motion: no-preference)" srcset="/desk-secretary-m1-animated.png">'
        self.assertIn(source + '<img class="avatar-image" src="/desk-secretary-m1.png"', page('csrf', True, True, None, 'm1', theme='gn'))
        self.assertIn('srcset="/desk-secretary-day-animated.png"', page('csrf', True, True, None))
        # Picker previews and the round profile stay still.
        self.assertEqual(page('csrf', True, True, None).count('-animated.png"'), 1)
        custom = {'custom': {'day': '/api/avatar/image/' + 'a' * 64 + '.png', 'night': '/api/avatar/image/' + 'b' * 64 + '.png', 'profile': None}}
        self.assertNotIn('<source', page('csrf', True, True, None, 'custom', custom))

    def test_avatar_is_private_per_runtime_and_survives_viewer_restart(self):
        profiles = {}
        apps = {}
        for name in ('alice', 'bob'):
            runtime = self.root / name
            runtime.mkdir(mode=0o700)
            profile = runtime / 'profile.md'
            profile.write_bytes((self.root / 'profile.md').read_bytes())
            profiles[name] = profile.read_bytes()
            apps[name] = BrowserApp(runtime, FakeChamber())
        apps['alice'].set_avatar('f2')
        apps['bob'].set_avatar('m2')
        for name, selected in (('alice', 'f2'), ('bob', 'm2')):
            runtime = self.root / name
            self.assertEqual((runtime / 'website-avatar.json').stat().st_mode & 0o777, 0o600)
            restarted = BrowserApp(runtime, FakeChamber())
            self.assertEqual(restarted.avatar(), selected)
            self.assertEqual(restarted.chat_settings()['avatar'], selected)
            self.assertIn(f'data-avatar="{selected}"', restarted.chat_page().decode())
            for kind in ('gm', 'gn'):
                self.assertIn(f'data-avatar="{selected}"', restarted.page(restarted.today(), kind, False).decode())
            self.assertEqual((runtime / 'profile.md').read_bytes(), profiles[name])
        apps['alice'].set_avatar('m1')
        self.assertEqual(BrowserApp(self.root / 'alice', FakeChamber()).avatar(), 'm1')
        self.assertEqual(apps['bob'].avatar(), 'm2')

    def test_briefings_show_selected_avatar_without_rewriting_saved_content(self):
        app = BrowserApp(self.root, FakeChamber())
        day = app.today()
        (self.root / 'daily').mkdir()
        document = encode({'v': 1, 'greeting': 'Hello.', 'opening': 'A saved greeting.',
                           'sections': [['notes', [['p', 'Keep this saved content.']]]]})
        for kind in ('gm', 'gn'):
            source = self.root / 'daily' / f'{day}.{kind}.json'
            source.write_text(document)
            for selected in AVATAR_IDS:
                app.set_avatar(selected)
                for pinned in (False, True):
                    rendered = app.page(day, kind, pinned).decode()
                    self.assertIn(f'class="briefing-avatar avatar-display" data-avatar="{selected}"', rendered)
                    self.assertIn(f'src="{app.avatar_sources()[selected]["night" if kind == "gn" else "day"]}"', rendered)
                    self.assertIn('class="orbit"', rendered)
                    self.assertTrue(celestial(kind).casefold() in rendered.casefold(), 'Original edition SVG must be retained')
                    self.assertIn('class="letter-copy"', rendered)
                    self.assertNotIn('class="secretary-panel"', rendered)
                    self.assertNotIn('class="briefing-tools"', rendered)
                    self.assertNotIn('href="/chat"><img', rendered)
                    self.assertIn('width="220" height="220"', rendered)
                    self.assertIn('Keep this saved content.', rendered)
                    self.assertEqual(source.read_text(), document)
        self.assertEqual(app.chamber.calls, [])

    def test_preview_waiting_and_setup_pages_share_the_avatar(self):
        app = BrowserApp(self.root, FakeChamber())
        app.set_avatar('m2')
        for kind in ('gm', 'gn'):
            preview = app.page(app.today(), kind, False).decode()
            archive = app.page(app.dates()[1], kind, True).decode()
            setup = app.initialization_page(kind).decode()
            for rendered in (preview, archive, setup):
                self.assertIn('class="briefing-avatar avatar-display" data-avatar="m2"', rendered)
                self.assertIn('alt="' + ui.text('Secretary avatar') + '"', rendered)
                self.assertTrue(celestial(kind).casefold() in rendered.casefold(), 'Original edition SVG must be retained')
            self.assertIn('class="orbit"', preview)
            self.assertIn('class="waiting-art"', archive)
            self.assertIn('class="waiting-art"', setup)
        self.assertEqual(app.chamber.calls, [])

    def test_generation_questions_stay_out_of_the_avatar_picker(self):
        app = BrowserApp(self.root, FakeChamber())
        rendered = app.page(app.today(), 'gm', False).decode()
        panel = rendered.split('class="briefing-avatar avatar-display"', 1)[1].split('</figure>', 1)[0]
        self.assertIn('id="generate"', rendered)
        self.assertIn('id="generation-progress"', rendered)
        self.assertNotIn('id="agent-questions"', panel)
        self.assertEqual(rendered.count('id="agent-questions"'), 1)
        self.assertEqual(rendered.count('class="briefing-avatar avatar-display"'), 1)

    def test_avatar_strings_translate(self):
        for key in ('Secretary avatar', 'Secretary avatars', 'Upload your own avatar', 'Avatar {number}',
                    'Saving avatar…', 'Avatar could not be saved. Try again.'):
            self.assertTrue(ui.CATALOG.get(key, '').strip(), key)
        with selected(ui.CURRENT, 'zh-CN'):
            self.assertNotEqual(ui.text('Secretary avatar'), 'Secretary avatar')

if __name__ == '__main__':
    unittest.main()
