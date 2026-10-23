"""Linking the Android app to an account: pairing codes, revocable app tokens and a notification outbox.

The app asks for a pairing code, the signed-in owner types that code into Settings, and the app then
claims a token with the pairing secret only it holds. The code alone never yields a token, and nothing
secret travels in a URL. Tokens are stored as SHA-256 hashes in the encrypted account metadata.
"""
import hashlib
import json
import re
import secrets
import time

from . import web_push

ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'  # No 0/O, 1/I/L: easy to read and type.
PAIR_SECONDS = 600
MAX_LINKS = 10
OUTBOX = 30
INVALID_CODE = 'That code is not valid. Check it, or show a new code in the app.'


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _metadata(db, key, default):
    row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def _store(db, key, value):
    db.execute('INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
               (key, json.dumps(value, separators=(',', ':'))))


def label(value):
    """The phone's name as the app reports it, shown in Settings."""
    if not isinstance(value, str) or not 0 < len(value.strip()) <= 60 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid phone name')
    return ' '.join(value.split())


def pair(accounts, name):
    """A short code for the owner to type and a secret the app keeps to claim its token."""
    name = label(name)
    code = ''.join(secrets.choice(ALPHABET) for _ in range(8))
    secret = secrets.token_urlsafe(32)
    now = time.time()
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        for key, raw in db.execute("SELECT key, value FROM metadata WHERE key LIKE 'app-pair:%'").fetchall():
            if json.loads(raw)['expires'] < now:
                db.execute('DELETE FROM metadata WHERE key=?', (key,))
        _store(db, 'app-pair:' + _hash(code), {'secret': _hash(secret), 'label': name, 'expires': now + PAIR_SECONDS})
    return {'code': code[:4] + '-' + code[4:], 'secret': secret, 'expires': PAIR_SECONDS}


def confirm(accounts, user, typed):
    """The signed-in owner vouches for the phone that shows this code."""
    code = re.sub(r'[\s-]', '', typed.upper()) if isinstance(typed, str) else ''
    if len(code) != 8 or any(c not in ALPHABET for c in code):
        raise ValueError(INVALID_CODE)
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        key = 'app-pair:' + _hash(code)
        value = _metadata(db, key, None)
        if not value or value['expires'] < time.time() or value.get('user'):
            raise ValueError(INVALID_CODE)
        _store(db, key, {**value, 'user': user})
    return value['label']


def claim(accounts, secret):
    """None while the code waits for the owner; then the token, exactly once."""
    if not isinstance(secret, str) or len(secret) > 100:
        raise ValueError('Unknown pairing')
    digest = _hash(secret)
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        for key, raw in db.execute("SELECT key, value FROM metadata WHERE key LIKE 'app-pair:%'").fetchall():
            value = json.loads(raw)
            if not secrets.compare_digest(value['secret'], digest):
                continue
            if value['expires'] < time.time():
                db.execute('DELETE FROM metadata WHERE key=?', (key,))
                break
            if not value.get('user'):
                return None
            db.execute('DELETE FROM metadata WHERE key=?', (key,))
            token = 'gma_' + secrets.token_urlsafe(32)
            entry = {'id': secrets.token_hex(8), 'hash': _hash(token), 'label': value['label'], 'created': time.time(), 'used': None}
            links = _metadata(db, 'app-links:' + value['user'], [])
            _store(db, 'app-links:' + value['user'], (links + [entry])[-MAX_LINKS:])
            return {'token': token, 'id': entry['id']}
    raise ValueError('Unknown pairing')


def verify(accounts, token, notifies=None):
    """The account and link a token belongs to, or None. notifies records whether the phone posts
    notifications itself (no Web Push there), as the app reports it."""
    if not isinstance(token, str) or not token.startswith('gma_') or len(token) > 100:
        return None
    digest = _hash(token)
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        for key, raw in db.execute("SELECT key, value FROM metadata WHERE key LIKE 'app-links:%'").fetchall():
            links = json.loads(raw)
            for entry in links:
                if secrets.compare_digest(entry['hash'], digest):
                    stale = not entry['used'] or time.time() - entry['used'] > 3600
                    if stale or (notifies is not None and entry.get('notifies') != notifies):
                        entry['used'] = time.time()
                        if notifies and entry.get('notifies') is False:
                            # The app left Chrome; this phone keeps the choices it made there.
                            retired = web_push.retire(db, key.removeprefix('app-links:'), entry['id'])
                            if retired:
                                entry['settings'] = retired
                        if notifies is not None:
                            entry['notifies'] = notifies
                        _store(db, key, links)
                    return key.removeprefix('app-links:'), entry['id']
    return None


def choices(state, entry):
    """What one phone asked to hear about; phones linked before choices moved to devices start from the account's."""
    return {**state['settings'], **entry.get('settings', {})}


def links(accounts, user):
    state = web_push.account(accounts, user)
    with accounts.db() as db:
        return [{**{key: entry[key] for key in ('id', 'label', 'created', 'used')},
                 'notifies': bool(entry.get('notifies')), 'settings': choices(state, entry), 'appearance': entry.get('appearance')}
                for entry in _metadata(db, 'app-links:' + user, [])]


def settings(accounts, user, identifier, replacement):
    """Replaces one linked phone's notification choices."""
    replacement = web_push.validated(replacement)
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        entries = _metadata(db, 'app-links:' + user, [])
        if not any(entry['id'] == identifier for entry in entries):
            raise ValueError('This phone is no longer linked. Link it again in Account.')
        _store(db, 'app-links:' + user, [{**entry, 'settings': replacement} if entry['id'] == identifier else entry for entry in entries])
    return replacement


def appearance(accounts, user, identifier, replacement):
    """The color schemes chosen on this phone, for its widgets; False when it is not one of the account's links."""
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        entries = _metadata(db, 'app-links:' + user, [])
        if not any(entry['id'] == identifier for entry in entries):
            return False
        _store(db, 'app-links:' + user, [{**entry, 'appearance': replacement} if entry['id'] == identifier else entry for entry in entries])
    return True


def unlink(accounts, user, identifier):
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        kept = [entry for entry in _metadata(db, 'app-links:' + user, []) if entry['id'] != identifier]
        _store(db, 'app-links:' + user, kept)


def record(accounts, user, kind, message):
    """Keeps recent status notifications for linked phones that cannot receive Web Push; each phone
    reads only the kinds it chose."""
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if not _metadata(db, 'app-links:' + user, []):
            return
        outbox = _metadata(db, 'app-outbox:' + user, [])
        sequence = (outbox[-1]['seq'] if outbox else 0) + 1
        entry = {'seq': sequence, 'kind': kind, 'at': time.time(), **{key: message[key] for key in ('title', 'body', 'url', 'tag')}}
        _store(db, 'app-outbox:' + user, (outbox + [entry])[-OUTBOX:])


def outbox(accounts, user, after, chosen):
    with accounts.db() as db:
        return [entry for entry in _metadata(db, 'app-outbox:' + user, []) if entry['seq'] > after and chosen.get(entry['kind'])]
