"""Safety checks for the opt-in paid matrix; these tests never call a model."""
from pathlib import Path
import argparse
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from benchmarks import task_tone_live as trial
from benchmarks.task_tone_live import matrix_lock


class MatrixLockTests(unittest.TestCase):
    def test_overlapping_runner_is_refused_and_lock_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'matrix'
            with matrix_lock(output):
                with self.assertRaisesRegex(ValueError,'active runner'):
                    with matrix_lock(output):
                        self.fail('Second runner entered the matrix')
            with matrix_lock(output):
                self.assertFalse(output.exists())

    def test_exception_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'matrix'
            with self.assertRaisesRegex(RuntimeError,'interrupted'):
                with matrix_lock(output):
                    raise RuntimeError('interrupted')
            with matrix_lock(output):
                pass


class MatrixLanguageTests(unittest.TestCase):
    def setUp(self):
        # The trial CLI only accepts private output beneath the checkout's task root.
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        task_root=patch('benchmarks.trial_engine.task_root',return_value=self.root)
        task_root.start()
        self.addCleanup(task_root.stop)

    def test_output_outside_the_task_root_is_refused(self):
        arguments=['task_tone_live.py','--output',str(self.root.parent/'elsewhere')]
        with patch.object(sys,'argv',arguments),patch.object(argparse.ArgumentParser,'error',side_effect=SystemExit) as error:
            with self.assertRaises(SystemExit):
                trial.main()
        self.assertIn('beneath',error.call_args.args[0])

    def test_language_filter_reaches_runner_without_model_dispatch(self):
        arguments=['task_tone_live.py','--output',str(self.root/'matrix'),'--model','deepseek-flash','--language','zh-CN']
        with patch.object(sys,'argv',arguments),patch.object(trial,'run_matrix',return_value=0) as run:
            self.assertEqual(trial.main(),0)
        args=run.call_args.args[0]
        self.assertEqual((args.model,args.language),('deepseek-flash','zh-CN'))

    def test_resume_cannot_change_language(self):
        output=self.root/'matrix'
        output.mkdir()
        (output/'matrix.json').write_text(json.dumps({
            'model':'opencode-go/muse-spark-1.3-contributor','variant':'xhigh',
            'tone_only':False,'language':'en','date':'2026-10-14'}))
        arguments=['task_tone_live.py','--output',str(output),'--resume','--language','zh-CN']
        with patch.object(sys,'argv',arguments),patch.object(argparse.ArgumentParser,'error',side_effect=SystemExit) as error:
            with self.assertRaises(SystemExit):
                trial.main()
        self.assertIn('language',error.call_args.args[0])


class ChatStructureTests(unittest.TestCase):
    def test_confirmation_allows_progress_but_does_not_grade_tone(self):
        self.assertEqual(trial.chat_structure_issues('deadline',{'assistant':['Recorded.'],'forms':[]}),[])
        self.assertEqual(trial.chat_structure_issues('deadline',{'assistant':['Saving now.','Recorded.'],'forms':[]}),[])
        self.assertTrue(trial.chat_structure_issues('deadline',{'assistant':[],'forms':[]}))

    def test_clarification_asks_only_interval_and_allows_progress(self):
        observation={'assistant':[],'forms':[{'fields':[{'key':'interval','type':'integer'}]}]}
        self.assertEqual(trial.chat_structure_issues('ambiguity-before-write',observation),[])
        observation['forms'][0]['fields'].append({'key':'start','type':'string','format':'date'})
        self.assertTrue(trial.chat_structure_issues('ambiguity-before-write',observation))
        observation['forms'][0]['fields'].pop()
        observation['assistant']=['Let me ask you a question.']
        self.assertEqual(trial.chat_structure_issues('ambiguity-before-write',observation),[])


class BasePromptPreflightTests(unittest.TestCase):
    def test_waits_for_exact_location_prompt_without_mutations(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock(directory='/synthetic/source')
            bridge.request.side_effect=[{'data':{'id':'build'}},{'data':{'id':'build','system':'Trial prompt'}}]
            with patch.object(trial.time,'sleep'):
                trial.verify_trial_system(bridge,Path(directory),'Trial prompt')
            for call in bridge.request.call_args_list:
                self.assertEqual(len(call.args),1)  # GET only: no request body.
                self.assertTrue(call.args[0].startswith('/api/agent/build?location%5Bdirectory%5D='))
            evidence=json.loads((Path(directory)/'base-prompt-preflight.json').read_text())
            self.assertEqual(len(evidence['checks']),2)

    def test_unavailable_prompt_blocks_all_model_work(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge=Mock(directory='/synthetic/source')
            bridge.request.return_value={'data':{'id':'build'}}
            with patch.object(trial.time,'sleep'):
                with self.assertRaisesRegex(AssertionError,'no model requests dispatched'):
                    trial.verify_trial_system(bridge,Path(directory),'Trial prompt')
            self.assertEqual(bridge.request.call_count,10)


if __name__=='__main__':
    unittest.main()
