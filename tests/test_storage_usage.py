"""Storage sizes without file-content reads, deletions, model calls or double counting."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.storage_usage import inventory, measure
from goodmorning.web.session_inventory import main


class StorageUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.volume = self.root / ('a' * 32)
        self.runtime = self.volume / 'secretary'
        self.runtime.mkdir(parents=True)

    def add(self, relative, size):
        path = self.volume / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x' * size)
        return path

    def test_disjoint_categories_explain_fixed_libraries_without_reading_contents(self):
        self.add('secretary/profile.md', 20)
        self.add('secretary/avatar-previews/a.webp', 30)
        self.add('secretary/browser-uploads/a/metadata.json', 40)
        self.add('home/.local/share/opencode/engine.db', 50)
        self.add('home/.config/openchamber/settings.json', 60)
        self.add('tmp/native.so', 70)
        self.add('tmp/native.node', 80)
        self.add('cache/cache.sqlite', 90)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('No content reads')), \
             patch.object(Path, 'read_text', side_effect=AssertionError('No content reads')):
            result = inventory(self.runtime)
        self.assertEqual(result['logical_bytes'], 440)
        self.assertEqual(result['groups']['records']['logical_bytes'], 20)
        self.assertEqual(result['groups']['temporary']['library_bytes'], 150)
        self.assertTrue(result['complete'])
        self.assertTrue(result['read_only'])
        self.assertNotIn('settings.json', json.dumps(result))

    def test_selected_overlapping_cache_is_not_counted_twice(self):
        self.add('secretary/profile.md', 10)
        self.add('secretary/avatar-previews/a.webp', 20)
        self.assertEqual(inventory(self.runtime, self.runtime / 'avatar-previews')['logical_bytes'], 30)
        self.assertEqual(inventory(self.runtime, self.runtime)['logical_bytes'], 30)
        self.add('home/.local/share/opencode/engine.db', 40)
        self.add('home/.config/openchamber/settings.json', 50)
        self.add('home/another-file', 60)
        self.assertEqual(inventory(self.runtime, self.volume / 'home')['logical_bytes'], 180)

    def test_missing_directories_are_reported_without_initialization(self):
        path = self.root / 'missing'
        result = inventory(path)
        self.assertEqual(result['logical_bytes'], 0)
        self.assertFalse(result['groups']['records']['present'])
        self.assertFalse(path.exists())

    def test_unreadable_subdirectories_are_reported_as_incomplete_not_empty_success(self):
        def unreadable(*args, **kwargs):
            kwargs['onerror'](PermissionError('Synthetic denied directory'))
            return iter([])
        with patch('goodmorning.storage_usage.os.walk', side_effect=unreadable):
            self.assertFalse(measure(self.runtime)['complete'])

    def test_symlinked_runtime_and_vanished_files_are_incomplete(self):
        linked = self.root / 'linked-runtime'
        linked.symlink_to(self.runtime, target_is_directory=True)
        result = measure(linked)
        self.assertEqual((result['complete'], result['skipped_symlinks'], result['logical_bytes']), (False, 1, 0))
        self.add('secretary/kept', 5)
        walk = [(str(self.runtime), [], ['kept', 'vanished'])]
        with patch('goodmorning.storage_usage.os.walk', return_value=iter(walk)):
            result = measure(self.runtime)
        self.assertEqual((result['complete'], result['files'], result['logical_bytes']), (False, 1, 5))

    def test_links_are_not_followed_and_large_inventories_are_explicitly_incomplete(self):
        outside = self.root / 'outside'; outside.mkdir()
        (outside / 'private-file').write_bytes(b'x' * 1000)
        (self.runtime / 'linked-directory').symlink_to(outside, target_is_directory=True)
        (self.runtime / 'linked-file').symlink_to(outside / 'private-file')
        result = measure(self.runtime)
        self.assertEqual(result['logical_bytes'], 0)
        self.assertEqual(result['skipped_symlinks'], 2)
        self.add('secretary/one', 3); self.add('secretary/two', 4)
        self.assertFalse(measure(self.runtime, limit=1)['complete'])

    def test_cli_never_loads_even_an_invalid_registry_or_changes_records(self):
        path = self.add('secretary/browser-chats/chats.json', 10)
        before = path.read_bytes()
        output = io.StringIO()
        with patch('sys.stdout', output):
            self.assertEqual(main(['--secretary-dir', str(self.runtime), '--storage']), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['logical_bytes'], 10)
        self.assertEqual(path.read_bytes(), before)
        path.write_text(json.dumps({'old': {'state': 'idle', 'created': 0}}))  # Archivable on its own.
        snapshot = lambda: {p: p.read_bytes() for p in self.volume.rglob('*') if p.is_file()}
        records = snapshot()
        output = io.StringIO()
        with patch('sys.stdout', output):
            self.assertEqual(main(['--secretary-dir', str(self.runtime), '--storage', '--archive-chats', '--keep', '0', '--apply']), 1)
        self.assertEqual(json.loads(output.getvalue())['error'], 'sessions_unavailable')
        self.assertEqual(snapshot(), records)


if __name__ == '__main__':
    unittest.main()
