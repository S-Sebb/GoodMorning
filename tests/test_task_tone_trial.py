"""Safety checks for the opt-in paid matrix; these tests never call a model."""
from pathlib import Path
import argparse
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from benchmarks import task_tone_live as trial
from benchmarks.task_tone_live import matrix_lock

# The trial CLI only accepts private output below this root.
Path('/tmp/opencode').mkdir(exist_ok=True)


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
    def test_language_filter_reaches_runner_without_model_dispatch(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as directory:
            output=Path(directory)/'matrix'
            arguments=['task_tone_live.py','--output',str(output),'--model','deepseek-flash','--language','zh-CN']
            with patch.object(sys,'argv',arguments),patch.object(trial,'run_matrix',return_value=0) as run:
                self.assertEqual(trial.main(),0)
            args=run.call_args.args[0]
            self.assertEqual((args.model,args.language),('deepseek-flash','zh-CN'))

    def test_resume_cannot_change_language(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as directory:
            output=Path(directory)
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
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as directory:
            source=Path(directory)/'source'
            replies=[SimpleNamespace(returncode=0,stdout=json.dumps({'data':{'id':'build'}})),
                     SimpleNamespace(returncode=0,stdout=json.dumps({'data':{'id':'build','system':'Trial prompt'}}))]
            with patch.object(trial.subprocess,'run',side_effect=replies) as run,patch.object(trial.time,'sleep'):
                trial.verify_trial_system(source,'Trial prompt')
            for call in run.call_args_list:
                command=call.args[0]
                self.assertEqual(command[:3],['opencode','api','get'])
                self.assertIn('location%5Bdirectory%5D',command[3])
            evidence=json.loads((Path(directory)/'base-prompt-preflight.json').read_text())
            self.assertEqual(len(evidence['checks']),2)

    def test_unavailable_prompt_blocks_all_model_work(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as directory:
            response=SimpleNamespace(returncode=0,stdout=json.dumps({'data':{'id':'build'}}))
            with patch.object(trial.subprocess,'run',return_value=response) as run,patch.object(trial.time,'sleep'):
                with self.assertRaisesRegex(AssertionError,'no model requests dispatched'):
                    trial.verify_trial_system(Path(directory)/'source','Trial prompt')
            self.assertEqual(run.call_count,10)


if __name__=='__main__':
    unittest.main()
