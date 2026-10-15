"""Versioned bilingual history, account dismissals and isolated local persistence."""
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from support import TEMP_ROOT, HOSTS, FakeChamber, gateway, session_cookie
from goodmorning.web import release
from goodmorning.web.briefing_server import BrowserApp


def note(version='0.2.0', **values):
    changes = [{'category': 'Added', 'en': [values.pop('en', 'Current')], 'zh': [values.pop('zh', '最新')]}]
    return {'version': version, 'date': '2026-10-12', 'author': 'Synthetic deployer',
            'title_en': 'Test release', 'title_zh': '测试版本', 'changes': changes, **values}


class PatchNoteTests(unittest.TestCase):
    def setUp(self):
        release._note_cache = None
        self.addCleanup(setattr, release, '_note_cache', None)
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.original = release.PATCH_NOTES
        self.addCleanup(setattr, release, 'PATCH_NOTES', self.original)

    def write(self, payload):
        path = Path(self.temp.name) / 'patch-notes.json'
        path.write_text(json.dumps(payload, ensure_ascii=False))
        release.PATCH_NOTES = path
        release._note_cache = None
        return path

    def test_repo_history_is_current_and_bilingual(self):
        notes = release.patch_notes()
        versions = [release.version_number(entry['version']) for entry in notes]
        self.assertEqual(versions, sorted(set(versions), reverse=True))
        self.assertEqual(release.patch_note(), notes[0])
        self.assertEqual(release.release_info()['release'], notes[0]['version'])
        self.assertEqual(release.release_info()['note'], notes[0])
        self.assertEqual(release.release_info()['notes'], notes)
        self.assertRegex(release.VERSION, r'^[a-f0-9]{64}$')
        for entry in notes:
            self.assertTrue(all(entry[key].strip() for key in ('en', 'zh', 'title_en', 'title_zh')))
            self.assertTrue(entry['changes'])
            for group in entry['changes']:
                self.assertIn(group['category'], release.NOTE_CATEGORIES)
                self.assertEqual(len(group['en']), len(group['zh']))
                self.assertTrue(group['en'] and group['zh'])

    def test_all_historical_commits_have_exactly_one_note(self):
        repo = Path(__file__).resolve().parents[1]
        if not (repo / '.git').exists():
            self.skipTest('Deployment archives do not include Git metadata')
        # Pin the reconstruction boundary; future releases do not rewrite old notes.
        commits = subprocess.check_output(['git', 'rev-list', '--abbrev-commit', '--abbrev=7', 'f1f79d1'], cwd=repo, text=True).splitlines()
        covered = [commit for entry in release.patch_notes() if release.version_number(entry['version']) <= (0, 18, 3) for commit in entry['commits']]
        self.assertEqual(set(covered), set(commits))
        self.assertEqual(len(covered), len(commits))

    def test_missing_or_malformed_file_yields_empty_history(self):
        release.PATCH_NOTES = Path(self.temp.name) / 'absent.json'
        self.assertIsNone(release.patch_note())
        self.assertEqual(release.patch_notes(), [])
        release.PATCH_NOTES.write_text('{broken')
        self.assertEqual(release.release_info()['notes'], [])

    def test_invalid_notes_never_raise(self):
        bad = [{}, {'notes': []}, {'notes': [{}]}]
        for key, value in [('version', '1.0.0'), ('version', '0.02.0'), ('version', '0.1٢.0'), ('version', None),
                           ('date', '2026-02-30'), ('date', 'tomorrow'), ('author', ''),
                           ('en', ''), ('zh', None), ('title_en', ''), ('en', 'x' * 2001),
                           ('en', 'Hi\x00'), ('en', ' ' * 2000 + 'x'), ('commits', ['not-a-commit'])]:
            bad.append({'notes': [note(**{key: value})]})
        bad += [{'notes': [note(), note()]}, {'notes': [note('0.1.0'), note('0.2.0')]}]
        for changes in (None, [], {}, [{'category': 'Unknown', 'en': ['Hi'], 'zh': ['你好']}],
                        [{'category': 'Added', 'en': [], 'zh': []}],
                        [{'category': 'Added', 'en': 'Paragraph', 'zh': ['你好']}],
                        [{'category': 'Added', 'en': ['One', 'Two'], 'zh': ['一个']}],
                        [{'category': 'Added', 'en': ['Hi'], 'zh': ['你好']}] * 2):
            bad.append({'notes': [note(changes=changes)]})
        for payload in bad:
            with self.subTest(payload=payload):
                self.write(payload)
                self.assertIsNone(release.patch_note())
                self.assertEqual(release.patch_notes(), [])

    def test_history_orders_versions_numerically_and_cache_tracks_edits(self):
        path = self.write({'notes': [note('0.10.0'), note('0.9.1', en='Previous')]})
        self.assertEqual(release.patch_note()['version'], '0.10.0')
        self.assertEqual(release.patch_notes()[1]['changes'][0]['en'], ['Previous'])
        path.write_text(json.dumps({'notes': [note('0.11.0', en='New release')]}))
        self.assertEqual(release.patch_note()['changes'][0]['en'], ['New release'])

    def test_legacy_summary_uses_the_same_categories_and_bullets(self):
        self.write({'notes': [note(changes=[
            {'category': 'Added', 'en': ['One', 'Two'], 'zh': ['一', '二']},
            {'category': 'Fixed', 'en': ['Three'], 'zh': ['三']}
        ])]})
        latest = release.patch_note()
        for key, bullets in (('en', [['One', 'Two'], ['Three']]), ('zh', [['一', '二'], ['三']])):
            blocks = [block.split('\n') for block in latest[key].split('\n\n')]
            self.assertTrue(all(block[0].endswith(':') for block in blocks), latest[key])
            self.assertEqual([[line.removeprefix('- ') for line in block[1:]] for block in blocks], bullets)
            self.assertTrue(all(line.startswith('- ') for block in blocks for line in block[1:]))

    def test_acknowledgments_reject_unknown_versions_and_never_go_backward(self):
        self.write({'notes': [note('0.10.0'), note('0.9.0')]})
        self.assertEqual(release.acknowledge_version('0.9.0', '0.10.0'), '0.10.0')
        self.assertEqual(release.acknowledge_version('0.10.0', '0.9.0'), '0.10.0')
        for value in ('0.99.0', 'bad', {}, None):
            with self.assertRaises(ValueError):
                release.acknowledge_version(value)

    def test_local_seen_state_survives_restart_and_keeps_records(self):
        root = Path(self.temp.name)
        (root / 'profile.md').write_text('timezone: Europe/London\n')
        app = BrowserApp(root, FakeChamber())
        self.assertIsNone(app.release_seen())
        self.assertEqual(app.release_seen('0.19.0'), '0.19.0')
        self.assertEqual((root / 'release-seen.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(BrowserApp(root, FakeChamber()).release_seen(), '0.19.0')
        other = root / 'other'; other.mkdir()
        self.assertIsNone(BrowserApp(other, FakeChamber()).release_seen())

    def test_local_seen_state_rejects_symlinks(self):
        root = Path(self.temp.name)
        target = root / 'preserved.json'
        target.write_text('{"version": "0.1.0"}')
        (root / 'release-seen.json').symlink_to(target)
        app = BrowserApp(root, FakeChamber())
        with self.assertRaises(ValueError):
            app.release_seen('0.19.0')
        self.assertEqual(target.read_text(), '{"version": "0.1.0"}')


class ReleaseAccountTests(unittest.TestCase):
    def test_guests_can_read_history_but_cannot_dismiss_for_accounts(self):
        fixture = gateway(self)
        self.assertEqual(json.loads(fixture.request('/api/release/seen')[2]), {'version': None, 'enabled': False})
        _, headers, data = fixture.request('/login')
        fixture.cookie = headers['Set-Cookie'].split(';')[0]
        fixture.csrf = re.search(b'data-csrf="([a-f0-9]+)"', data)[1].decode()
        self.assertEqual(fixture.request('/api/release/seen', {'version': '0.19.0'})[0], 403)
        self.assertIsNone(fixture.store.release_seen(fixture.id))

    def test_dismissal_shared_across_devices_and_hosts_but_not_users(self):
        fixture = gateway(self)
        fixture.permanent()
        status, headers, data = fixture.request('/api/release/seen')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(json.loads(data), {'version': None, 'enabled': True})
        self.assertEqual(fixture.request('/api/release/seen', {'version': '0.19.0'})[0], 200)
        for host in HOSTS:
            status, _, data = fixture.request('/api/release/seen', headers={'Host': host, 'Cookie': session_cookie(fixture, fixture.id, host)})
            self.assertEqual((status, json.loads(data)['version']), (200, '0.19.0'))
        self.assertIsNone(fixture.store.release_seen(fixture.other))
        self.assertEqual(fixture.request('/api/release/seen', {'version': '0.18.0'})[0], 200)
        self.assertEqual(fixture.store.release_seen(fixture.id), '0.19.0')
        self.assertIsNone(fixture.gateway.ticket())

    def test_dismissal_requires_csrf_same_origin_and_known_version(self):
        fixture = gateway(self)
        fixture.permanent()
        for headers in ({'X-Briefing-CSRF': ''}, {'Origin': 'https://other.example.test'}):
            self.assertEqual(fixture.request('/api/release/seen', {'version': '0.19.0'}, headers=headers)[0], 403)
        for body in ({'version': '0.999.0'}, {'version': None}, {'version': '0.19.0', 'user_id': fixture.other}):
            self.assertEqual(fixture.request('/api/release/seen', body)[0], 400)
        self.assertIsNone(fixture.store.release_seen(fixture.id))
        self.assertIsNone(fixture.store.release_seen(fixture.other))


if __name__ == '__main__':
    unittest.main()
