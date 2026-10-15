"""Custom portrait validation, persistence and authenticated gateway round trips."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request

from PIL import Image
from support import TEMP_ROOT, FakeChamber
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web.avatar_images import MAX_AVATAR_BYTES, read_image
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.briefings.briefing_document import encode
import test_chat_uploads


def portrait(color='red', format='PNG', size=(90, 120)):
    output = io.BytesIO()
    Image.new('RGB', size, color).save(output, format=format)
    return output.getvalue()


class CustomAvatarTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'profile.md').write_text('timezone: Europe/London\nsecretary_language: English\n')
        self.app = BrowserApp(self.root, FakeChamber())

    def test_supported_formats_are_normalized_and_keep_all_defaults(self):
        for format in ('PNG', 'JPEG', 'WEBP'):
            settings = self.app.upload_avatar(portrait(format=format, size=(1800, 1200)))
            self.assertEqual(settings['avatar'], 'custom')
            self.assertEqual([item['id'] for item in settings['avatars']], ['f1', 'f2', 'm1', 'm2', 'custom'])
            with Image.open(io.BytesIO(read_image(self.root)[1])) as image:
                self.assertEqual(image.format, 'PNG')
                self.assertLessEqual(max(image.size), 1024)
                self.assertEqual(image.info, {})
        for filename in ('website-avatar.json', 'website-avatar-image.json'):
            self.assertEqual((self.root / filename).stat().st_mode & 0o777, 0o600)

    def test_restart_default_switch_and_account_isolation(self):
        self.app.upload_avatar(portrait())
        restarted = BrowserApp(self.root, FakeChamber())
        self.assertEqual(restarted.avatar(), 'custom')
        self.assertIn('data-avatar="custom"', restarted.chat_page().decode())
        other = self.root / 'other'; other.mkdir()
        self.assertNotIn('custom', BrowserApp(other, FakeChamber()).avatar_sources())
        self.app.set_avatar('m2')
        self.assertIn('custom', self.app.avatar_sources())
        self.app.set_avatar('custom')
        self.assertEqual(self.app.avatar(), 'custom')
        with self.assertRaises(ValueError):
            BrowserApp(other, FakeChamber()).set_avatar('custom')

    def test_photo_orientation_is_applied_and_private_metadata_is_removed(self):
        image = Image.new('RGB', (60, 90), 'blue')
        exif = Image.Exif()
        exif[274] = 6
        exif[315] = 'Private photographer'
        output = io.BytesIO()
        image.save(output, format='PNG', exif=exif, icc_profile=b'private profile')
        self.app.upload_avatar(output.getvalue())
        with Image.open(io.BytesIO(read_image(self.root)[1])) as normalized:
            self.assertEqual(normalized.size, (90, 60))
            self.assertEqual(normalized.info, {})

    def test_replacement_refreshes_saved_briefings_without_editing_them(self):
        day = self.app.today()
        daily = self.root / 'daily'; daily.mkdir()
        document = encode({'v': 1, 'greeting': 'Hello.', 'opening': 'Your saved briefing.',
                           'sections': [['notes', [['p', 'Keep this.']]]]})
        for kind in ('gm', 'gn'):
            (daily / f'{day}.{kind}.json').write_text(document)
        first = self.app.upload_avatar(portrait())['avatars'][-1]['src']
        for kind in ('gm', 'gn'):
            self.assertIn(first, self.app.page(day, kind, True).decode())
        second = self.app.upload_avatar(portrait('blue'))['avatars'][-1]['src']
        self.assertNotEqual(first, second)
        for kind in ('gm', 'gn'):
            self.assertIn(second, self.app.page(day, kind, True).decode())
            self.assertEqual((daily / f'{day}.{kind}.json').read_text(), document)
        self.assertEqual(self.app.chamber.calls, [])

    def test_invalid_uploads_preserve_previous_portrait(self):
        self.app.upload_avatar(portrait())
        previous = read_image(self.root)
        for data in (b'', b'<svg onload="alert(1)"/>', b'not an image', portrait()[:30],
                     b'x' * (MAX_AVATAR_BYTES + 1), portrait(size=(5000, 4000))):
            with self.assertRaises(ValueError):
                self.app.upload_avatar(data)
            self.assertEqual(read_image(self.root), previous)
            self.assertEqual(self.app.avatar(), 'custom')

    def test_symlink_storage_is_never_followed(self):
        target = self.root / 'untouched'; target.write_text('unchanged')
        for name in ('website-avatar-image.json', 'website-avatar.json'):
            path = self.root / name
            path.symlink_to(target)
            with self.assertRaises(ValueError):
                self.app.upload_avatar(portrait())
            self.assertEqual(target.read_text(), 'unchanged')
            path.unlink()


class CustomAvatarHTTPTests(unittest.TestCase):
    def setUp(self):
        self.backend_fixture = test_chat_uploads.UploadHTTPTests()
        self.backend_fixture.setUp()
        self.addCleanup(self.backend_fixture.doCleanups)
        self.fixture = self.backend_fixture.fixture

    def upload(self, data=None, headers=None):
        values = {'Host': 'gm.example.test', 'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1',
                  'Cookie': self.fixture.cookie or '', 'Origin': 'https://gm.example.test',
                  'X-Briefing-CSRF': self.fixture.csrf or '', 'Content-Type': 'application/octet-stream'}
        values.update(headers or {})
        request = Request(f'http://127.0.0.1:{self.fixture.server.server_port}/api/avatar/upload',
                          data=portrait() if data is None else data, headers=values)
        try:
            response = self.fixture.opener.open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_upload_image_and_selection_cross_gateway_without_model_calls(self):
        self.fixture.permanent()
        status, settings = self.upload()
        self.assertEqual(status, 201)
        url = settings['avatars'][-1]['src']
        status, headers, raw = self.fixture.request(url)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertTrue(raw.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(json.loads(self.fixture.request('/api/avatar')[2])['avatar'], 'custom')
        self.assertEqual(self.fixture.request('/api/avatar', {'avatar': 'f1'})[0], 200)
        self.assertEqual(self.fixture.request('/api/avatar', {'avatar': 'custom'})[0], 200)
        self.assertEqual(self.backend_fixture.chamber.calls, [])
        self.assertIsNone(self.fixture.gateway.ticket())
        self.assertEqual(self.fixture.request('/api/avatar/image/' + '0' * 64 + '.png')[0], 404)

    def test_authentication_csrf_origin_and_size_limits(self):
        self.assertEqual(self.upload()[0], 403)
        self.fixture.permanent()
        for headers in ({'Origin': 'https://evil.test'}, {'X-Briefing-CSRF': 'wrong'}, {'Cookie': ''}):
            self.assertEqual(self.upload(headers=headers)[0], 403)
        self.assertEqual(self.upload(b'', {'Content-Length': str(MAX_AVATAR_BYTES + 1)})[0], 413)
        self.assertEqual(self.upload(b'<svg/>')[0], 400)
        self.assertNotIn('custom', self.backend_fixture.app.avatar_sources())

    def test_image_urls_cannot_select_another_account(self):
        self.fixture.permanent()
        url = self.upload()[1]['avatars'][-1]['src']
        registry = self.fixture.root / 'backends.json'
        registry.write_text(json.dumps({self.fixture.other: {
            'port': self.backend_fixture.backend.server_port, 'key': self.fixture.key}}))
        self.assertNotEqual(self.fixture.request(url)[0], 200)


if __name__ == '__main__':
    unittest.main()
