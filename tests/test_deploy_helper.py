"""The deploy tools load without side effects and publish only public files."""
import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest

from support import TEMP_ROOT

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'deploy'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helper = load('deploy_native')


class DeployHelperTests(unittest.TestCase):
    def test_archive_members_must_be_public_regular_files(self):
        def member(name, kind=tarfile.REGTYPE):
            item = tarfile.TarInfo(name)
            item.type = kind
            return item
        helper.check_members([member('src/goodmorning/cli.py'), member('LICENSE')])
        for bad in ([member('/etc/passwd')], [member('src/../../x')], [member('.github/workflows/validate.yml')],
                    [member('src/.env')], [member('src/goodmorning/__pycache__/x.pyc')],
                    [member('src/link', tarfile.SYMTYPE)], [member('LICENSE'), member('LICENSE')]):
            with self.subTest(bad=[item.name for item in bad]), self.assertRaises(AssertionError):
                helper.check_members(bad)

    def test_release_names_cannot_escape_the_release_directory(self):
        self.assertEqual(helper.release_path('20261015-ship-3a5b299'), helper.RELEASES/'20261015-ship-3a5b299')
        for bad in ('../current', '20261015', 'ship-3a5b299', '20261015-ship/../x', '20261015-Ship'):
            with self.subTest(name=bad), self.assertRaises(ValueError):
                helper.release_path(bad)

    def test_engine_names_cannot_escape_the_engine_directory(self):
        self.assertEqual(helper.engine_path('2.4.0-2.0.32'), helper.ENGINES/'2.4.0-2.0.32')
        for bad in ('current', '../2.4.0-2.0.32', '2.4.0', '2.4.0-latest', '2.4.0-2.0.32/..', '.staging-2.4.0-2.0.32'):
            with self.subTest(name=bad), self.assertRaises(ValueError):
                helper.engine_path(bad)

    def test_deploys_pair_latest_openchamber_with_its_pinned_opencode(self):
        release = load('release')
        manifest = {'version': '2.4.0', 'dependencies': {'@opencode/client': '2.0.32', 'zod': '^4.3.6'}}
        self.assertEqual(release.engine_versions(manifest), ('2.4.0', '2.0.32'))
        for pin in ('^2.0.32', '2.0.x', 'latest'):
            manifest['dependencies']['@opencode/client'] = pin
            with self.subTest(pin=pin), self.assertRaises(release.Stop):
                release.engine_versions(manifest)

    def test_openchamber_choices_survive_its_split_into_preferences(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as name:
            directory = Path(name)
            (directory/'settings.json').write_text('{"defaultModel": "a/b", "lightThemeId": "day", "projects": []}')
            before = helper.openchamber_choices(directory)
            # What OpenChamber 2.5.1 writes on its first start.
            (directory/'settings.json').write_text('{\n  "projects": [],\n  "defaultModel": "a/b",\n  "lightThemeId": "day"\n}')
            (directory/'preferences.json').write_text('{"version": 1, "fields": {"defaultModel": {"value": "a/b", "updatedAt": 5},'
                                                       ' "lightThemeId": {"value": "day", "updatedAt": 5}}}')
            self.assertEqual(helper.openchamber_choices(directory), before)
            (directory/'preferences.json').write_text('{"version": 1, "fields": {"defaultModel": {"value": "c/d", "updatedAt": 6}}}')
            self.assertNotEqual(helper.openchamber_choices(directory), before)

    def test_engine_unit_mounts_only_root_owned_trees(self):
        unit = (ROOT/'deploy/goodmorning-engine.service').read_text()
        self.assertNotIn('/home/', unit)
        self.assertIn('--bind /opt/goodmorning/engines/current/lib/node_modules /opt/goodmorning/engine/node_modules', unit)
        self.assertIn('goodmorning-engine.service', helper.UNITS)

    def test_only_the_deployments_own_ticket_counts_as_idle(self):
        import json
        import sqlite3
        db = sqlite3.connect(':memory:')
        db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)')
        own = {'deployment': '20261015-ship-3a5b299'}
        helper.require_no_work(db, own)
        db.execute("INSERT INTO metadata VALUES ('generation', ?)", (json.dumps(own),))
        helper.require_no_work(db, own)
        with self.assertRaises(helper.Busy):
            helper.require_no_work(db)
        db.execute("UPDATE metadata SET value=? WHERE key='generation'", (json.dumps({'account': 'x', 'job': 'y'}),))
        with self.assertRaises(helper.Busy):
            helper.require_no_work(db, own)
        db.execute("DELETE FROM metadata")
        db.execute("INSERT INTO metadata VALUES ('generation_waiting', ?)", (json.dumps([{'request': 1}]),))
        helper.require_no_work(db, own)
        db.execute("INSERT INTO metadata VALUES ('generation_queue', ?)", (json.dumps([{'request': 1}]),))
        with self.assertRaises(helper.Busy):
            helper.require_no_work(db, own)

    def test_public_archive_contains_the_release_and_nothing_private(self):
        if not (ROOT/'.git').exists():
            self.skipTest('Deployment archives do not include Git metadata')
        release = load('release')
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            target = Path(directory)/'public.tar.gz'
            count = release.build_archive('HEAD', target)
            first = target.read_bytes()
            release.build_archive('HEAD', target)
            self.assertEqual(target.read_bytes(), first, 'A rerun must rebuild the identical archive')
            with tarfile.open(target) as archive:
                names = {item.name for item in archive.getmembers()}
        self.assertEqual(len(names), count)
        self.assertTrue({Path(name).parts[0] for name in names} <= helper.ALLOWED)
        for required in ('LICENSE', 'AGENTS.md', 'SERVER-DATA-GUIDE.md', 'scripts/goodmorning.py', 'deploy/deploy_native.py',
                         '.opencode/agents/secretary.md'):
            self.assertIn(required, names)


if __name__ == '__main__':
    unittest.main()
