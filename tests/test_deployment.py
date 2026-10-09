"""Bundle boundaries and compatibility checks; no personal data or network."""

import ast
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

from support import TEMP_ROOT

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from package_release import build, public_files


class DeploymentTests(unittest.TestCase):
    def test_bundle_excludes_runtime_secrets_sandbox_cache_and_git(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            (root / 'scripts/example.py').write_text('print("public")\n')
            for relative in ('.env', 'secretary/profile.md', '.sandbox/profile.md', '.cache/news.sqlite', '.git/config'):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fictional-private-sentinel')
            output = root / 'release.zip'
            result = build(root, output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(sorted(archive.namelist()), ['GoodMorning/RELEASE-MANIFEST.json', 'GoodMorning/scripts/example.py'])
                manifest = json.loads(archive.read('GoodMorning/RELEASE-MANIFEST.json'))
                self.assertEqual(manifest['scripts/example.py'], hashlib.sha256(archive.read('GoodMorning/scripts/example.py')).hexdigest())
            self.assertEqual(result['sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
            with self.assertRaises(ValueError):
                build(root, output)

    def test_release_rejects_symlinked_public_files(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            (root / 'private.txt').write_text('fictional-private-sentinel')
            (root / 'scripts/example.py').symlink_to(root / 'private.txt')
            with self.assertRaises(ValueError):
                public_files(root)

    def test_runtime_python_sources_parse_with_supported_grammar(self):
        for path in (ROOT / 'scripts').glob('*.py'):
            with self.subTest(path=path.name):
                ast.parse(path.read_text(), filename=str(path), feature_version=(3, 9))

    def test_bundled_vendor_hashes_and_license_are_intact(self):
        directory = ROOT / 'scripts/vendor/openchamber-relay'
        manifest = json.loads((directory / 'manifest.json').read_text())
        for name, expected in manifest['sha256'].items():
            self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), expected)

    def test_runtime_ignore_rule_does_not_hide_the_secretary_skill(self):
        rules = (ROOT / '.gitignore').read_text().splitlines()
        self.assertIn('/secretary/', rules)
        self.assertNotIn('secretary/', rules)
        self.assertTrue((ROOT / '.opencode/skills/secretary/SKILL.md').is_file())


if __name__ == '__main__':
    unittest.main()
