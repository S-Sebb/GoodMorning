"""Safety/fixture checks for the opt-in live briefing trial, without model calls."""
from datetime import datetime, timezone
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
from benchmarks.briefing_tone_live import CheckpointBridge, seed_tasks, link_handoff, collection_order_issues, trial_config, external_allowed, job_action
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
        (self.runtime/'profile.md').write_text('city: London, GB\ntimezone: Europe/London\nnews_country: GB\ncalendar_source: custom\n')
        initialize(self.runtime)
        CalendarStore(str(self.runtime/'calendar.sqlite')).close()

    def test_empty_fixture_has_no_unrequested_actions(self):
        self.assertEqual(seed_tasks(self.runtime,'en','morning-empty','2026-10-14'), [])

    def test_bilingual_feedback_fixture_preserves_future_report_days(self):
        rows = seed_tasks(self.runtime,'zh-CN','evening-feedback','2026-10-14')
        self.assertEqual([row['title'] for row in rows], ['发送 Atlas 报告','发送 Boreal 报告','购买食品'])
        self.assertEqual([row['planned_date'] for row in rows], ['2026-10-15','2026-10-15','2026-10-14'])
        context = prepare(self.runtime, {'id':'a'*32,'date':'2026-10-14','kind':'gn','language':'zh-CN'})
        self.assertEqual({field['key'] for field in context['form']['fields']}, {'completed','details'})
        self.assertTrue(context['awaiting'])

    def test_checkpoint_seed_retains_owner_and_next_unresolved_position(self):
        bridge = CheckpointBridge('/synthetic/source', self.runtime, True, 'en')
        app = BrowserApp(self.runtime, bridge, now=lambda:datetime(2026,10,14,12,tzinfo=timezone.utc), preflight=True)
        job = {'id':'a'*32,'date':'2026-10-14','kind':'gm','session':'ses_trial','state':'running','language':'en'}
        app.jobs['2026-10-14.gm'] = job
        app.save_jobs()
        prepare(self.runtime,job)
        prompt='/gm\nBrowser job: '+job['id']+'\nRuntime: '+str(self.runtime)+'\nWebsite language: en'
        with patch('benchmarks.native_bridge.NativeBridge.control',return_value={'promptDispatched':True}) as dispatch:
            bridge.control('session.send',sessionId='ses_trial',prompt=prompt)
        self.assertEqual(dispatch.call_args.kwargs['prompt'],prompt)
        receipt=act(self.runtime,job['id'],'ses_trial','prepare')
        self.assertEqual(receipt['next_position'],1)
        self.assertEqual(receipt['next']['section'][0],'news')
        self.assertEqual(bridge.seeded['greeting'],'Good morning.')
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
        self.assertTrue(check('[晨间简报](/d/2026-10-14/gm.html)'))
        self.assertTrue(check('http://127.0.0.1:8765/gn.html'))
        self.assertTrue(check('Your evening review is ready: /gn.html'))
        self.assertTrue(check('Your morning briefing is ready: `/gm.html`'))
        self.assertTrue(check('今晚的回顾已经保存好了：[/gn.html](/gn.html)'))
        self.assertTrue(check('晨间简报已保存：\n\n`/d/2026-10-14/gm.html`'))
        self.assertFalse(check('All saved.\nWeather unavailable.\nhttp://127.0.0.1:8765/gm.html'))
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
        expected='/d/2026-10-14/gm.html'
        for text,valid in (('[Morning briefing]('+expected+')',True),
                           ('https://wrong.example'+expected,False),('/d/2026-10-13/gm.html',False)):
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
            'text':'早上好，简报准备好了。\n\n[简报](/d/2026-10-14/gm.html)\n\n祝你今天顺顺利利。'}]}))
        self.assertTrue(link_handoff(self.runtime,'original','/d/2026-10-14/gm.html'))

    def scoped_job(self, kind='gm'):
        app=BrowserApp(self.runtime,None,now=lambda:datetime(2026,10,14,12,tzinfo=timezone.utc),preflight=True)
        job={'id':'a'*32,'date':'2026-10-14','kind':kind,'session':'ses_trial','state':'running','language':'en'}
        app.jobs['2026-10-14.'+kind]=job;app.save_jobs()
        prepared=prepare(self.runtime,job)
        if prepared['awaiting']:
            answer(self.runtime,job,{'details':'No updates today'})
        act(self.runtime,job['id'],'ses_trial','init',{'greeting':'Hello.','opening':'Review saved records.'})
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

    def test_report_lookup_does_not_treat_todays_completion_choices_as_all_candidates(self):
        job=self.scoped_job('gn')
        from goodmorning.briefings.briefing_job import context_path
        target=context_path(self.runtime,job['id']);prepared=json.loads(target.read_text())
        prepared['feedback']['details']='One report is blocked, but the report is not named.'
        target.write_text(json.dumps(prepared))
        receipt=act(self.runtime,job['id'],'ses_trial','prepare')
        self.assertIn('--section tasks',receipt['next']['read'][0])
        self.assertIn('--section today',receipt['next']['read'][1])
        self.assertIn('completion choices',receipt['feedback_task_scope'])


if __name__ == '__main__':
    unittest.main()
