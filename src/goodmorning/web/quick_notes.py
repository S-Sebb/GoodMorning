"""Quick notes from the phone's sticky-note widget: saved word for word, sorted only on request.

A note's text is user content, never instructions. Sorting sends unsorted and edited notes to a
new Secretary conversation; `sorted_text` keeps the text Aria last saw, so a later edit shows as
changed and the next sort includes it.
"""
import contextlib
import datetime as dt
import re
import sqlite3
import threading
import time
from zoneinfo import ZoneInfo

from . import language as ui

NAME = 'quick-notes.sqlite'
MAX_TEXT = 3000
LIST_LIMIT = 100
# Room for the heading, labels and an edited note's earlier words within the 8,000-character chat limit.
BATCH_LIMIT = 7000
BEFORE_LIMIT = 300
SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY, text TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
    revision INTEGER NOT NULL, sorted_text TEXT, sorted_at REAL, sort_chat TEXT);
"""
HEADING = 'Quick notes to sort'


def note_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('Invalid note')
    return value


def note_text(value):
    if not isinstance(value, str) or len(value) > MAX_TEXT or '\x00' in value:
        raise ValueError(f'Use a note of up to {MAX_TEXT:,} characters')
    return value.strip()


class Notes:
    def __init__(self, runtime):
        path = runtime / NAME
        if path.is_symlink():
            raise ValueError('Unsafe notes store')
        self.path = path
        self.lock = threading.Lock()

    @contextlib.contextmanager
    def db(self):
        new = not self.path.exists()
        db = sqlite3.connect(self.path, timeout=10)
        try:
            if new:
                self.path.chmod(0o600)
            db.row_factory = sqlite3.Row
            db.executescript(SCHEMA)
            with db:
                yield db
        finally:
            db.close()

    def save(self, body):
        """Creates or replaces one note; the phone names it, so a retried save never duplicates it.
        Empty text deletes the note; what an earlier sort saved from it stays."""
        if not isinstance(body, dict) or set(body) != {'id', 'text', 'created'}:
            raise ValueError('Invalid note')
        identifier, text, created = note_id(body['id']), note_text(body['text']), body['created']
        now = time.time()
        if type(created) not in (int, float) or not 0 < created <= now * 1000 + 86_400_000:
            raise ValueError('Invalid note time')
        with self.lock, self.db() as db:
            if not text:
                db.execute('DELETE FROM notes WHERE id=?', (identifier,))
                return {'id': identifier, 'deleted': True}
            row = db.execute('SELECT text FROM notes WHERE id=?', (identifier,)).fetchone()
            if row is None:
                db.execute('INSERT INTO notes (id,text,created,updated,revision) VALUES (?,?,?,?,1)',
                           (identifier, text, created / 1000, now))
            elif row['text'] != text:
                db.execute('UPDATE notes SET text=?,updated=?,revision=revision+1 WHERE id=?', (text, now, identifier))
        return {'id': identifier, 'deleted': False}

    def listing(self, chat_state):
        """The newest notes with their sorting state; chat_state(id) reads a sort conversation's state."""
        with self.lock, self.db() as db:
            rows = db.execute('SELECT * FROM notes ORDER BY created DESC LIMIT ?', (LIST_LIMIT,)).fetchall()
            total = db.execute('SELECT count(*) FROM notes').fetchone()[0]
            pending = db.execute('SELECT count(*) FROM notes WHERE sorted_text IS NULL OR text!=sorted_text').fetchone()[0]
        states = {}
        notes = []
        for row in rows:
            if row['sorted_text'] is None:
                state = 'unsorted'
            elif row['text'] != row['sorted_text']:
                state = 'changed'
            else:
                if row['sort_chat'] not in states:
                    states[row['sort_chat']] = chat_state(row['sort_chat'])
                state = {'starting': 'sorting', 'running': 'sorting', 'waiting': 'question', 'idle': 'sorted'}.get(states[row['sort_chat']], 'check')
            notes.append({'id': row['id'], 'text': row['text'], 'created': int(row['created'] * 1000),
                          'state': state, 'chat': row['sort_chat']})
        return {'notes': notes, 'total': total, 'pending': pending}

    def batch(self, zone):
        """The next sorting message: unsorted and edited notes, oldest first, as many as fit."""
        with self.lock, self.db() as db:
            rows = db.execute('SELECT * FROM notes WHERE sorted_text IS NULL OR text!=sorted_text ORDER BY created').fetchall()
        parts, chosen, size = [], [], 0
        for row in rows:
            when = written(row['created'], zone)
            if row['sorted_text'] is None:
                part = f"{len(parts) + 1}. {when}\n{row['text']}"
            else:
                before = row['sorted_text'] if len(row['sorted_text']) <= BEFORE_LIMIT else row['sorted_text'][:BEFORE_LIMIT - 1] + '…'
                part = (f"{len(parts) + 1}. {when} · " + ui.text('Edited after you sorted it') + '\n'
                        + ui.text('Now: {text}', text=row['text']) + '\n' + ui.text('Before: {text}', text=before))
            if parts and size + len(part) > BATCH_LIMIT:
                break
            parts.append(part)
            chosen.append({'id': row['id'], 'text': row['text']})
            size += len(part) + 2
        if not parts:
            return {'text': None, 'notes': [], 'remaining': 0}
        intro = ui.text('I jotted these down on my phone. Please save each one as whatever fits and ask me about anything unclear.')
        return {'text': ui.text(HEADING) + '\n\n' + intro + '\n\n' + '\n\n'.join(parts),
                'notes': chosen, 'remaining': len(rows) - len(parts)}

    def mark(self, body):
        """Records that a sort conversation received these notes, as they were worded then."""
        if not isinstance(body, dict) or set(body) != {'chat', 'notes'} or not isinstance(body['notes'], list):
            raise ValueError('Invalid sort')
        chat = note_id(body['chat'])
        now = time.time()
        with self.lock, self.db() as db:
            for note in body['notes']:
                if not isinstance(note, dict) or set(note) != {'id', 'text'} or not isinstance(note['text'], str):
                    raise ValueError('Invalid sort')
                db.execute('UPDATE notes SET sorted_text=?,sorted_at=?,sort_chat=? WHERE id=?',
                           (note['text'], now, chat, note_id(note['id'])))
        return {'chat': chat}


def written(created, zone):
    """When the note was written, in the account's timezone and the website language."""
    moment = dt.datetime.fromtimestamp(created, ZoneInfo(zone) if zone else dt.timezone.utc)
    if ui.current() == 'zh-CN':
        return f'{moment.month}月{moment.day}日 {moment:%H:%M}'
    return f'{moment:%a} {moment.day} {moment:%b}, {moment:%H:%M}'
