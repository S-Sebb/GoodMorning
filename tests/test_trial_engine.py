"""Private trial engines stay isolated from the developer's own OpenCode; no engine or model runs."""
import argparse
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from support import TEMP_ROOT
from benchmarks import trial, trial_engine
from benchmarks.trial_engine import Engine, TrialBridge


class TrialEngineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_output_must_be_a_run_beneath_this_checkouts_task_root(self):
        parser = Mock(spec=argparse.ArgumentParser)
        parser.error.side_effect = SystemExit
        with patch.object(trial_engine, 'task_root', return_value=self.root):
            self.assertEqual(trial_engine.private_output(parser, self.root/'run'), self.root/'run')
            for path in (self.root, self.root.parent/'elsewhere', '/tmp/opencode/run'):
                with self.subTest(path=path), self.assertRaises(SystemExit):
                    trial_engine.private_output(parser, path)

    def test_release_copy_includes_the_setup_configuration_contract(self):
        source = self.root/'release'
        source.mkdir()
        for name in trial_engine.RELEASE_DIRECTORIES:
            (source/name).mkdir()
        for name in trial_engine.RELEASE_FILES:
            (source/name).write_text('Public release document\n')
        (source/'skill-source/goodmorning.md').write_text('Secretary skill\n')
        (source/'config.example.md').write_text('Synthetic setup configuration\n')
        target = self.root/'copy'
        trial_engine.copy_release(target, source)
        self.assertEqual((target/'config.example.md').read_text(), 'Synthetic setup configuration\n')

    def test_detached_runner_does_not_inherit_the_launchers_temporary_environment(self):
        with patch.object(trial, 'task_root', return_value=self.root/'runs'), \
                patch.object(trial.subprocess, 'Popen', return_value=SimpleNamespace(pid=4242)) as launch, \
                patch.dict(os.environ, {'VIRTUAL_ENV': '/temporary/uv-environment'}), \
                redirect_stdout(io.StringIO()):
            trial.start('setup', 'holidays_live', ['--language', 'zh-CN'])
            self.assertNotIn('VIRTUAL_ENV', launch.call_args.kwargs['env'])
            self.assertEqual(os.environ['VIRTUAL_ENV'], '/temporary/uv-environment')

    def test_engine_gets_only_its_own_account_paths(self):
        engine = Engine(self.root/'source', self.root/'case/account')
        engine.password = 'synthetic'
        with patch.dict(os.environ, {'CALENDAR_DB_PATH':'/developer/calendar.sqlite', 'OPENCODE_API_KEY':'developer'}):
            environment = engine.environment(Path('/engines/tree'))
        self.assertNotIn('CALENDAR_DB_PATH', environment)
        self.assertNotIn('OPENCODE_API_KEY', environment)
        case = self.root/'case'
        for name in ('HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR',
                     'TMPDIR', 'SECRETARY_DIR', 'GM_CACHE_DIR', 'OPENCHAMBER_DATA_DIR'):
            with self.subTest(name=name):
                self.assertTrue(Path(environment[name]).is_relative_to(case))
        self.assertEqual(environment['SECRETARY_DIR'], str(case/'account'))
        self.assertEqual(environment['TMPDIR'], str(case/'account/tmp'))
        self.assertEqual(environment['HOME'], str(case/'engine/home'))
        self.assertEqual(environment['OPENCODE_CONFIG'], str(self.root/'source/integrations/opencode/opencode.json'))
        self.assertNotIn('OPENCODE_CONFIG_DIR', environment)

    def test_pinned_agent_is_confirmed_before_any_prompt(self):
        engine = SimpleNamespace(url='http://127.0.0.1:9', release=self.root/'source', runtime=self.root/'account', password='x')
        bridge = TrialBridge(engine, agent='build')
        with patch('benchmarks.trial_engine.LocalBridge.control', return_value={'sessionId':'ses_trial'}) as control, \
                patch.object(bridge, 'request', return_value={'data':{'agent':'secretary'}}) as request:
            with self.assertRaisesRegex(ValueError, 'not confirmed'):
                bridge.control('session.create', agent='secretary')
        control.assert_called_once_with('session.create', agent='build')
        self.assertEqual(request.call_args_list[0].args, ('/api/session/ses_trial/agent', {'agent':'build'}))
        self.assertEqual(bridge.sessions, ['ses_trial'])

    def test_stop_interrupts_running_work_before_stopping_the_engine(self):
        engine = Engine(self.root/'source', self.root/'account')
        engine.url, engine.password = 'http://127.0.0.1:9', 'x'
        engine.process = Mock(pid=4242, **{'poll.return_value':None})
        trial_engine.LIVE.add(engine)
        calls = []
        client = Mock(**{'request.side_effect':lambda path, body=None: calls.append(path) or {'data':{'ses_a':{}, 'ses_b':{}}}})
        with patch.object(trial_engine, 'LocalBridge', return_value=client), \
                patch.object(trial_engine.os, 'killpg', side_effect=lambda *call: calls.append(call)):
            engine.stop()
        self.assertEqual(calls, ['/api/session/active', '/api/session/ses_a/interrupt', '/api/session/ses_b/interrupt',
                                 (4242, signal.SIGTERM)])
        self.assertNotIn(engine, trial_engine.LIVE)


if __name__ == '__main__':
    unittest.main()
