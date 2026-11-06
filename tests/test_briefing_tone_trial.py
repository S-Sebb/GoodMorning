"""Safety/fixture checks for the opt-in live briefing trial, without model calls."""
from datetime import datetime, timezone
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from support import TEMP_ROOT, offline_provider_reads
from benchmarks.briefing_tone_live import TRIAL_CLI, section_timings, CheckpointBridge, seed_tasks, seed_flexible, link_handoff, collection_order_issues, trial_config, external_allowed, job_action
from goodmorning.briefings import briefing_job
from goodmorning.briefings.briefing_job import act, writing_rule
from goodmorning.briefings.briefing_preflight import initialize as prepare, answer
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.records.inbox_store import initialize
from goodmorning.web.briefing_server import BrowserApp


class BriefingTrialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name)
        offline_provider_reads(self)
        (self.runtime/'profile.md').write_text('city: London, GB\ntimezone: Europe/London\nnews_country: GB\ncalendar_source: custom\n')
        initialize(self.runtime)
        CalendarStore(str(self.runtime/'calendar.sqlite')).close()

    def test_timings_split_reads_from_model_turns_and_keep_rejected_calls_in_the_turn(self):
        job = 'b'*32
        (self.runtime/'browser-jobs').mkdir()
        steps = [(100,'receive',{}),(101,'opening',{}),(110,'receive',{}),(111,'collect',{'section':'schedule'}),
                 (112,'write',{'section':'schedule'}),(120,'receive',{}),(126,'receive',{}),(127,'closing',{}),
                 (130,'receive',{}),(131,'save',{})]
        (self.runtime/'browser-jobs'/(job+'.timings.jsonl')).write_text(''.join(
            json.dumps({'step':step,**values,'at':at})+'\n' for at, step, values in steps))
        timings = section_timings(self.runtime, job, started=90)
        self.assertEqual(timings['start'], {'read':0.0,'model':10.0,'code':1.0,'calls':1})
        self.assertEqual(timings['opening'], {'read':0.0,'model':9.0,'code':1.0,'calls':1})
        self.assertEqual(timings['schedule'], {'read':1.0,'model':14.0,'code':1.0,'calls':2})
        self.assertEqual(timings['closing'], {'read':0.0,'model':3.0,'code':1.0,'calls':1})

    def test_empty_fixture_has_no_unrequested_actions(self):
        self.assertEqual(seed_tasks(self.runtime,'en','morning-empty','2026-10-14'), [])

    def test_bilingual_feedback_fixture_preserves_future_report_days(self):
        rows = seed_tasks(self.runtime,'zh-CN','evening-feedback','2026-10-14')
        self.assertEqual([row['title'] for row in rows], ['发送 Atlas 报告','发送 Boreal 报告','购买食品'])
        self.assertEqual([row['planned_date'] for row in rows], ['2026-10-15','2026-10-15','2026-10-14'])
        context = prepare(self.runtime, {'id':'a'*32,'date':'2026-10-14','kind':'gn','language':'zh-CN'})
        self.assertEqual({field['key'] for field in context['form']['fields']}, {'completed','details'})
        self.assertTrue(context['awaiting'])

    def test_flexible_fixtures_need_judgment_not_new_dates(self):
        vague = seed_flexible(self.runtime,'en','morning-vague','2026-10-14')
        self.assertEqual([row['title'] for row in vague],['atlas report stuff etc','Groceries','Prepare Q3 slides for the Boreal review'])
        self.assertEqual({row['planned_date'] for row in vague},{'2026-10-14'})
        messy = seed_flexible(self.runtime,'zh-CN','evening-complex','2026-10-14')
        self.assertEqual([row['planned_date'] for row in messy[3:]],['2026-10-14','2026-10-15','2026-10-14'])
        context = prepare(self.runtime, {'id':'b'*32,'date':'2026-10-14','kind':'gn','language':'zh-CN'})
        self.assertTrue(context['awaiting'])

    def test_checkpoint_seed_retains_owner_and_next_unresolved_position(self):
        # The trial source's faulting CLI, so the server's in-process receipt reads are checked through it.
        source = self.runtime/'source'
        (source/'scripts').mkdir(parents=True)
        (source/'scripts/goodmorning.py').write_text(TRIAL_CLI)
        (source/'src').symlink_to(Path(__file__).resolve().parents[1]/'src')
        engine = SimpleNamespace(url='http://127.0.0.1:9', release=source, runtime=self.runtime, password='x')
        bridge = CheckpointBridge(engine, True, 'en')
        self.addCleanup(setattr, briefing_job, 'run_reads', bridge.real_reads)
        app = BrowserApp(self.runtime, bridge, now=lambda:datetime(2026,10,14,12,tzinfo=timezone.utc), preflight=True)
        job = {'id':'a'*32,'date':'2026-10-14','kind':'gm','state':'starting','language':'en',
               'created':datetime(2026,10,14,6,tzinfo=timezone.utc).timestamp()}
        app.jobs['2026-10-14.gm'] = job
        app.save_jobs()
        prepare(self.runtime,job)
        engine_calls = lambda action, **kw: {'sessionId':'ses_trial'} if action == 'session.create' else {'promptDispatched':True}
        with patch('benchmarks.trial_engine.TrialBridge.control',side_effect=engine_calls) as control, \
             patch('benchmarks.trial_engine.TrialBridge.request',return_value={}):
            app.dispatch(job)
        # Seeded before the server's prepare, so the dispatched receipt resumes after the seeded section.
        prompt = control.call_args.kwargs['prompt']
        header = '/gm\nBrowser job: '+job['id']+'\nRuntime: '+str(self.runtime)+'\nWebsite language: en\nPrepare receipt: '
        self.assertTrue(prompt.startswith(header))
        receipt = json.loads(prompt[len(header):])
        self.assertEqual((receipt['next_position'],receipt['next']['section'][0],app.job(job['id'])['state']),(1,'news','running'))
        self.assertEqual(receipt['next']['results'][0]['output']['error'],'provider_unavailable')
        self.assertEqual(json.loads((self.runtime/'seeded-checkpoint.json').read_text()),bridge.seeded)

    def test_request_labels_use_the_pinned_language_not_current_interface(self):
        app=BrowserApp(self.runtime,None)
        job={'id':'a'*32,'kind':'gn','language':'zh-CN'}
        prompt=app.generation_prompt(job)
        self.assertEqual(prompt,'请准备我的晚间简报（/gn）。\n浏览器任务: '+job['id']+'\n运行目录: '+str(self.runtime)+'\nWebsite language: zh-CN')
        self.assertEqual(app.generation_prompt({**job,'language':'en'}),
                         '/gn\nBrowser job: '+job['id']+'\nRuntime: '+str(self.runtime)+'\nWebsite language: en')

    def test_ambiguous_feedback_is_saved_without_changing_task_status(self):
        from benchmarks.task_tone_live import records
        rows=seed_tasks(self.runtime,'en','evening-ambiguous','2026-10-14')
        job={'id':'a'*32,'date':'2026-10-14','kind':'gn','language':'en'}
        prepare(self.runtime,job)
        result=answer(self.runtime,job,{'completed':['none'],'details':'One report is blocked; target not specified.'})
        self.assertTrue(result['feedback']['saved'])
        self.assertEqual(records(self.runtime),rows)

    def test_terminal_link_check_does_not_reject_earlier_progress(self):
        target=self.runtime/'original.messages.json'
        def check(text):
            target.write_text(json.dumps({'messages':[
                {'role':'assistant','text':'Checking the weather.'},
                {'role':'assistant','text':text}]}))
            return link_handoff(self.runtime,'original')
        self.assertTrue(check('[晨间简报](/d/2026-10-14/gm)'))
        self.assertTrue(check('http://127.0.0.1:8765/gn'))
        self.assertTrue(check('Your evening review is ready: /gn'))
        self.assertTrue(check('Your morning briefing is ready: `/gm`'))
        self.assertTrue(check('今晚的回顾已经保存好了：[/gn](/gn)'))
        self.assertTrue(check('晨间简报已保存：\n\n`/d/2026-10-14/gm`'))
        self.assertFalse(check('All saved.\nWeather unavailable.\nhttp://127.0.0.1:8765/gm'))
        self.assertFalse(check('No link.'))

    def test_section_collection_check_allows_help_but_flags_future_reads(self):
        plan=[['weather','Weather'],['news','News']]
        publish={'argv':['job','publish'],'input':{'position':0,'section':['weather',[['p','Unavailable.']]]}}
        self.assertEqual(collection_order_issues([
            {'argv':['job','--help']},{'argv':['weather']},publish,{'argv':['news']}],plan),[])
        self.assertTrue(collection_order_issues([{'argv':['news']}],plan))
        self.assertTrue(collection_order_issues([
            {'argv':['task','--briefing','gm','--section','schedule']}],plan))
        rejected={'argv':['task','--briefing','gm','--section','schedule'],
                  'exit':1,'error':'browser_section_not_ready'}
        self.assertEqual(collection_order_issues([rejected],plan),[])
        self.assertTrue(collection_order_issues([{'argv':['news'],'exit':1,'error':'provider_unavailable'}],plan))

    def test_job_actions_allow_options_after_the_positional_action(self):
        self.assertEqual(job_action(['job','prepare','--session','ses_trial']),'prepare')
        publish={'argv':['job','publish','--session','ses_trial'],'exit':0,
                 'input':{'position':0,'section':['weather',[['p','Unavailable.']]]}}
        self.assertEqual(collection_order_issues([publish,{'argv':['news']}],
                         [['weather','Weather'],['news','News']]),[])

    def test_evening_attribution_reads_are_not_future_section_collection(self):
        plan=[['today','Today'],['schedule','Schedule'],['tasks','Tasks']]
        review={'argv':['task','--briefing','gn','--section','tasks']}
        self.assertEqual(collection_order_issues([review],plan,reconcile=True),[])
        self.assertTrue(collection_order_issues([review],plan))
        self.assertTrue(collection_order_issues([
            {'argv':['task','--briefing','gn','--section','schedule']}],plan,reconcile=True))

    def test_each_trial_only_allows_its_own_runtime_outside_the_source(self):
        rules=trial_config(self.runtime)['agents']['build']['permissions']
        external=[rule for rule in rules if rule['action']=='external_directory']
        self.assertEqual(external,[{'action':'external_directory','resource':'*','effect':'deny'},
                                  {'action':'external_directory','resource':str(self.runtime)+'/*','effect':'allow'}])
        self.assertTrue(external_allowed(rules,str(self.runtime)+'/cache/*'))
        self.assertFalse(external_allowed(rules,str(self.runtime.parent)+'/*'))

    def test_verified_handoff_rejects_guessed_domain_or_other_date(self):
        target=self.runtime/'original.messages.json'
        expected='/d/2026-10-14/gm'
        for text,valid in (('[Morning briefing]('+expected+')',True),
                           ('https://wrong.example'+expected,False),('/d/2026-10-13/gm',False)):
            target.write_text(json.dumps({'messages':[{'role':'assistant','text':text}]}))
            self.assertEqual(link_handoff(self.runtime,'original',expected),valid)

    def test_writing_reminders_are_localized_and_only_attached_to_relevant_steps(self):
        context={'website_language':'zh-CN'}
        for action in ({'action':'init'},{'action':'finish'},
                       {'action':'publish','section':['tasks','Tasks']},
                       {'action':'publish','section':['news','News']}):
            chinese=writing_rule(context,action)
            english=writing_rule({'website_language':'en'},action)
            self.assertTrue(any('\u4e00' <= character <= '\u9fff' for character in chinese))
            self.assertNotEqual(chinese,english)
        self.assertIsNone(writing_rule(context,{'action':'publish','section':['attention','Reminders']}))

    def test_brief_link_delivery_can_include_a_tone_matched_wish(self):
        target=self.runtime/'original.messages.json'
        target.write_text(json.dumps({'messages':[{'role':'assistant',
            'text':'早上好，简报准备好了。\n\n[简报](/d/2026-10-14/gm)\n\n祝你今天顺顺利利。'}]}))
        self.assertTrue(link_handoff(self.runtime,'original','/d/2026-10-14/gm'))

    def scoped_job(self, kind='gm', **feedback):
        app=BrowserApp(self.runtime,None,now=lambda:datetime(2026,10,14,12,tzinfo=timezone.utc),preflight=True)
        job={'id':'a'*32,'date':'2026-10-14','kind':kind,'session':'ses_trial','state':'running','language':'en',
             'created':datetime(2026,10,14,6,tzinfo=timezone.utc).timestamp()}
        app.jobs['2026-10-14.'+kind]=job;app.save_jobs()
        prepared=prepare(self.runtime,job)
        if prepared['awaiting']:
            answer(self.runtime,job,{'details':'Started the draft.',**feedback})  # Something reported keeps Today's position.
        act(self.runtime,job['id'],'ses_trial','init',{})
        return job

    def read_section(self, job, section, extra=()):
        from goodmorning.records.task import main
        output=io.StringIO()
        with redirect_stdout(output), patch.dict('os.environ',{'OPENCODE_SESSION_ID':'ses_trial'}):
            code=main(['--secretary-dir',str(self.runtime),'--briefing',job['kind'],
                       '--date',job['date'],'--section',section,*extra])
        return code,json.loads(output.getvalue())

    def test_active_actor_cannot_fetch_future_sections_even_without_the_job_flag(self):
        job=self.scoped_job()
        with patch('goodmorning.records.routing.prepare') as query:
            code,result=self.read_section(job,'schedule')
        self.assertEqual(code,1)
        self.assertEqual(result['error'],'browser_section_not_ready')
        query.assert_not_called()
        act(self.runtime,job['id'],'ses_trial','publish',{'position':0,'section':['weather',[['p','Unavailable.']]]})
        act(self.runtime,job['id'],'ses_trial','publish',{'position':1,'section':['news',[['p','Unavailable.']]]})
        code,result=self.read_section(job,'schedule')
        self.assertEqual(code,0)
        self.assertIn('items',result)

    def test_explicit_foreign_actor_and_wrong_day_are_rejected_before_data_fetch(self):
        job=self.scoped_job('gn')
        for extra in (['--browser-job',job['id'],'--session','ses_other'],
                      ['--browser-job',job['id'],'--date','2026-10-15']):
            with patch('goodmorning.records.routing.prepare') as query:
                code,_=self.read_section(job,'today',extra)
            self.assertEqual(code,1)
            query.assert_not_called()

    def test_original_feedback_lookup_is_allowed_but_regeneration_cannot_read_ahead(self):
        from goodmorning.briefings.briefing_job import context_path
        job=self.scoped_job('gn')
        code,_=self.read_section(job,'tasks')
        self.assertEqual(code,0)
        target=context_path(self.runtime,job['id']);prepared=json.loads(target.read_text())
        prepared['regenerating']=True;target.write_text(json.dumps(prepared))
        with patch('goodmorning.records.routing.prepare') as query:
            code,result=self.read_section(job,'tasks')
        self.assertEqual(code,1)
        self.assertEqual(result['error'],'browser_section_not_ready')
        query.assert_not_called()

    def test_code_places_today_cards_read_after_this_steps_task_write(self):
        seed_tasks(self.runtime,'en','evening-feedback','2026-10-14')
        job=self.scoped_job('gn',completed=['none'])
        receipt=act(self.runtime,job['id'],'ses_trial','prepare')['next']
        tasks,today=receipt['results']
        self.assertIsNone(today['output']['block'])  # Nothing recorded yet: no cards before the write.
        groceries=next(row for row in tasks['output']['items'] if row['title']=='Buy groceries')
        from goodmorning.records.task import main
        with redirect_stdout(io.StringIO()) as output:
            main(['--secretary-dir',str(self.runtime),'--report',groceries['id'],'--date','2026-10-14',
                  '--expect-revision',str(groceries['revision']),'--session','ses_trial','--request-key','gn-report:test',
                  '--input-json','{"status":"partial","detail":"Got half the list."}'])
        self.assertEqual(json.loads(output.getvalue())['revision'],groceries['revision']+1)  # The next write needs no --show.
        words=['today',[['p','Half the groceries are in.']],'Steady progress.','Today']
        stale=['today',[['actions',[]],*words[1]],*words[2:]]  # A copied card block is replaced, never kept.
        act(self.runtime,job['id'],'ses_trial','publish',{'position':0,'section':stale})
        from goodmorning.briefings.briefing_stream import load
        from goodmorning.briefings.briefing_job import context_path
        saved=load(context_path(self.runtime,job['id']).with_name(job['id']+'.preview.json'))['document']['sections'][0]
        self.assertEqual(saved[0],'today')
        self.assertEqual([block[0] for block in saved[1]],['actions','p'])
        self.assertEqual([(row[0],row[4]) for row in saved[1][0][1]],[(groceries['id'],'partial')])
        self.assertEqual(saved[1][1:]+saved[2:],[['p','Half the groceries are in.'],'Steady progress.','Today'])
        # A retried call with the same words is the same publication.
        self.assertTrue(act(self.runtime,job['id'],'ses_trial','publish',{'position':0,'section':words})['reused'])

    def test_today_without_cards_publishes_only_the_words(self):
        job=self.scoped_job('gn')
        act(self.runtime,job['id'],'ses_trial','publish',{'position':0,'section':['today',[['p','The draft is started.']],'']})
        from goodmorning.briefings.briefing_stream import load
        from goodmorning.briefings.briefing_job import context_path
        saved=load(context_path(self.runtime,job['id']).with_name(job['id']+'.preview.json'))['document']['sections'][0]
        self.assertEqual(saved[1],[['p','The draft is started.']])

    def evening_to_tasks(self, job):
        act(self.runtime,job['id'],'ses_trial','publish',{'position':0,'section':['today',[['p','The draft is started.']],'']})
        act(self.runtime,job['id'],'ses_trial','publish',{'position':1,'section':['weather',[['p','Unavailable.']],'','Weather tomorrow']})
        return act(self.runtime,job['id'],'ses_trial','publish',{'position':2,'section':['schedule',[['p','Nothing saved.']],'']})['next']

    def test_evening_sections_with_empty_reads_are_skipped_by_code(self):
        job=self.scoped_job('gn')
        finish=self.evening_to_tasks(job)
        self.assertEqual(finish['action'],'finish')  # Tasks and Reminders had 0 rows: no model turn.
        from goodmorning.briefings.briefing_stream import load
        from goodmorning.briefings.briefing_job import context_path
        checkpoint=load(context_path(self.runtime,job['id']).with_name(job['id']+'.preview.json'))
        self.assertEqual(checkpoint['outcomes'][3:],['skipped','skipped'])
        # The evening greeting and opening are written last, about tonight (#256); until then a placeholder shows.
        self.assertEqual(finish['input'],{'greeting':'…','opening':'…'})
        app=BrowserApp(self.runtime,None,now=lambda:datetime(2026,10,14,12,tzinfo=timezone.utc),preflight=True)
        self.assertEqual(app.preview(job['id'])['greeting'],'Preparing tonight’s briefing…')
        self.assertEqual(app.activity(job['id'],checkpoint,'gn')['label'],'Writing your greeting')
        for payload in ({},{'greeting':'x'*61,'opening':'Tonight.'},{'greeting':'Evening!\nRest.','opening':'Tonight.'}):
            with self.assertRaises(ValueError):
                act(self.runtime,job['id'],'ses_trial','finish',payload)
        act(self.runtime,job['id'],'ses_trial','finish',{'greeting':'Good evening!','opening':'The draft is started; tomorrow has no saved appointments.'})
        self.assertEqual(json.loads((self.runtime/'daily'/'2026-10-14.gn.json').read_text())['greeting'],'Good evening!')

    def test_evening_section_with_rows_waits_for_the_model_and_names_skip(self):
        seed_tasks(self.runtime,'en','evening-feedback','2026-10-14')
        job=self.scoped_job('gn',completed=['none'])
        receipt=self.evening_to_tasks(job)
        self.assertEqual(receipt['section'][0],'tasks')
        self.assertGreater(receipt['results'][-1]['output']['total'],0)
        with self.assertRaisesRegex(ValueError,r'skip is a separate action: run .* skip with input \{"position":3\}'):
            act(self.runtime,job['id'],'ses_trial','publish',{'position':3,'skip':True})

    def test_empty_schedule_window_uses_real_calendar_weekdays_for_focus_day_only(self):
        from benchmarks.briefing_tone_live import empty_schedule_block
        block=empty_schedule_block(self.runtime,'2026-10-14','gn','zh-CN')
        self.assertEqual(block[0],'p')
        self.assertIn('10月15日',block[1])
        self.assertIn('周四',block[1])
        self.assertNotIn('10月17日',block[1])
        self.assertNotIn('周六',block[1])
        self.assertNotIn('<',block[1])
        self.assertNotIn('>',block[1])

    def test_morning_weather_read_never_reports_the_daily_maximum_at_any_hour(self):
        # The live check rejects a 100% rain card; a late-evening run reads into tomorrow's night.
        from benchmarks.briefing_tone_live import synthetic_weather
        for hour in (6, 19, 22):
            reading=synthetic_weather(datetime(2026,11,5,hour,10,tzinfo=timezone.utc))
            self.assertLess(reading['json']['precip_prob_pct'],100,hour)
            self.assertNotIn('100%',reading['brief'],hour)

    def test_report_lookup_does_not_treat_todays_completion_choices_as_all_candidates(self):
        job=self.scoped_job('gn')
        from goodmorning.briefings.briefing_job import context_path
        target=context_path(self.runtime,job['id']);prepared=json.loads(target.read_text())
        prepared['feedback']['details']='One report is blocked, but the report is not named.'
        target.write_text(json.dumps(prepared))
        receipt=act(self.runtime,job['id'],'ses_trial','prepare')
        tasks,today=receipt['next']['results']
        self.assertIn('--section tasks',tasks['command'])
        self.assertIn('--section today',today['command'])
        self.assertEqual((tasks['exit'],today['exit']),(0,0))
        self.assertIsNone(today['output']['block'])
        self.assertIn('completion choices',receipt['feedback_task_scope'])


if __name__ == '__main__':
    unittest.main()
