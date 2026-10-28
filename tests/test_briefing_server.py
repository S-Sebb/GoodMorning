"""Live viewer isolation, date boundaries and agent round-trips, without model calls."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from support import TEMP_ROOT, FakeChamber, HTTPFixture, ImmediateThread, complete_profile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.briefings.briefing_day import briefing_day
from goodmorning.web.briefing_server import BrowserApp, Chamber, serve_live
from test_briefing_web import GM


class DayTests(unittest.TestCase):
    def test_before_and_at_four_in_multiple_timezones(self):
        for zone, instant, expected in [
            ('Europe/London', '2026-10-10T02:59:59+00:00', '2026-10-09'),
            ('Europe/London', '2026-10-10T03:00:00+00:00', '2026-10-10'),
            ('Asia/Shanghai', '2026-10-09T19:59:59+00:00', '2026-10-09'),
            ('Asia/Shanghai', '2026-10-09T20:00:00+00:00', '2026-10-10')]:
            self.assertEqual(briefing_day(zone, datetime.fromisoformat(instant)), expected)

    def test_dst_rollovers_use_wall_clock_hour(self):
        for day, utc_cutoff in [('2026-03-29', 3), ('2026-10-25', 4)]:
            self.assertEqual(briefing_day('Europe/London', datetime.fromisoformat(f'{day}T{utc_cutoff:02}:00:00+00:00')), day)
            self.assertNotEqual(briefing_day('Europe/London', datetime.fromisoformat(f'{day}T{utc_cutoff-1:02}:59:59+00:00')), day)


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        complete_profile(self.root)
        (self.root / 'daily').mkdir()
        self.chamber = FakeChamber()
        self.app = BrowserApp(self.root, self.chamber, now=lambda: datetime(2026,10,10,12,tzinfo=timezone.utc))

    def start(self):
        result = self.app.start('2026-10-10', 'gm')
        self.assertTrue(self.chamber.sent.wait(2))
        # Dispatch completion is serialized by the app lock; no arbitrary sleep.
        with self.app.lock:
            self.app.jobs['2026-10-10.gm']['state'] = 'running'
        return result['job']

    def answer(self, job):
        """Approves the permission and answers the saved question; the continued run keeps working."""
        self.app.reply(job,'permission','per_fixture',{'decision':'once'})
        with patch('goodmorning.web.briefing_server.threading.Thread', ImmediateThread):
            self.app.reply(job,'form','frm_test',{'answer':{'progress':['unreported']}})
        self.chamber.busy=True

    def test_question_is_saved_and_its_answer_continues_the_original_edition(self):
        job=self.start()
        self.chamber.permissions=[]
        self.assertEqual(self.app.status(job)['forms'][0]['id'],'frm_test')
        # The engine no longer holds the question, and a restart keeps the saved copy.
        self.assertEqual((self.chamber.forms,self.chamber.busy),([],False))
        later=datetime(2026,10,12,12,tzinfo=timezone.utc)
        self.app=BrowserApp(self.root,self.chamber,now=lambda:later)
        current=self.app.status(job)
        self.assertEqual((current['state'],current['forms'][0]['id'],current['reservation_required']),('waiting','frm_test',False))
        with self.assertRaises(ValueError):
            self.app.reply(job,'form','frm_test',{'answer':{'other':'x'}})
        with patch('goodmorning.web.briefing_server.threading.Thread', ImmediateThread):
            self.app.reply(job,'form','frm_test',{'answer':{'progress':['unreported']}})
            self.app.reply(job,'form','frm_test',{'answer':{'progress':['other']}})
        prompts=[body['prompt'] for action,body in self.chamber.calls if action=='session.send']
        self.assertEqual(len(prompts),2)
        self.assertTrue(prompts[-1].startswith(self.app.generation_prompt(self.app.job(job))))
        self.assertTrue(prompts[-1].endswith('User has answered your questions: "Reported progress"="unreported". '
                                             "You can now continue with the user's answers in mind."))
        # Answered after its day has passed, the edition still finishes under its own date.
        self.assertEqual((self.app.job(job)['state'],self.app.job(job)['date']),('running','2026-10-10'))

    def test_answer_that_cannot_continue_yet_waits_for_the_user_again(self):
        job=self.start()
        self.app.status(job)  # The question is closed, but the open permission keeps its run going.
        with patch('goodmorning.web.briefing_server.threading.Thread', ImmediateThread), patch('goodmorning.web.briefing_server.time.sleep'):
            self.app.reply(job,'form','frm_test',{'answer':{'progress':['unreported']}})
        sends=lambda:sum(action=='session.send' for action,_ in self.chamber.calls)
        # Nothing was sent, so the job is not stranded as an uncertain dispatch.
        current=self.app.status(job)
        self.assertEqual((sends(),self.app.job(job)['state'],current['state'],current['forms'][0]['id']),(1,'running','waiting','frm_test'))
        self.app.reply(job,'permission','per_fixture',{'decision':'once'})
        with patch('goodmorning.web.briefing_server.threading.Thread', ImmediateThread):
            self.app.reply(job,'form','frm_test',{'answer':{'progress':['unreported']}})
        self.assertEqual((sends(),self.app.job(job)['state'],self.app.status(job)['forms']),(2,'running',[]))

    def test_mobile_section_picker_is_inert_markup_and_does_not_change_records(self):
        (self.root/'daily/2026-10-10.gm.json').write_text(GM)
        before={path:path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        page=self.app.page('2026-10-10','gm',False).decode()
        self.assertIn('id="mobile-sections" type="button" hidden',page)
        self.assertIn('id="mobile-section-dialog" aria-labelledby="mobile-section-heading"',page)
        self.assertIn('class="briefing-section-nav"',page)
        self.assertEqual({path:path.read_bytes() for path in before},before)

    def test_offline_copy_is_the_latest_saved_edition_without_tokens_or_controls(self):
        import os, re
        from unittest.mock import patch
        with self.assertRaises(ValueError):
            self.app.offline_page('gm')  # Nothing saved this week: devices drop their copy.
        older = self.root/'daily/2026-10-08.gm.json'
        older.write_text(GM)
        # Saved after midnight, before the account's day ends at 04:00: still that day's edition.
        os.utime(older, (0, datetime(2026,10,9,0,5,tzinfo=timezone.utc).timestamp()))
        page = self.app.offline_page('gm').decode()
        self.assertIn('data-edition="gm"', page)
        self.assertIn('2026-10-08 / Morning edition', page)
        self.assertIn('data-day="2026-10-08" data-zone="Europe/London"', page)
        self.assertIn('01:05', page)  # The saved time in the account's timezone (London, BST).
        for line in ('offline-today', 'offline-earlier', 'unreachable-today', 'unreachable-earlier'):
            self.assertIn(f'class="{line}"', page)
        self.assertNotIn(self.app.csrf, page)
        for control in ('csrf', '<form', 'id="sign-out"', 'id="generate"', 'quick-chat', 'week-picker', 'srcset='):
            self.assertNotIn(control, page)
        # Every file it names is a shared fingerprinted asset or a briefing link the device opens offline.
        for path in re.findall(r'(?:href|src)="(/[^"]*)"', page):
            self.assertTrue(path.startswith('/assets/') or path in ('/gm', '/gn'), path)
        (self.root/'daily/2026-10-10.gm.json').write_text(GM)
        self.assertTrue('2026-10-10 / Morning edition' in self.app.offline_page('gm').decode())
        # While a regenerated edition awaits its check, devices keep the copy they have.
        self.app.preflight = True
        self.app.jobs['2026-10-10.gm'] = {'id': 'a'*32, 'date': '2026-10-10', 'kind': 'gm', 'state': 'running'}
        with patch.object(self.app, 'status', return_value={'state': 'running'}):
            self.assertIsNone(self.app.offline_page('gm'))

    def test_new_conversation_action_follows_the_preserved_history(self):
        page=self.app.chat_page().decode()
        self.assertLess(page.index('id="conversation-history"'),page.index('id="new-conversation"'))

    def test_failed_preflight_returns_durable_stopped_receipt_without_dispatch(self):
        from unittest.mock import patch
        self.app.preflight = True
        with patch('goodmorning.briefings.briefing_preflight.initialize', side_effect=OSError('Synthetic private preparation failure')), self.assertLogs('goodmorning.web.briefing_server', level='WARNING') as logs:
            result = self.app.start('2026-10-10', 'gm')
        self.assertIn('OSError', logs.output[0])
        self.assertNotIn('private', logs.output[0])
        self.assertEqual(self.app.status(result['job'])['state'], 'stopped')
        self.assertIsNone(self.app.job(result['job']).get('session'))
        self.assertEqual(self.chamber.calls, [])
        restored = BrowserApp(self.root, self.chamber, now=self.app.now, preflight=True)
        self.assertEqual(restored.start('2026-10-10', 'gm'), result)
        self.assertEqual(restored.status(result['job'])['recovery_action'], 'restart')

    def test_failed_recovery_preflight_returns_stopped_receipt_and_never_replays(self):
        from unittest.mock import patch
        self.app.preflight = True
        with patch('goodmorning.briefings.briefing_preflight.initialize', side_effect=OSError('Synthetic failure')), self.assertLogs('goodmorning.web.briefing_server', level='WARNING'):
            result = self.app.start('2026-10-10', 'gm')
            recovered = self.app.recover(result['job'], {'id':'b'*32})
        self.assertEqual(recovered, result)
        self.assertEqual(self.app.status(result['job'])['state'], 'stopped')
        self.assertEqual(self.app.job(result['job'])['recovery_request'], 'b'*32)
        with patch('goodmorning.briefings.briefing_preflight.initialize') as initialize:
            self.assertEqual(self.app.recover(result['job'], {'id':'b'*32}), result)
        initialize.assert_not_called()
        self.assertEqual(self.chamber.calls, [])

    def test_acknowledged_inputs_never_reappear_or_yield_before_engine_catches_up(self):
        from unittest.mock import patch
        job=self.start()
        self.chamber.forms=[]
        with patch.object(self.chamber,'request',return_value={}) as reply:
            self.app.reply(job,'permission','per_fixture',{'decision':'once'})
            self.app.reply(job,'permission','per_fixture',{'decision':'once'})
        self.assertEqual(reply.call_count,1)
        # The synthetic engine still lists its old inputs after acknowledging them.
        current=self.app.status(job)
        self.assertEqual(current['state'],'running')
        self.assertEqual(current['forms'],[]);self.assertEqual(current['permissions'],[])
        self.assertNotIn('reservation_required',current)
        restored=BrowserApp(self.root,self.chamber,now=self.app.now)
        self.assertEqual(restored.status(job)['permissions'],[])

    def test_seven_days_and_missing_archive_do_not_generate(self):
        self.assertEqual(self.app.dates(), [f'2026-10-{i:02}' for i in range(10,3,-1)])
        page = self.app.page('2026-10-04','gn',True).decode()
        self.assertIn('class="waiting-room"', page)
        self.assertNotIn('class="generation-desk"', page)
        self.assertNotIn('id="generate"', page)
        self.assertIn('&quot;pinned&quot;: true', page)
        with self.assertRaises(ValueError): self.app.start('2026-10-09','gm')
        with self.assertRaises(ValueError): self.app.page('2026-10-03','gm',True)
        self.assertEqual(self.chamber.calls, [])

    def test_widget_weather_rows_use_the_frame_headlines(self):
        from goodmorning.web.app_briefings import document
        frame = {'start': '2026-10-10T06:00', 'past': 1, 'hours': [[10 + h / 4, 80 if h >= 15 else 5, 30] for h in range(18)],
                 'sun': [], 'night': [], 'snow': False,
                 'links': {'forecast': 'https://open-meteo.com/en/docs', 'air': 'https://open-meteo.com/en/docs/air-quality-api'}}
        data = {'greeting': 'Morning', 'opening': 'Hi', 'sections': [['weather', [['weather', [
            ['temperature', '12°C', 'Mild.'], ['precipitation', '80% – Rain likely', 'Umbrella after 21:00.']], frame]]]]}
        rows = document(data, '2026-10-10')['sections'][0]['rows']
        self.assertEqual([(row['side'], row['text']) for row in rows],
                         [('14°', 'High · low 10° · Mild.'), ('Dry until 21:00', 'Then rain likely · up to 80% · Umbrella after 21:00.')])

    def test_widget_briefings_are_plain_rows_and_follow_preparation(self):
        from goodmorning.web.app_briefings import summary
        self.assertEqual(summary(self.app), {'date': '2026-10-10', 'editions': {'gm': {'state': 'missing'}, 'gn': {'state': 'missing'}}})
        self.start()
        self.assertEqual(summary(self.app)['editions']['gm'], {'state': 'waiting'})  # The fixture's secretary asks first.
        (self.root/'daily/2026-10-10.gn.json').write_text(GM)
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        evening = summary(self.app)['editions']['gn']
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertEqual((evening['state'], evening['greeting'], evening['closing']), ('ready', 'Good morning', 'A warm closing.'))
        self.assertEqual([section['type'] for section in evening['sections']], ['weather', 'news', 'schedule', 'must-do'])
        rows = {section['type']: section['rows'] for section in evening['sections']}
        self.assertEqual(rows['weather'][0], {'style': 'item', 'side': '14°C', 'title': 'Temperature', 'text': 'Cool.'})
        self.assertEqual(rows['news'], [{'style': 'heading', 'side': '', 'title': 'World', 'text': ''},
                                        {'style': 'story', 'side': '', 'title': 'A complete story.', 'text': 'A full summary.', 'source': 'Source'}])
        self.assertEqual(rows['schedule'][0], {'style': 'item', 'side': '09:00–11:00', 'title': 'Teaching', 'text': 'Room A · Bring notes'})
        self.assertEqual([row['side'] for row in rows['must-do']], ['○', '✓'])
        self.assertTrue(evening['sections'][1]['title'].startswith('News — 2026-10-09'))

    def test_missing_today_has_generation_layout(self):
        page = self.app.page('2026-10-10','gm',False).decode()
        self.assertIn('id="generate"', page)
        self.assertIn('class="generation-desk"', page)
        self.assertIn('id="agent-questions"', page)
        self.assertIn('generation-progress', page)

    def test_incomplete_setup_replaces_generation_without_model_or_record_changes(self):
        for profile in ('', 'timezone: Europe/London\n', 'city: London, GB\nnews_country: GB\n'):
            (self.root/'profile.md').write_text(profile)
            before = set(self.root.rglob('*'))
            for kind in ('gm','gn'):
                page = self.app.page('2026-10-10',kind,False).decode()
                self.assertIn('id="initialize"',page)
                self.assertIn('href="/chat?mode=initialize"',page)
                self.assertNotIn('id="generate"',page)
                with self.assertRaisesRegex(ValueError,'Initialize'):
                    self.app.start('2026-10-10',kind)
            self.assertEqual(before,set(self.root.rglob('*')))
            self.assertEqual(self.chamber.calls,[])

    def test_today_marker_is_unique_and_independent_of_archive_selection(self):
        for selected, kind in [('2026-10-10', 'gm'), ('2026-10-07', 'gn')]:
            week = self.app.week(selected, kind)
            self.assertEqual(week.count('class="today-marker"'), 1)
            self.assertIn(f'href="/{kind}"', week)
        self.assertIn('<span class="today-marker">Today</span>', week)
        self.assertIn('data-ui-date="2026-10-10">Sat, Oct 10', week)
        self.app.now = lambda: datetime(2026,10,11,3,0,tzinfo=timezone.utc)
        self.assertIn('<span class="today-marker">Today</span><span data-ui-date="2026-10-11">Sun, Oct 11</span>', self.app.week('2026-10-10', 'gm'))

    def test_rollover_changes_current_day_but_keeps_selected_archive(self):
        (self.root/'daily/2026-10-10.gm.json').write_text(GM)
        self.app.now=lambda:datetime(2026,10,11,2,59,59,tzinfo=timezone.utc)
        self.assertEqual(self.app.today(),'2026-10-10')
        self.app.now=lambda:datetime(2026,10,11,3,0,0,tzinfo=timezone.utc)
        self.assertEqual(self.app.today(),'2026-10-11')
        self.assertIn('id="generate"',self.app.page(self.app.today(),'gm',False).decode())
        self.assertIn('<article',self.app.page('2026-10-10','gm',True).decode())

    def test_saved_archive_source_unchanged_and_assets_are_absolute(self):
        source = self.root / 'daily/2026-10-10.gm.json'
        source.write_text(GM)
        page = self.app.page('2026-10-10','gm',True).decode()
        self.assertEqual(source.read_text(),GM)
        self.assertIn('href="' + self.app.resources.urls['briefing.css'] + '"',page)
        self.assertIn('href="/d/2026-10-10/gn"',page)
        self.assertNotIn('class="briefing-tools"',page)
        self.assertRegex(page,r'<h1\b[^>]*>Good morning</h1>')

    def test_missing_past_day_points_to_its_schedule_day(self):
        (self.root / 'daily/2026-10-10.gm.json').write_text(GM)
        self.app.now = lambda: datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
        page = self.app.page('2026-10-09', 'gm', True).decode()
        self.assertIn('href="/schedule?view=day&amp;day=-2"', page)
        self.assertNotIn('id="generate"', page)
        self.assertRegex(page, r'<a href="/d/2026-10-09/gm" class="is-missing" aria-current="date">')
        self.assertRegex(page, r'<a href="/d/2026-10-10/gm">')

    def test_duplicate_clicks_share_session_and_user_default(self):
        job = self.start()
        self.assertEqual(self.app.start('2026-10-10','gm')['job'],job)
        self.assertEqual(sum(action == 'session.create' for action,_ in self.chamber.calls),1)
        self.assertNotIn('model',self.chamber.calls[0][1])
        self.assertNotIn('variant',self.chamber.calls[0][1])
        from goodmorning.web.models import session_payload, DEFAULT
        self.assertIn(('/api/session/ses_fixture/model', {'model': session_payload(DEFAULT)}), self.chamber.calls)
        self.assertEqual((self.root / 'browser-jobs/jobs.json').stat().st_mode & 0o777,0o600)

    def test_question_and_permission_pause_progress_and_reply_to_owned_session(self):
        job = self.start()
        result = self.app.status(job)
        self.assertEqual(result['state'],'waiting')
        self.answer(job)
        self.assertEqual(self.app.status(job)['state'],'running')
        with self.assertRaises(ValueError): self.app.reply(job,'form','frm_other',{'answer':{}})
        with self.assertRaises(ValueError): self.app.status('1'*32)

    def test_permission_cannot_be_permanent_or_automatic(self):
        job=self.start()
        with self.assertRaises(ValueError): self.app.reply(job,'permission','per_fixture',{'decision':'always'})
        self.assertEqual(len(self.chamber.permissions),1)

    def test_progress_advances_only_with_published_sections(self):
        job=self.start()
        self.assertEqual(self.app.status(job)['progress'],5)
        self.answer(job)
        current=self.app.status(job)
        self.assertEqual((current['state'],current['progress']),('running',5))
        doc=json.loads(GM);doc.pop('closing',None);plan=[[section[0],'Planned'] for section in doc['sections'][:2]];doc['sections']=doc['sections'][:1]
        (self.app.job_dir/(job+'.preview.json')).write_text(json.dumps({'plan':plan,'outcomes':['ready'],'document':doc}))
        self.assertTrue(5<self.app.status(job)['progress']<100)

    def test_recorded_steps_label_and_move_the_bar_within_a_section(self):
        job=self.start()
        self.chamber.forms,self.chamber.permissions=[],[]
        import time
        while 'running_at' not in self.app.jobs['2026-10-10.gm']:time.sleep(.01)  # Dispatch records its start last.
        with self.app.lock:
            self.app.jobs['2026-10-10.gm']['running_at']=time.time()-75
        self.assertGreaterEqual(self.app.status(job)['elapsed'],75)
        activity=self.app.job_dir/(job+'.activity.json')
        def step(**value):
            activity.write_text(json.dumps(value))
            return self.app.status(job)
        self.assertEqual((step(step='opening')['label'],self.app.status(job)['progress']),('Writing your greeting',12))
        doc=json.loads(GM);doc.pop('closing',None);doc['sections']=doc['sections'][:1]
        plan=[['weather','Weather'],['news','News'],['schedule','Schedule']]
        (self.app.job_dir/(job+'.preview.json')).write_text(json.dumps({'plan':plan,'outcomes':['ready'],'document':doc}))
        first=step(step='collect',position=1,section='news',done=0,total=2)
        second=step(step='collect',position=1,section='news',done=1,total=2)
        writing=step(step='write',position=1,section='news',count=12)
        self.assertEqual([first['label'],second['label'],writing['label']],
                         ['Collecting the news · 1 of 2','Collecting the news · 2 of 2','Choosing from 12 stories'])
        self.assertEqual(writing['step_label'],writing['label'])
        self.assertTrue(45<first['progress']<second['progress']<writing['progress']<writing['progress_cap']<70)
        self.assertEqual(step(step='write',position=1,section='news',count=1)['label'],'Choosing from 1 story')
        stale=step(step='write',position=0,section='weather',count=None)
        self.assertEqual((stale['label'],stale.get('step_label')),('Preparing News',None))
        from support import selected
        from goodmorning.web import language as ui
        with selected(ui.CURRENT,'zh-CN'):
            self.assertEqual(step(step='write',position=1,section='news',count=12)['label'],'正在从 12 条新闻里挑选')

    def test_ready_needs_idle_and_saved_snapshot_not_agent_claim(self):
        job=self.start()
        self.chamber.idle()
        self.assertEqual(self.app.status(job)['state'],'stopped')
        (self.root/'daily/2026-10-10.gm.json').write_text(GM)
        self.assertEqual(self.app.status(job)['state'],'ready')

    def test_persistent_job_restores_without_dispatch(self):
        job=self.start()
        app=BrowserApp(self.root,self.chamber,now=self.app.now)
        self.assertEqual(app.start('2026-10-10','gm')['job'],job)
        self.assertEqual(sum(action=='session.create' for action,_ in self.chamber.calls),1)

    def test_uncertain_dispatch_never_replays(self):
        def fail(*args,**kwargs): raise TimeoutError()
        self.chamber.control=fail
        record={'id':'a'*32,'date':'2026-10-10','kind':'gm','state':'starting'}
        self.app.jobs['2026-10-10.gm']=record
        self.app.dispatch(record)
        self.assertEqual(record['state'],'uncertain')
        self.assertEqual(self.app.start('2026-10-10','gm')['job'],record['id'])

    def test_chamber_rejects_remote_origins_and_credentials_in_url(self):
        for url in ('https://example.org','http://localhost:3000','http://127.0.0.1:3000/api','http://user:secret@127.0.0.1:3000'):
            with self.assertRaises(ValueError): Chamber(url,self.root)


class HTTPTests(HTTPFixture):
    def test_csrf_host_origin_and_arbitrary_proxy_requests_denied(self):
        for headers in ({'Origin':'https://evil.example'},{'Host':'evil.example'},{'X-Briefing-CSRF':'wrong'}):
            with self.assertRaises(HTTPError) as error:self.request('/api/generate',{'date':self.date,'kind':'gm'},headers)
            self.assertEqual(error.exception.code,403);error.exception.close()
        with self.assertRaises(HTTPError) as error:self.request('/api/session/ses_other/form')
        self.assertEqual(error.exception.code,404);error.exception.close()

    def test_http_generate_resume_and_real_form_reply_shape(self):
        job=self.request('/api/generate',{'date':self.date,'kind':'gm'})['job']
        self.assertEqual(self.request('/api/generate',{'date':self.date,'kind':'gm'})['job'],job)
        self.assertEqual(self.request(f'/api/edition/{self.date}/gm')['job'],job)
        state=self.request('/api/jobs/'+job)
        self.assertEqual(state['forms'][0]['id'],'frm_test')
        self.request(f'/api/jobs/{job}/form/frm_test/reply',{'answer':{'progress':['unreported']}})
        self.request(f'/api/jobs/{job}/permission/per_fixture/reply',{'decision':'reject'})
        self.assertEqual(self.request('/api/jobs/'+job)['forms'],[])


if __name__=='__main__':
    if '--serve-fixture' in sys.argv:
        root = Path(sys.argv[-1])
        from support import returning_viewer
        returning_viewer(root)
        class CompletingFixture(FakeChamber):
            def request(self, path, body=None, method=None):
                result = super().request(path,body,method)
                if not self.forms and not self.permissions:
                    (root/'daily'/(briefing_day('Europe/London')+'.gm.json')).write_text(GM)
                    self.busy=False
                return result
        serve_live(BrowserApp(root,CompletingFixture()),0)
    else:
        unittest.main()
