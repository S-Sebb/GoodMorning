"""Secretary avatar choice: validation, server persistence, page toggle and routes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.paths import WEB_ASSETS
from goodmorning.web import language as ui
from goodmorning.web.briefing_chat import AVATARS, AVATAR_IDS, avatar_id, page, read_avatar, write_avatar
from goodmorning.web.briefing_resources import Resources
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.security.briefing_gateway import GET_ROUTES, POST_ROUTES
from test_briefing_server import FakeChamber
from goodmorning.briefings.briefing_document import encode


class AvatarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'profile.md').write_text(
            'secretary_language: English\ntimezone: Europe/London\ncity: London, GB\nnews_country: GB\n')

    def test_ids_cover_two_female_and_two_male_scenes(self):
        self.assertEqual(AVATAR_IDS, ('f1', 'f2', 'm1', 'm2'))
        self.assertEqual([entry[1] for entry in AVATARS],
                         ['desk-secretary.png', 'desk-secretary-f2.png',
                          'desk-secretary-m1.png', 'desk-secretary-m2.png'])
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

    def test_page_places_arrows_beside_avatar_above_your_desk(self):
        html = page('csrf', True, True, None)
        self.assertIn('data-avatar-prev', html)
        self.assertIn('data-avatar-next', html)
        self.assertIn('aria-label="Previous avatar"', html)
        self.assertIn('aria-label="Next avatar"', html)
        self.assertIn('Avatar 1 of 4', html)
        self.assertIn('data-avatar="f1"', html)
        self.assertLess(html.index('desk-figure'), html.index('<p class="eyebrow">Your desk'))
        html = page('csrf', True, True, None, 'm2', {'m2': '/hashed/m2.png'})
        self.assertIn('src="/hashed/m2.png"', html)
        self.assertIn('Avatar 4 of 4', html)
        self.assertIn('data-avatar="m2"', html)
        self.assertIn('data-avatar="f1"', page('csrf', True, True, None, 'evil'))

    def test_settings_and_page_follow_saved_avatar(self):
        app = BrowserApp(self.root, FakeChamber())
        settings = app.chat_settings()
        self.assertEqual(settings['avatar'], 'f1')
        self.assertEqual([item['id'] for item in settings['avatars']], list(AVATAR_IDS))
        self.assertTrue(all(item['src'].startswith('/assets/') for item in settings['avatars']))
        self.assertIn('Avatar 1 of 4', app.chat_page().decode())
        self.assertEqual(app.set_avatar('f2'), 'f2')
        self.assertEqual(app.chat_settings()['avatar'], 'f2')
        rendered = app.chat_page().decode()
        self.assertIn('data-avatar="f2"', rendered)
        self.assertIn('Avatar 2 of 4', rendered)
        with self.assertRaises(ValueError):
            app.set_avatar('unknown')

    def test_resources_and_gateway_serve_all_four_scenes(self):
        resources = Resources(WEB_ASSETS)
        for _, filename, _ in AVATARS:
            self.assertIn(filename, resources.urls)
        self.assertTrue(GET_ROUTES.fullmatch('/api/avatar'))
        self.assertTrue(POST_ROUTES.fullmatch('/api/avatar'))
        for short in ('/desk-secretary.png', '/desk-secretary-f2.png',
                      '/desk-secretary-m1.png', '/desk-secretary-m2.png'):
            self.assertTrue(GET_ROUTES.fullmatch(short), short)
        hashed = '/assets/' + 'a' * 64 + '/desk-secretary-m1.png'
        self.assertTrue(GET_ROUTES.fullmatch(hashed))
        self.assertFalse(GET_ROUTES.fullmatch('/desk-secretary-evil.png'))

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
                    self.assertIn(f'class="briefing-avatar" data-avatar="{selected}"', rendered)
                    self.assertIn(f'src="{app.avatar_sources()[selected]}"', rendered)
                    self.assertNotIn('class="orbit"', rendered)
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
                self.assertIn('class="briefing-avatar" data-avatar="m2"', rendered)
                self.assertIn('alt="Secretary avatar"', rendered)
                self.assertNotIn('class="orbit"', rendered)
                self.assertNotIn('class="waiting-art"', rendered)
        self.assertEqual(app.chamber.calls, [])

    def test_avatar_strings_translate(self):
        catalog = json.loads((WEB_ASSETS / 'translations.json').read_text())
        for key in ('Secretary avatar', 'Previous avatar', 'Next avatar',
                    'Avatar {current} of {total}', 'Avatar could not be saved. Try again.'):
            self.assertIn(key, catalog)
        token = ui.CURRENT.set('zh-CN')
        try:
            self.assertEqual(ui.text('Next avatar'), '下一个形象')
            self.assertEqual(ui.text('Avatar {current} of {total}', current=3, total=4), '形象 3 / 4')
        finally:
            ui.CURRENT.reset(token)


if __name__ == '__main__':
    unittest.main()
