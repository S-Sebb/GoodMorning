"""Secretary memory: one short note the secretary keeps about the user, like a friend who remembers.

The note has three parts and one entry per project the user works on; a project's name is its to-dos' project label.
The secretary rewrites the note in chat as it picks things up, and the evening briefing tidies it
with the day's chat messages and the patterns in recent check-ins and records. The About me page shows it and lets the user edit it, forget it all
or turn memory off. Unlike other records, forgotten text is deleted, not cancelled.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
import sqlite3
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

from goodmorning.briefings.briefing_day import briefing_day
from goodmorning.runtime_files import atomic_text, profile_fields, runtime_lock, secretary_path
from .inbox_store import encode

PARTS = ('life', 'likes', 'lately')
LENGTH = 4000  # The whole note with every project entry, about 1,200 tokens in every conversation.
PROJECTS, PROJECT, NAME = 8, 500, 160  # Projects kept, each entry's length, and a name's length (as a to-do's project label).
CHANGES = 30   # Recent chat sessions that changed the note, for the chat's memory marker.
MESSAGES, MESSAGE = 40, 500  # The newest user messages the evening tidy rereads, and each one's length.
DAYS, ACTIVITY, TITLE = 14, 80, 160  # Days of records the evening tidy reads for patterns, its newest lines, each title's length.


def path(runtime):
    target = Path(runtime) / 'memory.json'
    if target.is_symlink():
        raise ValueError('unsafe_path: memory must not be a symlink')
    return target


def load(runtime):
    target = path(runtime)
    if not target.exists():
        return {'enabled': True, 'revision': 0, 'note': dict.fromkeys(PARTS, ''), 'projects': [], 'changes': []}
    data = json.loads(target.read_text(encoding='utf-8'))
    data.setdefault('projects', [])  # A note saved before projects keeps none.
    return data


def key(name):
    """Project names match ignoring case and spacing."""
    return ' '.join(name.split()).casefold()


def find(entries, name):
    return next((entry for entry in entries if key(entry['name']) == key(name)), None)


def context(runtime):
    """What a conversation or briefing sees: the note, or only that memory is off."""
    data = load(runtime)
    if not data['enabled']:
        return {'enabled': False, 'revision': data['revision']}
    return {'enabled': True, 'revision': data['revision'], 'note': data['note'], 'projects': data['projects'],
            **({'updated': data['updated']} if 'updated' in data else {})}


def plain(label, text):
    if not isinstance(text, str) or any(ord(c) < 32 and c != '\n' for c in text):
        raise ValueError(f'invalid_input: {label} is plain text')
    return text.strip()


def project_name(name):
    if not isinstance(name, str) or not 0 < len(' '.join(name.split())) <= NAME or any(ord(c) < 32 and c not in ' \t' for c in name):
        raise ValueError(f'invalid_input: a project name is one line of 1-{NAME} characters, its to-dos\' project label')
    return ' '.join(name.split())


def checked(note):
    """The parts and the project entries a write changes; a project set to null is dropped."""
    if not isinstance(note, dict) or not note or set(note) - {*PARTS, 'projects'}:
        raise ValueError('invalid_input: supply a JSON object with any of life, likes, lately and projects')
    projects = note.get('projects', {})
    if not isinstance(projects, dict) or 'projects' in note and not projects:
        raise ValueError('invalid_input: projects maps each project name to its whole new entry, or to null to drop it')
    entries = {}
    for name, text in projects.items():
        name = project_name(name)
        if find([{'name': other} for other in entries], name):
            raise ValueError(f'invalid_input: {name} appears twice in projects')
        entries[name] = None if text is None else plain(name, text)
    return {part: plain(part, text) for part, text in note.items() if part != 'projects'}, entries


def conversations(runtime):
    chats = Path(runtime) / 'browser-chats' / 'chats.json'
    if chats.is_symlink():
        raise ValueError('unsafe_path: conversations must belong to this runtime')
    return json.loads(chats.read_text(encoding='utf-8')).values() if chats.exists() else []


def remembered(item, turn):
    """Setup answers are settings, not memories, and a message held for storage consent never reached the secretary."""
    return bool(turn.get('text')) and item['mode'] != 'initialize' and not turn.get('local')


def chinese(text):
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def change(runtime, revision, *, note=None, enabled=None, session=None):
    """Rewrite parts of the note or switch memory on or off, checked against the revision."""
    item = next((item for item in conversations(runtime) if session and item.get('session') == session), None)
    if note is not None and item and item['mode'] == 'initialize':
        raise ValueError('memory_setup: setup chats keep no memories; setup saves its answers itself, so write nothing')
    with runtime_lock(runtime, 'memory.lock'):
        data = load(runtime)
        if revision != data['revision']:
            raise ValueError(f'revision_conflict: memory changed (now revision {data["revision"]}); run memory --show and write again')
        if enabled is not None:
            data['enabled'] = enabled
        else:
            if not data['enabled']:
                raise ValueError('memory_off: the user turned memory off on the About me page; write nothing')
            parts, projects = checked(note)
            merged = data['note'] | parts
            today = briefing_day(profile_fields(runtime).get('timezone', ''))
            entries = [dict(entry) for entry in data['projects']]
            written = [text for part, text in merged.items() if text != data['note'][part]]
            # Drops first, so a write can replace a finished project with a new one when all are taken.
            for name, text in sorted(projects.items(), key=lambda item: item[1] is not None):
                entry = find(entries, name)
                if text is None:
                    if entry:
                        entries.remove(entry)
                    continue
                if len(text) > PROJECT:
                    raise ValueError(f'project_too_long: the {name} entry would be {len(text)} characters; trim it to {PROJECT} and write again')
                if not entry:
                    if len(entries) >= PROJECTS:
                        raise ValueError(f'memory_projects_full: the note keeps at most {PROJECTS} projects; drop a finished one '
                                         '(null) in the same write only if the user said it is finished, otherwise write nothing for this project')
                    entry = {'name': name, 'note': ''}
                    entries.append(entry)
                if text != entry['note']:
                    written.append(text)
                    entry.update(note=text, updated=today)
            if item and item['turns'] and item['turns'][-1].get('language') == 'zh-CN' and any(
                    text and not chinese(text) for text in written):
                raise ValueError('memory_language: write each changed part and project in Simplified Chinese, the website language; nothing was saved')
            size = sum(len(text) for text in merged.values()) + sum(len(entry['note']) for entry in entries)
            if size > LENGTH:
                raise ValueError(f'memory_too_long: the note with its projects would be {size} characters; merge and trim it to {LENGTH} and write again')
            if merged == data['note'] and entries == data['projects']:
                return {'saved': False, 'revision': data['revision']}
            data['note'], data['projects'] = merged, entries
            data['updated'] = today
        data['revision'] += 1
        if session and note is not None:
            stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
            data['changes'] = [*data['changes'], {'seq': data['revision'], 'session': session, 'at': stamp}][-CHANGES:]
        atomic_text(path(runtime), encode(data))
    return {'saved': True, 'revision': data['revision']}


def add_projects(runtime, names):
    """An empty entry for each project a to-do has just named for the first time, while memory is on and has room."""
    with runtime_lock(runtime, 'memory.lock'):
        data = load(runtime)
        if not data['enabled']:
            return
        entries, today = list(data['projects']), briefing_day(profile_fields(runtime).get('timezone', ''))
        for name in names:
            if len(' '.join(name.split())) <= NAME and not find(entries, name) and len(entries) < PROJECTS:
                entries.append({'name': project_name(name), 'note': '', 'updated': today})
        if entries != data['projects']:
            data['projects'], data['updated'] = entries, today
            data['revision'] += 1
            atomic_text(path(runtime), encode(data))


def rename(runtime, old, new):
    """Move a project's entry to the new name its to-dos now carry; nothing to move when memory is off or has no entry."""
    new = project_name(new)
    with runtime_lock(runtime, 'memory.lock'):
        data = load(runtime)
        entry = find(data['projects'], old)
        if not data['enabled'] or not entry or entry['name'] == new:
            return
        if find(data['projects'], new) not in (None, entry):
            raise ValueError(f'project_exists: the note already has an entry for {new}; merge the two entries in one memory write '
                             'and drop one before renaming')
        entry['name'] = new
        data['revision'] += 1
        atomic_text(path(runtime), encode(data))


def tidy(runtime):
    """The user's chat messages since the last tidy, oldest first, and mark them as seen.

    Only the user's own words: the secretary's replies never become memories."""
    zone = profile_fields(runtime).get('timezone', '')
    try:
        zone = ZoneInfo(zone or 'UTC')
    except (ValueError, KeyError):
        zone = timezone.utc
    items = conversations(runtime)
    with runtime_lock(runtime, 'memory.lock'):
        data = load(runtime)
        now = time.time()
        since = data.get('tidied', now - 86400)
        found = sorted((turn.get('created', item['created']), turn['text']) for item in items for turn in item['turns']
                       if remembered(item, turn) and since < turn.get('created', item['created']) <= now)[-MESSAGES:]
        data['tidied'] = now
        atomic_text(path(runtime), encode(data))
    return [{'at': datetime.fromtimestamp(at, zone).strftime('%a %H:%M'), 'text': text[:MESSAGE]} for at, text in found]


def activity(runtime, day):
    """The last DAYS days of check-ins and changes to to-dos, ideas and habits, oldest first, one line each.

    The evening tidy looks here for patterns that repeat across days; the records stay the source of each fact.
    Each line starts with its weekday and day, so patterns by weekday are visible."""
    from goodmorning.records.daily import inspect, read_record, record_path
    from .custom_store import CustomStore
    from .inbox_store import InboxStore
    zone = profile_fields(runtime).get('timezone', '')
    end = date.fromisoformat(day)
    days = [(end - timedelta(days=n)).isoformat() for n in range(DAYS - 1, -1, -1)]
    lines = set()

    def add(at, what, title, when='', project=''):
        """`at` is a day, or a local ISO time from the stores; `when` is the day the item is planned or due."""
        moment = datetime.fromisoformat(at) if 'T' in at else None
        on = briefing_day(zone, moment) if moment else at
        if days[0] <= on <= day and title:
            label = date.fromisoformat(on).strftime('%a ') + on + (moment.strftime(' %H:%M') if moment else '')
            lines.add((on, label + ' ' + what + ': ' + ' '.join(title.split())[:TITLE]
                       + (f' (for {date.fromisoformat(when).strftime("%a")} {when})' if when else '')
                       + (f' [project: {project}]' if project else '')))

    for on in days:
        text, _ = read_record(record_path(runtime, on))
        feedback, headings, _ = inspect(text, on)
        start = headings.get('feedback')
        if start is not None:
            stop = next((n for n in sorted(headings.values()) if n > start), len(feedback))
            for line in feedback[start + 1:stop]:
                add(on, 'check-in', line.strip().removeprefix('- '))
    try:
        inbox = InboxStore(runtime)
    except sqlite3.Error:
        inbox = None  # Nothing captured yet.
    if inbox:
        try:
            inbox.db.execute('BEGIN')
            for status, created, updated, summary, raw in inbox.db.execute(
                    "SELECT status,created_at,updated_at,summary,raw FROM entries WHERE kind='idea'"):
                add(created, 'idea saved', summary or raw)
                if status == 'done':
                    add(updated, 'idea closed', summary or raw)
            if inbox.version == 2:  # A store from before tasks has only ideas.
                finished = {row[0] for row in inbox.db.execute("SELECT task_id FROM task_occurrences WHERE status='done'")}
                for identifier, created, updated, raw in inbox.db.execute('SELECT id,created_at,updated_at,data FROM tasks'):
                    task = json.loads(raw)
                    project = task.get('project', '')
                    add(created, 'to-do added', task['title'], task.get('planned_date') or task.get('due_date') or '', project)
                    # A day's Done is its occurrence below; only an undated finish or a cancellation is dated by the change.
                    if task['status'] == 'cancelled' or task['status'] == 'done' and identifier not in finished:
                        add(updated, 'to-do ' + task['status'], task['title'], project=project)
                for title, project, on in inbox.db.execute("SELECT json_extract(t.data,'$.title'),json_extract(t.data,'$.project'),o.date "
                                                           "FROM task_occurrences o JOIN tasks t ON t.id=o.task_id WHERE o.status='done'"):
                    add(on, 'to-do done', title, project=project or '')
        finally:
            inbox.close()
    try:
        custom = CustomStore(runtime)
    except ValueError:
        custom = None  # No habits saved yet.
    if custom:
        try:
            names = {}
            for rule in custom.all():
                names[rule['id']] = rule['title']
                add(rule['created_at'], 'habit added', rule['title'])
            for rule_id, on in custom.db.execute("SELECT rule_id,date FROM custom_completions WHERE status='done'"):
                add(on, 'habit done', names.get(rule_id, ''))
        finally:
            custom.close()
    return [line for _, line in sorted(lines)][-ACTIVITY:]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog='JSON input fields and tested examples: docs/helper-inputs.md')
    parser.add_argument('--secretary-dir')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--show', action='store_true')
    actions.add_argument('--write', action='store_true')
    parser.add_argument('--expect-revision', type=int)
    parser.add_argument('--session', default=os.environ.get('OPENCODE_SESSION_ID'))
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--input-stdin', action='store_true')
    inputs.add_argument('--input-json')
    args = parser.parse_args(argv)
    try:
        runtime = secretary_path(args.secretary_dir)
        if args.show:
            print(encode(context(runtime)))
            return 0
        if args.expect_revision is None:
            raise ValueError('revision_required: supply the revision from prepare, memory --show or the last receipt')
        text = args.input_json if args.input_json is not None else sys.stdin.read(10001) if args.input_stdin else ''
        if not text or len(text) > 10000:
            raise ValueError('input_required: supply bounded JSON with --input-stdin or --input-json')
        print(encode(change(runtime, args.expect_revision, note=json.loads(text), session=args.session)))
        return 0
    except (ValueError, OSError) as error:
        message = (f'invalid_input: malformed JSON ({error.msg}, line {error.lineno} column {error.colno}); nothing was saved'
                   if isinstance(error, json.JSONDecodeError) else str(error) if isinstance(error, ValueError)
                   else 'memory_unavailable: preserve storage and inspect the runtime')
        print(encode({'error': message.split(':', 1)[0], 'next': message}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
