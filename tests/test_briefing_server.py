"""Live viewer isolation, date boundaries and agent round-trips, without model calls."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.error import HTTPError

from support import TEMP_ROOT, FakeChamber, HTTPFixture, complete_profile
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

    def test_mobile_section_picker_is_inert_markup_and_does_not_change_records(self):
        (self.root/'daily/2026-10-10.gm.json').write_text(GM)
        before={path:path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        page=self.app.page('2026-10-10','gm',False).decode()
        self.assertIn('id="mobile-sections" type="button" hidden',page)
        self.assertIn('id="mobile-section-dialog" aria-labelledby="mobile-section-heading"',page)
        self.assertIn('class="briefing-section-nav"',page)
        self.assertEqual({path:path.read_bytes() for path in before},before)

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
        with patch.object(self.chamber,'request',return_value={}) as reply:
            self.app.reply(job,'form','frm_test',{'answer':{'progress':['unreported']}})
            self.app.reply(job,'permission','per_fixture',{'decision':'once'})
            self.app.reply(job,'permission','per_fixture',{'decision':'once'})
        self.assertEqual(reply.call_count,2)
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
            self.assertIn(f'href="/{kind}.html"', week)
        self.assertIn('<span class="today-marker">Today</span>', week)
        self.assertIn('data-ui-date="2026-10-10">Sat 10 Oct', week)
        self.app.now = lambda: datetime(2026,10,11,3,0,tzinfo=timezone.utc)
        self.assertIn('<span class="today-marker">Today</span><span data-ui-date="2026-10-11">Sun 11 Oct</span>', self.app.week('2026-10-10', 'gm'))

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
        self.assertIn('href="/d/2026-10-10/gn.html"',page)
        self.assertNotIn('class="briefing-tools"',page)
        self.assertRegex(page,r'<h1\b[^>]*>Good morning</h1>')

    def test_missing_past_day_points_to_its_schedule_day(self):
        (self.root / 'daily/2026-10-10.gm.json').write_text(GM)
        self.app.now = lambda: datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
        page = self.app.page('2026-10-09', 'gm', True).decode()
        self.assertIn('href="/schedule?view=day&amp;day=-2"', page)
        self.assertNotIn('id="generate"', page)
        self.assertRegex(page, r'<a href="/d/2026-10-09/gm.html" class="is-missing" aria-current="date">')
        self.assertRegex(page, r'<a href="/d/2026-10-10/gm.html">')

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
        self.app.reply(job,'form','frm_test',{'answer':{'progress':['unreported']}})
        self.app.reply(job,'permission','per_fixture',{'decision':'once'})
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
        self.app.reply(job,'form','frm_test',{'answer':{'progress':['unreported']}})
        self.app.reply(job,'permission','per_fixture',{'decision':'once'})
        current=self.app.status(job)
        self.assertEqual((current['state'],current['progress']),('running',5))
        doc=json.loads(GM);doc.pop('closing',None);plan=[[section[0],'Planned'] for section in doc['sections'][:2]];doc['sections']=doc['sections'][:1]
        (self.app.job_dir/(job+'.preview.json')).write_text(json.dumps({'plan':plan,'outcomes':['ready'],'document':doc}))
        self.assertTrue(5<self.app.status(job)['progress']<100)

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
            def request(self, path, body):
                result = super().request(path,body)
                if not self.forms and not self.permissions:
                    (root/'daily'/(briefing_day('Europe/London')+'.gm.json')).write_text(GM)
                    self.busy=False
                return result
        serve_live(BrowserApp(root,CompletingFixture()),0)
    else:
        unittest.main()
