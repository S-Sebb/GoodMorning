"""Private account/session store. Production database must live on an encrypted mount."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time

COOKIE = '__Host-GoodMorning'
PASSWORD_MIN = 6
PASSWORD_MAX = 32
PASSWORD_RULE = 'Use 6–32 characters, including at least one letter and one digit. Symbols are optional.'
SCRYPT_N = 1 << 17
IDLE_SECONDS = 1800
SESSION_SECONDS = 43200
REMEMBER_SECONDS = 60 * 24 * 60 * 60


class Denied(ValueError):
    pass


class Limited(Denied):
    pass


def username(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}', value):
        raise ValueError('Usernames need 3–40 ASCII letters, digits, dots, underscores or hyphens')
    return value.lower()


def password(value):
    if (not isinstance(value, str) or not PASSWORD_MIN <= len(value) <= PASSWORD_MAX or '\x00' in value
            or not any(char.isalpha() for char in value) or not any(char.isdecimal() for char in value)):
        raise ValueError(PASSWORD_RULE)
    return value


def encrypted_mount(path):
    """Fail closed, including after an unexpected unmount; do not trust a marker file."""
    path = Path(path).absolute()
    if path.resolve() != path or not path.is_dir():
        raise ValueError('An absolute, non-symlink encrypted mount is required')
    # Mountpoints are provisioned with restricted ASCII IDs, without whitespace.
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        before, after = line.split(' - ', 1)
        if before.split()[4] == str(path) and after.split()[0] == 'fuse.gocryptfs':
            return path
    raise ValueError('Encrypted volume is not mounted; refusing plaintext storage')


class Accounts:
    def __init__(self, directory, *, testing=False, n=SCRYPT_N, now=time.time):
        self.directory = Path(directory).absolute()
        self.testing, self.n, self.now = testing, n, now
        if not testing and n != SCRYPT_N:
            raise ValueError('Production password cost cannot be reduced')
        self.path = self.directory/'accounts.sqlite'
        self.check()
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, salt BLOB NOT NULL,
                    digest BLOB NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                    temporary INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS sessions (
                    hash TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                    revision INTEGER, csrf TEXT NOT NULL, host TEXT NOT NULL,
                    created REAL NOT NULL, touched REAL NOT NULL, expires REAL NOT NULL,
                    remembered INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS attempts (
                    key TEXT PRIMARY KEY, started REAL NOT NULL, count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value BLOB NOT NULL);
            ''')
            db.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)',('rate_salt', secrets.token_bytes(32)))
            self.rate_salt = db.execute('SELECT value FROM metadata WHERE key=?',('rate_salt',)).fetchone()[0]
        os.chmod(self.path,0o600)
        self.dummy_salt = secrets.token_bytes(32)

    def check(self):
        if not self.testing:
            encrypted_mount(self.directory)
        if self.path.is_symlink():
            raise ValueError('Account database cannot be a symlink')

    @contextmanager
    def db(self):
        self.check()
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def derive(self, value, salt):
        return hashlib.scrypt(value.encode(),salt=salt,n=self.n,r=8,p=1,dklen=64,maxmem=256*1024*1024)

    def issue(self, db, host, user=None, *, remember=False):
        now = self.now()
        token, csrf = secrets.token_urlsafe(32), secrets.token_hex(32)
        remember = bool(user) and remember
        expiry = now + (REMEMBER_SECONDS if remember else SESSION_SECONDS if user else 600)
        db.execute('DELETE FROM sessions WHERE expires<=? OR (remembered=0 AND touched<=?)',(now,now-IDLE_SECONDS))
        db.execute('INSERT INTO sessions(hash,user_id,revision,csrf,host,created,touched,expires,remembered) VALUES (?,?,?,?,?,?,?,?,?)',
                    (hashlib.sha256(token.encode()).hexdigest(),user['id'] if user else None,
                     user['revision'] if user else None,csrf,host,now,now,expiry,int(remember)))
        return token, csrf

    def anonymous(self, host):
        with self.db() as db:
            return self.issue(db,host)

    def session(self, token, host):
        if not isinstance(token,str) or not re.fullmatch('[A-Za-z0-9_-]{43}',token):
            raise Denied('Login required')
        digest = hashlib.sha256(token.encode()).hexdigest()
        now = self.now()
        with self.db() as db:
            row = db.execute('''SELECT s.*,u.name,u.temporary,u.enabled,u.revision AS current_revision
                FROM sessions s LEFT JOIN users u ON u.id=s.user_id WHERE s.hash=?''',(digest,)).fetchone()
            if not row or row['host'] != host or row['expires'] <= now or (not row['remembered'] and row['touched'] <= now-IDLE_SECONDS):
                raise Denied('Login required')
            if row['user_id'] and (not row['enabled'] or row['revision'] != row['current_revision']):
                raise Denied('Login required')
            db.execute('UPDATE sessions SET touched=? WHERE hash=?',(now,digest))
            return dict(row)

    def limit(self, keys):
        now = self.now()
        blocked = False
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE started<?',(now-900,))
            for value, maximum in keys:
                key = hmac.new(self.rate_salt,value.encode(),hashlib.sha256).hexdigest()
                row = db.execute('SELECT count FROM attempts WHERE key=?',(key,)).fetchone()
                count = row['count'] if row else 0
                if count >= maximum:
                    blocked = True
                db.execute('INSERT INTO attempts VALUES (?,?,1) ON CONFLICT(key) DO UPDATE SET count=count+1',(key,now))
        if blocked:
            raise Limited('Too many attempts. Try again later.')

    def login(self, name, secret, host, address, prelogin, *, remember=False):
        if type(remember) is not bool:
            raise ValueError('Remember login must be true or false')
        # Rate-limit even unknown names, with no plaintext username/IP in counters.
        safe_name = str(name)[:128].lower()
        self.limit([('name:'+safe_name,5),('ip:'+address,30)])
        try:
            password(secret)
            valid = True
        except ValueError:
            valid = False
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM users WHERE name=?',(safe_name,)).fetchone()
            computed = self.derive(secret if valid else '',row['salt'] if row else self.dummy_salt)
            if not row or not valid or not row['enabled'] or not hmac.compare_digest(computed,row['digest']):
                raise Denied('Username or password is incorrect')
            # Rotation prevents an anonymous token being promoted or fixed by an attacker.
            db.execute('DELETE FROM sessions WHERE hash=?',(prelogin['hash'],))
            token, csrf = self.issue(db,host,row,remember=remember)
            return token,csrf,bool(row['temporary'])

    def change_password(self, session, current, replacement, address):
        self.limit([('reset:'+session['user_id'],5),('reset-ip:'+address,15)])
        password(replacement)
        try:
            password(current)
        except ValueError:
            raise Denied('Current password is incorrect') from None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone()
            if not row or row['revision'] != session['revision'] or not hmac.compare_digest(self.derive(current,row['salt']),row['digest']):
                raise Denied('Current password is incorrect')
            if hmac.compare_digest(current.encode(),replacement.encode()):
                raise ValueError('Choose a different permanent password')
            salt = secrets.token_bytes(32)
            db.execute('UPDATE users SET salt=?,digest=?,revision=revision+1,temporary=0 WHERE id=?',
                       (salt,self.derive(replacement,salt),row['id']))
            db.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
            updated = db.execute('SELECT * FROM users WHERE id=?',(row['id'],)).fetchone()
            return self.issue(db,session['host'],updated,remember=bool(session['remembered']))

    def logout(self, session):
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE hash=?',(session['hash'],))

    def website_language(self, identifier, replacement=None):
        from goodmorning.web.language import language
        with self.db() as db:
            key='website-language:'+identifier
            if replacement is not None:
                replacement=language(replacement)
                db.execute('INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,replacement))
                return replacement
            row=db.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()
            return language(row[0]) if row else None

    def website_model(self, identifier, replacement=None):
        from goodmorning.web.models import model
        with self.db() as db:
            key='website-model:'+identifier
            if replacement is not None:
                replacement=model(replacement)
                db.execute('INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,replacement))
                return replacement
            row=db.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()
            return model(row[0]) if row else None

    def website_color_schemes(self, identifier, replacement=None):
        from goodmorning.web.color_schemes import saved, validate
        with self.db() as db:
            key = 'website-color-schemes:' + identifier
            if replacement is not None:
                replacement = validate(replacement)
                db.execute('INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           (key, json.dumps(replacement)))
                return replacement
            row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            return saved(json.loads(row[0])) if row else None

    def create(self, name, secret):
        name,secret = username(name),password(secret)
        identifier,salt = secrets.token_hex(16),secrets.token_bytes(32)
        with self.db() as db:
            db.execute('INSERT INTO users(id,name,salt,digest,temporary) VALUES (?,?,?,?,1)',
                       (identifier,name,salt,self.derive(secret,salt)))
        return identifier

    def release_seen(self, identifier, replacement=None):
        from goodmorning.web.release import acknowledge_version
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            key = 'release-seen:' + identifier
            row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            seen = row[0] if row else None
            if replacement is not None:
                seen = acknowledge_version(replacement, seen)
                db.execute('INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, seen))
            return seen

    def check_password(self, name, secret):
        """Read-only SSH-admin diagnostic; never an unauthenticated website route."""
        name = username(name)
        password(secret)
        with self.db() as db:
            row=db.execute('SELECT salt,digest FROM users WHERE name=?',(name,)).fetchone()
            if not row:
                raise ValueError('Unknown account')
            return hmac.compare_digest(self.derive(secret,row['salt']),row['digest'])

    def administer(self, name, *, new_name=None, temporary=None, enabled=None):
        """SSH-only operations: no equivalent public route exists."""
        name = username(name)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM users WHERE name=?',(name,)).fetchone()
            if not row:
                raise ValueError('Unknown account')
            if new_name is not None:
                db.execute('UPDATE users SET name=? WHERE id=?',(username(new_name),row['id']))
            if temporary is not None:
                salt = secrets.token_bytes(32)
                db.execute('UPDATE users SET salt=?,digest=?,temporary=1 WHERE id=?',
                           (salt,self.derive(password(temporary),salt),row['id']))
            if enabled is not None:
                db.execute('UPDATE users SET enabled=? WHERE id=?',(int(enabled),row['id']))
            db.execute('UPDATE users SET revision=revision+1 WHERE id=?',(row['id'],))
            db.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
            return row['id']
