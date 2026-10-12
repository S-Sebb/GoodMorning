"""Manual skill-copy contracts; no personal data or network."""

import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from support import TEMP_ROOT

ROOT = Path(__file__).resolve().parents[1]


class DeploymentTests(unittest.TestCase):
    def test_manual_copy_is_self_contained_without_source_edits(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            home = Path(directory)
            skill = home / '.agents/skills/goodmorning'
            skill.mkdir(parents=True)
            shutil.copy2(ROOT / 'skill-source/goodmorning.md', skill / 'SKILL.md')
            shutil.copy2(ROOT / 'LICENSE', skill / 'LICENSE')
            shutil.copy2(ROOT / 'config.example.md', skill / 'config.example.md')
            for name in ('scripts', 'src', 'assets', 'integrations', 'vendor', 'requirements', 'docs', 'templates'):
                shutil.copytree(ROOT / name, skill / name,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            text = (skill / 'SKILL.md').read_text()
            self.assertEqual(text, (ROOT / 'skill-source/goodmorning.md').read_text())
            self.assertEqual((skill / 'LICENSE').read_bytes(), (ROOT / 'LICENSE').read_bytes())
            self.assertNotIn('../', text)
            for reference in re.findall(r'`((?:docs|templates)/[^`]+\.md)`', text):
                self.assertTrue((skill / reference).is_file(), reference)
            sys.path.insert(0, str(ROOT / 'src'))
            from goodmorning.cli import COMMANDS
            for helper in COMMANDS:
                result = subprocess.run([sys.executable, '-B', str(skill / 'scripts/goodmorning.py'), helper, '--help'],
                                        cwd=home, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(skill.rglob('SKILL.md')), [skill / 'SKILL.md'])
            for name in ('.config', '.local', '.cache', 'secretary'):
                self.assertFalse((home / name).exists())
            for name in ('.opencode', 'secretary', '.cache', '.env', 'tests', 'skill-source'):
                self.assertFalse((skill / name).exists())

    def test_no_installation_or_packaging_helpers_remain(self):
        for name in ('install_skill.py', 'package_release.py'):
            self.assertFalse((ROOT / 'scripts' / name).exists())

    def test_runtime_python_sources_parse_with_supported_grammar(self):
        paths = [*(ROOT / 'src').rglob('*.py'), *(ROOT / 'scripts').glob('*.py'), *(ROOT / 'integrations').rglob('*.py')]
        for path in paths:
            with self.subTest(path=path.name):
                ast.parse(path.read_text(), filename=str(path), feature_version=(3, 9))

    def test_bundled_vendor_hashes_and_license_are_intact(self):
        directory = ROOT / 'vendor/openchamber-relay'
        manifest = json.loads((directory / 'manifest.json').read_text())
        for name, expected in manifest['sha256'].items():
            self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), expected)

    def test_runtime_ignore_rule_does_not_hide_the_inactive_skill_source(self):
        rules = (ROOT / '.gitignore').read_text().splitlines()
        self.assertIn('/secretary/', rules)
        self.assertNotIn('secretary/', rules)
        self.assertTrue((ROOT / 'skill-source/goodmorning.md').is_file())


if __name__ == '__main__':
    unittest.main()
