"""Friendships between hosted accounts and what each owner shares with each friend.

A request names a username; the friendship exists only after the other person accepts. A declined
request disappears for the recipient but still shows as waiting to the sender. Rows hold
immutable account IDs, so renames keep friendships. Each direction keeps its own sharing choices,
which start empty and are deleted with the friendship.
"""
import json
import time

from .briefing_accounts import Denied, Refused, username

SECTIONS = ('schedule', 'todos', 'stocks', 'anime', 'games')
# Which shared sections each page can show in its friend version.
PAGE_SECTIONS = {'schedule': ('schedule', 'todos'), 'gm': ('schedule', 'todos'), 'gn': ('stocks', 'anime', 'games')}
MAX_FRIENDS = 100
MAX_OUTGOING = 50


def sections(value):
    if not isinstance(value, list) or any(item not in SECTIONS for item in value):
        raise Refused('Choose from the offered sections')
    return [item for item in SECTIONS if item in value]


def _named(db, name):
    try:
        name = username(name)
    except ValueError:
        name = None
    row = name and db.execute('SELECT id FROM users WHERE name=? AND enabled=1', (name,)).fetchone()
    return row['id'] if row else None


def _friend(db, user, name):
    """The friend called name, looked up among this user's friends only."""
    row = db.execute('SELECT u.id FROM friends f JOIN users u ON u.id=f.friend WHERE f.owner=? AND u.name=?',
                     (user, str(name)[:64].lower())).fetchone()
    if not row:
        raise Refused('That person is not on your friends list')
    return row['id']


def _befriend(db, user, other):
    now = time.time()
    db.execute('DELETE FROM friend_requests WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?)', (user, other, other, user))
    db.execute('INSERT OR IGNORE INTO friends VALUES (?,?,?,?)', (user, other, '[]', now))
    db.execute('INSERT OR IGNORE INTO friends VALUES (?,?,?,?)', (other, user, '[]', now))


def overview(accounts, user):
    with accounts.db() as db:
        me = db.execute('SELECT name FROM users WHERE id=?', (user,)).fetchone()['name']
        friends = [{'name': row['name'], 'sharing': json.loads(row['sections']), 'shared': json.loads(row['theirs'])} for row in db.execute(
            '''SELECT u.name, f.sections, back.sections AS theirs FROM friends f JOIN users u ON u.id=f.friend
               JOIN friends back ON back.owner=f.friend AND back.friend=f.owner WHERE f.owner=? ORDER BY u.name''', (user,))]
        incoming = [row['name'] for row in db.execute(
            'SELECT u.name FROM friend_requests r JOIN users u ON u.id=r.sender WHERE r.recipient=? AND NOT r.declined ORDER BY r.created', (user,))]
        outgoing = [row['name'] for row in db.execute(
            'SELECT u.name FROM friend_requests r JOIN users u ON u.id=r.recipient WHERE r.sender=? ORDER BY r.created', (user,))]
    return {'name': me, 'friends': friends, 'incoming': incoming, 'outgoing': outgoing, 'sections': list(SECTIONS)}


def request(accounts, user, name):
    """Returns 'sent', or 'friends' when they had already asked you."""
    accounts.limit([('friend-request:' + user, 20)])
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        other = _named(db, name)
        if not other:
            raise Refused('No account has that username. Check the spelling.')
        if other == user:
            raise Refused('That is your own username')
        if db.execute('SELECT 1 FROM friends WHERE owner=? AND friend=?', (user, other)).fetchone():
            raise Refused('You are already friends')
        if db.execute('SELECT COUNT(*) FROM friends WHERE owner=?', (user,)).fetchone()[0] >= MAX_FRIENDS:
            raise Refused('Your friends list is full')
        if db.execute('SELECT 1 FROM friend_requests WHERE sender=? AND recipient=?', (other, user)).fetchone():
            _befriend(db, user, other)
            return 'friends'
        if db.execute('SELECT COUNT(*) FROM friend_requests WHERE sender=?', (user,)).fetchone()[0] >= MAX_OUTGOING:
            raise Refused('Too many requests are waiting. Cancel some first.')
        db.execute('INSERT OR IGNORE INTO friend_requests(sender, recipient, created) VALUES (?,?,?)', (user, other, time.time()))
        return 'sent'


def answer(accounts, user, name, accept):
    """Accept or silently decline a request someone sent to this user. Accepting shares nothing yet."""
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        other = db.execute('SELECT r.sender FROM friend_requests r JOIN users u ON u.id=r.sender WHERE r.recipient=? AND u.name=? AND NOT r.declined',
                           (user, str(name)[:64].lower())).fetchone()
        if not other:
            raise Refused('That request is no longer waiting')
        if not accept:
            db.execute('UPDATE friend_requests SET declined=1 WHERE sender=? AND recipient=?', (other['sender'], user))
            return
        if db.execute('SELECT COUNT(*) FROM friends WHERE owner=?', (user,)).fetchone()[0] >= MAX_FRIENDS:
            raise Refused('Your friends list is full')
        _befriend(db, user, other['sender'])


def cancel(accounts, user, name):
    with accounts.db() as db:
        db.execute('DELETE FROM friend_requests WHERE sender=? AND recipient=(SELECT id FROM users WHERE name=?)',
                   (user, str(name)[:64].lower()))


def remove(accounts, user, name):
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        other = _friend(db, user, name)
        db.execute('DELETE FROM friends WHERE (owner=? AND friend=?) OR (owner=? AND friend=?)', (user, other, other, user))


def share(accounts, user, name, shared):
    shared = sections(shared)
    with accounts.db() as db:
        db.execute('BEGIN IMMEDIATE')
        other = _friend(db, user, name)
        db.execute('UPDATE friends SET sections=? WHERE owner=? AND friend=?', (json.dumps(shared), user, other))
    return shared


def shared_with(accounts, viewer, name):
    """The friend's ID, current name and the sections they share with viewer; Denied for anyone else."""
    with accounts.db() as db:
        row = db.execute('''SELECT u.id, u.name, f.sections FROM friends f JOIN users u ON u.id=f.owner
            WHERE f.friend=? AND u.name=? AND u.enabled=1''', (viewer, str(name)[:64].lower())).fetchone()
    if not row:
        raise Denied('Not found')
    return row['id'], row['name'], json.loads(row['sections'])


def sharing_with(accounts, viewer):
    """[(name, sections)] for every friend who shares something with viewer, by name."""
    with accounts.db() as db:
        rows = db.execute('''SELECT u.name, f.sections FROM friends f JOIN users u ON u.id=f.owner
            WHERE f.friend=? AND u.enabled=1 AND f.sections!='[]' ORDER BY u.name''', (viewer,)).fetchall()
    return [(row['name'], json.loads(row['sections'])) for row in rows]
