"""Canonical actions and event drafts in the inbox transaction, never section tables."""
import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA = """
CREATE TABLE tasks (
    id TEXT PRIMARY KEY, source_entry_id TEXT NOT NULL REFERENCES entries(id),
    revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    data TEXT NOT NULL);
CREATE INDEX task_sources ON tasks(source_entry_id);
CREATE TABLE task_occurrences (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
    date TEXT NOT NULL, revision INTEGER NOT NULL, status TEXT NOT NULL,
    detail TEXT NOT NULL, UNIQUE(task_id,date));
CREATE TABLE task_events (
    seq INTEGER PRIMARY KEY, item_id TEXT NOT NULL, action TEXT NOT NULL,
    at TEXT NOT NULL, session TEXT NOT NULL, snapshot TEXT NOT NULL,
    request_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, receipt TEXT NOT NULL);
CREATE TABLE event_drafts (
    id TEXT PRIMARY KEY, source_entry_id TEXT NOT NULL REFERENCES entries(id),
    revision INTEGER NOT NULL, data TEXT NOT NULL);
"""
STATES = ('open', 'partial', 'blocked', 'done', 'cancelled')
FIELDS = {'title', 'detail', 'project', 'optional', 'priority', 'status', 'due_date',
          'due_at', 'planned_date', 'timezone', 'repeat', 'defer_until', 'calendar_event_id', 'when', 'follow_up', 'work_kind', 'due_soft',
          'kind', 'trigger', 'after', 'notice'}
DRAFT_FIELDS = {'title', 'date', 'timezone', 'location', 'detail', 'confirmed_day',
                'state', 'calendar_event_id', 'event', 'repeat', 'notice'}
# Nudges and reference notes are never completed: they surface or are retired.
UNCHECKED = ('nudge', 'reference')
TIMING = ('planned_date', 'due_date', 'due_at', 'repeat', 'defer_until', 'when', 'follow_up', 'calendar_event_id', 'after', 'notice')
SERIES_LIMIT = 200


def category(task):
    """Code-owned category from explicit kind and timing fields; storage never trusts a label."""
    if task.get('kind') in UNCHECKED:
        return task['kind']
    if task.get('repeat'):
        return 'routine'
    if task.get('planned_date'):
        return 'day'
    if task.get('due_date') and not task.get('due_soft'):
        return 'deadline'
    return 'project' if task.get('project') else 'anytime'


def chasing(task, day):
    """A one-off follow-up is due every day from its start until it is closed."""
    if task.get('follow_up') != 'until-done' or task['status'] in ('done', 'cancelled'):
        return False
    return day >= (task.get('planned_date') or task.get('defer_until') or task['created_at'][:10])


def series_days(rule, first, last):
    """Weekday series of a recurring TBC appointment, bounded and exclusion-aware."""
    start = max(dt.date.fromisoformat(rule['start']), dt.date.fromisoformat(first))
    stop = dt.date.fromisoformat(min(last, rule['until'])) if rule.get('until') else dt.date.fromisoformat(last)
    days = []
    while start <= stop and len(days) < SERIES_LIMIT:
        if start.weekday() in rule['weekdays'] and start.isoformat() not in rule.get('exclude', []):
            days.append(start.isoformat())
        start += dt.timedelta(days=1)
    return days


def check_notice(value, event=False):
    """Advance notice for a dated item: from how many days before its day the
    morning and the evening briefing show it, and whether it can be done early."""
    if value is None:
        return
    keys = {'morning', 'evening'} | (set() if event else {'early'})
    if not isinstance(value, dict) or not value or set(value) - keys:
        raise ValueError('invalid_input: notice is {morning?: days, evening?: days' + ('' if event else ', early?: boolean') + '}')
    for key in ('morning', 'evening'):
        if key in value and (type(value[key]) is not int or not 0 <= value[key] <= 60):
            raise ValueError('invalid_input: notice days are integers 0..60 (morning 0 = on the day; evening 1 = the night before, 0 = never)')
    if 'early' in value and type(value['early']) is not bool:
        raise ValueError('invalid_input: notice.early must be boolean')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def date(value):
    if not isinstance(value, str) or dt.date.fromisoformat(value).isoformat() != value:
        raise ValueError('invalid_date: use YYYY-MM-DD')
    return value


def checked(value, maximum=5000, empty=True):
    from .inbox_store import check_text
    return check_text(value, maximum, 'task field', empty)


def validate(data, *, draft=False):
    if not isinstance(data, dict) or set(data) - (DRAFT_FIELDS if draft else FIELDS):
        raise ValueError('invalid_input: unsupported task or event-draft fields')
    out = dict(data)
    for key in ('title', 'detail', 'project', 'location', 'calendar_event_id'):
        if key in out:
            checked(out[key], 600 if key == 'title' else 5000, key != 'title')
    for key in ('date', 'planned_date', 'due_date', 'defer_until'):
        if out.get(key):
            date(out[key])
        elif key in out and out[key] != '':
            raise ValueError('invalid_date: unset dates use an empty string')
    if out.get('timezone'):
        checked(out['timezone'], 160, False)
        ZoneInfo(out['timezone'])
    elif 'timezone' in out and out['timezone'] != '':
        raise ValueError('invalid_input: unset timezone uses an empty string')
    for key in ('optional', 'confirmed_day', 'due_soft'):
        if key in out and type(out[key]) is not bool:
            raise ValueError('invalid_input: optional/confirmed_day must be boolean')
    if draft:
        if out.get('state', 'needs-details') not in ('tentative', 'needs-details', 'ready-for-confirmation', 'converted', 'withdrawn'):
            raise ValueError('invalid_input: unknown event draft state')
        if out.get('confirmed_day') and not (out.get('date') and out.get('timezone')):
            raise ValueError('invalid_input: confirmed appointment day needs date and timezone')
        if 'event' in out:
            from goodmorning.calendar.calendar_store import normalize
            out['event'] = normalize(out['event'])
        if out.get('state') == 'ready-for-confirmation' and not out.get('event'):
            raise ValueError('invalid_input: ready draft needs explicit event endpoints')
        if out.get('repeat'):
            rule = out['repeat']
            if (not isinstance(rule, dict) or set(rule) - {'weekdays', 'start', 'until', 'exclude'} or 'weekdays' not in rule
                    or not out.get('confirmed_day') or rule.get('start') != out.get('date')):
                raise ValueError('invalid_input: an appointment series needs a confirmed first date, start equal to date, and weekdays')
            validate({'repeat': rule, 'timezone': out['timezone']})
        elif 'repeat' in out and out['repeat'] is not None:
            raise ValueError('invalid_input: unset recurrence uses null')
        check_notice(out.get('notice'), event=True)
        return out
    kind = out.get('kind', '')
    if kind not in ('', 'nudge', 'reference'):
        raise ValueError('invalid_input: kind must be empty (action), nudge or reference')
    if kind and out.get('status', 'open') not in ('open', 'cancelled'):
        raise ValueError('invalid_input: nudges and reference notes are open or cancelled, never completed')
    if kind == 'reference':
        if not out.get('trigger') or any(out.get(key) for key in TIMING):
            raise ValueError('invalid_input: a reference note needs a trigger and no dates, repeats or conditions')
    if 'trigger' in out:
        checked(out['trigger'], 300, kind != 'reference')
        if out['trigger'] and kind != 'reference':
            raise ValueError('invalid_input: only reference notes have a trigger')
    if kind == 'nudge' and any(out.get(key) for key in ('due_date', 'due_at', 'due_soft', 'follow_up', 'after')):
        raise ValueError('invalid_input: a nudge has no deadline, follow-up or dependency')
    if out.get('after'):
        import re
        if (not isinstance(out['after'], str) or not re.fullmatch(r'task_[0-9a-f]{16}', out['after'])
                or out.get('planned_date') or out.get('repeat')):
            raise ValueError('invalid_input: after links an undated step to the task ID it waits for')
    if out.get('status', 'open') not in STATES or out.get('priority', '') not in ('', 'high', 'normal', 'low'):
        raise ValueError('invalid_input: unknown action status or explicit priority')
    if out.get('due_at'):
        checked(out['due_at'], 100, False)
        value = dt.datetime.fromisoformat(out['due_at'])
        if value.utcoffset() is None or not out.get('timezone'):
            raise ValueError('invalid_input: deadline timestamp needs offset and timezone')
        local = value.astimezone(ZoneInfo(out['timezone'])).date().isoformat()
        if out.get('due_date') and out['due_date'] != local:
            raise ValueError('invalid_input: deadline date disagrees with timestamp')
        out['due_date'] = local
    elif 'due_at' in out and out['due_at'] != '':
        raise ValueError('invalid_input: unset deadline timestamp uses an empty string')
    if out.get('repeat'):
        rule = out['repeat']
        modes = {'weekdays', 'interval_days', 'dates', 'event_subject'}
        if not isinstance(rule, dict) or set(rule) - (modes | {'start', 'until', 'exclude', 'include', 'offset_days'}) or 'start' not in rule or len(set(rule) & modes) != 1:
            raise ValueError('invalid_input: recurrence needs start and exactly one of weekdays, interval_days, dates or event_subject')
        if 'event_subject' in rule:
            checked(rule['event_subject'], 200, False)
            if type(rule.get('offset_days', 0)) is not int or not -14 <= rule.get('offset_days', 0) <= 0:
                raise ValueError('invalid_input: offset_days is an integer from -14 to 0 (days before the appointment)')
        elif 'offset_days' in rule:
            raise ValueError('invalid_input: offset_days applies only to event_subject preparation')
        if 'weekdays' in rule:
            weekdays = rule['weekdays']
            if not isinstance(weekdays, list) or not 1 <= len(weekdays) <= 7 or any(type(d) is not int or not 0 <= d <= 6 for d in weekdays) or len(set(weekdays)) != len(weekdays):
                raise ValueError('invalid_input: weekdays are distinct integers 0=Monday..6=Sunday')
        if 'interval_days' in rule and (type(rule['interval_days']) is not int or not 1 <= rule['interval_days'] <= 366):
            raise ValueError('invalid_input: interval_days must be an integer 1..366')
        for field in ('dates', 'exclude', 'include'):
            if field in rule:
                values = rule[field]
                if not isinstance(values, list) or not values or len(values) > 1000 or any(not isinstance(v, str) for v in values) or len(set(values)) != len(values):
                    raise ValueError('invalid_input: recurrence dates must be distinct date strings, at most 1000')
                for value in values:
                    date(value)
        date(rule['start'])
        if rule.get('until') and date(rule['until']) < rule['start']:
            raise ValueError('invalid_input: recurrence end precedes start')
        if not out.get('timezone') or out.get('planned_date'):
            raise ValueError('invalid_input: recurrence needs timezone and no single planned_date')
    elif 'repeat' in out and out['repeat'] is not None:
        raise ValueError('invalid_input: unset recurrence uses null')
    if out.get('when'):
        rule = out['when']
        import re
        if not isinstance(rule, dict) or set(rule) - {'morning_before', 'unless_experiment_plan', 'unless_timed_plan', 'planned_task_id', 'custom_rule_id'} or not out.get('timezone'):
            raise ValueError('invalid_input: unsupported reminder condition or missing timezone')
        if 'custom_rule_id' in rule:
            if (not isinstance(rule['custom_rule_id'], str) or not re.fullmatch(r'cu_[0-9a-f]{16}', rule['custom_rule_id'])
                    or 'planned_task_id' in rule or out.get('repeat') or out.get('planned_date')):
                raise ValueError('invalid_input: a habit-linked reminder needs one custom rule ID and no separate schedule')
        if 'morning_before' in rule and (not isinstance(rule['morning_before'], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', rule['morning_before'])):
            raise ValueError('invalid_input: morning_before must be HH:MM')
        for field in ('unless_experiment_plan', 'unless_timed_plan'):
            if field in rule and type(rule[field]) is not bool:
                raise ValueError('invalid_input: plan suppression must be boolean')
        if 'planned_task_id' in rule:
            if not isinstance(rule['planned_task_id'], str) or not re.fullmatch(r'task_[0-9a-f]{16}', rule['planned_task_id']) or out.get('repeat') or out.get('planned_date'):
                raise ValueError('invalid_input: linked planned-day reminder needs a task ID and no separate schedule')
    elif 'when' in out and out['when'] is not None:
        raise ValueError('invalid_input: unset condition uses null')
    if out.get('work_kind', '') not in ('', 'experiment'):
        raise ValueError('invalid_input: work_kind must be empty or experiment')
    if out.get('follow_up', '') not in ('', 'one-outstanding', 'until-done'):
        raise ValueError('invalid_input: follow_up must be empty, one-outstanding or until-done')
    if out.get('follow_up') == 'one-outstanding' and not (out.get('repeat') or {}).get('interval_days'):
        raise ValueError('invalid_input: one-outstanding follow-up requires an interval_days rule')
    if out.get('follow_up') == 'until-done' and out.get('repeat'):
        raise ValueError('invalid_input: until-done follows up a one-off action; a repeat has its own occurrences')
    if out.get('calendar_event_id'):
        import re
        if not re.fullmatch('[0-9a-f]{16}', out['calendar_event_id']):
            raise ValueError('invalid_input: calendar link needs a saved event ID')
    check_notice(out.get('notice'))
    if out.get('notice') and (kind or not (out.get('planned_date') or out.get('repeat') or out.get('due_date'))):
        raise ValueError('invalid_input: notice applies to a dated action (planned_date, repeat or due_date)')
    return out


def defaults(title, project=''):
    return {'title': title, 'detail': '', 'project': project, 'optional': False,
            'priority': '', 'status': 'open', 'due_date': '', 'due_at': '',
            'planned_date': '', 'timezone': '', 'repeat': None, 'defer_until': '',
            'calendar_event_id': ''}


def default_title(raw, limit=280):
    """Deterministic fallback title when the secretary supplies no revised summary.

    Collapses whitespace, strips trailing periods, capitalizes the first letter and
    truncates cleanly. Semantic rewrites (imperative verb, specific object, useful
    detail) remain the secretary's job per docs/workflows/todo.md; this only stops
    the worst verbatim artifacts such as trailing periods and lowercase starts.
    """
    collapsed = ' '.join((raw or '').split())
    if not collapsed:
        return collapsed
    text = collapsed[:limit].rstrip()
    text = text.rstrip('.').rstrip()
    if not text:
        return collapsed[:limit].rstrip()
    first = next((c for c in text if c.isalpha()), '')
    if first and first.islower():
        index = text.index(first)
        text = text[:index] + first.upper() + text[index + 1:]
    return text


def occurrence_id(identifier, day):
    return 'oc_' + hashlib.sha256((identifier + '\0' + day).encode()).hexdigest()[:16]


def planned_on(task, day, event_days=()):
    """A planned date, never an actual off-cadence report, qualifies a linked reminder.

    event_days holds the local dates of approved appointments for an event_subject
    rule; the caller reads them from the calendar."""
    if task['planned_date'] == day:
        return True
    rule = task['repeat']
    if not rule or day < rule['start'] or (rule.get('until') and day > rule['until']) or day in rule.get('exclude', []):
        return False
    target = dt.date.fromisoformat(day)
    if day in rule.get('include', []):
        return True
    if 'weekdays' in rule:
        return target.weekday() in rule['weekdays']
    if 'interval_days' in rule:
        return (target - dt.date.fromisoformat(rule['start'])).days % rule['interval_days'] == 0
    if 'event_subject' in rule:
        return (target - dt.timedelta(days=rule.get('offset_days', 0))).isoformat() in event_days
    return day in rule['dates']


def linked(db, data, identifier):
    """A dependency names another saved action; a step never waits for itself."""
    if data.get('after'):
        if data['after'] == identifier or not db.execute('SELECT 1 FROM tasks WHERE id=?', (data['after'],)).fetchone():
            raise ValueError('invalid_input: after must name another saved task')


def capture(db, entry, payload, now):
    """Called inside InboxStore.mutate: raw input, action and receipt commit together."""
    if payload['kind'] == 'todo':
        fields = payload.get('task', {})
        if fields.get('status', 'open') != 'open':
            raise ValueError('confirmation_required: capture cannot assert completion')
        summary = payload.get('summary') or default_title(payload['raw'])
        data = validate({**defaults(summary, payload.get('project', '')), **fields})
        identifier = 'task_' + uuid.uuid4().hex[:16]
        linked(db, data, identifier)
        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?)', (identifier, entry, 1, now, now, encode(data)))
        if not payload.get('also'):
            return {'task_id': identifier}
        siblings = [capture(db, entry, {'kind': 'todo', 'raw': payload['raw'], 'project': payload.get('project', ''),
                                        'task': fields}, now)['task_id'] for fields in payload['also']]
        return {'task_id': identifier, 'task_ids': [identifier, *siblings]}
    if payload['kind'] == 'event_proposal':
        if payload.get('draft', {}).get('state') in ('converted', 'withdrawn'):
            raise ValueError('invalid_input: new event proposal cannot be closed')
        data = validate({'title': payload.get('summary') or default_title(payload['raw']),
                         'date': '', 'timezone': '', 'location': '', 'detail': '',
                         'confirmed_day': False, 'state': 'needs-details', 'calendar_event_id': '',
                         **payload.get('draft', {})}, draft=True)
        identifier = 'draft_' + uuid.uuid4().hex[:16]
        db.execute('INSERT INTO event_drafts VALUES (?,?,?,?)', (identifier, entry, 1, encode(data)))
        return {'draft_id': identifier}
    return {}


class TaskStore:
    def __init__(self, inbox):
        self.inbox, self.db = inbox, inbox.db
        self._event_days, self._habits = {}, {}
        if inbox.version != 2:
            raise ValueError('migration_required: use task --migrate --confirm after reviewing its dry run')

    def event_days(self, task):
        """Local dates of approved appointments named by a preparation rule, read once per rule."""
        rule = task.get('repeat') or {}
        if 'event_subject' not in rule:
            return ()
        key = (rule['event_subject'].casefold(), rule['start'], rule.get('until', ''), task['timezone'])
        if key not in self._event_days:
            days = set()
            path = Path(self.inbox.directory) / 'calendar.sqlite'
            if path.is_symlink():
                raise ValueError('unsafe_path: preparation links must use this runtime calendar')
            if path.exists():
                from goodmorning.calendar.calendar_store import CalendarStore, endpoints
                zone = ZoneInfo(task['timezone'])
                first = dt.datetime.combine(dt.date.fromisoformat(rule['start']), dt.time(), zone)
                last = (dt.datetime.combine(dt.date.fromisoformat(rule['until']), dt.time(), zone) + dt.timedelta(days=15)
                        if rule.get('until') else first + dt.timedelta(days=740))
                calendar = CalendarStore(str(path), readonly=True)
                try:
                    for event in calendar.query(first, last, limit=-1):
                        if event.get('status') != 'cancelled' and event['subject'].strip().casefold() == key[0].strip():
                            days.add(endpoints(event)[0].astimezone(zone).date().isoformat())
                finally:
                    calendar.close()
            self._event_days[key] = days
        return self._event_days[key]

    def habit_due(self, identifier, day):
        """A habit-linked nudge follows the habit's code-owned due decision for that day."""
        if (identifier, day) not in self._habits:
            from .custom_store import CustomStore
            try:
                store = CustomStore(self.inbox.directory, write=False)
            except ValueError:
                return False  # No habits saved yet.
            try:
                rule = next((r for r in store.all() if r['id'] == identifier), None)
                self._habits[identifier, day] = bool(rule) and store.due(rule, day)['due']
            finally:
                store.close()
        return self._habits[identifier, day]

    def show(self, identifier, draft=False):
        row = self.db.execute('SELECT * FROM ' + ('event_drafts' if draft else 'tasks') + ' WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ValueError('not_found: task/event draft does not exist')
        item = dict(row)
        item.update(json.loads(item.pop('data')))
        if not draft:
            item['category'] = category(item)
        return item

    def all(self, draft=False):
        table = 'event_drafts' if draft else 'tasks'
        for row in self.db.execute('SELECT * FROM ' + table + ' ORDER BY rowid'):
            item = dict(row)
            item.update(json.loads(item.pop('data')))
            if not draft:
                item['category'] = category(item)
            yield item

    def occurrence(self, task, day):
        date(day)
        identifier = occurrence_id(task['id'], day)
        row = self.db.execute('SELECT * FROM task_occurrences WHERE id=?', (identifier,)).fetchone()
        if row:
            return dict(row)  # A confirmed report survives later rescheduling/recurrence edits.
        matches = planned_on(task, day, self.event_days(task))
        parent = (task.get('when') or {}).get('planned_task_id')
        if parent:
            source = self.show(parent)
            matches = source['status'] != 'cancelled' and planned_on(source, day, self.event_days(source))
        habit = (task.get('when') or {}).get('custom_rule_id')
        if habit:
            matches = self.habit_due(habit, day)
        if not matches and task.get('kind') != 'nudge' and chasing(task, day):
            matches = True
        if not matches:
            raise ValueError('unknown_occurrence: day is not agreed or recurring work')
        return {'id': identifier, 'task_id': task['id'], 'date': day,
                'revision': 0, 'status': task['status'], 'detail': ''}

    def adopt(self, identifier, expected, payload, session, key, now):
        checked(session, 200, False); checked(key, 240, False)
        if not isinstance(payload, dict) or 'tasks' not in payload or set(payload) - {'tasks', 'replace'} or not isinstance(payload['tasks'], list) or not 1 <= len(payload['tasks']) <= 50:
            raise ValueError('invalid_input: adoption needs tasks, an explicit list of 1..50 actions')
        digest = hashlib.sha256(encode([identifier, expected, payload, session]).encode()).hexdigest()
        with self.inbox.transaction():
            previous = self.db.execute('SELECT fingerprint,receipt FROM task_events WHERE request_key=?', (key,)).fetchone()
            if previous:
                if previous['fingerprint'] != digest:
                    raise ValueError('request_conflict: key belongs to different input')
                return {**json.loads(previous['receipt']), 'replayed': True}
            if self.db.execute('SELECT 1 FROM events WHERE request_key=?', (key,)).fetchone():
                raise ValueError('request_conflict: key belongs to capture')
            current = self.inbox.show(identifier)
            if current['revision'] != expected or current['kind'] not in ('idea', 'project_update', 'todo'):
                raise ValueError('write_conflict: read the current idea/project report before adopting')
            if current['needs_review'] or current['status'] != 'pending':
                raise ValueError('unreviewed_details: reconcile input or reuse existing adopted tasks')
            if current['questions']:
                raise ValueError('unresolved_questions: reconcile saved questions before adopting actions')
            replacements = payload.get('replace', [])
            if not isinstance(replacements, list) or (current['kind'] == 'todo' and not replacements) or (current['kind'] != 'todo' and replacements):
                raise ValueError('scope_required: splitting a TODO needs exact replace task IDs/revisions')
            seen = set()
            for target in replacements:
                if not isinstance(target, dict) or set(target) != {'id', 'revision'} or target['id'] in seen:
                    raise ValueError('invalid_input: replace needs distinct task IDs and revisions')
                original = self.show(target['id'])
                if original['source_entry_id'] != identifier or original['revision'] != target['revision'] or original['status'] in ('done', 'cancelled'):
                    raise ValueError('write_conflict: replacement scope changed or includes another/completed task')
                seen.add(target['id'])
            for fields in payload['tasks']:
                validate(fields)
            for identifier_to_replace in seen:
                original = self.show(identifier_to_replace)
                fields = {k: v for k, v in original.items() if k in FIELDS}
                fields['status'] = 'cancelled'  # Superseded, not completed or deleted.
                self.db.execute('UPDATE tasks SET revision=revision+1,updated_at=?,data=? WHERE id=?', (now, encode(fields), identifier_to_replace))
            tasks = [capture(self.db, identifier, {'kind': 'todo', 'raw': current['summary'],
                                                  'project': current['project'], 'task': fields}, now)['task_id'] for fields in payload['tasks']]
            self.db.execute("UPDATE entries SET status='confirmed',revision=revision+1 WHERE id=?", (identifier,))
            result = {'saved': True, 'id': identifier, 'revision': expected + 1, 'task_ids': tasks}
            self.db.execute('INSERT INTO task_events(item_id,action,at,session,snapshot,request_key,fingerprint,receipt) VALUES (?,?,?,?,?,?,?,?)',
                            (identifier, 'adopt', now, session, encode(payload), key, digest, encode(result)))
            return result

    def convert(self, runtime, identifier, expected, payload, session, key, now):
        """Persist conversion intent, use stable calendar identity, then finalize the receipt."""
        from goodmorning.calendar.calendar_store import CalendarStore, normalize
        from goodmorning.runtime_files import calendar_path
        checked(session, 200, False); checked(key, 240, False)
        if not isinstance(payload, dict) or set(payload) != {'event'}:
            raise ValueError('invalid_input: conversion needs an explicitly confirmed event')
        event = normalize(payload['event'])
        path = calendar_path(runtime)
        if not path.is_file() or path.is_symlink():
            raise ValueError('setup_required: existing authorized calendar is required')
        digest = hashlib.sha256(encode([identifier, expected, payload, session]).encode()).hexdigest()
        with self.inbox.transaction():
            previous = self.db.execute('SELECT fingerprint,receipt FROM task_events WHERE request_key=?', (key,)).fetchone()
            if previous:
                if previous['fingerprint'] != digest:
                    raise ValueError('request_conflict: key belongs to different conversion')
                receipt = json.loads(previous['receipt'])
                if receipt['saved']:
                    return {**receipt, 'replayed': True}
            else:
                if self.db.execute('SELECT 1 FROM events WHERE request_key=?', (key,)).fetchone():
                    raise ValueError('request_conflict: key belongs to capture')
                draft = self.show(identifier, True)
                if draft['revision'] != expected or draft['state'] in ('converted', 'withdrawn'):
                    raise ValueError('write_conflict: draft changed; inspect its current state')
                if self.db.execute("SELECT 1 FROM task_events WHERE item_id=? AND action='convert-pending'", (identifier,)).fetchone():
                    raise ValueError('outcome_unknown: resume the original conversion key/input, not another operation')
                self.db.execute('INSERT INTO task_events(item_id,action,at,session,snapshot,request_key,fingerprint,receipt) VALUES (?,?,?,?,?,?,?,?)',
                                (identifier, 'convert-pending', now, session, encode(payload), key, digest, encode({'saved': False})))
        series = self.show(identifier, True).get('repeat')
        calendar = CalendarStore(str(path))
        try:
            if series:
                event_id = calendar.add_many(self.series_events(identifier, series, event), session)[0]
            else:
                event_id = calendar.add(event, actor=session, external_id=identifier)
        finally:
            calendar.close()
        with self.inbox.transaction():
            draft = self.show(identifier, True)
            if draft['revision'] != expected:
                raise ValueError('outcome_unknown: calendar saved but draft changed; inspect before finalizing')
            data = {k: v for k, v in draft.items() if k in DRAFT_FIELDS}
            data.update(state='converted', calendar_event_id=event_id)
            self.db.execute('UPDATE event_drafts SET revision=revision+1,data=? WHERE id=?', (encode(data), identifier))
            result = {'saved': True, 'id': identifier, 'revision': expected + 1, 'calendar_event_id': event_id}
            self.db.execute("UPDATE task_events SET action='convert',receipt=? WHERE request_key=?", (encode(result), key))
            return result

    def series_events(self, identifier, series, event):
        """The confirmed first class sets the wall-clock time for every remaining date."""
        if event['all_day'] or not series.get('until'):
            raise ValueError('clarification_required: a weekly appointment series needs a confirmed time and end date before calendar conversion')
        draft = self.show(identifier, True)
        zone = ZoneInfo(event.get('timezone') or draft['timezone'])
        start = dt.datetime.fromisoformat(event['start']).astimezone(zone)
        length = dt.datetime.fromisoformat(event['end']) - dt.datetime.fromisoformat(event['start'])
        if start.date().isoformat() != draft['date']:
            raise ValueError('invalid_input: the confirmed time must be for the first class date')
        items = []
        for day in series_days(series, draft['date'], series['until']):
            begin = dt.datetime.combine(dt.date.fromisoformat(day), start.time(), zone)
            items.append(({**event, 'start': begin.isoformat(), 'end': (begin + length).isoformat()}, identifier + '@' + day))
        return items

    def complete_day(self, selections, day, session, key, now, details):
        """One browser receipt: exact planned or explicitly selected actual-day completions."""
        checked(session, 200, False); checked(key, 240, False); checked(details)
        digest = hashlib.sha256(encode([selections, day, session, details]).encode()).hexdigest()
        with self.inbox.transaction():
            previous = self.db.execute('SELECT fingerprint,receipt FROM task_events WHERE request_key=?', (key,)).fetchone()
            if previous:
                if previous['fingerprint'] != digest:
                    raise ValueError('request_conflict: feedback input changed')
                return {**json.loads(previous['receipt']), 'replayed': True}
            for selection in selections:
                task = self.show(selection['task_id'])
                if task.get('kind') in UNCHECKED:
                    raise ValueError('invalid_input: nudges and reference notes are never ticked off')
                if task['revision'] != selection['revision']:
                    raise ValueError('write_conflict: planned task changed; refresh feedback')
                if selection.get('actual'):
                    date(day)
                    reported = dt.datetime.fromisoformat(now)
                    if task.get('timezone'):
                        reported = reported.astimezone(ZoneInfo(task['timezone']))
                    if day > reported.date().isoformat():
                        raise ValueError('invalid_date: future work cannot already be completed')
                try:
                    occ = self.occurrence(task, day)
                except ValueError:
                    if not selection.get('actual'):
                        raise
                    occ = {'id': occurrence_id(task['id'], day), 'revision': 0, 'status': task['status']}
                if selection['id'] != occ['id'] or occ['status'] == 'cancelled':
                    raise ValueError('unknown_occurrence: complete only exact planned occurrences')
                self.db.execute('INSERT INTO task_occurrences VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                                'revision=excluded.revision,status=excluded.status,detail=excluded.detail',
                                (occ['id'], task['id'], day, occ['revision'] + 1, 'done', ''))
                data = {k: v for k, v in task.items() if k in FIELDS}
                if not task['repeat']:
                    data['status'] = 'done'
                self.db.execute('UPDATE tasks SET revision=revision+1,updated_at=?,data=? WHERE id=?', (now, encode(data), task['id']))
            result = {'saved': True, 'completed': [s['id'] for s in selections]}
            self.db.execute('INSERT INTO task_events(item_id,action,at,session,snapshot,request_key,fingerprint,receipt) VALUES (?,?,?,?,?,?,?,?)',
                            ('feedback:' + day, 'feedback', now, session, encode({'selected': selections, 'details': details}), key, digest, encode(result)))
            return result

    def mutate(self, identifier, expected, payload, session, key, now, *, day=None, draft=False, actual=False):
        if not isinstance(payload, dict) or not payload:
            raise ValueError('invalid_input: nonempty update required')
        checked(session, 200, False); checked(key, 240, False)
        data = dict(payload)
        confirmed = data.pop('confirmed_completion', False)
        if type(confirmed) is not bool:
            raise ValueError('confirmation_required: confirmed_completion must be boolean')
        if type(actual) is not bool or actual and (not day or draft or data.get('status') != 'done' or not confirmed):
            raise ValueError('confirmation_required: an actual-date report requires confirmed completion and its actual day')
        fingerprint = [identifier, expected, payload, session, day, draft]
        if actual:
            fingerprint.append(True)  # Keep existing non-actual retry fingerprints compatible.
        digest = hashlib.sha256(encode(fingerprint).encode()).hexdigest()
        with self.inbox.transaction():
            previous = self.db.execute('SELECT fingerprint,receipt FROM task_events WHERE request_key=?', (key,)).fetchone()
            if previous:
                if previous['fingerprint'] != digest:
                    raise ValueError('request_conflict: request key belongs to different input')
                return {**json.loads(previous['receipt']), 'replayed': True}
            if self.db.execute('SELECT 1 FROM events WHERE request_key=?', (key,)).fetchone():
                raise ValueError('request_conflict: request key belongs to a capture')
            current = self.show(identifier, draft)
            if draft and self.db.execute("SELECT 1 FROM task_events WHERE item_id=? AND action='convert-pending'", (identifier,)).fetchone():
                raise ValueError('outcome_unknown: reconcile pending calendar conversion before editing this draft')
            if expected != current['revision']:
                raise ValueError('write_conflict: task/draft revision changed; reread and reconcile')
            if data.get('status') == 'done' and not confirmed:
                raise ValueError('confirmation_required: completion requires actual user confirmation')
            if day:
                if current.get('kind') in UNCHECKED:
                    raise ValueError('invalid_input: nudges and reference notes have no occurrence reports; cancel them instead')
                if draft or set(data) - {'status', 'detail'} or data.get('status') not in STATES:
                    raise ValueError('invalid_input: occurrence report needs status and optional detail')
                if actual:
                    date(day)
                    reported = dt.datetime.fromisoformat(now)
                    if current.get('timezone'):
                        reported = reported.astimezone(ZoneInfo(current['timezone']))
                    if day > reported.date().isoformat():
                        raise ValueError('invalid_date: future work cannot already be completed')
                try:
                    occ = self.occurrence(current, day)
                except ValueError:
                    if not actual:
                        raise
                    occ = {'id':occurrence_id(identifier, day),'revision':0}
                checked(data.get('detail', ''))
                self.db.execute('INSERT INTO task_occurrences VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                                'revision=excluded.revision,status=excluded.status,detail=excluded.detail',
                                (occ['id'], identifier, day, occ['revision'] + 1, data['status'], data.get('detail', '')))
                # Daily effort is not automatically completion of a multi-day action.
                if actual and not current['repeat']:
                    completed = {k:v for k,v in current.items() if k in FIELDS}
                    completed['status'] = 'done'
                    self.db.execute('UPDATE tasks SET revision=revision+1,updated_at=?,data=? WHERE id=?', (now, encode(completed), identifier))
                else:
                    self.db.execute('UPDATE tasks SET revision=revision+1,updated_at=? WHERE id=?', (now, identifier))
            else:
                if current.get('repeat') and data.get('status') == 'done':
                    raise ValueError('occurrence_required: complete one recurring day, not the series')
                merged = {k: v for k, v in current.items() if k in (DRAFT_FIELDS if draft else FIELDS)}
                merged.update(data)
                merged = validate(merged, draft=draft)
                if not draft:
                    linked(self.db, merged, identifier)
                if draft:
                    if data.get('state') == 'converted' or 'calendar_event_id' in data:
                        raise ValueError('confirmation_required: use --convert after exact event confirmation')
                    self.db.execute('UPDATE event_drafts SET revision=revision+1,data=? WHERE id=?', (encode(merged), identifier))
                else:
                    self.db.execute('UPDATE tasks SET revision=revision+1,updated_at=?,data=? WHERE id=?', (now, encode(merged), identifier))
            result = {'saved': True, 'id': identifier, 'revision': expected + 1}
            if day:
                result['occurrence_id'] = occurrence_id(identifier, day)
            self.db.execute('INSERT INTO task_events(item_id,action,at,session,snapshot,request_key,fingerprint,receipt) '
                            'VALUES (?,?,?,?,?,?,?,?)', (identifier, 'report' if day else 'update', now, session,
                             encode({'item': self.show(identifier, draft), 'day': day, 'input': payload, 'actual': actual}), key, digest, encode(result)))
            return result


def migrate(directory, confirm=False, *, reviewed_tasks=None, session=None, now=None):
    """Explicit schema upgrade with an SQLite backup. Legacy daily dates remain untrusted."""
    from .inbox_store import InboxStore, NAME
    from goodmorning.runtime_files import runtime_lock
    with runtime_lock(directory, '.inbox.lock'):
        inbox = InboxStore(directory)
        try:
            if reviewed_tasks is not None:
                checked(session, 200, False)
                if not isinstance(now, str) or dt.datetime.fromisoformat(now).utcoffset() is None:
                    raise ValueError('invalid_input: reviewed migration requires an offset-aware maintenance timestamp')
                if not isinstance(reviewed_tasks, dict):
                    raise ValueError('invalid_input: reviewed_tasks must map exact capture IDs to task lists')
                sources = {r['id']:dict(r) for r in inbox.db.execute('SELECT * FROM entries')}
                todos = {key for key,row in sources.items() if row['kind']=='todo'}
                if not todos <= reviewed_tasks.keys() or not reviewed_tasks.keys() <= sources.keys():
                    raise ValueError('scope_required: reviewed migration must account for every TODO and reference only existing captures')
                for key, fields in reviewed_tasks.items():
                    if not isinstance(fields, list) or len(fields)>50:
                        raise ValueError('invalid_input: each reviewed source needs an explicit list of at most 50 tasks, empty for non-actions')
                    for task in fields:
                        validate(task)
                        validate({**defaults(sources[key]['summary'],sources[key]['project']), **task})
            report = {'version': inbox.version, 'target': 2, 'dry_run': not confirm,
                      'todo_captures': inbox.db.execute("SELECT COUNT(*) FROM entries WHERE kind='todo'").fetchone()[0],
                      'legacy_daily': [p.name for p in sorted(Path(directory, 'daily').glob('*.md'))[:200]],
                      'legacy_daily_total': sum(1 for p in Path(directory, 'daily').glob('*.md')),
                      'next': 'Legacy daily/project tasks need explicit identity/date reconciliation; no files are rewritten.'}
            if reviewed_tasks is not None:
                report['reviewed_sources'] = len(reviewed_tasks)
                report['reviewed_tasks'] = sum(map(len, reviewed_tasks.values()))
                if inbox.version != 1:
                    raise ValueError('migration_conflict: reviewed imports require an unmigrated v1 snapshot, not an existing task store')
            if not confirm or inbox.version == 2:
                return report
        finally:
            inbox.close()
        path = Path(directory) / NAME
        backup = Path(directory) / 'inbox.v1.backup.sqlite'
        if backup.exists():
            raise ValueError('backup_exists: preserve the existing backup and inspect before upgrading')
        with sqlite3.connect(path) as db:
            import os
            fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            with sqlite3.connect(backup) as target:
                db.backup(target)
            # Rebuild only the CHECK-constrained entry table; preserve IDs/audit bytes.
            db.execute('PRAGMA foreign_keys=OFF')
            old_sql = db.execute("SELECT sql FROM sqlite_master WHERE name='entries'").fetchone()[0]
            new_sql = old_sql.replace('CREATE TABLE entries', 'CREATE TABLE upgraded_entries').replace("'project_update'", "'project_update','event_proposal'")
            db.executescript('BEGIN IMMEDIATE;' + new_sql + ';INSERT INTO upgraded_entries SELECT * FROM entries;'
                             'DROP TABLE entries;ALTER TABLE upgraded_entries RENAME TO entries;'
                             'CREATE INDEX active_entries ON entries(status,seq);'
                             'CREATE INDEX review_entries ON entries(needs_review,seq);'
                             'CREATE INDEX project_entries ON entries(project,seq);' + SCHEMA +
                             'ALTER TABLE entries ADD COLUMN review_after TEXT NOT NULL DEFAULT "";')
            for row in db.execute("SELECT id,raw,summary,project,status,created_at,context,kind FROM entries").fetchall():
                if reviewed_tasks is not None:
                    for index, fields in enumerate(reviewed_tasks.get(row[0], [])):
                        data = validate({**defaults(row[2],row[3]), **fields})
                        seed = row[0] if index==0 else row[0] + ':' + str(index)
                        identifier = 'task_' + hashlib.sha256(seed.encode()).hexdigest()[:16]
                        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?)', (identifier,row[0],1,row[5],now,encode(data)))
                    continue
                if row[7]!='todo':
                    continue
                data = defaults(row[2] or ' '.join(row[1].split())[:280], row[3])
                data['detail'] = row[6] if len(row[6]) <= 5000 else 'Read the source entry for its full saved constraints: ' + row[0]
                if row[4] == 'done':
                    data['status'] = 'done'
                validate(data)
                identifier = 'task_' + hashlib.sha256(row[0].encode()).hexdigest()[:16]
                db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?)', (identifier, row[0], 1, row[5], row[5], encode(data)))
            if reviewed_tasks is not None:
                digest = hashlib.sha256(encode(reviewed_tasks).encode()).hexdigest()
                receipt = {'saved':True,'reviewed_tasks':report['reviewed_tasks'],'source_records_preserved':True}
                db.execute('INSERT INTO task_events(item_id,action,at,session,snapshot,request_key,fingerprint,receipt) VALUES (?,?,?,?,?,?,?,?)',
                    ('migration:v1','reviewed-migration',now,session,encode(reviewed_tasks),'migration:'+digest,digest,encode(receipt)))
            db.execute('PRAGMA user_version=2')
            db.commit()
        return {**report, 'saved': True, 'backup': backup.name}
