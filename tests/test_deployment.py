"""Manual skill-copy contracts; no personal data or network."""

import ast
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
            # One interpreter loads the copied entry point, then asks every helper for --help.
            code = ('import contextlib, io, runpy, sys\n'
                    'entry = runpy.run_path(sys.argv[1])\n'
                    'from goodmorning.cli import COMMANDS\n'
                    'import goodmorning; assert goodmorning.__file__.startswith(sys.argv[2]), goodmorning.__file__\n'
                    'for helper in COMMANDS:\n'
                    '    try:\n'
                    '        with contextlib.redirect_stdout(io.StringIO()): code = entry["main"]([helper, "--help"])\n'
                    '    except SystemExit as error: code = error.code\n'
                    '    assert code in (0, None), (helper, code)\n'
                    '    print(helper)\n')
            result = subprocess.run([sys.executable, '-B', '-c', code, str(skill / 'scripts/goodmorning.py'), str(skill)],
                                    cwd=home, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            sys.path.insert(0, str(ROOT / 'src'))
            from goodmorning.cli import COMMANDS
            self.assertEqual(result.stdout.split(), list(COMMANDS))
            self.assertEqual(list(skill.rglob('SKILL.md')), [skill / 'SKILL.md'])
            for name in ('.config', '.local', '.cache', 'secretary'):
                self.assertFalse((home / name).exists())
            for name in ('.opencode', 'secretary', '.cache', '.env', 'tests', 'skill-source'):
                self.assertFalse((skill / name).exists())

    def test_runtime_python_sources_parse_with_supported_grammar(self):
        paths = [*(ROOT / 'src').rglob('*.py'), *(ROOT / 'scripts').glob('*.py'), *(ROOT / 'integrations').rglob('*.py')]
        for path in paths:
            with self.subTest(path=path.name):
                ast.parse(path.read_text(), filename=str(path), feature_version=(3, 9))

    def test_runtime_ignore_rule_does_not_hide_the_inactive_skill_source(self):
        rules = (ROOT / '.gitignore').read_text().splitlines()
        self.assertIn('/secretary/', rules)
        self.assertNotIn('secretary/', rules)
        self.assertTrue((ROOT / 'skill-source/goodmorning.md').is_file())


if __name__ == '__main__':
    unittest.main()
