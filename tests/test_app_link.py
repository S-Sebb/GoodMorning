"""Android app linking: pairing codes, app tokens and the phone notification outbox, with synthetic accounts."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.security import app_link, web_push
from goodmorning.security.briefing_accounts import Accounts


class AppLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.accounts = Accounts(Path(self.temp.name), testing=True, n=1024)
        self.alice = self.accounts.create('alice', 'temporary-alice-secret1')
        self.bob = self.accounts.create('bob', 'temporary-bob-secret1')

    def link(self, user=None, name='Pixel 7'):
        pairing = app_link.pair(self.accounts, name)
        app_link.confirm(self.accounts, user or self.alice, pairing['code'])
        return app_link.claim(self.accounts, pairing['secret'])

    def test_only_the_owner_typed_code_and_the_phones_secret_together_yield_one_token(self):
        pairing = app_link.pair(self.accounts, '  Pixel   7 ')
        self.assertRegex(pairing['code'], r'^[A-Z2-9]{4}-[A-Z2-9]{4}$')
        self.assertIsNone(app_link.claim(self.accounts, pairing['secret']))  # Waiting for the owner.
        for wrong in ('', 'ABCD', pairing['code'].replace('-', '')[::-1], 'IIII-OOOO'):
            with self.subTest(code=wrong), self.assertRaises(ValueError):
                app_link.confirm(self.accounts, self.alice, wrong)
        self.assertEqual(app_link.confirm(self.accounts, self.alice, ' ' + pairing['code'].lower().replace('-', ' ')), 'Pixel 7')
        with self.assertRaises(ValueError):
            app_link.confirm(self.accounts, self.bob, pairing['code'])  # Already used.
        with self.assertRaises(ValueError):
            app_link.claim(self.accounts, 'not-the-secret')
        claimed = app_link.claim(self.accounts, pairing['secret'])
        self.assertTrue(claimed['token'].startswith('gma_'))
        with self.assertRaises(ValueError):
            app_link.claim(self.accounts, pairing['secret'])  # Exactly once.
        self.assertEqual(app_link.verify(self.accounts, claimed['token']), self.alice)
        self.assertIsNone(app_link.verify(self.accounts, claimed['token'] + 'x'))
        self.assertEqual([item['label'] for item in app_link.links(self.accounts, self.alice)], ['Pixel 7'])
        self.assertNotIn('hash', app_link.links(self.accounts, self.alice)[0])
        with self.accounts.db() as db:
            stored = db.execute("SELECT value FROM metadata WHERE key=?", ('app-links:' + self.alice,)).fetchone()[0]
        self.assertNotIn(claimed['token'].encode() if isinstance(stored, bytes) else claimed['token'], stored)

    def test_codes_expire_and_names_are_validated(self):
        pairing = app_link.pair(self.accounts, 'Phone')
        with patch.object(app_link.time, 'time', lambda: 10**12):
            with self.assertRaises(ValueError):
                app_link.confirm(self.accounts, self.alice, pairing['code'])
        for name in ('', ' ', 'x' * 61, 'bad\nname', None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                app_link.pair(self.accounts, name)

    def test_unlinking_revokes_only_that_phone(self):
        first, second = self.link(), self.link(name='Tablet')
        app_link.unlink(self.accounts, self.alice, first['id'])
        self.assertIsNone(app_link.verify(self.accounts, first['token']))
        self.assertEqual(app_link.verify(self.accounts, second['token']), self.alice)

    def test_outbox_keeps_recent_allowed_status_for_linked_accounts_only(self):
        message = {'title': 'Ready', 'body': 'Tap', 'url': '/', 'tag': 't'}
        app_link.record(self.accounts, self.alice, 'chat', message)
        self.assertEqual(app_link.outbox(self.accounts, self.alice, 0), [])  # No phone linked yet.
        self.link()
        for _ in range(app_link.OUTBOX + 5):
            app_link.record(self.accounts, self.alice, 'chat', message)
        web_push.settings(self.accounts, self.alice, {**web_push.DEFAULTS, 'briefing': False})
        app_link.record(self.accounts, self.alice, 'briefing', message)
        recent = app_link.outbox(self.accounts, self.alice, 0)
        self.assertEqual(len(recent), app_link.OUTBOX)
        self.assertEqual((recent[-1]['seq'], recent[-1]['kind']), (app_link.OUTBOX + 5, 'chat'))
        self.assertEqual(app_link.outbox(self.accounts, self.alice, recent[-1]['seq']), [])
        self.assertEqual(app_link.outbox(self.accounts, self.bob, 0), [])


if __name__ == '__main__':
    unittest.main()
