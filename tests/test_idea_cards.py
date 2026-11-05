"""Idea cards on briefing pages close and reopen synthetic ideas without the secretary."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from support import TEMP_ROOT, start_server
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.briefings import briefing_document as native
from goodmorning.records.inbox_store import InboxStore, initialize
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web.ideas import close, states

NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
STAMP = '2026-10-13T13:00:00+01:00'


class IdeaCardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'profile.md').write_text('timezone: Europe/London\nsecretary_language: English\ncity: London, GB\nnews_country: GB\n')
        initialize(self.root)
        inbox = InboxStore(self.root, write=True)
        try:
            self.idea = inbox.mutate('add', {'kind': 'idea', 'raw': 'Weekly mood chart'}, 'ses_test', 'idea', STAMP)['id']
            self.update = inbox.mutate('add', {'kind': 'project_update', 'raw': 'Which scope?', 'questions': ['Which scope?']},
                                       'ses_test', 'update', STAMP)['id']
            self.organized = inbox.mutate('add', {'kind': 'idea', 'raw': 'Organized idea'}, 'ses_test', 'organized', STAMP)['id']
            inbox.mutate('update', {'status': 'confirmed'}, 'ses_test', 'organize', STAMP, self.organized, 1)
            inbox.mutate('append', {'detail': 'Maybe weekly, not daily.'}, 'ses_test', 'follow-up', STAMP, self.idea)
        finally:
            inbox.close()
        self.app = BrowserApp(self.root, now=lambda: NOW)

    def status(self, identifier):
        inbox = InboxStore(self.root)
        try:
            return inbox.show(identifier)['status']
        finally:
            inbox.close()

    def tap(self, closed, revision, key='idea-key-00000001', identifier=None):
        return close(self.app, {'id': identifier or self.idea, 'revision': revision, 'closed': closed, 'key': key})

    def test_only_pending_or_closed_ideas_get_a_button(self):
        self.assertEqual(states(self.app, [self.idea, self.update, self.organized, 'ib_0000000000000000']),
                         {'ideas': {self.idea: {'revision': 2, 'closed': False}}})
        self.assertEqual(states(self.app, []), {'ideas': {}})
        for bad in (['not-an-id'], ['ib_0000000000000000'] * 51):
            with self.assertRaises(ValueError):
                states(self.app, bad)
        html = native.render_block(['decisions', [[self.idea, 2, 'Weekly mood chart', 'A saved idea.'],
                                                   ['abcdefabcdefabcd', 1, 'Canceled: Catchup', 'outlook · confirmed']]], {}, '2026-10-13')
        self.assertIn(f'<li class="decision-card" data-entry="{self.idea}">', html)
        self.assertEqual(html.count('data-entry'), 1)  # An applied calendar change is no inbox entry.

    def test_close_settles_unread_details_undo_reopens_and_retries_replay(self):
        first = self.tap(True, 2)
        self.assertEqual(first, {'saved': True, 'id': self.idea, 'closed': True, 'revision': 3})
        self.assertEqual(self.status(self.idea), 'done')
        self.assertEqual(states(self.app, [self.idea])['ideas'][self.idea], {'revision': 3, 'closed': True})
        self.assertEqual(self.tap(True, 2), first)  # The same retry key saves once.
        with self.assertRaisesRegex(ValueError, 'write_conflict'):
            self.tap(False, 2, key='idea-key-00000002')
        self.assertEqual(self.tap(False, 3, key='idea-key-00000003')['revision'], 4)
        self.assertEqual(self.status(self.idea), 'pending')
        for identifier, revision in ((self.update, 1), (self.organized, 2)):
            with self.assertRaisesRegex(ValueError, 'not_found'):
                self.tap(True, revision, key='idea-key-00000004', identifier=identifier)
        for bad in ({'closed': 'yes'}, {'revision': '4'}, {'key': 'short'}, {'id': 'nope'}, {'extra': 1}):
            with self.assertRaises(ValueError):
                close(self.app, {'id': self.idea, 'revision': 4, 'closed': True, 'key': 'idea-key-00000005', **bad})

    def test_http_routes_need_csrf_and_report_conflicts(self):
        server = start_server(self.app)
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'
        def call(path, body=None, csrf=self.app.csrf):
            headers = {'Origin': origin, 'X-Briefing-CSRF': csrf, 'Content-Type': 'application/json'}
            try:
                response = urlopen(Request(origin + path, data=json.dumps(body).encode() if body else None, headers=headers), timeout=3)
            except HTTPError as error:
                response = error
            with response:
                return response.status, json.loads(response.read())
        self.assertEqual(call(f'/api/ideas?ids={self.idea},{self.update}'), (200, {'ideas': {self.idea: {'revision': 2, 'closed': False}}}))
        body = {'id': self.idea, 'revision': 2, 'closed': True, 'key': 'idea-key-00000001'}
        self.assertEqual(call('/api/ideas/close', body, csrf='wrong')[0], 403)
        self.assertEqual(self.status(self.idea), 'pending')
        self.assertEqual(call('/api/ideas/close', body), (200, {'saved': True, 'id': self.idea, 'closed': True, 'revision': 3}))
        status, result = call('/api/ideas/close', {**body, 'closed': False, 'key': 'idea-key-00000002'})
        self.assertEqual((status, result['error']), (409, 'Couldn’t save — this idea changed since the page loaded. Refresh and try again.'))


if __name__ == '__main__':
    unittest.main()
