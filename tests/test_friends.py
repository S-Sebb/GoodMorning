"""Friendships, per-friend sharing and self-service renames, with synthetic accounts only."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from support import TEMP_ROOT, GatewayFixture
from test_weekly_schedule import NOW, canonical_records, make_runtime
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.security import friends
from goodmorning.security.briefing_accounts import Accounts, Denied, Refused
from goodmorning.web import language as ui
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
        friends.answer(self.store, self.bob, 'alice', True, ['stocks'])
        self.assertEqual(self.friends_of(self.bob), {'alice': ['stocks']})
        self.assertEqual(self.friends_of(self.alice), {'bob': []})
        self.assertEqual(friends.shared_with(self.store, self.alice, 'bob')[1:], ('bob', ['stocks']))
        self.assertEqual(friends.shared_with(self.store, self.bob, 'alice')[1:], ('alice', []))

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
        friends.answer(self.store, self.bob, 'alice', True, ['schedule'])
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
        friends.answer(self.store, self.bob, 'alice', True, ['stocks'])
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
        friends.answer(self.store, self.bob, 'alice', True, ['stocks'])
        self.store.administer('bob', enabled=False)
        with self.assertRaises(Denied):
            friends.shared_with(self.store, self.alice, 'bob')
        self.store.create('carol', 'temporary-carol-secret1')
        self.store.administer('carol', enabled=False)
        with self.assertRaises(Refused):
            friends.request(self.store, self.alice, 'carol')


class FriendGateway(GatewayFixture):
    def setUp(self):
        super().setUp()
        self.carol = self.store.create('carol', 'temporary-carol-secret1')
        registry = json.loads((self.root/'backends.json').read_text())
        registry[self.other] = registry[self.carol] = registry[self.id]
        (self.root/'backends.json').write_text(json.dumps(registry))
        self.permanent()

    def shared_requests(self):
        return [path for path, _ in self.received if path.startswith('/shared')]

    def test_friend_page_needs_an_accepted_friendship(self):
        self.assertEqual(self.request('/api/friends/request', {'name': 'bob'})[0], 200)
        status, _, page = self.request('/friends/bob')
        self.assertEqual(status, 404)
        self.assertEqual(self.request('/friends/nobody')[0], 404)
        self.assertEqual(self.shared_requests(), [])
        friends.answer(self.store, self.other, 'alice', True, ['stocks', 'schedule'])
        status, _, page = self.request('/friends/bob?week=-1')
        self.assertEqual(status, 200)
        self.assertEqual(self.shared_requests(), ['/shared?sections=schedule%2Cstocks&week=-1&name=bob'])
        self.assertIn(b'id="friends-menu"', page)
        # The friend's backend-wide CSRF never reaches the viewer.
        self.assertNotIn(b'a' * 43, page)
        self.assertEqual(self.request('/friends/bob?week=9')[0], 404)
        self.assertEqual(self.request('/friends/carol')[0], 404)
        self.assertEqual(self.request('/api/friends/remove', {'name': 'bob'})[0], 200)
        self.assertEqual(self.request('/friends/bob')[0], 404)
        self.assertEqual(len(self.shared_requests()), 1)

    def test_shared_view_is_not_a_browser_route(self):
        self.assertEqual(self.request('/shared?sections=stocks&week=0&name=alice')[0], 403)
        self.assertEqual(self.shared_requests(), [])

    def test_friend_requests_need_the_session_csrf(self):
        csrf, self.csrf = self.csrf, 'b' * 64
        self.assertEqual(self.request('/api/friends/request', {'name': 'bob'})[0], 403)
        self.csrf = csrf
        status, _, body = self.request('/api/friends/request', {'name': 'nobody'})
        self.assertEqual(status, 400)
        self.assertIn('No account has that username', json.loads(body)['error'])
        self.assertEqual(friends.overview(self.store, self.other)['incoming'], [])

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

    def page(self, sections, week=0):
        return shared.page(self.app, f'sections={sections}&week={week}&name=bob').decode()

    def test_schedule_shows_titles_and_times_only(self):
        page = self.page('schedule')
        self.assertIn('Team check-in', page)
        self.assertIn('09:30–10:00', page)
        self.assertIn('Dentist', page)
        for private in ('Studio 2', 'Bring the outline.', 'Library', 'Town Clinic', 'Bring the referral.', 'Pick up a parcel'):
            self.assertNotIn(private, page)

    def test_todos_without_details(self):
        page = self.page('todos')
        self.assertIn('Pick up a parcel', page)
        self.assertNotIn('Team check-in', page)
        for private in ('First baseline compared.', 'Awaiting lab approval.', 'Compare the two baselines.'):
            self.assertNotIn(private, page)

    def test_latest_evening_stocks(self):
        self.assertIn('No evening briefing in the last two weeks.', self.page('stocks'))
        stocks.save(self.root, '2026-10-12', {'block': ['holdings', [['usAAPL', 'Apple', '2026-10-09', 10, 200.0, 190.0, None, 'USD']]]})
        page = self.page('stocks')
        self.assertIn('Apple', page)
        self.assertNotIn('Team check-in', page)

    def test_nothing_shared_and_invalid_requests(self):
        self.assertIn('bob is not sharing anything with you yet.', self.page(''))
        for query in ('sections=chats&week=0&name=bob', 'sections=&week=0&name=../x', 'sections=&week=5&name=bob'):
            with self.assertRaises(ValueError):
                shared.page(self.app, query)


if __name__ == '__main__':
    unittest.main()
