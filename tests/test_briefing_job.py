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

from support import TEMP_ROOT, FakeChamber, complete_profile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning.briefings.briefing_job import act, context_path, decode_input, next_step
from goodmorning.briefings import briefing_guides
from goodmorning.briefings.briefing_preflight import answer, initialize
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.briefings.briefing_stream import load
from goodmorning.records.daily import inspect
from goodmorning.records.daily import amend as daily_amend
from goodmorning.records import state


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
        complete_profile(self.root)
        (self.root/'daily').mkdir()
        self.chamber = FakeChamber()
        self.app = BrowserApp(self.root,self.chamber,now=lambda:datetime(2026,10,11,12,tzinfo=timezone.utc),preflight=True)
        self.identifier = 'a'*32
        self.job = {'id':self.identifier,'date':'2026-10-11','kind':'gm','session':'ses_fixture','state':'running','workflow':2,
                    'created':datetime(2026,10,11,6,30,tzinfo=timezone.utc).timestamp()}
        self.app.jobs['2026-10-11.gm'] = self.job
        self.app.save_jobs()
        initialize(self.root,self.job)

    def init(self):
        return act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.','opening':'Let’s plan carefully.',
            'plan':[['must-do','Project steps'],['nice-to-do','Optional project steps']]})

    def test_saved_user_name_reaches_the_greeting_step(self):
        (self.root/'profile.md').write_text((self.root/'profile.md').read_text()+'user_name: Sam\n')
        initialize(self.root,self.job)
        result=act(self.root,self.identifier,'ses_fixture','prepare')
        self.assertEqual(result['reply_context']['user_name'],'Sam')
        for language,optional,only in (('en','or by none','never use it in the opening, notes or progress'),
                                       ('zh-CN','也可以不称呼','开场、注记和进度里都不要用')):
            guide=briefing_guides.guide({'date':'2026-10-20','website_language':language},{'action':'init'},[],
                                        runtime=self.root,job='j'*32,session='ses_fixture')
            self.assertIn(optional,guide)  # The name is optional and limited to the greeting.
            self.assertIn(only,guide)

    def test_owner_and_prepared_context_are_code_owned(self):
        with self.assertRaises(ValueError): act(self.root,self.identifier,'ses_other','prepare')
        self.init()
        target=self.app.job_dir/(self.identifier+'.preview.json');before=target.read_bytes()
        for action,payload in (('publish',{'position':0,'section':['must-do',[['tasks',[['open','Ranking','']]]]]}),('finish',{})):
            with self.assertRaises(ValueError): act(self.root,self.identifier,'ses_other',action,payload)
        self.assertEqual(target.read_bytes(),before)
        self.assertFalse((self.root/'daily/2026-10-11.gm.json').exists())
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
        self.assertEqual(result['next']['section'],['news','News — as of 07:30'])
        self.assertIn('--latest --as-of 2026-10-11T07:30:00+01:00',result['next']['read'][0])
        self.assertNotIn('calendar',str(result['next']))

    def test_weather_read_frame_is_attached_by_code_when_publishing(self):
        frame = {'start':'2026-10-11T06:00','past':6,'hours':[[12,5,30]]*18,'sun':[['sunrise',1.2]],'night':[[0,1.2]],'snow':False,
                 'links':{'forecast':'https://open-meteo.com/en/docs#api_response','air':'https://open-meteo.com/en/docs/air-quality-api#api_response'}}
        def reads(commands):
            return [{'command':command,'exit':0,'output':{'frame':frame} if command.endswith('--json') else 'London: dry.'} for command in commands]
        from goodmorning.records.inbox_store import initialize as version_two
        version_two(self.root)
        initialize(self.root,self.job)
        with patch('goodmorning.briefings.briefing_job.run_reads', side_effect=reads):
            act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.','opening':'Let’s look.'})
        self.assertTrue((self.app.job_dir/(self.identifier+'.weather.json')).exists())
        section = ['weather',[['weather',[['temperature','12°C','Mild.'],['precipitation','5% – No rain','Dry.']]]]]
        act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':section})
        saved = load(self.app.job_dir/(self.identifier+'.preview.json'))['document']['sections'][0]
        self.assertEqual(saved[1][0][2], frame)
        # A retried publish of the agent's own section is recognised as the same one.
        self.assertTrue(act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':section})['reused'])

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
        result=act(self.root,self.identifier,'ses_fixture','finish',{})
        self.assertEqual(result['url'],'/d/2026-10-11/gm.html')
        self.assertEqual(result['reply_context']['language'],'en')
        self.assertEqual(result['reply_context']['tone'],'warm and helpful')
        self.assertNotIn('user_name',result['reply_context'])
        self.chamber.idle()
        self.assertEqual(self.app.status(self.identifier)['state'],'ready')
        self.assertFalse((self.app.job_dir/(self.identifier+'.preview.json')).exists())
        before = {path:path.read_bytes() for path in (self.root/'daily').iterdir()}
        for action in ('prepare','init','finish'):
            with self.assertRaisesRegex(ValueError,'complete; stop'):
                act(self.root,self.identifier,'ses_fixture',action,{})
        self.assertEqual(before,{path:path.read_bytes() for path in (self.root/'daily').iterdir()})

    def test_verified_link_uses_job_date_and_edition_not_profile_domains(self):
        self.job['language']='zh-CN'
        self.app.jobs['2026-10-11.gm']=self.job;self.app.save_jobs()
        initialize(self.root,self.job)
        (self.root/'profile.md').write_text((self.root/'profile.md').read_text()+'website: https://wrong.example\n')
        self.init()
        act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':['must-do',[['tasks',[['open','Ranking','']]]],'','Project steps']})
        act(self.root,self.identifier,'ses_fixture','skip',{'position':1})
        result=act(self.root,self.identifier,'ses_fixture','finish',{})
        self.assertEqual(result['url'],'/d/2026-10-11/gm.html')
        self.assertEqual(result['reply_context']['language'],'zh-CN')
        self.chamber.idle()
        self.assertEqual(self.app.status(self.identifier)['state'],'ready')
        from goodmorning.web import language
        token=language.CURRENT.set('zh-CN')
        try:
            self.assertTrue('Ranking' in self.app.page('2026-10-11','gm',True).decode())
        finally:
            language.CURRENT.reset(token)

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

    def read_news(self, counts, shown=()):
        """The news read as the job receives it, after the previous morning's links are removed."""
        from goodmorning.briefings.briefing_job import fresh_news
        story = lambda section, n: {'title':f'{section} story {n}','links':[{'source':'Publisher','url':f'https://example.org/{section}/{n}'}]}
        sections = {section:{'selected':[story(section, n) for n in range(count)],'more':[story(section, 9)]} for section, count in counts.items()}
        if shown:
            (self.root/'daily/2026-10-10.gm.json').write_text(json.dumps({'v':2,'greeting':'Morning.','opening':'Earlier.','lang':'en','sections':[
                ['news',[['news','World',[['Seen','Shown yesterday.',[['Publisher',url] for url in shown]]]]],'','News — as of 07:00']]}))
        results = [{'command':'news','exit':0,'output':{'sections':sections}}]
        fresh_news(self.root, self.identifier, self.job, json.loads(context_path(self.root,self.identifier).read_text()), results)
        return sections

    def test_news_leaves_out_stories_the_previous_morning_showed(self):
        sections = self.read_news({'ai':1,'major':1,'national':1}, shown=('https://example.org/major/0', 'https://example.org/ai/9'))
        self.assertEqual(sections['major']['selected'], [])
        self.assertEqual(sections['ai']['more'], [])
        self.assertEqual(len(sections['national']['selected']), 1)
        self.assertEqual(json.loads((self.app.job_dir/(self.identifier+'.news.json')).read_text()), ['GB','ai'])

    def test_news_must_cover_every_category_its_read_filled(self):
        self.read_news({'ai':1,'major':2,'national':1})
        act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.','opening':'Let’s look.', 'plan':[['news','News — 2026-10-10']]})
        story = lambda name: [name+' headline','Sourced summary.',[['Publisher','https://example.org/'+name]]]
        ai_only = {'position':0,'section':['news',[['news','AI',[story('ai')]]]]}
        with self.assertRaisesRegex(ValueError, 'World, National GB'):
            act(self.root,self.identifier,'ses_fixture','publish',ai_only)
        self.assertEqual(load(self.app.job_dir/(self.identifier+'.preview.json'))['outcomes'],[])
        complete = {'position':0,'section':['news',[['news','AI',[story('ai')]],['news','World',[story('world')]],
                                                    ['news','UK',[story('uk')],'GB']]]}
        self.assertEqual(act(self.root,self.identifier,'ses_fixture','publish',complete)['next']['action'],'finish')

    def test_news_without_read_material_is_not_held_to_coverage(self):
        self.read_news({'ai':1,'major':0,'national':0})
        act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.','opening':'Let’s look.', 'plan':[['news','News — 2026-10-10']]})
        section = ['news',[['news','AI',[['Headline','Sourced summary.',[['Publisher','https://example.org/a']]]]]]]
        self.assertEqual(act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':section})['next']['action'],'finish')
        # An omitted title would render as yesterday's date, so the plan's title is saved with the section.
        self.assertEqual(load(self.app.job_dir/(self.identifier+'.preview.json'))['document']['sections'][0][2:],['','News — 2026-10-10'])
        self.assertTrue(act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':section})['reused'])

    def test_news_read_lists_every_section_at_once(self):
        result = act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.','opening':'Let’s look.'})
        result = act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':['weather',[['p','Weather unavailable.']]]})
        reads = result['next']['read']
        self.assertTrue(any('--view sections' in read for read in reads), reads)
        self.assertFalse(any('--view candidates' in read for read in reads), reads)

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

    def test_morning_dispatches_without_archive_gap_confirmation(self):
        self.app.jobs={};self.app.save_jobs()
        gap=self.root/'daily/2026-10-10.md';gap.write_text('# 2026-10-10\n- gn: yes (session ses_old)\n')
        result=self.app.start('2026-10-11','gm')
        self.assertTrue(self.chamber.sent.wait(2))
        self.assertEqual(sum(action=='session.create' for action,_ in self.chamber.calls),1)
        context=json.loads(context_path(self.root,result['job']).read_text())
        self.assertFalse(context['awaiting'])
        self.assertIsNone(context['form'])
        self.assertEqual((context['missed_total'],context['past_missing_choice']),(0,'continue_today'))
        self.assertFalse((self.root/'daily/2026-10-10.gm.json').exists())
        self.assertEqual(gap.read_text(),'# 2026-10-10\n- gn: yes (session ses_old)\n')

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
        self.app.reply(result['job'],'form','preflight_'+result['job'],{'answer':{'details':'No updates today'}})
        self.assertTrue(self.chamber.sent.wait(2))
        self.assertEqual(sum(a=='session.create' for a,_ in self.chamber.calls),1)

    def test_original_generation_timestamp_survives_delay_and_regeneration(self):
        self.job['generation_started_at']=datetime(2026,10,11,1,59,tzinfo=timezone.utc).timestamp()
        self.app.save_jobs()
        self.save_original()
        identifier,_=self.regenerate()
        self.assertEqual(self.app.job(identifier)['generation_started_at'],self.job['generation_started_at'])

    def test_legacy_dispatch_time_is_not_guessed_as_the_original_request_trigger(self):
        self.job['created']=datetime(2026,10,11,1,59,tzinfo=timezone.utc).timestamp()
        self.app.save_jobs()
        self.save_original()
        identifier,_=self.regenerate()
        self.assertIsNone(self.app.job(identifier)['generation_started_at'])

    def test_new_job_uses_the_original_request_timestamp_instead_of_dispatch_clock(self):
        self.app.jobs={};self.app.save_jobs()
        started=datetime(2026,10,11,1,59,tzinfo=timezone.utc).timestamp()
        with patch('goodmorning.web.briefing_server.threading.Thread'):
            result=self.app.start('2026-10-11','gm',requested_at=started)
        self.assertEqual(self.app.job(result['job'])['generation_started_at'],started)

    def test_modern_saved_snapshot_without_run_marker_is_not_ready(self):
        self.init()
        section=['must-do',[['tasks',[['open','Ranking','']]]]]
        act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':section})
        act(self.root,self.identifier,'ses_fixture','skip',{'position':1})
        checkpoint=load(self.app.job_dir/(self.identifier+'.preview.json'))
        (self.root/'daily/2026-10-11.gm.json').write_text(json.dumps(checkpoint['document']))
        self.chamber.idle()
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
        self.chamber.idle()
        self.assertEqual(self.app.status(self.identifier)['state'],'stopped')
        page=self.app.page('2026-10-11','gm',False).decode()
        self.assertIn('&quot;missing&quot;: true',page)
        self.assertIn('id="generation"',page)
        before={p:p.read_bytes() for p in (self.root/'daily').iterdir()}
        self.assertTrue(act(self.root,self.identifier,'ses_fixture','finish',{})['saved'])
        self.assertEqual(before,{p:p.read_bytes() for p in (self.root/'daily').iterdir()})
        self.assertTrue((self.root/'state.json').exists())
        self.assertEqual(self.app.status(self.identifier)['state'],'ready')

    def test_explicit_recovery_reopens_legacy_stopped_preflight_without_archive_question(self):
        (self.root/'daily/2026-10-10.md').write_text('# 2026-10-10\n- gn: yes (session ses_old)\n')
        identifier=self.identifier
        job={'id':identifier,'date':'2026-10-11','kind':'gn','state':'preflight'}
        self.app.jobs={'2026-10-11.gn':job};self.app.save_jobs()
        context=initialize(self.root,job)
        context['form']['fields'].insert(0,{'key':'continue','title':'Past missing editions','type':'string','required':True,
            'options':[{'value':'today','label':'Continue today'},{'value':'stop','label':'Stop for now'}]})
        context_path(self.root,identifier).write_text(json.dumps(context))
        self.app.reply(identifier,'form','preflight_'+identifier,{'answer':{'continue':'stop','details':'No updates today'}})
        self.assertEqual(self.app.status(identifier)['state'],'stopped')
        body={'id':'b'*32}
        self.app.recover(identifier,body)
        current=self.app.status(identifier)
        self.assertEqual(current['state'],'waiting')
        self.assertNotEqual(current['forms'][0]['id'],'preflight_'+identifier)
        self.assertNotIn('continue',{f['key'] for f in current['forms'][0]['fields']})
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
        self.assertIn('[date,status,title,detail]',recipe['instruction'])

    def test_night_default_project_priorities_save_without_rescheduling_or_completion(self):
        path = self.root/'daily/2026-10-11.md'
        path.write_text('# 2026-10-11\n\n## must-do\n- [x] Confirmed completion\n- [ ] Project A: prepare update\n')
        self.job['kind'] = 'gn'; self.app.jobs = {'2026-10-11.gn': self.job}; self.app.save_jobs()
        initialize(self.root, self.job)
        answer(self.root, self.job, {'completed':['none'], 'details':'The project update remains open.'})
        before = [{key:value for key,value in task.items() if key != 'line'}
                  for task in inspect(path.read_text(), '2026-10-11')[2]]
        result = act(self.root, self.identifier, 'ses_fixture', 'init', {'greeting':'Evening.', 'opening':'Review the confirmed work.'})
        self.assertEqual(result['next']['section'], ['today','Today'])
        sections = [
            ['today', [['p','The confirmed completion is saved.']]],
            None,
            ['tomorrow', [['p','No date has been agreed for the remaining project work.']]],
            ['must-do', [['tasks', [['open','Project A: prepare update','Necessary next action; no date assigned.']]]]],
            ['nice-to-do', [['tasks', [['open','Project A: tidy notes','Optional improvement; no date assigned.']]]]],
            None,
        ]
        for position, section in enumerate(sections):
            payload = {'position':position, **({'section':section} if section else {})}
            result = act(self.root, self.identifier, 'ses_fixture', 'publish' if section else 'skip', payload)
        self.assertEqual(result['next']['action'], 'finish')
        act(self.root, self.identifier, 'ses_fixture', 'finish', {})
        document = json.loads((self.root/'daily/2026-10-11.gn.json').read_text())
        self.assertEqual([section[0] for section in document['sections']], ['today','tomorrow','must-do','nice-to-do'])
        self.assertEqual([{key:value for key,value in task.items() if key != 'line'}
                          for task in inspect(path.read_text(), '2026-10-11')[2]], before)
        self.assertFalse((self.root/'daily/2026-10-12.md').exists())

    def test_night_empty_project_priority_sections_are_skippable(self):
        self.job['kind'] = 'gn'; self.app.jobs = {'2026-10-11.gn': self.job}; self.app.save_jobs()
        initialize(self.root, self.job)
        answer(self.root, self.job, {'details':'No project work to report.'})
        act(self.root, self.identifier, 'ses_fixture', 'init', {'greeting':'Evening.', 'opening':'A quiet review.'})
        for position, tag in enumerate(('today','still-open','tomorrow','must-do','nice-to-do','notes')):
            if tag in ('today','tomorrow'):
                act(self.root, self.identifier, 'ses_fixture', 'publish', {'position':position,
                    'section':[tag, [['p','Only confirmed records are included.']]]})
            else:
                act(self.root, self.identifier, 'ses_fixture', 'skip', {'position':position})
        act(self.root, self.identifier, 'ses_fixture', 'finish', {})
        document = json.loads((self.root/'daily/2026-10-11.gn.json').read_text())
        self.assertEqual([section[0] for section in document['sections']], ['today','tomorrow'])

    def test_schedule_recipe_includes_untimed_work_without_a_calendar(self):
        context=json.loads(context_path(self.root,self.identifier).read_text())
        context['paths']['calendar_db']=None
        recipe=next_step(self.root,self.identifier,'ses_fixture',context,{'outcomes':[], 'plan':[['schedule','Schedule']]})
        self.assertEqual(recipe['read'],[])

    def test_flexible_today_tasks_sync_once_and_keep_priority_and_completion(self):
        path=self.root/'daily/2026-10-11.md'
        path.write_text('# 2026-10-11\n\n## must-do\n- [x] Prior task\n- [ ] Unrelated task\n')
        act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.','opening':'Plan carefully.',
            'plan':[['schedule','Schedule'],['must-do','Project steps']]})
        section=['schedule',[['flexible',[
            ['2026-10-11','open','Prior task',''],['2026-10-11','partial','Untimed work','Still open.'],
            ['2026-10-11','open','Important task',''],['2026-10-12','open','Future work',''],
            ['','open','Undated work','']]]]]
        bad=deepcopy(section);bad[1][0][1][1][1]='done'
        with self.assertRaisesRegex(ValueError,'planned_task_completion'):
            act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':bad})
        act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':section})
        act(self.root,self.identifier,'ses_fixture','publish',{'position':1,'section':
            ['must-do',[['tasks',[['open','Project: compare validation settings','']]]]]})
        act(self.root,self.identifier,'ses_fixture','finish',{})
        text=path.read_text();tasks=inspect(text,'2026-10-11')[2]
        self.assertIn('- [x] Prior task',text)
        self.assertEqual(len(tasks),5)
        self.assertEqual(next(t for t in tasks if t['text']=='Important task')['section'],'flexible')
        self.assertEqual(next(t for t in tasks if t['text']=='Project: compare validation settings')['section'],'must-do')
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

    def test_duplicate_project_card_cannot_change_the_published_schedule(self):
        act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Morning.','opening':'Current plan.',
            'plan':[['schedule','Schedule'],['must-do','Project steps']]})
        schedule=['schedule',[['flexible',[['2026-10-11','open','Project: prepare review','Agreed today.']]]]]
        act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':schedule})
        target=self.app.job_dir/(self.identifier+'.preview.json')
        before=target.read_bytes()
        with self.assertRaisesRegex(ValueError,'duplicate task card'):
            act(self.root,self.identifier,'ses_fixture','publish',{'position':1,'section':
                ['must-do',[['tasks',[['open','Project: prepare review','Repeated project action.']]]]]})
        self.assertEqual(target.read_bytes(),before)
        self.assertEqual(list((self.root/'daily').iterdir()),[])
        act(self.root,self.identifier,'ses_fixture','publish',{'position':1,'section':
            ['must-do',[['tasks',[['open','Project: compare validation settings','Sustained progress.']]]]]})
        self.assertTrue(act(self.root,self.identifier,'ses_fixture','finish',{})['saved'])
        saved=json.loads((self.root/'daily/2026-10-11.gm.json').read_text())
        self.assertEqual(saved['sections'][0],schedule)
        tasks=inspect((self.root/'daily/2026-10-11.md').read_text(),'2026-10-11')[2]
        self.assertEqual(len(tasks),2)

    def test_status_names_edition_saved_outside_its_job(self):
        self.save_original()
        source=self.root/'daily/2026-10-11.gm.json'
        saved=source.read_bytes()
        path=self.root/'daily/2026-10-11.md'
        path.write_text(path.read_text().replace('ses_fixture','ses_other'))
        state.save_state(str(self.root),state.rebuild_index(str(self.root),state.load_state(str(self.root)),'2026-10-11'))
        foreign=self.app.status(self.identifier)
        self.assertEqual((foreign['state'],foreign['progress']),('stopped',95))
        self.assertEqual(source.read_bytes(),saved)
        source.write_text('{broken')
        invalid=self.app.status(self.identifier)
        self.assertEqual((invalid['state'],invalid['progress']),('stopped',95))
        self.assertNotEqual(invalid['label'],foreign['label'])

    def save_original(self):
        self.init()
        act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':
            ['must-do',[['tasks',[['open','Ranking','']]]]]})
        act(self.root,self.identifier,'ses_fixture','skip',{'position':1})
        act(self.root,self.identifier,'ses_fixture','finish',{})
        self.chamber.idle()
        self.assertEqual(self.app.status(self.identifier)['state'],'ready')

    def regenerate(self, request='b'*32):
        self.chamber.pending=lambda session:(self.chamber.forms,self.chamber.permissions)
        previous=self.app.jobs['2026-10-11.'+self.job['kind']]['id']
        body={'date':'2026-10-11','kind':self.job['kind'],'id':request,'previous':previous}
        # Dispatch synchronously with a distinct engine session, without model calls.
        with patch('goodmorning.web.briefing_server.threading.Thread'):
            result=self.app.regenerate(body)
        job=self.app.jobs['2026-10-11.'+self.job['kind']]
        if job['state']=='starting':
            control=self.chamber.control
            def create(action, **kwargs):
                if action=='session.create':
                    self.chamber.calls.append((action,kwargs))
                    return {'sessionId':'ses_replacement'}
                return control(action,**kwargs)
            with patch.object(self.chamber,'control',side_effect=create):self.app.dispatch(job)
        return result['job'],body

    def test_failed_regeneration_preflight_preserves_owner_and_returns_definite_rejection(self):
        self.save_original()
        original_jobs = (self.app.job_dir/'jobs.json').read_bytes()
        original_source = (self.root/'daily/2026-10-11.gm.json').read_bytes()
        before = sum(action=='session.create' for action,_ in self.chamber.calls)
        with patch('goodmorning.briefings.briefing_preflight.initialize', side_effect=OSError('Synthetic private error')), self.assertLogs('goodmorning.web.briefing_server', level='WARNING') as logs:
            with self.assertRaisesRegex(ValueError, 'previous briefing is preserved'):
                self.regenerate()
        self.assertNotIn('private', logs.output[0])
        self.assertEqual((self.app.job_dir/'jobs.json').read_bytes(), original_jobs)
        self.assertEqual((self.root/'daily/2026-10-11.gm.json').read_bytes(), original_source)
        self.assertEqual(sum(action=='session.create' for action,_ in self.chamber.calls), before)

    def test_regeneration_preserves_last_edition_until_save_and_merges_tasks(self):
        self.save_original()
        path=self.root/'daily/2026-10-11.md'
        path.write_text(path.read_text().replace('- [ ] Ranking','- [x] Ranking')+
                        '\n## nice-to-do\n- [ ] Unrelated task\n- gn: yes (session ses_night)\n')
        source=self.root/'daily/2026-10-11.gm.json';original=source.read_bytes()
        identifier,body=self.regenerate()
        self.assertEqual(source.read_bytes(),original)
        self.assertEqual((self.app.job_dir/(identifier+'.previous.json')).read_bytes(),original)
        self.assertEqual(self.app.regenerate(body),{'job':identifier})
        with self.assertRaisesRegex(ValueError,'briefing changed'):
            self.app.regenerate({**body,'id':'c'*32})
        self.assertEqual(sum(a=='session.create' for a,_ in self.chamber.calls),1)
        with self.assertRaisesRegex(ValueError,'replaced'):
            act(self.root,self.identifier,'ses_fixture','init',{})
        self.assertEqual(self.app.status(self.identifier)['state'],'stopped')
        self.assertIn('id="regenerate"',self.app.page('2026-10-11','gm',False).decode())
        act(self.root,identifier,'ses_replacement','init',{'greeting':'A fresh morning.','opening':'Use the current plan.',
            'plan':[['must-do','Project steps']]})
        act(self.root,identifier,'ses_replacement','publish',{'position':0,'section':
            ['must-do',[['tasks',[['open','Ranking',''],['open','New task','']]]]]})
        self.assertEqual(source.read_bytes(),original)
        act(self.root,identifier,'ses_replacement','finish',{})
        self.assertEqual(self.app.status(identifier)['state'],'ready')
        text=path.read_text()
        for line in ('- [x] Ranking','- [ ] Unrelated task','- [ ] New task','- gn: yes (session ses_night)',
                     '- gm: yes (session ses_replacement)'):self.assertIn(line,text)
        self.assertEqual(text.count('Ranking'),1)
        self.assertNotEqual(source.read_bytes(),original)

    def test_regeneration_uses_selected_current_actions_without_republishing_daily_history(self):
        self.save_original()
        path=self.root/'daily/2026-10-11.md'
        old='Project: prepare Tuesday review'
        current='Project: prepare moved Friday review'
        path.write_text(path.read_text()+'\n## nice-to-do\n- [ ] '+old+'\n- [ ] '+current+'\n- [x] Finished personal task\n')
        before={task['id']:task for task in inspect(path.read_text(),'2026-10-11')[2]}
        identifier,_=self.regenerate()
        context=act(self.root,identifier,'ses_replacement','prepare')
        self.assertEqual({task['text'] for task in context['daily']['tasks']},
                         {'Ranking',old,current,'Finished personal task'})
        act(self.root,identifier,'ses_replacement','init',{'greeting':'Morning.','opening':'Current commitments and progress.',
            'plan':[['schedule','Schedule'],['must-do','Project steps'],['nice-to-do','Optional project steps']]})
        sections=[
            ['schedule',[['flexible',[['2026-10-11','open',current,'Preparation agreed for today.']]]]],
            ['must-do',[['tasks',[['open','Project: compare validation settings','Next necessary step.']]]]],
            ['nice-to-do',[['tasks',[['open','Project: explore an extra control','Optional improvement.']]]]]]
        for position,section in enumerate(sections):
            act(self.root,identifier,'ses_replacement','publish',{'position':position,'section':section})
        act(self.root,identifier,'ses_replacement','finish',{})
        saved=json.loads((self.root/'daily/2026-10-11.gm.json').read_text())
        self.assertEqual(saved['sections'],sections)
        page=self.app.page('2026-10-11','gm',False).decode()
        self.assertNotIn(old,page)
        self.assertEqual(page.count(current+'</div>'),1)
        self.assertEqual(page.count('class="task-card task"'),3)
        after={task['id']:task for task in inspect(path.read_text(),'2026-10-11')[2]}
        for identifier,task in before.items():
            self.assertEqual({key:value for key,value in after[identifier].items() if key!='line'},
                             {key:value for key,value in task.items() if key!='line'})

    def test_regeneration_reuses_saved_night_feedback_without_reapplying_it(self):
        path=self.root/'daily/2026-10-11.md'
        path.write_text('# 2026-10-11\n\n## must-do\n- [ ] Ranking\n- [ ] Travel\n')
        self.job['kind']='gn';self.app.jobs={'2026-10-11.gn':self.job};self.app.save_jobs()
        context=initialize(self.root,self.job)
        payload={'completed':[context['daily']['tasks'][0]['id']],'details':'Travel is partial.'}
        answer(self.root,self.job,payload)
        act(self.root,self.identifier,'ses_fixture','init',{'greeting':'Night.','opening':'Rest carefully.','plan':[['today','Today']]})
        act(self.root,self.identifier,'ses_fixture','publish',{'position':0,'section':['today',[['p','Ranking is finished.']]]})
        act(self.root,self.identifier,'ses_fixture','finish',{})
        self.chamber.idle()
        before=path.read_bytes()
        identifier,_=self.regenerate()
        context=act(self.root,identifier,'ses_replacement','prepare')
        self.assertTrue(context['regenerating'])
        self.assertEqual(context['feedback'],{'completed':['Ranking'],'details':'Travel is partial.','saved':True,'date':'2026-10-11'})
        self.assertEqual(path.read_bytes(),before)
        act(self.root,identifier,'ses_replacement','init',{'greeting':'Night again.','opening':'Your progress is preserved.','plan':[['today','Today']]})
        act(self.root,identifier,'ses_replacement','publish',{'position':0,'section':['today',[['p','Ranking is finished; travel remains partial.']]]})
        act(self.root,identifier,'ses_replacement','finish',{})
        self.assertEqual(path.read_text().count('Completed: Ranking'),1)
        self.assertEqual(path.read_text().count('Travel is partial.'),1)
        self.assertIn('- [x] Ranking',path.read_text())
        self.assertIn('- [ ] Travel',path.read_text())

    def test_regeneration_refuses_busy_pending_uncertain_and_stale_requests(self):
        self.save_original()
        before={p:p.read_bytes() for p in (self.root/'daily').iterdir()}
        body={'date':'2026-10-11','kind':'gm','id':'b'*32,'previous':self.identifier}
        for job_state,busy,forms in [('starting',False,[]),('uncertain',False,[]),('complete',True,[]),
                                      ('complete',False,[{'id':'frm_pending'}])]:
            self.job['state']=job_state;self.app.save_jobs();self.chamber.busy=busy;self.chamber.forms=forms
            with self.assertRaises(ValueError):self.app.regenerate(body)
        self.job['state']='complete';self.app.save_jobs();self.chamber.forms=[]
        for changed in ({**body,'date':'2026-10-10'},{**body,'previous':'c'*32}):
            with self.assertRaises(ValueError):self.app.regenerate(changed)
        self.assertEqual(before,{p:p.read_bytes() for p in (self.root/'daily').iterdir()})
        self.assertEqual(sum(a=='session.create' for a,_ in self.chamber.calls),0)

    def test_regeneration_refuses_changed_snapshot_or_run_without_overwriting(self):
        self.save_original()
        identifier,_=self.regenerate()
        act(self.root,identifier,'ses_replacement','init',{'greeting':'Morning again.','opening':'Plan carefully.','plan':[['weather','Weather']]})
        source=self.root/'daily/2026-10-11.gm.json'
        original=source.read_bytes();source.write_bytes(original+b' ')
        with self.assertRaisesRegex(ValueError,'changed after regeneration'):
            act(self.root,identifier,'ses_replacement','publish',{'position':0,'section':['weather',[['p','Forecast unavailable; check before travelling.']]]})
        self.assertEqual(source.read_bytes(),original+b' ')
        source.write_bytes(original)
        path=self.root/'daily/2026-10-11.md'
        changed=path.read_text().replace('session ses_fixture','session ses_foreign');path.write_text(changed)
        with self.assertRaisesRegex(ValueError,'changed after regeneration'):
            act(self.root,identifier,'ses_replacement','prepare')
        self.assertEqual(path.read_text(),changed)

    def test_interrupted_replacement_save_finishes_exact_document_without_force(self):
        self.save_original()
        identifier,_=self.regenerate()
        act(self.root,identifier,'ses_replacement','init',{'greeting':'Morning again.','opening':'Plan carefully.','plan':[['weather','Weather']]})
        act(self.root,identifier,'ses_replacement','publish',{'position':0,'section':['weather',[['p','Forecast unavailable; check before travelling.']]]})
        with patch.object(state,'ensure_daily_line',side_effect=OSError('Synthetic marker interruption')):
            with self.assertRaises(ValueError):act(self.root,identifier,'ses_replacement','finish',{})
        source=self.root/'daily/2026-10-11.gm.json';saved=source.read_bytes()
        self.assertIn('ses_fixture',(self.root/'daily/2026-10-11.md').read_text())
        self.assertTrue(act(self.root,identifier,'ses_replacement','finish',{})['saved'])
        self.assertEqual(source.read_bytes(),saved)
        self.assertEqual(self.app.status(identifier)['state'],'ready')

    def test_stopped_partial_preview_can_start_fresh_without_deleting_it(self):
        self.init()
        target=self.app.job_dir/(self.identifier+'.preview.json');old=target.read_bytes()
        self.chamber.idle()
        identifier,_=self.regenerate()
        self.assertEqual(target.read_bytes(),old)
        self.assertFalse((self.root/'daily/2026-10-11.gm.json').exists())
        self.assertEqual(act(self.root,identifier,'ses_replacement','prepare')['next_position'],0)

    def test_saved_edition_without_browser_job_can_be_regenerated(self):
        self.save_original();self.app.jobs={};self.app.save_jobs()
        with patch('goodmorning.web.briefing_server.threading.Thread'):
            result=self.app.regenerate({'date':'2026-10-11','kind':'gm','id':'b'*32,'previous':None})
        self.assertNotEqual(result['job'],self.identifier)
        self.assertIn('replacement',self.app.jobs['2026-10-11.gm'])
        self.assertIn('id="regenerate"',self.app.page('2026-10-11','gm',False).decode())

    def test_regeneration_reconciles_uncertain_feedback_before_reusing_it(self):
        path=self.root/'daily/2026-10-11.md';path.write_text('# 2026-10-11\n\n## must-do\n- [ ] Ranking\n')
        self.job.update(kind='gn',state='preflight');self.job.pop('session')
        self.app.jobs={'2026-10-11.gn':self.job};self.app.save_jobs()
        context=initialize(self.root,self.job)
        payload={'completed':[context['daily']['tasks'][0]['id']],'details':'No other updates'}
        def interrupted(*args,**kwargs):
            result=daily_amend(*args,**kwargs)
            if not kwargs.get('dry_run'):raise OSError('Synthetic lost receipt')
            return result
        with patch('goodmorning.briefings.briefing_preflight.amend',side_effect=interrupted):
            with self.assertRaises(OSError):answer(self.root,self.job,payload)
        self.chamber.idle()
        identifier,_=self.regenerate()
        self.assertTrue(act(self.root,identifier,'ses_replacement','prepare')['feedback']['saved'])
        self.assertEqual(path.read_text().count('Completed: Ranking'),1)

    def test_old_status_poll_cannot_complete_replacement_job(self):
        self.save_original();self.job['state']='running';self.app.save_jobs()
        control=self.chamber.control
        replacement=[]
        def during_status(action, **kwargs):
            if action=='session.status' and not replacement:
                replacement.append(True)
                replacement.append(self.regenerate()[0])
            return control(action,**kwargs)
        with patch.object(self.chamber,'control',side_effect=during_status):
            self.assertEqual(self.app.status(self.identifier)['state'],'stopped')
        self.assertEqual(self.app.jobs['2026-10-11.gm']['id'],replacement[1])
        self.assertEqual(self.app.jobs['2026-10-11.gm']['state'],'running')

    def test_regeneration_can_replace_unreadable_json_without_erasing_backup(self):
        self.save_original()
        source=self.root/'daily/2026-10-11.gm.json';source.write_text('{broken JSON\n')
        self.assertTrue(self.app.status(self.identifier)['regeneratable'])
        identifier,_=self.regenerate()
        act(self.root,identifier,'ses_replacement','init',{'greeting':'A fresh morning.','opening':'Plan carefully.','plan':[['weather','Weather']]})
        act(self.root,identifier,'ses_replacement','publish',{'position':0,'section':['weather',[['p','Forecast unavailable; check before travelling.']]]})
        act(self.root,identifier,'ses_replacement','finish',{})
        self.assertEqual((self.app.job_dir/(identifier+'.previous.json')).read_text(),'{broken JSON\n')
        self.assertEqual(self.app.status(identifier)['state'],'ready')

    def test_stale_preflight_reply_cannot_answer_replacement_question(self):
        self.job.update(kind='gn',state='preflight');self.job.pop('session')
        self.app.jobs={'2026-10-11.gn':self.job};self.app.save_jobs()
        context=initialize(self.root,self.job)
        before=self.app.job
        replaced=[]
        def racing_read(identifier):
            job=before(identifier)
            if identifier==self.identifier and not replaced:
                replaced.append(True)
                with patch('goodmorning.web.briefing_server.threading.Thread'):
                    replaced.append(self.app.regenerate({'date':'2026-10-11','kind':'gn','id':'b'*32,'previous':identifier})['job'])
            return job
        with patch.object(self.app,'job',side_effect=racing_read):
            with self.assertRaisesRegex(ValueError,'replaced'):
                self.app.reply(self.identifier,'form',context['form']['id'],{'answer':{'completed':['none'],'details':'No other updates'}})
        pending=json.loads(context_path(self.root,replaced[1]).read_text())
        self.assertTrue(pending['awaiting'])
        self.assertNotIn('feedback',pending)
        self.assertEqual(self.chamber.calls,[])


if __name__=='__main__':
    unittest.main()
