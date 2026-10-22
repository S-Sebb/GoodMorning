"""Skill discovery and workflow references."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SkillTests(unittest.TestCase):
    def test_discovery_and_workflow_references(self):
        entry = (ROOT / 'skill-source/goodmorning.md').read_text()
        self.assertIn('name: goodmorning', entry)
        self.assertEqual(list(ROOT.glob('**/SKILL.md')), [])
        for kind in ('gm', 'gn', 'eureka', 'todo', 'secretary'):
            path = 'docs/workflows/' + kind + '.md'
            self.assertIn(path, entry)
            text = (ROOT / path).read_text()
            self.assertRegex(text, rf'^---\nname: {kind}\ndescription: .+')
            for reference in re.findall(r'`((?:docs|templates)/[^`]+\.md)`', text):
                self.assertTrue((ROOT / reference).is_file(), reference)


if __name__ == '__main__':
    unittest.main()
