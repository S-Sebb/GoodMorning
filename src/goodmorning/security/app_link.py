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


def verify(accounts, token):
    """The account a token belongs to, or None."""
    if not isinstance(token, str) or not token.startswith('gma_') or len(token) > 100:
        return None
    digest = _hash(token)
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        for key, raw in db.execute("SELECT key, value FROM metadata WHERE key LIKE 'app-links:%'").fetchall():
            links = json.loads(raw)
            for entry in links:
                if secrets.compare_digest(entry['hash'], digest):
                    if not entry['used'] or time.time() - entry['used'] > 3600:
                        entry['used'] = time.time()
                        _store(db, key, links)
                    return key.removeprefix('app-links:')
    return None


def links(accounts, user):
    with accounts.db() as db:
        return [{key: entry[key] for key in ('id', 'label', 'created', 'used')}
                for entry in _metadata(db, 'app-links:' + user, [])]


def unlink(accounts, user, identifier):
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        kept = [entry for entry in _metadata(db, 'app-links:' + user, []) if entry['id'] != identifier]
        _store(db, 'app-links:' + user, kept)


def record(accounts, user, kind, message):
    """Keeps recent status notifications for linked phones that cannot receive Web Push."""
    if not web_push.account(accounts, user)['settings'].get(kind):
        return
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if not _metadata(db, 'app-links:' + user, []):
            return
        outbox = _metadata(db, 'app-outbox:' + user, [])
        sequence = (outbox[-1]['seq'] if outbox else 0) + 1
        entry = {'seq': sequence, 'kind': kind, 'at': time.time(), **{key: message[key] for key in ('title', 'body', 'url', 'tag')}}
        _store(db, 'app-outbox:' + user, (outbox + [entry])[-OUTBOX:])


def outbox(accounts, user, after):
    with accounts.db() as db:
        return [entry for entry in _metadata(db, 'app-outbox:' + user, []) if entry['seq'] > after]
