"""Deployer-authored patch notes stay small, bilingual and optional."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web import release


class PatchNoteTests(unittest.TestCase):
    def setUp(self):
        release._note_cache = None
        self.addCleanup(setattr, release, '_note_cache', None)
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)

    def write(self, payload):
        path = Path(self.temp.name) / 'patch-notes.json'
        path.write_text(json.dumps(payload, ensure_ascii=False))
        release.PATCH_NOTES, self._original = path, release.PATCH_NOTES
        self.addCleanup(setattr, release, 'PATCH_NOTES', self._original)
        release._note_cache = None
        return path

    def test_repo_note_is_current_and_bilingual(self):
        note = release.patch_note()
        self.assertIsNotNone(note)
        self.assertEqual(set(note), {'date', 'author', 'en', 'zh'})
        self.assertRegex(note['date'], r'^\d{4}-\d{2}-\d{2}$')
        self.assertTrue(note['author'].strip())
        self.assertTrue(note['en'].strip() and note['zh'].strip())

    def test_missing_file_yields_no_note(self):
        release.PATCH_NOTES, self._original = Path(self.temp.name) / 'absent.json', release.PATCH_NOTES
        self.addCleanup(setattr, release, 'PATCH_NOTES', self._original)
        self.assertIsNone(release.patch_note())

    def test_invalid_notes_yield_no_note_never_an_error(self):
        bad = [
            {},
            {'notes': []},
            {'notes': [{}]},
            {'notes': [{'date': 'tomorrow', 'author': 'Deployer', 'en': 'Hi', 'zh': '你好'}]},
            {'notes': [{'date': '2026-10-12', 'author': '', 'en': 'Hi', 'zh': '你好'}]},
            {'notes': [{'date': '2026-10-12', 'author': 'Deployer', 'en': '', 'zh': '你好'}]},
            {'notes': [{'date': '2026-10-12', 'author': 'Deployer', 'en': 'Hi'}]},
            {'notes': [{'date': '2026-10-12', 'author': 'Deployer', 'en': 'x' * 2001, 'zh': '你好'}]},
            {'notes': [{'date': '2026-10-12', 'author': 'D', 'en': 'Hi\x00', 'zh': '你好'}]},
        ]
        for payload in bad:
            with self.subTest(payload=payload):
                self.write(payload)
                self.assertIsNone(release.patch_note())

    def test_only_the_newest_entry_is_current(self):
        self.write({'notes': [
            {'date': '2026-10-12', 'author': 'New', 'en': 'Current', 'zh': '最新'},
            {'date': '2026-10-11', 'author': 'Old', 'en': 'Previous', 'zh': '之前'},
        ]})
        self.assertEqual(release.patch_note()['en'], 'Current')


if __name__ == '__main__':
    unittest.main()
