"""Friendships, per-friend sharing, friends' versions of pages and self-service renames, with synthetic accounts only."""
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import secrets
import sys
import tempfile
import unittest

from support import TEMP_ROOT, GatewayFixture, QuickServer
from test_weekly_schedule import NOW, canonical_records, make_runtime
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.security import friends
from goodmorning.security.briefing_accounts import Accounts, Denied, Refused
from goodmorning.web import shared
from goodmorning import stocks


class FriendStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT); self.addCleanup(self.temp.cleanup)
        self.store = Accounts(Path(self.temp.name), testing=True, n=1024)
        self.alice = self.store.create('alice', 'temporary-alice-secret1')
        self.bob = self.store.create('bob', 'temporary-bob-secret1')

    def friends_of(self, user):
        return {item['name']: item['sharing'] for item in friends.overview(self.store, user)['friends']}

    def test_friendship_needs_acceptance_and_sharing_starts_off(self):
        self.assertEqual(friends.request(self.store, self.alice, 'Bob'), 'sent')
        self.assertEqual(friends.overview(self.store, self.bob)['incoming'], ['alice'])
        with self.assertRaises(Denied):
            friends.shared_with(self.store, self.alice, 'bob')
        friends.answer(self.store, self.bob, 'alice', True)
        self.assertEqual(self.friends_of(self.bob), {'alice': []})
        self.assertEqual(self.friends_of(self.alice), {'bob': []})
        self.assertEqual(friends.sharing_with(self.store, self.alice), [])
        friends.share(self.store, self.bob, 'alice', ['stocks'])
        self.assertEqual(friends.shared_with(self.store, self.alice, 'bob')[1:], ('bob', ['stocks']))
        self.assertEqual(friends.sharing_with(self.store, self.alice), [('bob', ['stocks'])])
        self.assertEqual(friends.overview(self.store, self.alice)['friends'], [{'name': 'bob', 'sharing': [], 'shared': ['stocks']}])

    def test_unknown_self_and_declined_requests(self):
        with self.assertRaises(Refused):
            friends.request(self.store, self.alice, 'nobody')
        with self.assertRaises(Refused):
            friends.request(self.store, self.alice, 'alice')
        friends.request(self.store, self.alice, 'bob')
        friends.answer(self.store, self.bob, 'alice', False)
        # Declining is silent: gone for the recipient, still waiting for the sender, even when sent again.
        self.assertEqual(friends.overview(self.store, self.bob)['incoming'], [])
        self.assertEqual(friends.request(self.store, self.alice, 'bob'), 'sent')
        self.assertEqual(friends.overview(self.store, self.bob)['incoming'], [])
        self.assertEqual(friends.overview(self.store, self.alice)['outgoing'], ['bob'])
        self.assertEqual(self.friends_of(self.alice), {})

    def test_crossed_requests_become_friends(self):
        friends.request(self.store, self.alice, 'bob')
        self.assertEqual(friends.request(self.store, self.bob, 'alice'), 'friends')
        self.assertEqual(self.friends_of(self.alice), {'bob': []})
        self.assertEqual(friends.overview(self.store, self.alice)['outgoing'], [])

    def test_removal_ends_both_directions_and_forgets_sharing(self):
        friends.request(self.store, self.alice, 'bob')
        friends.answer(self.store, self.bob, 'alice', True)
        friends.share(self.store, self.alice, 'bob', ['games', 'todos'])
        self.assertEqual(self.friends_of(self.alice), {'bob': ['todos', 'games']})
        friends.remove(self.store, self.alice, 'bob')
        for viewer, owner in ((self.alice, 'bob'), (self.bob, 'alice')):
            with self.assertRaises(Denied):
                friends.shared_with(self.store, viewer, owner)
        friends.request(self.store, self.bob, 'alice')
        friends.answer(self.store, self.alice, 'bob', True)
        self.assertEqual(self.friends_of(self.bob), {'alice': []})

    def test_only_offered_sections(self):
        friends.request(self.store, self.alice, 'bob')
        friends.answer(self.store, self.bob, 'alice', True)
        for value in (['chats'], 'stocks', [['stocks']]):
            with self.assertRaises(Refused):
                friends.share(self.store, self.alice, 'bob', value)

    def test_rename_keeps_friendships_and_sessions(self):
        friends.request(self.store, self.alice, 'bob')
        friends.answer(self.store, self.bob, 'alice', True)
        friends.share(self.store, self.bob, 'alice', ['stocks'])
        with self.store.db() as db:
            token, _ = self.store.issue(db, 'gm.example.test', db.execute('SELECT * FROM users WHERE id=?', (self.bob,)).fetchone())
        session = self.store.session(token, 'gm.example.test')
        with self.assertRaises(Denied):
            self.store.rename(session, 'robert', 'wrong-password1', '192.0.2.1')
        with self.assertRaises(Refused):
            self.store.rename(session, 'alice', 'temporary-bob-secret1', '192.0.2.1')
        self.assertEqual(self.store.rename(session, 'Robert', 'temporary-bob-secret1', '192.0.2.1'), 'robert')
        self.assertEqual(self.store.session(token, 'gm.example.test')['name'], 'robert')
        self.assertEqual(friends.shared_with(self.store, self.alice, 'robert')[1:], ('robert', ['stocks']))
        with self.assertRaises(Denied):
            friends.shared_with(self.store, self.alice, 'bob')
        self.assertTrue(self.store.check_password('robert', 'temporary-bob-secret1'))
        # The old name is free straight away.
        self.store.create('bob', 'temporary-new-bob1')

    def test_disabled_accounts_cannot_be_found_or_viewed(self):
        friends.request(self.store, self.alice, 'bob')
        friends.answer(self.store, self.bob, 'alice', True)
        friends.share(self.store, self.bob, 'alice', ['stocks'])
        self.store.administer('bob', enabled=False)
        with self.assertRaises(Denied):
            friends.shared_with(self.store, self.alice, 'bob')
        self.store.create('carol', 'temporary-carol-secret1')
        self.store.administer('carol', enabled=False)
        with self.assertRaises(Refused):
            friends.request(self.store, self.alice, 'carol')


class FriendGateway(GatewayFixture):
    """alice views bob's versions of her pages; carol is a stranger."""
    def setUp(self):
        super().setUp()
        self.carol = self.store.create('carol', 'temporary-carol-secret1')
        self.pages = pages = []
        class Viewer(BaseHTTPRequestHandler):
            def do_GET(self):
                pages.append(self.path)
                kind = 'json' if self.path == '/api/day' else 'html'
                self.send_response(200); self.send_header('Content-Type', 'application/json' if kind == 'json' else 'text/html'); self.end_headers()
                self.wfile.write(b'{"date":"2026-10-13","timezone":"Asia/Shanghai"}' if kind == 'json' else
                    ('<head></head><body><header class="masthead">Desk</header><div data-config="{&quot;csrf&quot;: &quot;' + 'a' * 43 + '&quot;}"></div>' + self.path + '</body>').encode())
            def log_message(self, *_): pass
        viewer = QuickServer(('127.0.0.1', 0), Viewer); self.serve(viewer)
        (self.root/'backends.json').write_text(json.dumps({user: {'port': viewer.server_port, 'key': self.key} for user in (self.id, self.other, self.carol)}))
        self.permanent()

    def befriend(self, *sections):
        self.assertEqual(self.request('/api/friends/request', {'name': 'bob'})[0], 200)
        friends.answer(self.store, self.other, 'alice', True)
        if sections:
            friends.share(self.store, self.other, 'alice', list(sections))

    def shared_requests(self):
        return [path for path in self.pages if path.startswith('/shared')]

    def test_switch_lists_friends_who_share_for_that_page(self):
        self.assertNotIn(b'person-switch', self.request('/schedule')[2])
        self.befriend()
        self.assertNotIn(b'person-switch', self.request('/schedule')[2])
        friends.share(self.store, self.other, 'alice', ['stocks'])
        self.assertNotIn(b'person-switch', self.request('/schedule')[2])
        page = self.request('/d/2026-10-12/gn.html')[2]
        self.assertIn(b'<nav class="person-switch"', page)
        self.assertIn(b'href="/d/2026-10-12/gn.html?friend=bob"', page)
        self.assertIn(b'href="/d/2026-10-12/gn.html" aria-current="page"', page)
        self.assertEqual(self.shared_requests(), [])

    def test_friend_version_needs_friendship_and_a_shared_section(self):
        self.assertEqual(self.request('/api/friends/request', {'name': 'bob'})[0], 200)
        self.assertEqual(self.request('/schedule?friend=bob')[0], 404)
        self.assertEqual(self.request('/schedule?friend=nobody')[0], 404)
        friends.answer(self.store, self.other, 'alice', True)
        self.assertEqual(self.request('/schedule?friend=bob')[0], 404)
        friends.share(self.store, self.other, 'alice', ['stocks', 'todos'])
        self.assertEqual(self.request('/schedule?friend=carol')[0], 404)
        self.assertEqual(self.request('/chat?friend=bob')[0], 404)
        self.assertEqual(self.shared_requests(), [])
        status, _, page = self.request('/schedule?view=day&day=1&friend=bob')
        self.assertEqual(status, 200)
        self.assertEqual(self.shared_requests(), ['/shared?page=schedule&sections=todos&name=bob&zone=Asia%2FShanghai&view=day&day=1'])
        self.assertIn(b'href="/schedule?view=day&amp;day=1&amp;friend=bob" aria-current="page"', page)
        # The friend's backend-wide CSRF never reaches the viewer.
        self.assertNotIn(b'a' * 43, page)
        self.request('/gn.html?friend=bob')
        self.request('/d/2026-10-10/gm.html?friend=bob')
        self.assertEqual(self.shared_requests()[1:], ['/shared?page=gn&sections=stocks&name=bob&zone=Asia%2FShanghai&date=2026-10-13&today=2026-10-13',
                                                      '/shared?page=gm&sections=todos&name=bob&zone=Asia%2FShanghai&date=2026-10-10&today=2026-10-13'])
        self.assertEqual(self.request('/gn.html?friend=bob&week=1')[0], 404)
        self.assertEqual(self.request('/api/friends/remove', {'name': 'bob'})[0], 200)
        self.assertEqual(self.request('/gn.html?friend=bob')[0], 404)
        self.assertEqual(len(self.shared_requests()), 3)

    def test_shared_view_is_not_a_browser_route(self):
        self.assertEqual(self.request('/shared?page=gn&sections=stocks&name=alice&zone=UTC&date=2026-10-13&today=2026-10-13')[0], 403)
        self.assertEqual(self.shared_requests(), [])

    def test_friend_requests_need_the_session_csrf(self):
        csrf, self.csrf = self.csrf, 'b' * 64
        self.assertEqual(self.request('/api/friends/request', {'name': 'bob'})[0], 403)
        self.csrf = csrf
        status, _, body = self.request('/api/friends/request', {'name': 'nobody'})
        self.assertEqual(status, 400)
        self.assertIn('No account has that username', json.loads(body)['error'])
        self.assertEqual(friends.overview(self.store, self.other)['incoming'], [])

    def test_accept_only_accepts(self):
        friends.request(self.store, self.other, 'alice')
        self.assertEqual(self.request('/api/friends/accept', {'name': 'bob', 'sections': ['stocks']})[0], 400)
        status, _, body = self.request('/api/friends/accept', {'name': 'bob'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['friends'], [{'name': 'bob', 'sharing': [], 'shared': []}])

    def test_sharing_is_chosen_per_friend(self):
        for name, user in (('bob', self.other), ('carol', self.carol)):
            self.request('/api/friends/request', {'name': name})
            friends.answer(self.store, user, 'alice', True)
        status, _, body = self.request('/api/friends/share', {'name': 'bob', 'sections': ['todos']})
        self.assertEqual(status, 200)
        self.assertEqual({item['name']: item['sharing'] for item in json.loads(body)['friends']}, {'bob': ['todos'], 'carol': []})
        self.assertEqual(friends.shared_with(self.store, self.other, 'alice')[2], ['todos'])
        self.assertEqual(friends.shared_with(self.store, self.carol, 'alice')[2], [])

    def test_rename_from_the_website(self):
        status, _, body = self.request('/api/account/username', {'username': 'alicia', 'password': 'wrong-password1'})
        self.assertEqual(status, 403)
        status, _, body = self.request('/api/account/username', {'username': 'alicia', 'password': 'permanent-alice-secret1'})
        self.assertEqual((status, json.loads(body)['name']), (200, 'alicia'))
        # Still signed in on this device.
        self.assertEqual(json.loads(self.request('/api/friends')[2])['name'], 'alicia')


class SharedView(unittest.TestCase):
    """What the owner's own viewer renders for a friend: titles and times only, never notes."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = make_runtime(self.root)
        canonical_records(self.root)

    def page(self, query):
        return shared.page(self.app, query).decode()

    def test_schedule_in_the_viewers_time_zone_without_private_details(self):
        page = self.page('page=schedule&sections=schedule&name=bob&zone=Asia%2FShanghai')
        self.assertIn('Team check-in', page)
        self.assertIn('16:30–17:00', page)  # 09:30 in London is 16:30 in Shanghai.
        self.assertIn('Times are in your time zone; bob is in Europe/London.', page)
        self.assertIn('Dentist', page)
        for private in ('Studio 2', 'Bring the outline.', 'Library', 'Town Clinic', 'Bring the referral.', 'Pick up a parcel'):
            self.assertNotIn(private, page)
        self.assertIn('href="/schedule?week=-1&amp;friend=bob"', page)
        # An all-day event stays on its own date even where another zone's midnight falls the day before or after.
        self.assertEqual(page.count('A day away'), 1)

    def test_morning_day_and_todos_without_details(self):
        page = self.page('page=gm&sections=todos&name=bob&zone=Europe%2FLondon&date=2026-10-13&today=2026-10-13')
        self.assertIn('Pick up a parcel', page)
        self.assertNotIn('Team check-in', page)
        self.assertNotIn('Times are in your time zone', page)
        for private in ('First baseline compared.', 'Awaiting lab approval.', 'Compare the two baselines.'):
            self.assertNotIn(private, page)
        self.assertNotIn('id="day-next"', page)  # Never past the viewer's own day.

    def test_evening_rows_of_that_date(self):
        query = 'page=gn&sections=stocks&name=bob&zone=Europe%2FLondon&date=2026-10-12&today=2026-10-13'
        self.assertIn('Nothing saved for this evening.', self.page(query))
        stocks.save(self.root, '2026-10-11', {'block': ['holdings', [['usAAPL', 'Apple', '2026-10-09', 10, 200.0, 190.0, None, 'USD']]]})
        self.assertNotIn('Apple', self.page(query))
        stocks.save(self.root, '2026-10-12', {'block': ['holdings', [['usAAPL', 'Apple', '2026-10-09', 10, 200.0, 190.0, None, 'USD']]]})
        self.assertIn('Apple', self.page(query))

    def test_invalid_requests(self):
        for query in ('page=gn&sections=schedule&name=bob&zone=UTC&date=2026-10-12&today=2026-10-13',
                      'page=gn&sections=&name=bob&zone=UTC&date=2026-10-12&today=2026-10-13',
                      'page=gm&sections=todos&name=../x&zone=UTC&date=2026-10-12&today=2026-10-13',
                      'page=gm&sections=todos&name=bob&zone=Nowhere%2FCity&date=2026-10-12&today=2026-10-13',
                      'page=schedule&sections=todos&name=bob&zone=UTC&week=5',
                      'page=chat&sections=todos&name=bob&zone=UTC'):
            with self.assertRaises(ValueError):
                shared.page(self.app, query)


if __name__ == '__main__':
    unittest.main()
