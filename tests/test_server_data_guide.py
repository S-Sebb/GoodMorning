"""Public release and synthetic trials retain their required data-safety contract."""
import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUIDES = {'AGENTS.md','AGENT-PROMPT-GUIDE.md','SERVER-USER-GUIDE.md','SERVER-DATA-GUIDE.md'}


class ServerDataGuideTests(unittest.TestCase):
    def test_filtered_release_keeps_every_required_root_guide(self):
        runbook = (ROOT/'docs/server-deployment.md').read_text()
        allowed = ast.literal_eval(re.search(r'^allowed=(\{.*\})$',runbook,re.M)[1])
        self.assertTrue(GUIDES <= allowed)
        for name in GUIDES:
            self.assertTrue((ROOT/name).is_file(), name)
        self.assertIn('`SERVER-DATA-GUIDE.md`', (ROOT/'AGENTS.md').read_text())

    def test_isolated_model_trials_keep_the_referenced_guide(self):
        for name in ('website_live.py','task_tone_live.py','manual_trial.py','briefing_tone_live.py'):
            with self.subTest(trial=name):
                self.assertIn('SERVER-DATA-GUIDE.md', (ROOT/'tests/benchmarks'/name).read_text())
