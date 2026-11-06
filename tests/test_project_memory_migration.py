"""The #290 migration of legacy projects into memory, on synthetic records shaped like the hosted ones."""
import io
import json
from contextlib import redirect_stdout
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import migrate_project_memory as migration
from goodmorning.records import memory
from goodmorning.records.inbox_store import InboxStore, initialize, stamp

HEAD = 'timezone: "Europe/London"\n\n'
TAIL = '\n## Setup rules\n\n- Keep credentials in the environment, never in this file.\n'
EXAMPLE = '''<!-- Add one user-confirmed project per line:
- Name | folder path
Never put passwords or keys here. -->
'''
ROOTS = HEAD + '## Project roots\n\n' + EXAMPLE + ''.join(
    f'- {name} | /home/sam/{name.lower()} | local | read\n' for name in ('Atlas', 'Boreal Survey', 'Comet', 'Delta')) + TAIL
# A file from before projects: no version key and no projects field.
OLD = {'changes': [], 'enabled': True, 'note': {'lately': '', 'life': 'You have a dog, Mochi.', 'likes': ''},
       'revision': 3, 'tidied': 1761400000.5, 'updated': '2026-10-20'}
WRITE_BACK = '''## Write-back rules

- Use only registered paths and the agreed read/write-back scope.
- Resolve ambiguous changes before saving. Update `last_update` after edits.
'''


def record(name, goal='', progress='', updated='2026-09-14'):
    """A projects/*.md record in the oldest template's shape, its guidance comments left in."""
    return (f'# Project record\n\nname: "{name}"\nroot_path: "/home/sam/x"\naccess_method: "local"\nregistry_alias: ""\n'
            f'write_back_scope: "read"\nlast_update: {updated}\n\n'
            f'## Goal outline\n\n<!-- State the overall goal and the main milestones. -->\n{goal}\n\n'
            f'## Current progress\n\n<!-- Record completed work, active work, and blockers; do not invent progress. -->\n{progress}\n\n'
            f'## Deadlines\n\n- 2026-12-01 review\n\n' + WRITE_BACK)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name) / 'vault'
        self.root = self.vault / 'secretary'
        self.root.mkdir(parents=True)

    def account(self, profile=ROOTS, records=None, labels=(), done=(), memory_file=OLD):
        """`records` maps file stems to text; to-dos are open, except those labelled in `done`."""
        (self.root / 'profile.md').write_bytes(profile.encode() if isinstance(profile, str) else profile)
        if labels or done:
            initialize(self.root)
            inbox = InboxStore(self.root, write=True)
            for n, label in enumerate((*labels, *done)):
                inbox.mutate('add', {'kind': 'todo', 'raw': f'Step {n}', 'project': label}, 'ses_a', f'k{n}', stamp(self.root))
            for label in done:
                inbox.db.execute("UPDATE tasks SET data=json_set(data,'$.status','done') WHERE json_extract(data,'$.project')=?", (label,))
            inbox.close()
        memory_path = self.root / 'memory.json'
        if memory_file is None:
            memory_path.unlink(missing_ok=True)
        else:
            memory_path.write_text(json.dumps(memory_file, sort_keys=True, separators=(',', ':')))
        os.chmod(self.root / 'profile.md', 0o640)
        if records is not None:
            (self.root / 'projects').mkdir()
            for stem, text in records.items():
                (self.root / 'projects' / f'{stem}.md').write_text(text)
            (self.root / 'projects.json').write_text('{"version":1,"projects":[]}\n')

    def run_main(self, *args):
        with redirect_stdout(io.StringIO()) as out:
            code = migration.main(['--vault', str(self.vault), *args])
        return code, json.loads(out.getvalue())

    def entries(self):
        return {entry['name']: (entry['note'], entry['updated']) for entry in memory.load(self.root)['projects']}

    def snapshot(self):
        return {str(path.relative_to(self.root)): (path.read_bytes() if path.is_file() else None, path.stat().st_mode,
                                                   path.stat().st_mtime_ns)
                for path in [self.root / 'profile.md', self.root / 'memory.json', *migration.legacy(self.root)] if path.exists()}

    def test_seb_shape_seeds_notes_from_records_and_removes_the_legacy_copies(self):
        self.account(records={'Atlas': record('Atlas', 'Compare two baselines.', '- Methods half written.'),
                              'Boreal Survey': record('Boreal Survey', 'Map the lakes.', updated='not a date'),
                              'comet-notes': record('Comet'), 'Delta': record('Delta', '- First', '- Second')},
                     labels=('atlas', 'Boreal Survey', 'Comet', 'Delta', 'Echo'))
        code, dry = self.run_main('migrate', '--dry-run')
        self.assertEqual((code, dry['status'], dry['counts']['projects'], dry['counts']['notes']), (0, 'dry_run', 5, 3))
        self.assertNotIn('Atlas', json.dumps(dry), 'output holds counts, never names or text')
        self.assertFalse((self.vault / 'backups').exists(), 'a dry run writes nothing')
        code, result = self.run_main('migrate', '--expect', dry['fingerprint'])
        self.assertEqual((code, result['status'], result['revision']), (0, 'migrated', 4))
        today = memory.load(self.root)['updated']
        self.assertEqual(self.entries(), {
            'atlas': ('Compare two baselines.\n- Methods half written.', '2026-09-14'),  # The label's spelling wins.
            'Boreal Survey': ('Map the lakes.', today), 'Comet': ('', '2026-09-14'),  # Matched by name, not stem.
            'Delta': ('- First\n- Second', '2026-09-14'), 'Echo': ('', today)})
        self.assertEqual(list(self.entries()), ['atlas', 'Boreal Survey', 'Comet', 'Delta', 'Echo'], 'roots first, then labels')
        self.assertEqual({**memory.load(self.root), 'projects': None, 'revision': 3, 'updated': OLD['updated']}, {**OLD, 'projects': None})
        self.assertEqual((self.root / 'profile.md').read_text(), HEAD + TAIL.lstrip('\n'))
        self.assertEqual((self.root / 'profile.md').stat().st_mode & 0o777, 0o640)
        self.assertEqual(migration.legacy(self.root), [])
        backup = Path(result['backup'])
        self.assertEqual(backup.parent, self.vault / 'backups')
        self.assertEqual({path.stat().st_mode & 0o777 for path in backup.rglob('*')}, {0o600, 0o700})
        manifest = json.loads((backup / 'manifest.json').read_text())
        self.assertEqual((list(manifest)[-1], manifest['revision'], len(manifest['files'])), ('complete', 3, 8))
        self.assertEqual(self.run_main('migrate')[1]['status'], 'nothing_to_migrate', 'a rerun changes nothing')
        self.assertEqual(self.run_main('verify-backup', str(backup), '--restore-test')[1]['restore_test'], 'passed')
        self.assertEqual(sorted(path.name for path in backup.iterdir()), ['done.json', 'files', 'intent.json', 'manifest.json'],
                         'the restore test deletes its scratch copy')

    def test_yuka_shape_has_no_projects_but_loses_its_legacy_records(self):
        profile = HEAD + '## Project roots\n\n' + EXAMPLE + TAIL
        self.account(profile, records={'thesis-plan': record('Thesis', 'Write it.'), 'misc': record('Garden', 'Plant.')},
                     done=('Thesis',))
        before = (self.root / 'memory.json').read_bytes()
        code, result = self.run_main('migrate')
        self.assertEqual((code, result['status'], result['counts']['projects']), (0, 'migrated', 0), 'a done-only label is no project')
        self.assertEqual((self.root / 'memory.json').read_bytes(), before)
        self.assertEqual((self.root / 'profile.md').read_text(), HEAD + TAIL.lstrip('\n'))
        self.assertFalse((self.root / 'projects').exists() or (self.root / 'projects.json').exists())

    def test_comment_only_section_bare_heading_section_at_the_end_and_crlf(self):
        for profile, expected, projects in (
                (HEAD + '## Project roots\n\n' + EXAMPLE + TAIL, HEAD + TAIL.lstrip('\n'), 0),
                (HEAD + '## Project roots\n' + TAIL, HEAD + TAIL.lstrip('\n'), 0),
                (HEAD + '## Setup rules\n\n- x\n\n## Project roots\n- Atlas | /a\n', HEAD + '## Setup rules\n\n- x\n\n', 1),
                (ROOTS.replace('\n', '\r\n'), (HEAD + TAIL.lstrip('\n')).replace('\n', '\r\n'), 4)):
            with self.subTest(profile[30:60]):
                self.setUp()
                self.account(profile.encode(), records={}, memory_file=None)
                self.assertEqual(self.run_main('migrate')[1]['status'], 'migrated')
                self.assertEqual((self.root / 'profile.md').read_bytes(), expected.encode())
                self.assertFalse((self.root / 'projects').exists())
                self.assertEqual(len(memory.load(self.root)['projects']), projects)

    def test_note_limits_fall_back_to_the_goal_then_to_nothing(self):
        goal = 'G' * 300
        self.account(records={'Atlas': record('Atlas', goal, 'P' * 250), 'Comet': record('Comet', 'C' * 501),
                              'Delta': record('Delta', 'Tab\tinside'), 'Boreal Survey': record('Boreal Survey', 'B' * 400)},
                     memory_file={**OLD, 'note': {**OLD['note'], 'lately': 'L' * (memory.LENGTH - 300 - 22 - 300)}})
        result = self.run_main('migrate')[1]
        self.assertEqual({name: note for name, (note, _) in self.entries().items()},
                         {'Atlas': goal, 'Boreal Survey': '', 'Comet': '', 'Delta': ''},
                         'over 500 drops progress; then the 4,000 total leaves no room; a tab is not plain text')
        self.assertEqual((result['counts']['shortened'], result['counts']['no_note']), (1, 3))

    def test_a_chinese_account_skips_an_english_note(self):
        self.account(records={'Atlas': record('Atlas', 'Compare two baselines.'), 'Comet': record('Comet', '比较两个基线。')})
        (self.root / 'browser-chats').mkdir()
        (self.root / 'browser-chats' / 'chats.json').write_text(json.dumps(
            {'c1': {'mode': 'secretary', 'created': 1, 'turns': [{'text': '你好', 'language': 'zh-CN', 'created': 2}]}}))
        self.assertEqual(self.run_main('migrate')[1]['counts']['wrong_language'], 1)
        self.assertEqual(self.entries()['Atlas'][0], '')
        self.assertEqual(self.entries()['Comet'][0], '比较两个基线。')

    def test_memory_off_changes_nothing(self):
        self.account(records={'Atlas': record('Atlas', 'Goal.')}, memory_file={**OLD, 'enabled': False})
        before = self.snapshot()
        self.assertEqual(self.run_main('migrate')[1]['status'], 'memory_off')
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.vault / 'backups').exists())

    def test_an_interrupted_removal_resumes_from_its_backup(self):
        self.account(records={'Atlas': record('Atlas', 'Goal.')}, labels=('Atlas',))
        with patch.object(Path, 'rmdir', side_effect=OSError('interrupted')):
            self.assertEqual(self.run_main('migrate'), (1, {'error': 'storage_error', 'next': 'storage_error: OSError; preserve the files and inspect'}))
        self.assertNotIn('Project roots', (self.root / 'profile.md').read_text())
        self.assertFalse((self.root / 'projects' / 'Atlas.md').exists())
        self.assertTrue((self.root / 'projects').is_dir())
        code, result = self.run_main('migrate')
        self.assertEqual((code, result['status'], result['revision']), (0, 'migrated', 4), 'seeded once')
        self.assertTrue(result['resume'])
        self.assertEqual(self.entries()['Atlas'][0], 'Goal.')
        self.assertEqual(migration.legacy(self.root), [])

    def test_restore_round_trip_and_refusal_after_a_newer_revision(self):
        self.account(records={'Atlas': record('Atlas', 'Goal.')})
        before = self.snapshot()
        backup = self.run_main('migrate')[1]['backup']
        self.assertEqual(self.run_main('restore', backup)[1]['status'], 'restored')
        self.assertEqual(self.snapshot(), before, 'bytes, modes and mtimes come back')
        self.assertEqual(self.run_main('migrate')[1]['status'], 'migrated', 'a restored account can migrate again')
        backup = sorted((self.vault / 'backups').iterdir())[-1]
        memory.change(self.root, memory.load(self.root)['revision'], note={'likes': 'Tea.'})
        code, result = self.run_main('restore', str(backup))
        self.assertEqual((code, result['error']), (1, 'memory_changed'))
        self.assertEqual(memory.load(self.root)['note']['likes'], 'Tea.')

    def test_expect_refuses_a_changed_account_and_missing_runtimes_pass(self):
        self.account(records={})
        fingerprint = self.run_main('migrate', '--dry-run')[1]['fingerprint']
        (self.root / 'projects' / 'New.md').write_text(record('New'))
        self.assertEqual(self.run_main('migrate', '--expect', fingerprint)[1]['error'], 'fingerprint_changed')
        self.assertTrue((self.root / 'projects' / 'New.md').exists())
        (self.root / 'profile.md').unlink()
        self.assertEqual(self.run_main('migrate'), (0, {'mode': 'migrate', 'status': 'no_runtime'}))

    def test_only_the_accounts_own_user_runs_it(self):
        self.account(records={})
        with patch('os.geteuid', return_value=os.geteuid() + 1):
            self.assertEqual(self.run_main('migrate')[1]['error'], 'wrong_user')
        self.assertTrue((self.root / 'projects.json').exists())

    def refused(self, error, *args):
        """Run migrate (or `args`) and check it refuses with `error` and leaves every runtime file as it was."""
        before = self.snapshot()
        code, result = self.run_main(*(args or ('migrate',)))
        self.assertEqual((code, result.get('error')), (1, error), result)
        self.assertEqual(self.snapshot(), before)
        return result

    def test_a_missing_unowned_or_unreadable_vault_is_an_error_not_no_runtime(self):
        self.vault = self.vault.with_name('typo')
        self.assertEqual(self.run_main('migrate')[1]['error'], 'no_vault')
        self.vault.mkdir()
        self.assertEqual(self.run_main('migrate')[1]['error'], 'no_runtime_dir')
        self.vault = self.root.parent
        with patch('os.geteuid', return_value=os.geteuid() + 1):
            self.assertEqual(self.run_main('migrate')[1]['error'], 'wrong_user', 'checked before profile.md')
        os.chmod(self.root, 0)
        self.addCleanup(os.chmod, self.root, 0o700)
        self.assertEqual(self.run_main('migrate')[0], 1, 'an unreadable runtime is not a missing profile')

    def test_an_unclear_profile_is_refused(self):
        tail = '\n## Setup rules\n'
        for profile in (HEAD + '<!--\n## Project roots\n- Atlas | /a\n-->\n' + tail,
                        HEAD + '```\n## Project roots\n- Atlas | /a\n```\n' + tail,
                        HEAD + '## Project roots\n- Atlas | /a\n\n## Project roots\n- Comet | /c\n' + tail,
                        HEAD + '## project roots\n- Atlas | /a\n' + tail,
                        HEAD + '## Project roots (old)\n- Atlas | /a\n' + tail,
                        HEAD + 'Project roots moved to the notes below.\n' + tail):
            with self.subTest(profile[len(HEAD):len(HEAD) + 30]):
                self.setUp()
                self.account(profile, records={'Atlas': record('Atlas', 'Goal.')})
                self.refused('profile_unclear')
                self.assertFalse((self.vault / 'backups').exists())
        self.setUp()
        self.account(HEAD + tail, records={'Atlas': record('Atlas', 'Goal.')})
        self.assertEqual(self.run_main('migrate')[1]['status'], 'migrated', 'a profile that never had the section is clear')

    def test_the_section_ends_at_any_top_heading_outside_comments(self):
        profile = HEAD + '## Project roots\n<!-- a\n# not a heading\n-->\n- Atlas | /a\n# Notes\n\nKeep this.\n'
        self.account(profile, records={})
        self.run_main('migrate')
        self.assertEqual((self.root / 'profile.md').read_text(), HEAD + '# Notes\n\nKeep this.\n')

    def test_crlf_records_keep_their_name_and_date(self):
        self.account(records={'atlas-notes': record('Atlas', 'Goal.', updated='2026-08-01').replace('\n', '\r\n')})
        self.run_main('migrate')
        self.assertEqual(self.entries()['Atlas'], ('Goal.', '2026-08-01'))

    def test_the_fingerprint_covers_to_do_labels_and_the_chat_language(self):
        self.account(records={'Echo': record('Echo', 'Goal.')}, labels=('Echo',))
        fingerprint = self.run_main('migrate', '--dry-run')[1]['fingerprint']
        inbox = InboxStore(self.root, write=True)
        inbox.db.execute("UPDATE tasks SET data=json_set(data,'$.status','done')")
        inbox.close()
        self.refused('fingerprint_changed', 'migrate', '--expect', fingerprint)
        fingerprint = self.run_main('migrate', '--dry-run')[1]['fingerprint']
        (self.root / 'browser-chats').mkdir()
        (self.root / 'browser-chats' / 'chats.json').write_text(json.dumps(
            {'c1': {'mode': 'secretary', 'created': 1, 'turns': [{'text': '你好', 'language': 'zh-CN', 'created': 2}]}}))
        self.refused('fingerprint_changed', 'migrate', '--expect', fingerprint)

    def test_resume_refuses_a_memory_write_made_after_the_interruption(self):
        self.account(records={'Atlas': record('Atlas', 'Goal.')}, labels=('Atlas',))
        with patch.object(Path, 'rmdir', side_effect=OSError('interrupted')):
            self.run_main('migrate')
        memory.change(self.root, memory.load(self.root)['revision'], note={'likes': 'Tea.'})
        self.refused('memory_changed')
        backup = next((self.vault / 'backups').iterdir())
        self.refused('memory_changed', 'restore', str(backup))

    def test_a_crash_around_the_memory_write_still_resumes_and_restores(self):
        real = migration.atomic_bytes
        for after in (False, True):  # Crash on the memory write, or on the first write after it.
            with self.subTest(after=after):
                self.setUp()
                self.account(records={'Atlas': record('Atlas', 'Goal.')}, labels=('Atlas',))
                before, written = self.snapshot(), []

                def crash(path, data, mode):
                    if written or path == self.root / 'memory.json' and not after:
                        raise OSError('crash')
                    real(path, data, mode)
                    if path == self.root / 'memory.json':
                        written.append(path)
                with patch.object(migration, 'atomic_bytes', crash):
                    self.assertEqual(self.run_main('migrate')[0], 1)
                backup = next((self.vault / 'backups').iterdir())
                self.assertEqual(self.run_main('restore', str(backup))[1]['status'], 'restored')
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.run_main('migrate')[1]['revision'], 4, 'seeded once')

    def test_restore_refuses_after_any_later_memory_write(self):
        self.account(records={'Atlas': record('Atlas', 'Goal.')})
        backup = self.run_main('migrate')[1]['backup']
        memory.tidy(self.root)  # The evening tidy changes only `tidied`.
        self.refused('memory_changed', 'restore', backup)

    def test_legacy_files_added_after_the_backup_are_refused_not_deleted(self):
        self.account(records={'Atlas': record('Atlas', 'Goal.')})
        real = migration.verify_backup

        def add_file(*args):
            (self.root / 'projects' / 'Late.md').write_text('late')
            return real(*args)
        with patch.object(migration, 'verify_backup', add_file):
            self.assertEqual(self.run_main('migrate')[1]['error'], 'changed_since_backup')
        self.assertTrue((self.root / 'projects' / 'Late.md').exists())
        self.assertIn('Project roots', (self.root / 'profile.md').read_text())
        self.assertEqual(memory.load(self.root)['revision'], 3, 'nothing is seeded either')

    def test_foreign_owners_and_failed_restore_tests_stop_before_anything_changes(self):
        self.account(records={'Atlas': record('Atlas', 'Goal.')})
        with patch('os.getegid', return_value=os.getegid() + 1):
            self.refused('foreign_owner')
        with patch.object(migration, 'verify_backup', side_effect=ValueError('restore_mismatch: test')):
            self.refused('restore_mismatch')

    def test_restore_checks_every_owner_before_writing(self):
        self.account(records={'Atlas': record('Atlas', 'Goal.')})
        backup = Path(self.run_main('migrate')[1]['backup'])
        manifest = json.loads((backup / 'manifest.json').read_text())
        manifest['files'][-1]['uid'] += 1
        (backup / 'manifest.json').write_text(json.dumps(manifest))
        self.refused('restore_owner', 'restore', str(backup))

    def test_xattrs_are_recorded_and_refused(self):
        self.account(records={'Atlas': record('Atlas', 'Goal.')})
        try:
            os.setxattr(self.root / 'projects' / 'Atlas.md', 'user.tag', b'x')
        except OSError:
            self.skipTest('no user xattrs here')
        self.refused('unsupported_metadata')
        os.removexattr(self.root / 'projects' / 'Atlas.md', 'user.tag')
        backup = Path(self.run_main('migrate')[1]['backup'])
        self.assertEqual({tuple(entry['xattrs']) for entry in json.loads((backup / 'manifest.json').read_text())['files']}, {()})


if __name__ == '__main__':
    unittest.main()
