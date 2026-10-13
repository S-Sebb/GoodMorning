"""Small avatar-inspection images without changing originals, records or publications."""
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web.avatar_preview import create, main, PREVIEW_DIRECTORY
from goodmorning.cli import main as cli


class AvatarPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'secretary'
        self.runtime.mkdir()
        self.source = self.root / 'original.png'
        Image.new('RGBA', (900, 1800), (19, 71, 37, 128)).save(self.source)
        for name in ('profile.md', 'website-avatar-image.json', 'browser-chats/chats.json', 'daily/saved.gm.json'):
            path = self.runtime / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'Preserved synthetic record')

    def test_dimensions_alpha_lossless_preview_and_originals_are_preserved(self):
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        result = create(self.runtime, self.source)
        self.assertEqual((result['width'], result['height']), (256, 512))
        self.assertEqual((result['original_width'], result['original_height']), (900, 1800))
        self.assertTrue(result['original_preserved'])
        preview = Path(result['preview'])
        self.assertEqual(preview.stat().st_mode & 0o777, 0o600)
        self.assertEqual(preview.parent.stat().st_mode & 0o777, 0o700)
        with Image.open(self.source) as image:
            expected = image.convert('RGBA')
            expected.thumbnail((512, 512), Image.Resampling.LANCZOS)
        with Image.open(preview) as image:
            self.assertEqual(image.format, 'WEBP')
            self.assertEqual(image.convert('RGBA').tobytes(), expected.tobytes())
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_repeat_reads_reuse_one_preview_and_revisions_preserve_earlier_previews(self):
        first = create(self.runtime, self.source)
        before = Path(first['preview']).read_bytes()
        second = create(self.runtime, self.source)
        self.assertEqual(first['preview'], second['preview'])
        self.assertTrue(second['reused'])
        self.assertEqual(len(list((self.runtime / PREVIEW_DIRECTORY).glob('*.webp'))), 1)
        Image.new('RGBA', (900, 1800), 'blue').save(self.source)
        third = create(self.runtime, self.source)
        self.assertNotEqual(first['preview'], third['preview'])
        self.assertEqual(Path(first['preview']).read_bytes(), before)

    def test_stock_avatar_cache_plus_native_payload_is_smaller_than_original_native_payload(self):
        assets = Path(__file__).resolve().parents[1] / 'assets/web'
        original_native = optimized_storage = 0
        for name in ('desk-secretary.png', 'desk-secretary-f2.png', 'desk-secretary-m1.png'):
            source = assets / name
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            result = create(self.runtime, source)
            original_native += len(base64.b64encode(source.read_bytes()))
            preview = Path(result['preview']).read_bytes()
            optimized_storage += len(preview) + len(base64.b64encode(preview))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        # Count both the retained preview file and its new native inline image.
        self.assertLess(optimized_storage, original_native * 0.4)

    def test_invalid_sources_do_not_initialize_records_or_read_environment_files(self):
        missing = self.root / 'missing-runtime'
        with self.assertRaises(ValueError):
            create(missing, self.source)
        self.assertFalse(missing.exists())
        secret = self.root / '.env.png'
        with patch.object(Path, 'open', side_effect=AssertionError('Must not read credentials')):
            with self.assertRaises(ValueError):
                create(self.runtime, secret)
        linked = self.root / 'linked.png'; linked.symlink_to(self.source)
        with self.assertRaises(ValueError):
            create(self.runtime, linked)
        invalid = self.root / 'invalid.png'; invalid.write_bytes(b'not an image')
        with self.assertRaises(ValueError):
            create(self.runtime, invalid)

    def test_conflicting_files_and_symlink_caches_are_never_overwritten(self):
        result = create(self.runtime, self.source)
        path = Path(result['preview'])
        path.write_bytes(b'Preserve unexpected file')
        with self.assertRaises(ValueError):
            create(self.runtime, self.source)
        self.assertEqual(path.read_bytes(), b'Preserve unexpected file')
        other = self.root / 'other'; other.mkdir()
        (other / PREVIEW_DIRECTORY).symlink_to(self.runtime / PREVIEW_DIRECTORY, target_is_directory=True)
        with self.assertRaises(ValueError):
            create(other, self.source)

    def test_orientation_is_correct_and_preview_does_not_copy_private_metadata(self):
        image = Image.new('RGB', (60, 90), 'blue')
        exif = Image.Exif(); exif[274] = 6; exif[315] = 'Private synthetic photographer'
        image.save(self.source, exif=exif)
        before = self.source.read_bytes()
        result = create(self.runtime, self.source)
        self.assertEqual((result['width'], result['height']), (90, 60))
        with Image.open(result['preview']) as preview:
            self.assertNotIn('exif', preview.info)
        self.assertEqual(self.source.read_bytes(), before)

    def test_cli_dispatches_and_returns_paths_for_only_selected_images(self):
        output = io.StringIO()
        with patch('sys.stdout', output):
            self.assertEqual(cli(['avatar-preview', '--secretary-dir', str(self.runtime), '--source', str(self.source)]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(len(result['previews']), 1)
        self.assertTrue(Path(result['previews'][0]['preview']).is_file())
        with patch('sys.stdout', io.StringIO()):
            self.assertEqual(main(['--secretary-dir', str(self.runtime), *sum([['--source', str(self.source)]] * 5, [])]), 1)


if __name__ == '__main__':
    unittest.main()
