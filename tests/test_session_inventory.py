"""Organized session titles and bounded local registries. No network or engine."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web import session_inventory as inventory
from goodmorning.web.briefing_chat import Chats
from goodmorning.web.briefing_server import BrowserApp
from test_briefing_chat import MockChamber, ImmediateThread


class SessionInventoryTests(unittest.TestCase):
    def test_titles_carry_fixed_prefix_without_touching_saved_text(self):
        self.assertTrue(inventory.chat_session_title('Secretary', 'Plan tonight').startswith('GoodMorning · '))
        self.assertIn('Plan tonight', inventory.chat_session_title('Secretary', 'Plan tonight'))
        self.assertTrue(inventory.job_session_title('Morning briefing', '2026-10-11').startswith('GoodMorning · '))
        self.assertIn('2026-10-11', inventory.job_session_title('Morning briefing', '2026-10-11'))
        self.assertLessEqual(len(inventory.chat_session_title('Secretary', 'x' * 500)), 120)

    def test_chat_leaves_native_auto_title_enabled_and_briefing_keeps_its_prefix(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            (root / 'profile.md').write_text('city: London\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n')
            chamber = MockChamber(root)
            chats = Chats(root, chamber)
            with patch('goodmorning.web.briefing_chat.threading.Thread', ImmediateThread):
                chats.start({'id': 'a' * 32, 'mode': 'secretary', 'text': 'Plan tonight'})
            created = next(call for call in chamber.calls if call[0] == 'session.create')
            self.assertNotIn('title', created[1])
            app = BrowserApp(root, chamber)
            with patch('goodmorning.web.briefing_server.threading.Thread', ImmediateThread):
                app.start(app.today(), 'gm')
            created = next(call for call in chamber.calls if call[0] == 'session.create' and 'briefing' in call[1].get('title',''))
            self.assertTrue(created[1]['title'].startswith('GoodMorning · '))
            self.assertIn(app.today(), created[1]['title'])
            self.assertIn(app.jobs[app.today() + '.gm']['session'], inventory.owned_sessions(root))
            self.assertIn(chats.get('a' * 32)['session'], inventory.owned_sessions(root))

    def test_prune_and_archive_preserve_saved_editions_and_active_work(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            (root / 'daily').mkdir()
            (root / 'browser-jobs').mkdir()
            (root / 'browser-chats').mkdir()
            (root / 'daily/2026-09-01.gm.json').write_text('{"saved":true}')
            jobs = {'2026-09-01.gm': {'id': 'a' * 32, 'date': '2026-09-01', 'kind': 'gm', 'state': 'complete'},
                    '2026-10-11.gm': {'id': 'b' * 32, 'date': '2026-10-11', 'kind': 'gm', 'state': 'running', 'session': 'ses_old'},
                    'undated': {'id': 'c' * 32, 'date': 'someday', 'kind': 'gm', 'state': 'complete'}}
            (root / 'browser-jobs/jobs.json').write_text(json.dumps(jobs))
            (root / 'browser-jobs' / ('a' * 32 + '.preview.json')).write_text('{}')
            report = inventory.prune_jobs(root, older_than_days=14, today='2026-10-11', apply=True)
            self.assertEqual(report['pruned'], ['2026-09-01.gm'])
            self.assertTrue((root / 'daily/2026-09-01.gm.json').is_file())
            self.assertFalse((root / 'browser-jobs' / ('a' * 32 + '.preview.json')).exists())
            remaining = json.loads((root / 'browser-jobs/jobs.json').read_text())
            self.assertIn('2026-10-11.gm', remaining)
            self.assertIn('undated', remaining)
            chats = {'old-idle': {'id': 'old-idle', 'mode': 'secretary', 'title': 'Old', 'state': 'idle',
                                  'turns': [], 'created': 1000.0},
                     'old-busy': {'id': 'old-busy', 'mode': 'secretary', 'title': 'Busy', 'state': 'running',
                                  'turns': [], 'created': 1000.0},
                     'new-idle': {'id': 'new-idle', 'mode': 'secretary', 'title': 'New', 'state': 'idle',
                                  'turns': [], 'created': 2000000000.0}}
            (root / 'browser-chats/chats.json').write_text(json.dumps(chats))
            report = inventory.archive_chats(root, keep=1, older_than_days=90, now=2000000000.0, apply=True)
            self.assertEqual(report['archived'], ['old-idle'])
            self.assertEqual(report['retained_non_idle'], ['old-busy'])
            kept = json.loads((root / 'browser-chats/chats.json').read_text())
            archived = json.loads((root / 'browser-chats/archive.json').read_text())
            self.assertNotIn('old-idle', kept)
            self.assertIn('old-idle', archived)
            self.assertIn('old-busy', kept)

    def test_cli_lists_and_dry_runs_without_changing_records(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            (root / 'browser-chats').mkdir()
            (root / 'browser-jobs').mkdir()
            (root / 'browser-chats/chats.json').write_text('{}')
            (root / 'browser-jobs/jobs.json').write_text('{}')
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(inventory.main(['--secretary-dir', str(root), '--list']), 0)
            self.assertEqual(inventory.main(['--secretary-dir', str(root), '--prune-jobs']), 0)
            self.assertEqual(inventory.main(['--secretary-dir', str(root), '--archive-chats']), 0)
            self.assertEqual({p: p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)


if __name__ == '__main__':
    unittest.main()
