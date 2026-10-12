"""Mechanical web workflow: short dispatch, explicit feedback and durable tasks."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning.briefings.briefing_job import act, context_path, decode_input, next_step
from goodmorning.briefings.briefing_preflight import answer, initialize
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.briefings.briefing_stream import load
from goodmorning.records.daily import inspect
from goodmorning.records.daily import amend as daily_amend
from goodmorning.records import state
from test_briefing_server import FakeChamber


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        workers = []
        def worker(*args, **kwargs):
            thread = Thread(*args, **kwargs)
            workers.append(thread)
            return thread
        def join_workers():
            for thread in workers:
                thread.join(5)
                self.assertFalse(thread.is_alive(), 'Fixture worker must finish before deleting its runtime')
        patcher = patch('goodmorning.web.briefing_server.threading.Thread', side_effect=worker)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(join_workers)
        self.root = Path(self.temp.name)
        (self.root/'profile.md').write_text('city: London, GB\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n')
        (self.root/'daily').mkdir()
        self.chamber = FakeChamber()
        self.app = BrowserApp(self.root,self.chamber,now=lambda:datetime(2026,10,11,12,tzinfo=timezone.utc),preflight=True)
        self.identifier = 'a'*32
        self.job = {'id':self.identifier,'date':'2026-10-11','kind':'gm','session':'ses_fixture','state':'running','workflow':2}
        self.app.jobs['2026-10-11.gm'] = self.job
        self.app.save_jobs()
        initialize(self.root,self.job)

    def init(self):
        return act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.','opening':'Let’s plan carefully.',
            'plan':[['must-do','Must-do'],['nice-to-do','Nice-to-do']]})

    def test_owner_and_prepared_context_are_code_owned(self):
        with self.assertRaises(ValueError): act(self.root,self.identifier,'ses_other','prepare')
        result = act(self.root,self.identifier,'ses_fixture','prepare')
        self.assertEqual(result['date'],'2026-10-11')
        self.assertNotIn('form',result)
        (self.root/'profile.md').write_text('timezone: Asia/Shanghai\n')
        self.assertEqual(act(self.root,self.identifier,'ses_fixture','prepare')['timezone'],'Europe/London')

    def test_exact_recipes_initialize_before_collection_and_advance_one_section(self):
        result = act(self.root,self.identifier,'ses_fixture','prepare')
        self.assertEqual(result['next']['action'],'init')
        self.assertNotIn('read',result['next'])
        self.assertIn('--session ses_fixture init',result['next']['command'])
        result = act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.','opening':'Let’s look.'})
        self.assertEqual(result['next']['section'],['weather','Weather'])
        self.assertEqual(len(result['next']['read']),1)
        self.assertIn('goodmorning.py weather --secretary-dir',result['next']['read'][0])
        result = act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':['weather',[['p','Forecast unavailable; check before travelling.']]]})
        self.assertEqual(result['next']['position'],1)
        self.assertEqual(result['next']['section'],['news','News — 2026-10-10'])
        self.assertIn('--today 2026-10-11',result['next']['read'][0])
        self.assertNotIn('calendar',str(result['next']))

    def test_bad_json_and_block_shape_preserve_preview_and_explain_repairs(self):
        self.init()
        target = self.app.job_dir/(self.identifier+'.preview.json')
        before = target.read_bytes()
        for raw in (b'{"position":0,"position":1}', b'{"position":0,}', b'{"position":NaN}', b'\xff'):
            with self.assertRaises(ValueError): decode_input(raw)
        with self.assertRaisesRegex(ValueError,'line 1, column'):
            decode_input(b'{"position":0,}')
        with self.assertRaisesRegex(ValueError,'use p/list/table/agenda/tasks/weather/news'):
            act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':['must-do',[['text','Wrong tag']]]})
        self.assertEqual(target.read_bytes(),before)

    def test_completed_cleanup_cannot_reinitialize_or_replay(self):
        self.init()
        act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':['must-do',[['tasks',[['open','Ranking','']]]]]})
        act(self.root,self.identifier,'ses_fixture','skip',{'position':1})
        act(self.root,self.identifier,'ses_fixture','finish',{})
        self.chamber.forms=[];self.chamber.permissions=[];self.chamber.busy=False
        self.assertEqual(self.app.status(self.identifier)['state'],'ready')
        self.assertFalse((self.app.job_dir/(self.identifier+'.preview.json')).exists())
        before = {path:path.read_bytes() for path in (self.root/'daily').iterdir()}
        for action in ('prepare','init','finish'):
            with self.assertRaisesRegex(ValueError,'complete; stop'):
                act(self.root,self.identifier,'ses_fixture',action,{})
        self.assertEqual(before,{path:path.read_bytes() for path in (self.root/'daily').iterdir()})

    def test_authorized_images_only_after_news_is_published(self):
        context = json.loads(context_path(self.root,self.identifier).read_text())
        context['integration_policy']={'publisher_images':True,'calendar_sync':False}
        context_path(self.root,self.identifier).write_text(json.dumps(context))
        act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.','opening':'Let’s look.', 'plan':[['news','News — 2026-10-10']]})
        section=['news',[['news','World',[['Headline','Sourced news.',[['Publisher','https://example.org/story']]]]]]]
        def cache(*args):
            checkpoint = load(self.app.job_dir/(self.identifier+'.preview.json'))
            self.assertEqual(checkpoint['outcomes'],['ready'])
            self.assertFalse((self.root/'daily/2026-10-11.gm.json').exists())
            return {args[0][0]:{'status':'unavailable'}}
        with patch('goodmorning.briefings.briefing_images.cache_previews',side_effect=cache) as fetch:
            result=act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':section})
            self.assertEqual(result['images']['unavailable'],1)
            self.assertEqual(result['next']['action'],'finish')
            act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':section})
            fetch.assert_called_once()

    def test_disabled_image_policy_makes_no_fetch(self):
        act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.','opening':'Let’s look.', 'plan':[['news','News — 2026-10-10']]})
        with patch('goodmorning.briefings.briefing_images.cache_previews',side_effect=AssertionError('No consent')):
            result=act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':['news',[['news','World',[
                ['Headline','Sourced news.',[['Publisher','https://example.org/story']]]]]]]})
            self.assertTrue(result['images']['disabled'])
            self.assertEqual(result['images']['unavailable'],1)
            self.assertEqual(result['images']['cached'],0)

    def test_image_cache_errors_do_not_undo_published_news_or_trigger_republication(self):
        import sqlite3
        context=json.loads(context_path(self.root,self.identifier).read_text())
        context['integration_policy']={'publisher_images':True}
        context_path(self.root,self.identifier).write_text(json.dumps(context))
        act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.','opening':'Let’s look.','plan':[['news','News — 2026-10-10']]})
        payload={'position':0,'section':['news',[['news','World',[
            ['Headline','Sourced news.',[['Publisher','https://example.org/story']]]]]]]}
        with patch('goodmorning.briefings.briefing_images.cache_previews',side_effect=sqlite3.OperationalError('Synthetic cache failure')) as fetch:
            result=act(self.root,self.identifier,'ses_fixture','publish',payload)
            self.assertTrue(result['images']['unavailable'])
            self.assertEqual(result['next']['action'],'finish')
            self.assertEqual(load(self.app.job_dir/(self.identifier+'.preview.json'))['outcomes'],['ready'])
            self.assertTrue(act(self.root,self.identifier,'ses_fixture','publish',payload)['reused'])
            fetch.assert_called_once()

    def test_section_only_publication_idempotence_and_automatic_daily_sync(self):
        self.init()
        section = ['must-do',[['tasks',[['open','Compute the ranking','Due today.']]]],'Start with the deadline.']
        payload = {'position':0,'section':section}
        act(self.root,self.identifier,'ses_fixture','publish',payload)
        self.assertTrue(act(self.root,self.identifier,'ses_fixture','publish',payload)['reused'])
        bad = deepcopy(payload);bad['section'][2]='Changed'
        with self.assertRaises(ValueError): act(self.root,self.identifier,'ses_fixture','publish',bad)
        act(self.root,self.identifier,'ses_fixture','skip',{'position':1})
        self.assertTrue(act(self.root,self.identifier,'ses_fixture','skip',{'position':1})['reused'])
        self.assertFalse((self.root/'daily/2026-10-11.md').exists())
        receipt = act(self.root,self.identifier,'ses_fixture','finish',{'closing':'Take care.'})
        self.assertTrue(receipt['saved'])
        self.assertFalse((self.app.job_dir/(self.identifier+'.draft.json')).exists())
        text = (self.root/'daily/2026-10-11.md').read_text()
        self.assertIn('- [ ] Compute the ranking',text)
        self.assertIn('- gm: yes (session ses_fixture)',text)
        self.assertEqual(len(inspect(text,'2026-10-11')[2]),1)

    def test_cannot_save_partial_preview_or_skip_unavailable_required_material(self):
        act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.','opening':'Let’s look.', 'plan':[['weather','Weather']]})
        with self.assertRaises(ValueError): act(self.root,self.identifier,'ses_fixture','skip',{'position':0})
        with self.assertRaises(ValueError): act(self.root,self.identifier,'ses_fixture','finish',{})
        self.assertFalse((self.root/'daily/2026-10-11.gm.json').exists())

    def test_gn_preflight_marks_only_exact_user_selected_tasks(self):
        (self.root/'daily/2026-10-11.md').write_text('# 2026-10-11\n\n## must-do\n- [ ] Ranking\n- [ ] Travel plan\n')
        self.job['kind']='gn';self.app.jobs={'2026-10-11.gn':self.job};self.app.save_jobs()
        context=initialize(self.root,self.job)
        self.assertTrue(context['awaiting'])
        task=context['daily']['tasks'][0]['id']
        with self.assertRaises(ValueError): answer(self.root,self.job,{'completed':['none',task],'details':'No other updates'})
        with self.assertRaises(ValueError): answer(self.root,self.job,{'completed':['foreign'],'details':'No other updates'})
        payload={'completed':[task],'details':'Travel planning is partial.'}
        result=answer(self.root,self.job,payload)
        self.assertFalse(result['awaiting'])
        self.assertEqual(answer(self.root,self.job,payload),result)
        text=(self.root/'daily/2026-10-11.md').read_text()
        self.assertIn('- [x] Ranking',text)
        self.assertIn('- [ ] Travel plan',text)
        self.assertEqual(text.count('Travel planning is partial.'),1)
        self.assertFalse((self.root/'daily/2026-10-11.gn.json').exists())

    def test_missed_choice_is_resolved_once_without_model(self):
        (self.root/'daily/2026-10-10.md').write_text('# 2026-10-10\n- gn: yes (session ses_old)\n')
        context=initialize(self.root,self.job)
        self.assertTrue(context['awaiting'])
        self.assertEqual(self.chamber.calls,[])
        result=answer(self.root,self.job,{'continue':'today'})
        self.assertEqual(result['missed_total'],0)
        self.assertEqual(result['past_missing_choice'],'continue_today')

    def test_feedback_retry_recovers_atomic_amendment_without_double_recording(self):
        path=self.root/'daily/2026-10-11.md'
        path.write_text('# 2026-10-11\n\n## must-do\n- [ ] Ranking\n')
        self.job['kind']='gn';self.app.jobs={'2026-10-11.gn':self.job};self.app.save_jobs()
        context=initialize(self.root,self.job)
        payload={'completed':[context['daily']['tasks'][0]['id']],'details':'No other updates'}
        def interrupted(*args,**kwargs):
            result=daily_amend(*args,**kwargs)
            if not kwargs.get('dry_run'):
                raise OSError('Synthetic interrupted receipt')
            return result
        with patch('goodmorning.briefings.briefing_preflight.amend',side_effect=interrupted):
            with self.assertRaises(OSError):answer(self.root,self.job,payload)
        self.assertIn('- [x] Ranking',path.read_text())
        self.assertTrue(json.loads(context_path(self.root,self.identifier).read_text())['awaiting'])
        result=answer(self.root,self.job,payload)
        self.assertFalse(result['awaiting'])
        self.assertEqual(path.read_text().count('Completed: Ranking'),1)

    def test_feedback_conflict_preserves_changed_plan_and_blocks_dispatch(self):
        path=self.root/'daily/2026-10-11.md'
        path.write_text('# 2026-10-11\n\n## must-do\n- [ ] Ranking\n')
        self.job['kind']='gn';self.app.jobs={'2026-10-11.gn':self.job};self.app.save_jobs()
        context=initialize(self.root,self.job)
        changed=path.read_text()+'- [ ] New user task\n';path.write_text(changed)
        payload={'completed':[context['daily']['tasks'][0]['id']],'details':'No other updates'}
        with self.assertRaisesRegex(ValueError,'daily plan changed'):
            answer(self.root,self.job,payload)
        self.assertEqual(path.read_text(),changed)
        self.assertEqual(self.chamber.calls,[])

    def test_finished_plan_preserves_prior_completion_and_unrelated_tasks(self):
        path=self.root/'daily/2026-10-11.md'
        path.write_text('# 2026-10-11\n\n## must-do\n- [x] Prior task\n- [ ] Unrelated task\n')
        self.init()
        act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':
            ['must-do',[['tasks',[['open','Prior task',''],['open','New task','']]]]]})
        act(self.root,self.identifier,'ses_fixture','skip',{'position':1})
        act(self.root,self.identifier,'ses_fixture','finish',{})
        self.assertIn('- [x] Prior task',path.read_text())
        self.assertIn('- [ ] Unrelated task',path.read_text())
        self.assertIn('- [ ] New task',path.read_text())
        self.assertEqual(len(inspect(path.read_text(),'2026-10-11')[2]),3)

    def test_browser_waits_for_gn_feedback_before_creating_session(self):
        self.app.jobs={};self.app.save_jobs()
        result=self.app.start('2026-10-11','gn')
        self.assertEqual(self.app.status(result['job'])['state'],'waiting')
        self.assertEqual(self.chamber.calls,[])
        self.app.reply(result['job'],'form','preflight_'+result['job'],{'answer':{'completed':['none'],'details':'No other updates'}})
        self.assertTrue(self.chamber.sent.wait(2))
        self.assertEqual(sum(a=='session.create' for a,_ in self.chamber.calls),1)

    def test_modern_saved_snapshot_without_run_marker_is_not_ready(self):
        self.init()
        section=['must-do',[['tasks',[['open','Ranking','']]]]]
        act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':section})
        act(self.root,self.identifier,'ses_fixture','skip',{'position':1})
        checkpoint=load(self.app.job_dir/(self.identifier+'.preview.json'))
        (self.root/'daily/2026-10-11.gm.json').write_text(json.dumps(checkpoint['document']))
        self.chamber.forms=[];self.chamber.permissions=[];self.chamber.busy=False
        self.assertEqual(self.app.status(self.identifier)['state'],'stopped')
        self.assertEqual(self.app.start('2026-10-11','gm'),{'job':self.identifier})
        # The authentic same job can finish its interrupted matching save without --force.
        act(self.root,self.identifier,'ses_fixture','finish',{})
        self.assertEqual(self.app.status(self.identifier)['state'],'ready')

    def test_invalid_content_is_rejected_before_immutable_publication(self):
        with self.assertRaisesRegex(ValueError, 'boilerplate'):
            act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.',
                'opening':'Weather retrieval returned no warnings.'})
        self.init()
        target = self.app.job_dir/(self.identifier+'.preview.json')
        before = target.read_bytes()
        for status, detail in (('open','Weather retrieval returned no warnings.'), ('done','Claimed completion.')):
            with self.assertRaises(ValueError):
                act(self.root,self.identifier,'ses_fixture','publish',{'position':0,
                    'section':['must-do',[['tasks',[[status,'Ranking',detail]]]]]})
            self.assertEqual(target.read_bytes(),before)
        act(self.root,self.identifier,'ses_fixture','publish',{'position':0,
            'section':['must-do',[['tasks',[['open','Ranking','Due tomorrow.']]]]]})
        act(self.root,self.identifier,'ses_fixture','skip',{'position':1})
        self.assertTrue(act(self.root,self.identifier,'ses_fixture','finish',{})['saved'])

    def test_interrupted_final_save_repairs_only_matching_index(self):
        self.init()
        act(self.root,self.identifier,'ses_fixture','publish',{'position':0,
            'section':['must-do',[['tasks',[['open','Ranking','']]]]]})
        act(self.root,self.identifier,'ses_fixture','skip',{'position':1})
        with patch.object(state,'save_state',side_effect=OSError('Synthetic index interruption')):
            with self.assertRaisesRegex(ValueError,'state_unavailable'):
                act(self.root,self.identifier,'ses_fixture','finish',{})
        self.chamber.forms=[];self.chamber.permissions=[];self.chamber.busy=False
        self.assertEqual(self.app.status(self.identifier)['state'],'stopped')
        page=self.app.page('2026-10-11','gm',False).decode()
        self.assertIn('&quot;missing&quot;: true',page)
        self.assertIn('id="generation"',page)
        before={p:p.read_bytes() for p in (self.root/'daily').iterdir()}
        self.assertTrue(act(self.root,self.identifier,'ses_fixture','finish',{})['saved'])
        self.assertEqual(before,{p:p.read_bytes() for p in (self.root/'daily').iterdir()})
        self.assertTrue((self.root/'state.json').exists())
        self.assertEqual(self.app.status(self.identifier)['state'],'ready')

    def test_explicit_recovery_reopens_stopped_undispatched_preflight(self):
        self.app.jobs={};self.app.save_jobs()
        (self.root/'daily/2026-10-10.md').write_text('# 2026-10-10\n- gn: yes (session ses_old)\n')
        identifier=self.app.start('2026-10-11','gm')['job']
        self.app.reply(identifier,'form','preflight_'+identifier,{'answer':{'continue':'stop'}})
        self.assertEqual(self.app.status(identifier)['state'],'stopped')
        body={'id':'b'*32}
        self.app.recover(identifier,body)
        current=self.app.status(identifier)
        self.assertEqual(current['state'],'waiting')
        self.assertNotEqual(current['forms'][0]['id'],'preflight_'+identifier)
        self.app.recover(identifier,body)
        self.assertEqual(self.app.status(identifier),current)
        self.assertEqual(self.chamber.calls,[])

    def test_feedback_refresh_requires_new_confirmation_and_preserves_changed_plan(self):
        self.app.jobs={};self.app.save_jobs()
        path=self.root/'daily/2026-10-11.md'
        path.write_text('# 2026-10-11\n\n## must-do\n- [ ] Ranking\n')
        identifier=self.app.start('2026-10-11','gn')['job']
        old=self.app.status(identifier)['forms'][0]['id']
        changed=path.read_text()+'- [ ] New user task\n';path.write_text(changed)
        self.app.recover(identifier,{'id':'b'*32})
        form=self.app.status(identifier)['forms'][0]
        self.assertIn('New user task',str(form))
        self.assertEqual(path.read_text(),changed)
        with self.assertRaises(ValueError):
            self.app.reply(identifier,'form',old,{'answer':{'completed':['none'],'details':'No other updates'}})
        self.assertEqual(self.chamber.calls,[])
        self.app.reply(identifier,'form',form['id'],{'answer':{'completed':['none'],'details':'No other updates'}})
        self.assertTrue(self.chamber.sent.wait(2))

    def test_recovery_continues_only_a_known_idle_session_once(self):
        for job_state in ('uncertain','starting'):
            self.job['state']=job_state;self.app.save_jobs()
            with self.assertRaises(ValueError): self.app.recover(self.identifier,{'id':'b'*32})
        self.job['state']='running';self.app.save_jobs()
        self.chamber.forms=[];self.chamber.permissions=[]
        with self.assertRaises(ValueError): self.app.recover(self.identifier,{'id':'b'*32})
        self.chamber.busy=False
        self.app.recover(self.identifier,{'id':'b'*32})
        self.assertTrue(self.chamber.sent.wait(2))
        self.app.recover(self.identifier,{'id':'b'*32})
        self.assertEqual(sum(a=='session.send' for a,_ in self.chamber.calls),1)
        self.assertEqual(sum(a=='session.create' for a,_ in self.chamber.calls),0)

    def test_night_recipe_reads_only_tomorrow(self):
        self.job['kind']='gn';self.app.jobs={'2026-10-11.gn':self.job};self.app.save_jobs()
        context=initialize(self.root,self.job)
        recipe=next_step(self.root,self.identifier,'ses_fixture',context,{'outcomes':[1,1],
            'plan':[['today','Today'],['still-open','Still open'],['tomorrow','Tomorrow']]})
        self.assertIn('--from 2026-10-12 --days 1',recipe['read'][0])
        self.assertIn('No timed appointments does not mean a free day',recipe['instruction'])
        self.assertIn('[date,status,title,detail]',recipe['instruction'])

    def test_schedule_recipe_includes_untimed_work_without_a_calendar(self):
        context=json.loads(context_path(self.root,self.identifier).read_text())
        context['paths']['calendar_db']=None
        recipe=next_step(self.root,self.identifier,'ses_fixture',context,{'outcomes':[], 'plan':[['schedule','Schedule']]})
        self.assertEqual(recipe['read'],[])
        self.assertIn('active inbox/project constraints',recipe['instruction'])
        self.assertIn('flexible rows',recipe['instruction'])

    def test_flexible_today_tasks_sync_once_and_keep_priority_and_completion(self):
        path=self.root/'daily/2026-10-11.md'
        path.write_text('# 2026-10-11\n\n## must-do\n- [x] Prior task\n- [ ] Unrelated task\n')
        act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.','opening':'Plan carefully.',
            'plan':[['schedule','Schedule'],['must-do','Must-do']]})
        section=['schedule',[['flexible',[
            ['2026-10-11','open','Prior task',''],['2026-10-11','partial','Untimed work','Still open.'],
            ['2026-10-11','open','Important task',''],['2026-10-12','open','Future work',''],
            ['','open','Undated work','']]]]]
        bad=deepcopy(section);bad[1][0][1][1][1]='done'
        with self.assertRaisesRegex(ValueError,'planned_task_completion'):
            act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':bad})
        act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':section})
        act(self.root,self.identifier,'ses_fixture','publish',{'position':1,'section':
            ['must-do',[['tasks',[['open','Important task','']]]]]})
        act(self.root,self.identifier,'ses_fixture','finish',{})
        text=path.read_text();tasks=inspect(text,'2026-10-11')[2]
        self.assertIn('- [x] Prior task',text)
        self.assertEqual(len(tasks),4)
        self.assertEqual(next(t for t in tasks if t['text']=='Important task')['section'],'must-do')
        self.assertEqual(next(t for t in tasks if t['text']=='Untimed work')['section'],'flexible')
        self.assertFalse(next(t for t in tasks if t['text']=='Untimed work')['done'])
        self.assertNotIn('Future work',text)
        self.assertNotIn('Undated work',text)

    def test_night_flexible_work_does_not_create_or_complete_daily_tasks(self):
        path=self.root/'daily/2026-10-11.md'
        path.write_text('# 2026-10-11\n\n## flexible\n- [ ] Untimed work\n')
        self.assertTrue(state.parse_daily(str(path))['sections']['tasks'])
        self.job['kind']='gn';self.app.jobs={'2026-10-11.gn':self.job};self.app.save_jobs()
        context=initialize(self.root,self.job)
        self.assertEqual(context['daily']['tasks'][0]['section'],'flexible')
        self.assertIn('Untimed work',str(context['form']))
        answer(self.root,self.job,{'completed':['none'],'details':'No other updates'})
        act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Evening.','opening':'Plan carefully.',
            'plan':[['tomorrow','Tomorrow']]})
        act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':
            ['tomorrow',[['flexible',[['2026-10-12','open','Tomorrow task','No fixed time.']]]]]})
        act(self.root,self.identifier,'ses_fixture','finish',{})
        self.assertIn('- [ ] Untimed work',path.read_text())
        self.assertNotIn('Tomorrow task',path.read_text())
        self.assertFalse((self.root/'daily/2026-10-12.md').exists())


if __name__=='__main__':
    unittest.main()
