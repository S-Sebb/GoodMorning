"""The #290 migration of profile Project roots into memory, on synthetic records only."""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import migrate_project_memory as migration
from goodmorning.records import memory

PROFILE = '''timezone: "Europe/London"

## Project roots

<!-- Add one user-confirmed project per line:
- Name | folder path
Never put passwords or keys here. -->
- Atlas | /home/sam/atlas
- Boreal Survey | /home/sam/boreal | local | read
- atlas | /home/sam/elsewhere

## Setup rules

- Keep credentials in the environment, never in this file.
'''
# A file from before projects: no version key and no projects field.
OLD = {'changes': [], 'enabled': True, 'note': {'lately': '', 'life': 'You have a dog, Mochi.', 'likes': ''},
       'revision': 3, 'tidied': 1761400000.5, 'updated': '2026-10-20'}


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'profile.md').write_text(PROFILE)
        (self.root / 'memory.json').write_text(json.dumps(OLD, sort_keys=True, separators=(',', ':')))

    def stored(self):
        return json.loads((self.root / 'memory.json').read_text())

    def test_seed_adds_root_names_once_in_profile_order_and_keeps_every_other_key(self):
        before = (self.root / 'memory.json').read_bytes()
        self.assertEqual(migration.seed(self.root, dry_run=True)['added'], 2)
        self.assertEqual((self.root / 'memory.json').read_bytes(), before, 'a dry run writes nothing')
        result = migration.seed(self.root)
        self.assertEqual(result, {'mode': 'seed', 'roots': 3, 'added': 2, 'projects': 2, 'revision': 4, 'saved': True})
        data = self.stored()
        self.assertEqual(data['projects'], [{'name': 'Atlas', 'note': ''}, {'name': 'Boreal Survey', 'note': ''}],
                         'the commented example is not a project and the 4-field line keeps only its name')
        self.assertEqual({**data, 'revision': 3, 'projects': None}, {**OLD, 'projects': None})
        self.assertEqual(migration.seed(self.root)['saved'], False)
        self.assertEqual(self.stored()['revision'], 4, 'a rerun changes nothing')
        self.assertEqual(memory.context(self.root)['projects'][1]['name'], 'Boreal Survey')

    def test_seed_keeps_existing_entries_and_reads_names_without_paths(self):
        memory.change(self.root, 3, note={'projects': {'BOREAL  survey': 'Field sampling with Priya.'}})
        (self.root / 'profile.md').write_text(PROFILE.replace('- Atlas | /home/sam/atlas', '- Atlas'))
        self.assertEqual(migration.seed(self.root)['added'], 1)
        self.assertEqual([(entry['name'], entry['note']) for entry in self.stored()['projects']],
                         [('BOREAL survey', 'Field sampling with Priya.'), ('Atlas', '')])

    def test_strip_roots_keeps_names_and_every_other_byte(self):
        self.assertEqual(migration.strip_roots(self.root), {'mode': 'strip-roots', 'stripped': 3, 'saved': True})
        self.assertEqual((self.root / 'profile.md').read_text(),
                         PROFILE.replace(' | /home/sam/atlas', '').replace(' | /home/sam/boreal | local | read', '')
                         .replace(' | /home/sam/elsewhere', ''))
        self.assertEqual(migration.strip_roots(self.root)['saved'], False, 'a rerun changes nothing')
        self.assertEqual(migration.seed(self.root)['added'], 2, 'seeding still reads stripped roots')

    def test_no_memory_file_and_no_roots(self):
        (self.root / 'memory.json').unlink()
        migration.seed(self.root)
        self.assertEqual([entry['name'] for entry in self.stored()['projects']], ['Atlas', 'Boreal Survey'])
        (self.root / 'profile.md').write_text('timezone: "UTC"\n')
        self.assertEqual(migration.seed(self.root)['added'], 0)
        self.assertEqual(migration.strip_roots(self.root)['stripped'], 0)

    def test_only_the_accounts_own_user_runs_it_and_output_holds_no_names(self):
        with patch('os.geteuid', return_value=0), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(migration.main(['--secretary-dir', str(self.root), 'seed']), 1)
        self.assertIn('wrong_user', out.getvalue())
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(migration.main(['--secretary-dir', str(self.root), 'seed']), 0)
        self.assertNotIn('Atlas', out.getvalue())
        self.assertEqual((self.root / 'memory.json').stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
