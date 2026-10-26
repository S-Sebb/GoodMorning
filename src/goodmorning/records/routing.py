"""Deterministic edition views. Dates and action identity never come from headings."""
import datetime as dt
import json
import re
from pathlib import Path
import sqlite3

from .inbox_store import InboxStore
from .task_store import UNCHECKED, TaskStore, chasing, occurrence_id, planned_on, series_days


def clean_task_detail(title, detail):
    """Extra notes only: never repeat the title or structured project/due text.

    Display-time cleanup so both future captures and existing polluted rows
    read cleanly without rewriting canonical history. Secretary capture rules
    (docs/workflows/todo.md, docs/item-taxonomy.md) prevent new duplication;
    this handles what is already saved.
    """
    if not detail or not isinstance(detail, str):
        return ''
    text = detail.strip()
    if not text:
        return ''
    title_norm = ' '.join((title or '').split())
    if title_norm and (' '.join(text.split()) == title_norm):
        return ''
    if title_norm and ' '.join(text.split()).startswith(title_norm):
        remainder = ' '.join(text.split())[len(title_norm):].lstrip()
        remainder = re.sub(r'^[|·—\-–:;,.]+\s*', '', remainder)
        text = remainder.strip()
        if not text:
            return ''
    # Drop legacy fragments that duplicate structured fields code already emits.
    text = re.sub(r'\|\s*deadline\s+\d{4}-\d{2}-\d{2}(\s*\(soft\))?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(?:^|[·|])\s*deadline\s+\d{4}-\d{2}-\d{2}(\s*\(soft\))?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(?:Project|项目)\s*[:：]\s*[^·|\n]+', '', text)
    text = re.sub(r'(?:Soft target|Due|弹性目标日期|截止)\s*[:：]\s*\S+', '', text)
    text = re.sub(r'To be scheduled|No workday assigned|待安排|还没定在哪天做', '', text)
    parts = [p.strip(' \t|·—-–:;,') for p in re.split(r'[·\n]+', text.replace('|', '·'))]
    parts = [p for p in parts if p and p not in ('.',)]
    text = ' · '.join(parts).strip(' \t·|')
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'(^|[·|]\s*)[|·]\s*', r'\1', text).strip(' \t·|')
    return text


def _human_when(start_raw, end_raw, all_day, zone):
    """Human range for calendar change cards; raw ISO is never shown."""
    from goodmorning.web.language import short_day
    try:
        if all_day:
            start_day = dt.date.fromisoformat(str(start_raw)[:10])
            end_day = dt.date.fromisoformat(str(end_raw)[:10]) if end_raw else start_day + dt.timedelta(days=1)
            last = end_day - dt.timedelta(days=1)
            if last <= start_day:
                return short_day(start_day)
            return f"{short_day(start_day)} → {short_day(last)}"
        start = dt.datetime.fromisoformat(str(start_raw))
        end = dt.datetime.fromisoformat(str(end_raw)) if end_raw else None
        if zone:
            from zoneinfo import ZoneInfo
            try:
                start = start.astimezone(ZoneInfo(zone))
                if end:
                    end = end.astimezone(ZoneInfo(zone))
            except Exception:
                pass
        if end and end.date() == start.date():
            return f"{short_day(start)} {start:%H:%M}–{end:%H:%M}"
        if end:
            return f"{short_day(start)} {start:%H:%M} → {short_day(end)} {end:%H:%M}"
        return f"{short_day(start)} {start:%H:%M}"
    except Exception:
        return ''


def calendar_change_copy(change, zone, ui):
    """Title and facts for one imported change: what the event is now and what it was. None when nothing shown changed."""
    before, after = (e if e and e.get('status') != 'cancelled' and 'subject' in e else None
                     for e in (change['before'], change['after']))
    when = lambda e: _human_when(e['start'], e['end'], e['all_day'], zone)
    if after and not before:
        return ui.text('New: {title}', title=after['subject']), [when(after), after.get('location', '')]
    if before and not after:
        return ui.text('Canceled: {title}', title=before['subject']), [when(before)]
    shown = ('subject', 'start', 'end', 'all_day', 'location')
    if not after or [before.get(k) for k in shown] == [after.get(k) for k in shown]:
        return None  # Notes-only changes are mostly invitation boilerplate.
    facts = [ui.text('Renamed from “{title}”', title=before['subject'])] if after['subject'] != before['subject'] else []
    old, new = when(before), when(after)
    timed = not (before['all_day'] or after['all_day']) and '→' not in old + new
    if old != new and timed and old.rsplit(' ', 1)[0] == new.rsplit(' ', 1)[0]:
        new = new.rsplit(' ', 1)[1]  # Same day: only the clock moved.
    facts.append(new if old == new else old + ' → ' + new)
    old, new = before.get('location', ''), after.get('location', '')
    if old != new:
        facts.append(ui.text('Place: {old} → {new}', old=old, new=new) if old and new else
                     ui.text('Place: {place}', place=new) if new else ui.text('No place listed now (was {place})', place=old))
    return ui.text('Changed: {title}', title=after['subject']), facts


def _clash_label(subject, start_raw, end_raw, all_day, zone):
    when = _human_when(start_raw, end_raw, all_day, zone)
    subject = (subject or '').strip()
    if when and subject:
        return f'{subject} ({when})'
    return subject or when


def reminder_eligible(store, task, day):
    """Missing trigger evidence is unknown, never guessed from wake time or the clock now."""
    if task.get('defer_until') and day < task['defer_until']:
        return False
    if not task.get('when'):
        return True
    from zoneinfo import ZoneInfo
    if task['when'].get('unless_experiment_plan'):
        for candidate in store.all():
            if candidate.get('work_kind') != 'experiment' or candidate['status'] == 'cancelled':
                continue
            try:
                if store.occurrence(candidate, day)['status'] != 'cancelled':
                    return False
            except ValueError:
                pass
    if task['when'].get('unless_experiment_plan') or task['when'].get('unless_timed_plan'):
        from goodmorning.calendar.calendar_store import CalendarStore
        target = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(), ZoneInfo(task['timezone']))
        calendar_path = store.inbox.directory/'calendar.sqlite'
        if calendar_path.is_symlink():
            raise ValueError('unsafe_path: calendar conditions must belong to this runtime')
        calendar = CalendarStore(str(calendar_path), readonly=True)
        try:
            for row in calendar.query(target, target + dt.timedelta(days=1), details=True, limit=-1):
                if task['when'].get('unless_experiment_plan') and '实验' in (row['subject'] + ' ' + row.get('notes','')):
                    return False
                if task['when'].get('unless_timed_plan') and not row.get('all_day'):
                    return False
        finally:
            calendar.close()
    if 'morning_before' not in task['when']:
        return True
    from goodmorning.briefings.briefing_stream import bounded_json
    from goodmorning.web.generation_clock import timestamp
    path = store.inbox.directory/'browser-jobs/jobs.json'
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('unsafe_path: generation trigger must belong to this runtime')
    if not path.exists():
        return False
    jobs = bounded_json(path, 2_000_000)
    job = jobs.get(day + '.gm', {})
    started = job.get('generation_started_at')
    if started is None:
        return False
    local = dt.datetime.fromtimestamp(timestamp(started), ZoneInfo(task['timezone']))
    return local.date().isoformat() == day and local.strftime('%H:%M') < task['when']['morning_before']


def outstanding_reminder(store, task, today):
    """One outstanding reminder; actual completion clears it without rewriting missed days."""
    rule = task['repeat']
    stop = min(today, rule.get('until') or today)
    if stop < rule['start']:
        return None
    start = dt.date.fromisoformat(rule['start'])
    distance = (dt.date.fromisoformat(stop) - start).days
    due = start + dt.timedelta(days=distance // rule['interval_days'] * rule['interval_days'])
    while due.isoformat() in rule.get('exclude', []):
        due -= dt.timedelta(days=rule['interval_days'])
    if due < start:
        return None
    day = due.isoformat()
    completed = store.db.execute("SELECT MAX(date) FROM task_occurrences WHERE task_id=? AND status='done'", (task['id'],)).fetchone()[0]
    if completed and completed >= day:
        return None
    occurrence = store.occurrence(task, day)
    if occurrence['status'] in ('done','cancelled'):
        return None
    row = task_row(task, day, occurrence, 'still-open')
    from goodmorning.web import language as ui
    row['detail'] += ('\n' if row['detail'] else '') + ui.text('One outstanding reminder; completion is not yet confirmed. No makeup backlog and no change to the original cadence.')
    first = start
    if completed:
        elapsed = (dt.date.fromisoformat(completed) - start).days
        first = start + dt.timedelta(days=max(0, elapsed // rule['interval_days'] + 1) * rule['interval_days'])
    while first < due and (first.isoformat() in rule.get('exclude', []) or store.occurrence(task, first.isoformat())['status'] == 'cancelled'):
        first += dt.timedelta(days=rule['interval_days'])
    if first.isoformat() < today:
        row['detail'] += '\n' + ui.text('Use the requested firmer follow-up: a prior planned workout remains unconfirmed. Ask for an actual completion report; do not assume failure or shame the user.')
    return row


def task_row(task, day='', occurrence=None, group='other'):
    return {'id': task['id'], 'revision': task['revision'], 'occurrence_id': occurrence['id'] if occurrence else '',
            'date': day, 'status': occurrence['status'] if occurrence else task['status'],
            'title': task['title'], 'detail': task['detail'], 'project': task['project'],
            'optional': task['optional'], 'priority': task['priority'], 'due_date': task['due_date'],
            'due_at': task['due_at'], 'timezone': task['timezone'], 'group': group,
             'source_entry_id': task['source_entry_id'], 'owner': 'tasks',
              'report_detail': occurrence['detail'] if occurrence else '', 'created_at': task['created_at'],
              'category': task['category'], 'kind': task.get('kind', ''),
              **{key:task[key] for key in ('when','due_soft','follow_up','notice','extra','display') if task.get(key)},
              **({'prep_for': task['repeat']['event_subject'], 'offset_days': task['repeat'].get('offset_days', 0)}
                 if 'event_subject' in (task['repeat'] or {}) else {})}


PROJECT_STEPS = 3


def triggered(task):
    """Whether something other than every morning decides when this item appears."""
    when = task.get('when') or {}
    return bool(task['planned_date'] or task['repeat'] or when.get('planned_task_id') or when.get('custom_rule_id'))


def waiting(store, task):
    """A step that waits for another task stays hidden until that task is closed."""
    if not task.get('after'):
        return False
    try:
        return store.show(task['after'])['status'] not in ('done', 'cancelled')
    except ValueError:
        return False


def notice_days(item, kind, default):
    """Days before an item's own day that this edition starts showing it."""
    return (item.get('notice') or {}).get('morning' if kind == 'gm' else 'evening', default)


def notice_end(today, item, kind, default):
    return (dt.date.fromisoformat(today) + dt.timedelta(days=notice_days(item, kind, default))).isoformat()


def coming(row, task):
    """A row shown ahead of its day; without early completion it is only a heads-up."""
    return {**row, 'group': 'coming', 'preview': (task.get('notice') or {}).get('early') is False}


def task_view(store, today, kind='gm', offset=0, limit=7, owned=()):
    """One focus day: the morning shows today, the evening previews tomorrow.

    Before their day appear only hard deadlines (default: morning seven days,
    evening due tomorrow), items with their own notice, and unfinished earlier work."""
    day = dt.date.fromisoformat(today)
    start = day + dt.timedelta(days=kind == 'gn')
    rows = habit_rows(store, start.isoformat(), chase=kind == 'gm')
    for task in store.all():
        if task['status'] in ('done', 'cancelled') or task['category'] == 'reference' or waiting(store, task):
            continue
        nudge = task['category'] in ('nudge', 'errand')
        if nudge and kind == 'gn':
            continue  # Heads-ups and errands are for the morning; the evening never asks about them.
        scheduled = []
        target = start.isoformat()
        quiet = kind == 'gn' and notice_days(task, kind, 1) == 0  # Asked never to be told the night before.
        if not quiet and reminder_eligible(store, task, target) and (task.get('follow_up') != 'until-done' or planned_on(task, target)):
            try:
                occ = store.occurrence(task, target)
            except ValueError:
                occ = None
            if occ and occ['status'] not in ('done', 'cancelled'):
                scheduled.append(task_row(task, target, occ, 'nudge' if nudge else 'planned'))
        if nudge:
            if scheduled:
                rows.extend(scheduled)
            elif not triggered(task) and reminder_eligible(store, task, today):
                rows.append(task_row(task, today, None, 'nudge'))
            continue
        if task.get('when') and not scheduled and not (kind == 'gn' and reminder_eligible(store, task, today)):
            continue  # A future morning's trigger has not been established.
        if task.get('defer_until') and today < task['defer_until']:
            continue
        if task.get('notice') and not scheduled and not task['due_date'] and (task['planned_date'] or task['repeat']):
            # The nearest later day within the notice, as a heads-up or an early option.
            for n in range(1, notice_days(task, kind, 0) + 1 - int(kind == 'gn')):
                target = (start + dt.timedelta(days=n)).isoformat()
                if not reminder_eligible(store, task, target):
                    continue
                try:
                    occ = store.occurrence(task, target)
                except ValueError:
                    continue  # Not one of its days.
                if occ['status'] not in ('done', 'cancelled'):
                    scheduled.append(coming(task_row(task, target, occ), task))
                break
        if scheduled:
            rows.extend(scheduled)
        elif kind == 'gm' and chasing(task, today):
            rows.append(task_row(task, today, store.occurrence(task, today), 'follow-up'))
        elif task['due_date'] and task['due_date'] <= notice_end(today, task, kind, 7 if kind == 'gm' else 1):
            if task['due_date'] > today and (task.get('notice') or {}).get('early') is False:
                rows.append(coming(task_row(task, task['due_date']), task))  # Only on the day: a heads-up until then.
            else:
                rows.append(task_row(task, group='deadline'))
        elif kind == 'gn' and (task['planned_date'] == today or task['repeat']):
            try:
                occ = store.occurrence(task, today)
            except ValueError:
                continue
            if occ['status'] not in ('done', 'cancelled'):
                rows.append(task_row(task, today, occ, 'still-open'))
        elif kind == 'gn' and task['status'] in ('partial', 'blocked'):
            rows.append(task_row(task, group='still-open'))
        elif kind == 'gm' and task['planned_date'] and task['planned_date'] < today:
            occ = store.occurrence(task, task['planned_date'])
            if occ['status'] not in ('done', 'cancelled'):
                rows.append(task_row(task, task['planned_date'], occ, 'still-open'))
        elif (kind == 'gm' and not task['planned_date'] and not task['repeat'] and (not task['defer_until'] or task['defer_until'] <= today)
              and not (task.get('notice') and task['due_date'])):  # A chosen notice waits until it starts.
            rows.append(task_row(task))
    for task in store.all():
        if task['status'] in ('done','cancelled') or task.get('follow_up') != 'one-outstanding':
            continue
        row = outstanding_reminder(store, task, today)
        if row:
            existing = next((r for r in rows if (r['id'],r['occurrence_id']) == (row['id'],row['occurrence_id'])), None)
            if existing:
                existing['detail'] = row['detail']
            else:
                rows.append(row)
    rows = [row for row in rows if (row['id'], row['occurrence_id']) not in owned]
    # The secretary does errands itself; they are never cards unless it reports a finding.
    from goodmorning.web import language as ui
    from .display import wording
    errands = []
    for r in rows:
        if r['category'] == 'errand':
            heading = wording(r, 'task', 'morning', ui.current())  # The card heading; the body is each morning's result.
            errands.append({'id': r['id'], 'revision': r['revision'], 'title': heading['title'] if heading else r['title'],
                            'worded': bool(heading), 'instruction': r['detail'], 'extra': r.get('extra', '')})
    if errands:
        last = errand_memory(store.inbox.directory, today)
        for errand in errands:
            errand['last'] = last.get(errand['id'])
    rows = [row for row in rows if row['category'] != 'errand']
    rank = {'nudge': 0, 'planned': 1, 'follow-up': 2, 'still-open': 3, 'coming': 4, 'deadline': 5, 'other': 6}  # Dated days before the undated backlog.
    priority = {'high': 0, 'normal': 1, '': 2, 'low': 3}
    rows.sort(key=lambda r: (rank[r['group']], r['date'], r['optional'], priority[r['priority']], r['due_date'] or '9999', r['created_at'], r['id']))
    # Project work offers the next few steps per project, not the whole backlog.
    shown = {}
    kept = []
    for row in rows:
        if row['group'] == 'other' and row['category'] == 'project':
            shown[row['project']] = shown.get(row['project'], 0) + 1
            if shown[row['project']] > PROJECT_STEPS:
                continue
        kept.append(row)
    rows = kept
    return {'items': rows[offset:offset + limit], 'total': len(rows),
            'next_offset': offset + limit if offset + limit < len(rows) else None, 'errands': errands}


TIDY_DAYS = {'still-open': 7, 'deadline': 7, 'other': 30}  # Days without any change before a morning row counts as stale.
TIDY_EVERY = 7
TIDY_REST = 28  # Days before an item asked about, and not kept, can be asked about again.
TIDY_LIMIT = 3


def stale_tasks(store, today):
    """Morning rows untouched for a while, oldest first: the weekly evening tidy-up asks about these.

    Age counts from the row's own day (workday, deadline, or creation for undated
    work), a later start day or any update. Items asked about recently or kept
    ("keep it, stop asking") are left out; a night that already offered a tidy-up
    offers the same items again."""
    day = dt.date.fromisoformat(today)
    last, asked, kept, tonight = '', {}, set(), None
    for item_id, action, snapshot in store.db.execute(
            "SELECT item_id,action,snapshot FROM task_events WHERE action IN ('tidy','tidy-offer') ORDER BY seq"):
        night, data = item_id[5:], json.loads(snapshot)
        ids = data['offered'] if action == 'tidy-offer' else list(data['answers'])
        if action == 'tidy-offer' and night == today:
            tonight = set(ids)
        last = max(last, night)
        for identifier in ids:
            asked[identifier] = max(asked.get(identifier, ''), night)
        if action == 'tidy':
            kept |= {identifier for identifier, choice in data['answers'].items() if choice == 'keep'}
    if tonight is None and last > (day - dt.timedelta(days=TIDY_EVERY)).isoformat():
        return []
    rested = (day - dt.timedelta(days=TIDY_REST)).isoformat()
    rows = []
    for row in task_view(store, today, 'gm', limit=10_000)['items']:
        if row['group'] not in TIDY_DAYS or row['category'] in UNCHECKED:
            continue
        if tonight is not None:
            if row['id'] not in tonight:
                continue
        elif row['id'] in kept or asked.get(row['id'], '') > rested:
            continue
        task = store.show(row['id'])
        base = {'still-open': task['planned_date'], 'deadline': task['due_date'], 'other': task['created_at'][:10]}[row['group']]
        since = max(base, task['defer_until'], task['updated_at'][:10])
        if tonight is not None or (day - dt.date.fromisoformat(since)).days >= TIDY_DAYS[row['group']]:
            rows.append({'id': task['id'], 'revision': task['revision'], 'title': task['title'],
                         'project': task['project'], 'group': row['group'], 'date': base, 'since': since})
    return sorted(rows, key=lambda r: (r['since'], r['id']))[:TIDY_LIMIT]


def errand_memory(directory, today, days=60):
    """The latest earlier morning's result for each errand, read from saved briefings; the morning never edits records."""
    from goodmorning.briefings.briefing_document import validate
    from goodmorning.briefings.briefing_stream import bounded_json
    found = {}
    sources = sorted((Path(directory) / 'daily').glob('????-??-??.gm.json'), reverse=True)
    for source in [s for s in sources if s.name[:10] < today][:days]:
        try:
            document = validate(bounded_json(source, 150_000))
        except (ValueError, OSError):
            continue  # An unreadable edition only loses that day's memory.
        for section in document['sections']:
            for block in section[1]:
                if section[0] == 'tasks' and block[0] == 'errands':
                    for row in block[1]:
                        found.setdefault(row[0], {'date': source.name[:10], 'note': row[5]})
    return found


def planned_day(store, day, completed=True, chase=False):
    """Agreed work for one day. Heads-ups, errands and reference notes are never work to tick off."""
    rows = []
    for task in store.all():
        if task['status'] == 'cancelled' or task['category'] in UNCHECKED:
            continue
        if not reminder_eligible(store, task, day):
            continue
        if task.get('follow_up') == 'until-done' and not planned_on(task, day) and not (chase and chasing(task, day)):
            continue
        try:
            occ = store.occurrence(task, day)
        except ValueError:
            continue
        if task['status'] == 'done' and occ['revision'] == 0:
            occ = {**occ, 'status': 'done'}
        if occ['status'] != 'cancelled' and (completed or occ['status'] != 'done'):
            rows.append(task_row(task, day, occ, 'planned'))
    return rows


def calendar_day_extras(store, day, today):
    """Schedule-tab markers that reserve no workday: hard deadlines and habit days.

    A habit's future days are projections from its saved rule and confirmed
    completions; they move when the user actually does it earlier or later."""
    rows = []
    for task in store.all():
        if task['category'] == 'deadline' and task['due_date'] == day and task['status'] != 'cancelled' and not task['repeat']:
            rows.append({**task_row(task, day, None, 'due'), 'marker': 'due'})
    if day >= today:
        rows.extend({**row, 'marker': 'flexible'} for row in habit_rows(store, day, chase=day == today))
    from .custom_store import CustomStore
    try:
        custom = CustomStore(store.inbox.directory, write=False)
    except ValueError:
        return rows  # No habits saved yet.
    try:
        for rule in custom.all():
            if day <= today and custom.db.execute("SELECT 1 FROM custom_completions WHERE rule_id=? AND date=? AND status='done'",
                                                  (rule['id'], day)).fetchone():
                rows = [row for row in rows if row['id'] != rule['id']]  # A done day shows once, as done.
                rows.append({**habit_row(rule, day, 'done'), 'marker': 'flexible', 'closed': rule['status'] != 'open'})
    finally:
        custom.close()
    return rows


def habit_row(rule, day, status):
    return {'id': rule['id'], 'revision': rule['revision'], 'occurrence_id': f"cuoc_{rule['id'][3:]}_" + day.replace('-', ''),
            'date': day, 'status': status, 'title': rule['title'], 'detail': rule['detail'], 'project': '',
            'optional': False, 'priority': '', 'due_date': '', 'due_at': '', 'timezone': rule['timezone'],
            'report_detail': '', 'category': 'habit', 'kind': '', 'group': 'planned', 'created_at': '', 'source_entry_id': '',
            'owner': 'tasks'}


def habit_rows(store, day, chase):
    """Habits due on one day. Only the current day carries a missed-day follow-up;
    later days are projections that move when the user actually trains."""
    from .custom_store import CustomStore
    try:
        custom = CustomStore(store.inbox.directory, write=False)
    except ValueError:
        return []  # No habits saved yet.
    try:
        rows = []
        for rule in custom.all():
            if rule['status'] != 'open':
                continue
            decision = custom.due(rule, day)
            if decision['due'] and (chase or decision['reason'] == 'due'):
                rows.append(habit_row(rule, day, 'open'))
        return rows
    finally:
        custom.close()


def reported_day(store, day):
    """Actual dated reports only; a global status/audit timestamp is not daily evidence."""
    return [task_row(store.show(row['task_id']), day, dict(row), 'reported')
            for row in store.db.execute('SELECT * FROM task_occurrences WHERE date=? AND status!=?', (day, 'cancelled'))]


def feedback_day(store, day):
    """Today's plan plus saved morning choices, without assigning new workdays."""
    rows = {row['id']: row for row in planned_day(store, day, chase=True)}
    for task in store.all():
        # A hard deadline that has arrived is checked tonight even without a morning edition.
        if (task['id'] not in rows and task['category'] == 'deadline' and task['due_date'] <= day
                and task['status'] not in ('done', 'cancelled') and not waiting(store, task)):
            rows[task['id']] = {**task_row(task, day, {'id': occurrence_id(task['id'], day), 'status': task['status'], 'detail': ''}, 'reported'),
                                'actual': True, 'due_now': True}
    morning = store.inbox.directory / 'daily' / (day + '.gm.json')
    if not morning.exists():
        return list(rows.values())
    from goodmorning.briefings.briefing_document import validate
    from goodmorning.briefings.briefing_stream import bounded_json
    document = validate(bounded_json(morning, 150_000))
    identifiers = {row[0] for section in document['sections'] if section[0] == 'tasks'
                   for block in section[1] if block[0] == 'actions' for row in block[1]}
    for task in store.all():
        if (task['id'] not in identifiers or task['id'] in rows or task['status'] in ('done', 'cancelled')
                or task['category'] in UNCHECKED):
            continue
        if (task.get('notice') or {}).get('early') is False and (task['repeat'] or day < (task['planned_date'] or task['due_date'] or day)):
            continue  # Only possible on its own day: never offered as done early.
        # Selection reports actual work today; the archived date/revision is not a live plan.
        occurrence = store.db.execute('SELECT * FROM task_occurrences WHERE task_id=? AND date=?',
                                      (task['id'], day)).fetchone()
        occurrence = dict(occurrence) if occurrence else {'id': occurrence_id(task['id'], day), 'status': task['status'], 'detail': ''}
        if occurrence['status'] == 'cancelled':
            continue
        row = task_row(task, day, occurrence, 'reported')
        row['actual'] = True
        rows[task['id']] = row
    return list(rows.values())


IDEA_CYCLE = 14  # Days between a clear idea's morning returns.
IDEA_REST = 7  # Days after capture or the last change before its first return.


def idea_return(entry, today, kind):
    """The Reminders line for a clear idea back this morning, or None; it never asks for a reply.

    A review date that has arrived keeps the idea there every morning until the
    date is cleared or moved, so a skipped morning loses nothing. Otherwise the
    idea comes back for one morning each cycle, and the entry's sequence picks
    its day, so a batch saved together returns on different mornings."""
    if kind != 'gm':
        return None
    if entry['review_after'] and entry['review_after'] <= today:
        return 'You asked to look at this idea again. It stays here until you review it or pick a new date.'
    day = dt.date.fromisoformat(today)
    rested = day >= dt.date.fromisoformat(entry['updated_at'][:10]) + dt.timedelta(days=IDEA_REST)
    if rested and (day.toordinal() - entry['seq']) % IDEA_CYCLE == 0:
        return 'A saved idea, back for another look. Nothing needs doing unless it still interests you.'
    return None


def attention(store, today, kind, offset=0, limit=7, calendar_changes=()):
    rows = []
    db = store.db
    from goodmorning.web import language as ui
    for entry in db.execute("SELECT seq,id,revision,kind,summary,questions,needs_review,review_after,updated_at FROM entries WHERE "
                            + store.inbox.active_sql + ' ORDER BY seq'):
        import json
        questions = json.loads(entry['questions'])
        if entry['review_after'] and entry['review_after'] > today:
            continue
        if entry['kind'] == 'todo' and not questions and not entry['needs_review']:
            continue
        if entry['kind'] == 'idea' and not questions and not entry['needs_review']:
            line = idea_return(entry, today, kind)
            if not line:
                continue
            questions = [ui.text(line)]
        elif not questions and not entry['needs_review'] and not entry['review_after']:
            continue
        rows.append({'id': entry['id'], 'revision': entry['revision'], 'title': entry['summary'],
                     'questions': questions, 'needs_review': bool(entry['needs_review']), 'owner': 'attention'})
    represented = {row['id'] for row in rows}
    for draft in store.all(draft=True):
        if draft['state'] == 'ready-for-confirmation' and draft['source_entry_id'] not in represented:
            entry = store.inbox.show(draft['source_entry_id'])
            if entry.get('review_after') and entry['review_after'] > today:
                continue
            rows.append({'id': draft['id'], 'revision': draft['revision'], 'title': draft['title'],
                         'questions': ['Confirm the exact appointment before adding it.'], 'needs_review': False,
                         'draft_id': draft['id'], 'event': draft['event'], 'owner': 'attention'})
    rows.extend(calendar_changes)
    return {'items': rows[offset:offset + limit], 'total': len(rows),
            'next_offset': offset + limit if offset + limit < len(rows) else None}


def confirmed_drafts(store, start, end, converted=()):
    """Unknown-time attendance has a date, not invented interval endpoints.

    A weekly series appears once on each of its dates, each with its own card ID."""
    rows = []
    for draft in store.all(draft=True):
        if draft['state'] != 'needs-details' or not draft['confirmed_day'] or draft['id'] in converted:
            continue
        last = (dt.date.fromisoformat(end) - dt.timedelta(days=1)).isoformat()
        days = series_days(draft['repeat'], start, last) if draft.get('repeat') else [draft['date']]
        for day in days:
            if start <= day < end:
                rows.append({**draft, 'id': draft['id'] + ('@' + day if draft.get('repeat') else ''), 'date': day,
                             'draft': True, 'subject': draft['title'], 'time': 'TBC', 'category': 'appointment'})
    return rows


def converted_draft_ids(calendar):
    # A conversion can move attendance outside the displayed window before its
    # inbox finalization. Identity, not the current date query, suppresses the draft.
    # A converted series saves one event per date as DRAFT@DATE.
    return {row[0].split('@')[0] for row in calendar.con.execute(
        "SELECT external_id FROM events WHERE source='custom' AND approved_json IS NOT NULL")}


NOTICE_LIMIT = 60


def event_day(event, zone):
    from goodmorning.calendar.calendar_store import endpoints
    from zoneinfo import ZoneInfo
    return endpoints(event)[0].astimezone(ZoneInfo(zone)).date().isoformat()


def schedule(runtime, today, kind, store=None, offset=0, limit=7):
    from goodmorning.runtime_files import profile_fields
    from goodmorning.calendar.calendar_store import CalendarStore, endpoints
    from zoneinfo import ZoneInfo
    start_day = dt.date.fromisoformat(today) + dt.timedelta(days=kind == 'gn')
    end_day = start_day + dt.timedelta(days=1)  # One focus day: today for gm, tomorrow for gn.
    result = {'items': [], 'warnings': [], 'calendar_changes': [],
              'window': {'start': start_day.isoformat(), 'end': (end_day - dt.timedelta(days=1)).isoformat()}}
    converted = set()
    calendar = None
    try:
        zone = profile_fields(runtime)['timezone']
        start = dt.datetime.combine(start_day, dt.time(), ZoneInfo(zone))
        end = dt.datetime.combine(end_day, dt.time(), ZoneInfo(zone))
        # A source-linked account view never follows another account's process override.
        path = Path(runtime) / 'calendar.sqlite'
        if path.is_symlink():
            raise ValueError('Unsafe calendar path')
        calendar = CalendarStore(str(path), readonly=True)
        calendar.con.execute('BEGIN')
        result['items'] = [{**item, 'category': 'occasion' if item.get('all_day') else 'appointment'}
                           for item in calendar.query(start, end, details=True, limit=-1)
                           if not (kind == 'gn' and notice_days(item, kind, 1) == 0)]
        # Advance notice: a later appointment or occasion the user asked to hear about earlier.
        horizon = dt.datetime.combine(dt.date.fromisoformat(today) + dt.timedelta(days=NOTICE_LIMIT + 1), dt.time(), ZoneInfo(zone))
        for item in calendar.query(end, horizon, details=True, limit=-1):
            if item.get('notice') and end_day.isoformat() <= event_day(item, zone) <= notice_end(today, item, kind, 0):
                result['items'].append({**item, 'category': 'occasion' if item.get('all_day') else 'appointment'})
        converted = converted_draft_ids(calendar)
        from goodmorning.web import language as ui
        for change in calendar.changes(f'{today}.{kind}'):
            copy = calendar_change_copy(change, zone, ui)
            if not copy:
                continue
            title, facts = copy
            after = change['after']
            if after and after.get('status') != 'cancelled' and not after.get('all_day'):
                overlaps = [_clash_label(other['subject'], other['start'], other['end'], False, zone)
                            for other in calendar.query(*endpoints(after), details=True, limit=-1)
                            if other['id'] != change['id'] and not other.get('all_day')]
                if overlaps:
                    facts.append(ui.text('Overlaps {events}', events='; '.join(dict.fromkeys(overlaps))))
            result['calendar_changes'].append({'id': change['id'], 'revision': change['revision'], 'title': title,
                                               'questions': [' · '.join(f for f in facts if f)],
                                               'needs_review': False, 'owner': 'attention'})
        result['timezone'] = zone
    except (ValueError, KeyError, OSError, sqlite3.Error):
        result['warnings'].append('Calendar unavailable; saved tasks do not establish free time.')
    finally:
        if calendar:
            calendar.close()
    result['items'].extend(holiday_items(runtime, start_day.isoformat()))
    if store:
        result['items'].extend(row for row in confirmed_drafts(store, start_day.isoformat(), end_day.isoformat(), converted)
                               if not (kind == 'gn' and notice_days(row, kind, 1) == 0))
        nearest = {}
        horizon_day = (dt.date.fromisoformat(today) + dt.timedelta(days=NOTICE_LIMIT + 1)).isoformat()
        for row in confirmed_drafts(store, end_day.isoformat(), horizon_day, converted):
            base = row['id'].split('@')[0]
            if row.get('notice') and base not in nearest and row['date'] <= notice_end(today, row, kind, 0):
                nearest[base] = row  # Only the next class of a series.
        result['items'].extend(nearest.values())
        indexed = {row['id']: row for row in result['items']}
        for task in store.all():
            event = indexed.get(task['calendar_event_id'])
            if not event or event.get('draft') or not task['planned_date'] or task['status'] in ('done', 'cancelled'):
                continue
            begin, finish = [p.astimezone(ZoneInfo(zone)) for p in endpoints(event)]
            target = dt.datetime.combine(dt.date.fromisoformat(task['planned_date']), dt.time(), ZoneInfo(zone))
            if begin < target + dt.timedelta(days=1) and finish > target:
                linked = task_row(task, task['planned_date'], store.occurrence(task, task['planned_date']), 'planned')
                event.setdefault('linked_actions', []).append(linked)
    result['owned_tasks'] = [(row['id'], row['occurrence_id']) for event in result['items'] for row in event.get('linked_actions', [])]
    if result.get('timezone'):
        result['items'].sort(key=lambda r: (event_cells(r, result['timezone'])[0],
                                           -1 if r.get('holiday') else 2 if r.get('draft') else 0 if r.get('all_day') else 1,
                                           event_cells(r, result['timezone'])[1]))
    result['total'] = len(result['items'])
    result['next_offset'] = offset + limit if limit is not None and offset + limit < result['total'] else None
    result['items'] = result['items'][offset:offset + limit] if limit is not None else result['items']
    return result


def holiday_items(runtime, day):
    """The focus day's public holidays and make-up workdays: computed cards with stable IDs, not calendar events."""
    import hashlib
    from goodmorning.calendar import public_holidays
    from goodmorning.runtime_files import profile_fields
    from goodmorning.web import language as ui
    try:
        codes = public_holidays.regions(profile_fields(runtime).get('holiday_countries'))
    except ValueError:
        return []  # A bad optional setting shows no holidays; the setup check reports it.
    end = (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()
    listed = public_holidays.days(codes, day, end, ui.current()).get(day, [])
    return [{'id': 'hd_' + hashlib.sha256(f"{','.join(entry['regions'])}:{day}:{entry['kind']}".encode()).hexdigest()[:16],
             'revision': 1, 'holiday': entry['kind'], 'date': day, 'subject': entry['title'], 'all_day': True, 'category': 'holiday'}
            for entry in public_holidays.shown(listed, codes, ui.current())]


def prepare(runtime, today, kind, offset=0, limit=7):
    if not Path(runtime, 'inbox.sqlite').exists():
        return {'tasks': {'items': [], 'total': 0, 'next_offset': None},
                'attention': {'items': [], 'total': 0, 'next_offset': None},
                'schedule': schedule(runtime, today, kind), 'warnings': ['Task store unavailable; setup is required.']}
    inbox = InboxStore(runtime)
    try:
        store = TaskStore(inbox)
        with inbox.db:
            inbox.db.execute('BEGIN')
            agenda = schedule(runtime, today, kind, store, offset, limit)
            result = {'tasks': task_view(store, today, kind, offset, limit, agenda['owned_tasks']),
                    'attention': attention(store, today, kind, offset, limit, agenda['calendar_changes']),
                    'schedule': {k: v for k, v in agenda.items() if k not in ('calendar_changes', 'owned_tasks')}, 'warnings': []}
            outcomes = reported_day(store, today) if kind == 'gn' else []
            result['today'] = outcomes[offset:offset + limit]
            result['today_total'] = len(outcomes)
            result['today_next_offset'] = offset + limit if offset + limit < len(outcomes) else None
            result['blocks'] = {
                'tasks': ['actions', [action_cells(r, place_for(kind)) for r in result['tasks']['items']]],
                'schedule': ['events', [[r['id'], r['revision'], *event_cells(r, events_timezone(runtime), place_for(kind))] for r in result['schedule']['items']]],
                'attention': ['decisions', [[r['id'], r['revision'], r['title'], '\n'.join(r['questions']) or 'Review the supplied details.'] for r in result['attention']['items']]],
                'today': ['actions', [action_cells(r) for r in result['today'] if r['status'] != 'open']]}
            # Rows without fresh stored wording: the briefing may reword these for the page, never the item.
            from goodmorning.web import language as ui
            from .display import wording
            result['tasks']['fallback'] = [r['id'] for r in result['tasks']['items']
                                           if r.get('category') == 'habit' or not wording(r, 'task', place_for(kind), ui.current())]
            return result
    finally:
        inbox.close()


def validate_sources(runtime, document, today, kind):
    """Validate source-linked rows before publish/save, never on historical reads."""
    if document['v'] != 2:
        return
    if not any(block[0] in ('actions', 'events', 'decisions', 'errands') for section in document['sections'] for block in section[1]):
        return
    # One consistent task snapshot; approved calendar is another read-only store.
    inbox = InboxStore(runtime)
    from goodmorning.web import language as ui
    token = ui.CURRENT.set(document.get('lang', 'en'))
    try:
        store = TaskStore(inbox)
        inbox.db.execute('BEGIN')
        agenda = schedule(runtime, today, kind, store, limit=None)
        view = task_view(store, today, kind, limit=1000000, owned=agenda['owned_tasks'])
        tasks = {(r['id'], r['occurrence_id']): r for r in view['items']}
        errands = {r['id']: r for r in view['errands']}
        outcomes = {(r['id'], r['occurrence_id']): r for r in reported_day(store, today)}
        events = {r['id']: r for r in agenda['items']}
        decisions = {r['id']: r for r in attention(store, today, kind, limit=1000000, calendar_changes=agenda['calendar_changes'])['items']}
        for section in document['sections']:
            for block in section[1]:
                tag = block[0]
                if tag == 'actions':
                    available = outcomes if section[0] == 'today' else tasks
                    for row in block[1]:
                        identifier, revision, occ, day, status, title, detail = row
                        source = available.get((identifier, occ))
                        # Title and detail are display wording; the saved item is matched by identity, revision, date and status.
                        if not source or [revision, day, status] != [source['revision'], source['date'], source['status']]:
                            raise ValueError('source_conflict: action identity, date, status or revision is unsupported')
                elif tag == 'errands':
                    for identifier, revision, *_ in block[1]:
                        source = errands.get(identifier)
                        if not source or revision != source['revision']:
                            raise ValueError('source_conflict: errand is not due this morning or changed')
                elif tag == 'events':
                    for identifier, revision, *cells in block[1]:
                        source = events.get(identifier)
                        if not source or revision != source['revision'] or cells != event_cells(source, events_timezone(runtime), place_for(kind)):
                            raise ValueError('source_conflict: event is unapproved, changed or outside the edition window')
                elif tag == 'decisions':
                    for identifier, revision, title, detail in block[1]:
                        source = decisions.get(identifier)
                        if not source or [revision, title] != [source['revision'], source['title']]:
                            raise ValueError('source_conflict: decision is deferred, changed or not due for review')
    finally:
        inbox.close()
        ui.CURRENT.reset(token)


def events_timezone(runtime):
    from goodmorning.runtime_files import profile_fields
    return profile_fields(runtime)['timezone']


def place_for(kind):
    """Which stored wording an edition shows: the morning gets it done, the evening gets ready for tomorrow."""
    return 'evening' if kind == 'gn' else 'morning'


def action_cells(row, place='morning'):
    from goodmorning.web import language as ui
    from .display import wording
    stored = wording(row, 'task', place, ui.current()) if row.get('category') != 'habit' else None
    title = stored['title'] if stored else row['title']
    cleaned = stored['detail'] if stored else clean_task_detail(row.get('title', ''), row.get('detail', ''))
    detail = [cleaned] if cleaned else []
    if row['project']:
        detail.append(ui.text('Project: {name}', name=row['project']))
    if row['optional']:
        detail.append(ui.text('Optional'))
    if row['priority']:
        detail.append(ui.text('Priority: {priority}', priority=row['priority']))
    if row['due_date']:
        detail.append(ui.text('Soft target: {date}' if row.get('due_soft') else 'Due: {date}', date=row['due_at'] or row['due_date']))
    if row.get('kind') == 'nudge':
        detail.insert(0, ui.text('Heads-up only; nothing to tick off'))
    if row.get('preview'):
        detail.insert(0, ui.text('Heads-up: this can only be done on its day'))
    if row.get('follow_up') == 'until-done':
        detail.append(ui.text('Daily follow-up until done'))
    if row.get('prep_for'):
        detail.append(ui.text('Preparation for {subject}', subject=row['prep_for']) if not row.get('offset_days') else
                      ui.text('Preparation for {subject}, {count} day(s) before', subject=row['prep_for'], count=-row['offset_days']))
    if (row.get('when') or {}).get('morning_before'):
        detail.append(ui.text('Reminder trigger: morning starts before {time} ({zone})',
                              time=row['when']['morning_before'], zone=row['timezone']))
    if (row.get('when') or {}).get('unless_experiment_plan'):
        detail.append(ui.text('Not reminded on days with confirmed experiment plans'))
    if (row.get('when') or {}).get('unless_timed_plan'):
        detail.append(ui.text('Not reminded on days with fixed-time plans'))
    # No "To be scheduled" suffix: the date group heading already says it.
    if row['report_detail']:
        detail.append(row['report_detail'])
    return [row['id'], row['revision'], row['occurrence_id'], row['date'], row['status'], title, ' · '.join(detail)]


def event_cells(event, timezone, place='morning'):
    from goodmorning.calendar.calendar_store import endpoints
    from goodmorning.calendar.calendar_safety import clean_preparation
    from zoneinfo import ZoneInfo
    from goodmorning.web import language as ui
    from .display import wording
    if event.get('holiday'):
        return [event['date'], ui.text('Public holiday' if event['holiday'] == 'holiday' else 'Workday'), event['subject'], '', '']
    stored = wording(event, 'draft' if event.get('draft') else 'event', place, ui.current())
    if event.get('draft'):
        return [event['date'], ui.text('TBC'), stored['title'] if stored else event['title'], event['location'],
                stored['detail'] if stored else event['detail']]
    start, end = [p.astimezone(ZoneInfo(timezone)) for p in endpoints(event)]
    if event['all_day']:
        clock = ui.text('All day')
        if (end.date() - start.date()).days > 1:
            clock = ui.text('All day through {date}', date=(end.date() - dt.timedelta(days=1)).isoformat())
    else:
        finish = (end.date().isoformat() + ' ' if end.date() != start.date() else '') + end.strftime('%H:%M')
        clock = start.strftime('%H:%M') + '–' + finish
    notes = stored['detail'] if stored else clean_preparation(event.get('notes', '')) if event.get('notes') else ''
    prep = [notes] if notes else []
    for action in event.get('linked_actions', []):
        linked = wording(action, 'task', place, ui.current())
        prep.append((linked['title'] if linked else action['title']) + ('\n' + action['detail'] if action['detail'] and not linked else ''))
    return [start.date().isoformat(), clock, stored['title'] if stored else event['subject'], event.get('location', ''), '\n'.join(prep)]
