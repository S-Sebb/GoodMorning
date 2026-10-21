"""Web Push notifications: per-account subscriptions and settings, VAPID signing and RFC 8291 encryption.

Everything is stored in the encrypted account database's metadata table: the server's VAPID key
under ``push-vapid`` and each account's settings and subscriptions under ``push:<account>``.
"""
import base64
import hashlib
import hmac
import json
import os
import struct
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KINDS = ('briefing', 'waiting', 'chat', 'events')
LEADS = (5, 10, 15, 30, 60)
DEFAULTS = {'briefing': True, 'waiting': True, 'chat': True, 'events': True, 'lead': 15}
MAX_SUBSCRIPTIONS = 10
# Only browser push services, so a subscription can never make the server contact other hosts.
PUSH_HOSTS = ('fcm.googleapis.com', 'push.services.mozilla.com', 'web.push.apple.com', 'notify.windows.com')


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def unb64(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _raw(public_key):
    return public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _metadata(db, key, default):
    row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def _store(db, key, value):
    db.execute('INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
               (key, json.dumps(value, separators=(',', ':'))))


def vapid_key(accounts):
    """The server's signing key, created once."""
    with accounts.db() as db:
        row = db.execute('SELECT value FROM metadata WHERE key=?', ('push-vapid',)).fetchone()
        if not row:
            pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
            db.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)', ('push-vapid', pem))
            row = db.execute('SELECT value FROM metadata WHERE key=?', ('push-vapid',)).fetchone()
    return serialization.load_pem_private_key(row[0], password=None)


def public_key(accounts):
    return b64(_raw(vapid_key(accounts).public_key()))


def account(accounts, user):
    with accounts.db() as db:
        value = _metadata(db, 'push:' + user, {})
    return {'settings': {**DEFAULTS, **value.get('settings', {})}, 'subscriptions': value.get('subscriptions', [])}


def settings(accounts, user, replacement):
    if set(replacement) != set(DEFAULTS) or any(type(replacement[kind]) is not bool for kind in KINDS) \
            or replacement['lead'] not in LEADS or type(replacement['lead']) is not int:
        raise ValueError('Invalid notification settings')
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        value = _metadata(db, 'push:' + user, {})
        _store(db, 'push:' + user, {**value, 'settings': replacement})
    return replacement


def subscription(value):
    """A browser PushSubscription.toJSON(), reduced to what sending needs."""
    if not isinstance(value, dict) or not isinstance(value.get('keys'), dict):
        raise ValueError('Invalid push subscription')
    endpoint, keys = value.get('endpoint'), value['keys']
    parts = urlsplit(endpoint) if isinstance(endpoint, str) and len(endpoint) <= 1024 else None
    host = parts.hostname if parts else None
    if not parts or parts.scheme != 'https' or parts.port not in (None, 443) or parts.username or not host \
            or not any(host == known or host.endswith('.' + known) for known in PUSH_HOSTS):
        raise ValueError('Unsupported push service')
    try:
        p256dh, auth = unb64(keys['p256dh']), unb64(keys['auth'])
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), p256dh)
    except (KeyError, TypeError, ValueError):
        raise ValueError('Invalid push subscription')
    if len(auth) != 16:
        raise ValueError('Invalid push subscription')
    return {'endpoint': endpoint, 'p256dh': keys['p256dh'], 'auth': keys['auth']}


def subscribe(accounts, user, value):
    entry = subscription(value)
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        # A shared device now belongs to whoever signed in last; earlier accounts stop reaching it.
        for key, raw in db.execute("SELECT key, value FROM metadata WHERE key LIKE 'push:%'").fetchall():
            other = json.loads(raw)
            kept = [item for item in other.get('subscriptions', []) if item['endpoint'] != entry['endpoint']]
            if key != 'push:' + user and len(kept) != len(other.get('subscriptions', [])):
                _store(db, key, {**other, 'subscriptions': kept})
        value = _metadata(db, 'push:' + user, {})
        kept = [item for item in value.get('subscriptions', []) if item['endpoint'] != entry['endpoint']]
        _store(db, 'push:' + user, {**value, 'subscriptions': (kept + [entry])[-MAX_SUBSCRIPTIONS:]})


def unsubscribe(accounts, user, endpoint):
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        value = _metadata(db, 'push:' + user, {})
        _store(db, 'push:' + user, {**value, 'subscriptions': [item for item in value.get('subscriptions', [])
                                                               if item['endpoint'] != endpoint]})


def remembered(accounts, user, key):
    """Records a sent reminder; False when it was already sent."""
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        sent = _metadata(db, 'push-reminded:' + user, [])
        if key in sent:
            return False
        _store(db, 'push-reminded:' + user, (sent + [key])[-200:])
        return True


def _hkdf(salt, ikm, info, length):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b'\x01', hashlib.sha256).digest()[:length]


def encrypt(entry, payload):
    """RFC 8291 aes128gcm: only the subscribing browser can read the payload."""
    receiver = unb64(entry['p256dh'])
    private = ec.generate_private_key(ec.SECP256R1())
    sender = _raw(private.public_key())
    secret = private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), receiver))
    ikm = _hkdf(unb64(entry['auth']), secret, b'WebPush: info\x00' + receiver + sender, 32)
    salt = os.urandom(16)
    key = _hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = _hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
    return salt + struct.pack('!IB', 4096, len(sender)) + sender + AESGCM(key).encrypt(nonce, payload + b'\x02', None)


def vapid(accounts, endpoint, subject):
    """RFC 8292 authorization for one push service, valid for twelve hours."""
    parts = urlsplit(endpoint)
    key = vapid_key(accounts)
    header = b64(b'{"typ":"JWT","alg":"ES256"}')
    claims = b64(json.dumps({'aud': parts.scheme + '://' + parts.netloc, 'exp': int(time.time()) + 12 * 3600,
                             'sub': subject}, separators=(',', ':')).encode())
    r, s = decode_dss_signature(key.sign((header + '.' + claims).encode(), ec.ECDSA(hashes.SHA256())))
    token = header + '.' + claims + '.' + b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))
    return 'vapid t=' + token + ', k=' + b64(_raw(key.public_key()))


def post(request):
    """Returns the push service's status; separate so tests can replace the network."""
    try:
        with build_opener().open(request, timeout=10) as response:
            return response.status
    except HTTPError as error:
        return error.code
    except (URLError, OSError):
        return None


def send(accounts, user, message, *, kind, ttl, urgency='normal', subject):
    """Encrypts message for each of the account's devices when it allows this kind."""
    state = account(accounts, user)
    if not state['settings'].get(kind):
        return 0
    payload = json.dumps({**message, 'kind': kind}, ensure_ascii=False, separators=(',', ':')).encode()
    delivered = 0
    for entry in state['subscriptions']:
        request = Request(entry['endpoint'], data=encrypt(entry, payload), method='POST', headers={
            'Authorization': vapid(accounts, entry['endpoint'], subject), 'TTL': str(int(ttl)),
            'Urgency': urgency, 'Content-Encoding': 'aes128gcm', 'Content-Type': 'application/octet-stream'})
        status = post(request)
        if status in (404, 410):
            unsubscribe(accounts, user, entry['endpoint'])  # The browser dropped this subscription.
        elif status is not None and status < 300:
            delivered += 1
    return delivered
