"""Web Push storage, encryption and delivery rules with synthetic accounts and no network."""
import hashlib
import hmac
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.security import web_push
from goodmorning.security.briefing_accounts import Accounts

ENDPOINT = 'https://fcm.googleapis.com/fcm/send/device-a'


def browser():
    """A synthetic browser subscription and the private values it would keep."""
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b'0123456789abcdef'
    return private, {'endpoint': ENDPOINT, 'expirationTime': None,
                     'keys': {'p256dh': web_push.b64(public), 'auth': web_push.b64(auth)}}


def decrypt(private, subscription, body):
    """The receiving side of RFC 8291, written independently of the sender."""
    salt, record_size, length = body[:16], *struct.unpack('!IB', body[16:21])
    sender, ciphertext = body[21:21 + length], body[21 + length:]
    receiver = web_push.unb64(subscription['keys']['p256dh'])
    secret = private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender))
    def hkdf(salt, ikm, info, size):
        return hmac.new(hmac.new(salt, ikm, hashlib.sha256).digest(), info + b'\x01', hashlib.sha256).digest()[:size]
    ikm = hkdf(web_push.unb64(subscription['keys']['auth']), secret, b'WebPush: info\x00' + receiver + sender, 32)
    key = hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
    plain = AESGCM(key).decrypt(nonce, ciphertext, None)
    assert record_size == 4096 and plain.endswith(b'\x02')
    return plain[:-1]


class WebPushTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.accounts = Accounts(Path(self.temp.name), testing=True, n=1024)
        self.alice = self.accounts.create('alice', 'temporary-alice-secret1')
        self.bob = self.accounts.create('bob', 'temporary-bob-secret1')

    def test_only_browser_push_services_and_valid_keys_are_accepted(self):
        _, subscription = browser()
        self.assertEqual(web_push.subscription(subscription)['endpoint'], ENDPOINT)
        for endpoint in ('http://fcm.googleapis.com/x', 'https://evil.test/push', 'https://fcm.googleapis.com.evil.test/x',
                         'https://fcm.googleapis.com:8443/x', 'https://user@fcm.googleapis.com/x', 'https://127.0.0.1/x'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                web_push.subscription({**subscription, 'endpoint': endpoint})
        for keys in ({'p256dh': 'AAAA', 'auth': subscription['keys']['auth']}, {'p256dh': subscription['keys']['p256dh'], 'auth': 'AAAA'}, {}):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                web_push.subscription({**subscription, 'keys': keys})
        self.assertEqual(web_push.subscription({**subscription, 'endpoint': 'https://updates.push.services.mozilla.com/wpush/v2/x'})['endpoint'],
                         'https://updates.push.services.mozilla.com/wpush/v2/x')

    def test_only_the_subscribed_browser_can_read_the_payload(self):
        private, subscription = browser()
        body = web_push.encrypt(web_push.subscription(subscription), b'{"title":"Hello"}')
        self.assertEqual(decrypt(private, subscription, body), b'{"title":"Hello"}')
        self.assertNotIn(b'Hello', body)
        stranger, _ = browser()
        with self.assertRaises(Exception):
            decrypt(stranger, subscription, body)

    def test_vapid_token_is_signed_by_the_published_key_for_the_push_service(self):
        header = web_push.vapid(self.accounts, ENDPOINT, 'https://gm.example.test')
        token, key = header.removeprefix('vapid t=').split(', k=')
        self.assertEqual(key, web_push.public_key(self.accounts))
        head, claims, signature = token.split('.')
        values = json.loads(web_push.unb64(claims))
        self.assertEqual((values['aud'], values['sub']), ('https://fcm.googleapis.com', 'https://gm.example.test'))
        raw = web_push.unb64(signature)
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), web_push.unb64(key))
        public.verify(encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big')),
                      (head + '.' + claims).encode(), ec.ECDSA(hashes.SHA256()))
        self.assertEqual(web_push.public_key(self.accounts), key)  # Created once, then reused.

    def test_settings_are_validated_and_kept_per_account(self):
        self.assertEqual(web_push.account(self.accounts, self.alice)['settings'], web_push.DEFAULTS)
        chosen = {**web_push.DEFAULTS, 'chat': False, 'lead': 30}
        web_push.settings(self.accounts, self.alice, chosen)
        self.assertEqual(web_push.account(self.accounts, self.alice)['settings'], chosen)
        self.assertEqual(web_push.account(self.accounts, self.bob)['settings'], web_push.DEFAULTS)
        for bad in ({**chosen, 'lead': 7}, {**chosen, 'lead': True}, {**chosen, 'chat': 'no'}, {**chosen, 'extra': True}, {'chat': False}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                web_push.settings(self.accounts, self.alice, bad)

    def test_a_shared_device_belongs_to_the_account_that_subscribed_last(self):
        _, subscription = browser()
        web_push.subscribe(self.accounts, self.alice, subscription)
        web_push.subscribe(self.accounts, self.alice, subscription)
        self.assertEqual(len(web_push.account(self.accounts, self.alice)['subscriptions']), 1)
        web_push.subscribe(self.accounts, self.bob, subscription)
        self.assertEqual(web_push.account(self.accounts, self.alice)['subscriptions'], [])
        self.assertEqual(len(web_push.account(self.accounts, self.bob)['subscriptions']), 1)
        web_push.unsubscribe(self.accounts, self.bob, ENDPOINT)
        self.assertEqual(web_push.account(self.accounts, self.bob)['subscriptions'], [])

    def test_delivery_respects_each_kind_and_forgets_expired_devices(self):
        private, subscription = browser()
        web_push.subscribe(self.accounts, self.alice, subscription)
        web_push.subscribe(self.accounts, self.alice, {**subscription, 'endpoint': ENDPOINT + '-old'})
        sent = []
        def post(request):
            sent.append(request)
            return 410 if request.full_url.endswith('-old') else 201
        with patch.object(web_push, 'post', post):
            self.assertEqual(web_push.send(self.accounts, self.alice, {'title': 'Ready', 'url': '/'}, kind='briefing',
                                           ttl=60, subject='https://gm.example.test'), 1)
            web_push.settings(self.accounts, self.alice, {**web_push.DEFAULTS, 'briefing': False})
            self.assertEqual(web_push.send(self.accounts, self.alice, {'title': 'Ready'}, kind='briefing', ttl=60, subject='x'), 0)
        self.assertEqual([item['endpoint'] for item in web_push.account(self.accounts, self.alice)['subscriptions']], [ENDPOINT])
        request = next(item for item in sent if item.full_url == ENDPOINT)
        self.assertEqual((request.get_header('Ttl'), request.get_header('Content-encoding')), ('60', 'aes128gcm'))
        self.assertEqual(json.loads(decrypt(private, subscription, request.data)), {'title': 'Ready', 'url': '/', 'kind': 'briefing'})

    def test_reminders_are_sent_once(self):
        self.assertTrue(web_push.remembered(self.accounts, self.alice, 'event@1'))
        self.assertFalse(web_push.remembered(self.accounts, self.alice, 'event@1'))
        self.assertTrue(web_push.remembered(self.accounts, self.bob, 'event@1'))


if __name__ == '__main__':
    unittest.main()
