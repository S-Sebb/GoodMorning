"""Read-only, account-local reminders; no history reads or dispatches."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from support import TEMP_ROOT, GatewayFixture, FakeChamber
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web.activity import snapshot, panel


class SnapshotTests(unittest.TestCase):
    def test_live_state_without_transcripts_or_saved_state_changes(self):
        chamber = FakeChamber()
        item = {'id': 'a'*32, 'mode': 'secretary', 'state': 'running', 'session': 'ses_fixture'}
        app = SimpleNamespace(chats=SimpleNamespace(get=lambda _: dict(item)), chamber=chamber)
        self.assertEqual(snapshot(app, 'chat', item['id']), {'mode': 'secretary', 'state': 'waiting'})
        chamber.forms = []; chamber.permissions = []
        self.assertEqual(snapshot(app, 'chat', item['id'])['state'], 'working')
        chamber.busy = False
        self.assertEqual(snapshot(app, 'chat', item['id'])['state'], 'idle')
        self.assertEqual(item['state'], 'running')
        self.assertTrue(all(action == 'session.status' for action, _ in chamber.calls))
        with patch.object(chamber, 'pending', side_effect=OSError('Synthetic outage')):
            self.assertEqual(snapshot(app, 'chat', item['id'])['state'], 'unavailable')
        item['state'] = 'uncertain'
        self.assertEqual(snapshot(app, 'chat', item['id'])['state'], 'uncertain')

    def test_answered_inputs_and_finished_states_are_not_waiting(self):
        chamber = FakeChamber()
        item = {'id': 'a'*32, 'mode': 'todo', 'state': 'running', 'session': 'ses_fixture',
                'replied_inputs': ['form:frm_test', 'permission:per_fixture']}
        app = SimpleNamespace(chats=SimpleNamespace(get=lambda _: dict(item)), chamber=chamber)
        self.assertEqual(snapshot(app, 'chat', item['id'])['state'], 'working')
        chamber.busy = False
        self.assertEqual(snapshot(app, 'chat', item['id'])['state'], 'idle')
        chamber.busy = True
        item['replied_inputs'] = []
        for state in ('complete', 'superseded'):
            item['state'] = state
            self.assertEqual(snapshot(app, 'chat', item['id']), {'mode': 'todo', 'state': 'idle'})

    def test_briefing_feedback_and_recovery_keep_exact_edition_metadata(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory); (root/'browser-jobs').mkdir()
            item = {'id': 'a'*32, 'date': '2026-10-12', 'kind': 'gn', 'state': 'preflight'}
            (root/'browser-jobs/jobs.json').write_text(json.dumps({'2026-10-12.gn': item}))
            target = root/'browser-jobs'/('a'*32+'.context.json')
            target.write_text(json.dumps({'awaiting': True}))
            app = SimpleNamespace(runtime=root, job=lambda _: dict(item))
            before = target.read_bytes()
            self.assertEqual(snapshot(app, 'job', item['id']), {'mode': 'gn', 'state': 'waiting', 'date': '2026-10-12'})
            self.assertEqual(target.read_bytes(), before)
            target.write_text(json.dumps({'awaiting': False, 'cancelled': True}))
            self.assertEqual(snapshot(app, 'job', item['id'])['state'], 'idle')

    def test_panel_injects_activity_controls_once(self):
        source = '<html><head></head><body><header>Desk</header></body></html>'
        rendered = panel(source, ['gm.example.test', 'gn.example.test', 'sec.example.test'])
        self.assertEqual(panel(rendered, ['gm.example.test']), rendered)
        self.assertIn('id="account-activity" hidden', rendered)
        self.assertIn('/activity.js', rendered)
        self.assertIn('id="activity-window"', rendered)
        self.assertIn('id="activity-minimize" type="button"', rendered)
        self.assertIn('id="activity-restore" type="button" hidden', rendered)
        self.assertIn('aria-controls="activity-window"', rendered)
        self.assertIn('<template id="activity-desk-art">', rendered)


class GatewayActivityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = GatewayFixture(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.gateway = self.fixture.gateway
        self.ticket = {'user': self.fixture.id, 'host': 'gm.example.test', 'chat': 'a'*32, 'request': 'b'*32}
        with self.fixture.store.db() as db:
            db.execute('INSERT INTO metadata VALUES (?,?)', ('generation', json.dumps(self.ticket)))

    def test_authentication_account_isolation_and_no_queue_side_effects(self):
        self.assertEqual(self.fixture.request('/api/activity')[0], 401)
        self.fixture.permanent()
        with patch.object(self.gateway, 'proxy', return_value=(200, {}, b'{"mode":"secretary","state":"waiting","prompt":"Private synthetic prompt"}')) as proxy, \
             patch.object(self.gateway, 'pump_queue', side_effect=AssertionError('Must not dispatch')):
            status, headers, raw = self.fixture.request('/api/activity')
            self.assertEqual(status, 200)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertEqual(json.loads(raw), {'activity': [{'mode': 'secretary', 'state': 'waiting',
                'url': 'https://gm.example.test/chat?id='+'a'*32}]})
            self.assertEqual(self.gateway.activity(self.fixture.other), {'activity': []})
            proxy.assert_called_once()
            self.assertEqual(self.gateway.ticket(), self.ticket)
            self.assertNotIn(self.fixture.id.encode(), raw)
            self.assertNotIn(b'Private synthetic prompt', raw)

    def test_idle_disappears_and_outages_do_not_claim_completion(self):
        with patch.object(self.gateway, 'proxy', return_value=(200, {}, b'{"mode":"secretary","state":"idle"}')):
            self.assertEqual(self.gateway.activity(self.fixture.id), {'activity': []})
        with patch.object(self.gateway, 'proxy', side_effect=OSError('Synthetic outage')):
            self.assertEqual(self.gateway.activity(self.fixture.id)['activity'][0]['state'], 'unavailable')
        self.assertEqual(self.gateway.ticket(), self.ticket)

    def test_recovery_tickets_get_their_date_from_owner_metadata(self):
        ticket = {'user': self.fixture.id, 'host': 'gm.example.test', 'job': 'c'*32, 'request': 'd'*32}
        with self.fixture.store.db() as db:
            db.execute("UPDATE metadata SET value=? WHERE key='generation'", (json.dumps(ticket),))
        with patch.object(self.gateway, 'proxy', return_value=(200, {}, b'{"mode":"gn","state":"waiting","date":"2026-10-12"}')):
            self.assertEqual(self.gateway.activity(self.fixture.id)['activity'][0]['url'], 'https://gm.example.test/d/2026-10-12/gn.html')

    def test_queue_summary_is_owner_only_and_never_dispatches_or_discards(self):
        entry = {'kind': 'chat', 'user': self.fixture.id, 'host': 'gn.example.test', 'path': '/api/chats',
                 'body': {'id': 'c'*32, 'mode': 'todo', 'text': 'Private synthetic task'},
                 'candidate': {'chat': 'c'*32}, 'language': 'en', 'enqueued': 1}
        other = {**entry, 'user': self.fixture.other, 'body': {**entry['body'], 'text': 'Other private task'},
                 'candidate': {'chat': 'd'*32}}
        with self.fixture.store.db() as db:
            db.execute('INSERT INTO metadata VALUES (?,?)', ('generation_queue', json.dumps([entry, other])))
        with patch.object(self.gateway, 'proxy', return_value=(200, {}, b'{"mode":"secretary","state":"idle"}')):
            self.assertEqual(self.gateway.activity(self.fixture.id), {'activity': [{'mode': 'todo', 'state': 'queued',
                'url': 'https://gn.example.test/chat?id='+'c'*32}]})
        with self.fixture.store.db() as db:
            self.assertEqual(json.loads(db.execute("SELECT value FROM metadata WHERE key='generation_queue'").fetchone()[0]), [entry, other])

    def test_yielded_preflight_remains_visible_without_a_global_ticket(self):
        ticket = {'user':self.fixture.id, 'host':'gm.example.test', 'job':'a'*32, 'kind':'gn', 'date':'2026-10-12'}
        with self.fixture.store.db() as db:
            db.execute("DELETE FROM metadata WHERE key='generation'")
            self.gateway.remember_waiting(db, ticket)
        def proxy(user, host, path, method, body, headers):
            self.assertEqual(path, '/api/activity/job/'+'a'*32);self.assertEqual(method, 'GET')
            return 200, {}, b'{"mode":"gn","state":"waiting","date":"2026-10-12"}'
        with patch.object(self.gateway, 'proxy', side_effect=proxy):
            self.assertEqual(self.gateway.activity(self.fixture.id), {'activity':[{'mode':'gn','state':'waiting',
                'url':'https://gm.example.test/d/2026-10-12/gn.html'}]})
            self.assertEqual(self.gateway.activity(self.fixture.other), {'activity':[]})
