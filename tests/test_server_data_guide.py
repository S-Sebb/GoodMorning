"""Public release and synthetic trials retain their required data-safety contract."""
from pathlib import Path
import unittest

from test_deploy_helper import helper

ROOT = Path(__file__).resolve().parents[1]
GUIDES = {'AGENTS.md','AGENT-PROMPT-GUIDE.md','SERVER-USER-GUIDE.md','SERVER-DATA-GUIDE.md'}


class ServerDataGuideTests(unittest.TestCase):
    def test_filtered_release_keeps_every_required_root_guide(self):
        self.assertTrue(GUIDES <= helper.ALLOWED)
        for name in GUIDES:
            self.assertTrue((ROOT/name).is_file(), name)
        self.assertIn('`SERVER-DATA-GUIDE.md`', (ROOT/'AGENTS.md').read_text())

    def test_isolated_model_trials_keep_the_referenced_guide(self):
        from benchmarks import trial_engine
        self.assertIn('SERVER-DATA-GUIDE.md', trial_engine.RELEASE_FILES)
