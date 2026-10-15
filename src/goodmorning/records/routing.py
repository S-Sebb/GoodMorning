"""Deterministic edition views. Dates and action identity never come from headings."""
import datetime as dt
import re
from pathlib import Path
import sqlite3

from .inbox_store import InboxStore
from .task_store import TaskStore, chasing, occurrence_id, planned_on, series_days


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
    """Human range for calendar review cards; raw ISO is never shown."""
    try:
        if all_day:
            start_day = dt.date.fromisoformat(str(start_raw)[:10])
            end_day = dt.date.fromisoformat(str(end_raw)[:10]) if end_raw else start_day + dt.timedelta(days=1)
            last = end_day - dt.timedelta(days=1)
            if last <= start_day:
                return start_day.strftime('%a %d %b')
            return f"{start_day.strftime('%a %d %b')} → {last.strftime('%a %d %b')}"
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
            return f"{start.strftime('%a %d %b')} {start.strftime('%H:%M')}–{end.strftime('%H:%M')}"
        if end:
            return f"{start.strftime('%a %d %b %H:%M')} → {end.strftime('%a %d %b %H:%M')}"
        return start.strftime('%a %d %b %H:%M')
    except Exception:
        return ''


def calendar_review_copy(pending, zone, ui):
    """Concise, comfortable review copy: action prefix + subject, human time detail."""
    subject = (pending.get('subject') or '').strip() or ui.text('Cancellation')
    subject = re.sub(r'^(?:Review calendar change|Calendar (?:change|update))\s*[:：]\s*', '', subject, flags=re.IGNORECASE).strip() or subject
    status = str(pending.get('status') or '')
    raw_revision = pending.get('raw_revision') or 0
    if status == 'cancelled' or re.match(r'(?i)^cancell?ed\s*[:：]', subject):
        clean = re.sub(r'(?i)^cancell?ed\s*[:：]\s*', '', subject).strip() or subject
        title = ui.text('Canceled: {title}', title=clean)
    elif (raw_revision or 0) > 1:
        title = ui.text('Updated: {title}', title=subject)
    else:
        # New imports keep the plain subject; the section title already says review.
        title = subject
    when = _human_when(pending.get('start'), pending.get('end'), pending.get('all_day'), zone)
    source = str(pending.get('source') or '').strip()
    facts = ' · '.join(p for p in (source, when) if p)
    if not facts:
        facts = ui.text('Review the supplied details.')
    return title, facts


def _review_interval(start_raw, end_raw, zone):
    """Aware clock interval for clash checks; all-day never reserves clock time."""
    try:
        if not start_raw or not end_raw:
            return None
        start = dt.datetime.fromisoformat(str(start_raw))
        end = dt.datetime.fromisoformat(str(end_raw))
        if start.tzinfo is None or end.tzinfo is None:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(zone) if zone else dt.timezone.utc
            if start.tzinfo is None:
                start = start.replace(tzinfo=tz)
            if end.tzinfo is None:
                end = end.replace(tzinfo=tz)
        if end <= start:
            return None
        return (start, end)
    except Exception:
        return None


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
              **{key:task[key] for key in ('when','due_soft','follow_up') if task.get(key)},
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


def task_view(store, today, kind='gm', offset=0, limit=7, owned=()):
    day = dt.date.fromisoformat(today)
    start = day + dt.timedelta(days=kind == 'gn')
    end = start + dt.timedelta(days=2)
    deadline_end = day + dt.timedelta(days=7)
    rows = []
    for task in store.all():
        if task['status'] in ('done', 'cancelled') or task['category'] == 'reference' or waiting(store, task):
            continue
        nudge = task['category'] == 'nudge'
        if nudge and kind == 'gn':
            continue  # A heads-up is for the morning; the evening never asks about it.
        scheduled = []
        for n in range(1 if nudge else 3):
            target = (start + dt.timedelta(days=n)).isoformat()
            if not reminder_eligible(store, task, target):
                continue
            if task.get('follow_up') == 'until-done' and not planned_on(task, target):
                continue  # The daily follow-up appears once, below, not on every lookahead day.
            try:
                occ = store.occurrence(task, target)
            except ValueError:
                continue
            if occ['status'] not in ('done', 'cancelled'):
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
        if scheduled:
            rows.extend(scheduled)
        elif chasing(task, today):
            rows.append(task_row(task, today, store.occurrence(task, today), 'follow-up'))
        elif task['due_date'] and task['due_date'] <= deadline_end.isoformat():
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
        elif kind == 'gm' and not task['planned_date'] and not task['repeat'] and (not task['defer_until'] or task['defer_until'] <= today):
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
    rank = {'nudge': 0, 'planned': 1, 'follow-up': 2, 'deadline': 2, 'still-open': 3, 'other': 4}
    priority = {'high': 0, 'normal': 1, '': 2, 'low': 3}
    rows.sort(key=lambda r: (rank[r['group']], r['date'], priority[r['priority']], r['due_date'] or '9999', r['created_at'], r['id']))
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
            'next_offset': offset + limit if offset + limit < len(rows) else None}


def planned_day(store, day, completed=True, chase=False):
    """Agreed work for one day. Heads-ups and reference notes are never work to tick off."""
    rows = []
    for task in store.all():
        if task['status'] == 'cancelled' or task['category'] in ('nudge', 'reference'):
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
    from .custom_store import CustomStore
    try:
        custom = CustomStore(store.inbox.directory, write=False)
    except ValueError:
        return rows  # No habits saved yet.
    try:
        for rule in custom.all():
            done = custom.db.execute("SELECT 1 FROM custom_completions WHERE rule_id=? AND date=? AND status='done'",
                                     (rule['id'], day)).fetchone()
            if done:
                status = 'done'
            elif rule['status'] != 'open' or day < today:
                continue
            else:
                decision = custom.due(rule, day)
                if not decision['due'] or (day > today and decision['reason'] != 'due'):
                    continue  # Only today carries a missed-day follow-up; future days show the rhythm.
                status = 'open'
            rows.append({'id': rule['id'], 'revision': rule['revision'], 'occurrence_id': f"cuoc_{rule['id'][3:]}_" + day.replace('-', ''),
                         'date': day, 'status': status, 'title': rule['title'], 'detail': rule['detail'], 'project': '',
                         'optional': False, 'priority': '', 'due_date': '', 'due_at': '', 'timezone': rule['timezone'],
                         'report_detail': '', 'category': 'habit', 'marker': 'flexible'})
    finally:
        custom.close()
    return rows


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
                or task['category'] in ('nudge', 'reference')):
            continue
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


def attention(store, today, offset=0, limit=7, calendar_reviews=()):
    rows = []
    db = store.db
    for entry in db.execute("SELECT id,revision,kind,summary,questions,needs_review,review_after FROM entries WHERE "
                            + store.inbox.active_sql + ' ORDER BY seq'):
        import json
        questions = json.loads(entry['questions'])
        if entry['review_after'] and entry['review_after'] > today:
            continue
        if entry['kind'] == 'todo' and not questions and not entry['needs_review']:
            continue
        if not questions and not entry['needs_review'] and not entry['review_after']:
            continue  # A clear idea is not a recurring clarification obligation.
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
    rows.extend(calendar_reviews)
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


def schedule(runtime, today, kind, store=None, offset=0, limit=7):
    from goodmorning.runtime_files import profile_fields
    from goodmorning.calendar.calendar_store import CalendarStore
    from zoneinfo import ZoneInfo
    start_day = dt.date.fromisoformat(today) + dt.timedelta(days=kind == 'gn')
    end_day = start_day + dt.timedelta(days=3)
    result = {'items': [], 'pending': 0, 'warnings': [], 'reviews': [],
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
                           for item in calendar.query(start, end, details=True, limit=-1)]
        if kind in ('gm', 'gn'):
            # Briefings show the timed schedule for their focus day only
            # (today for morning, tomorrow for evening); all-day and TBC
            # commitments keep the three-day glance. Timed appointments on
            # other days stay out of the edition.
            from goodmorning.calendar.calendar_store import endpoints as _endpoints
            focus_start = start
            focus_end = focus_start + dt.timedelta(days=1)
            kept = []
            for item in result['items']:
                if item.get('draft') or item.get('all_day'):
                    kept.append(item)
                    continue
                try:
                    begin, finish = _endpoints(item)
                except (ValueError, KeyError, TypeError):
                    kept.append(item)
                    continue
                if begin < focus_end and finish > focus_start:
                    kept.append(item)
            result['items'] = kept
        converted = converted_draft_ids(calendar)
        result['pending'] = calendar.stats()['pending']
        from goodmorning.web import language as ui
        pendings = calendar.pending(limit=-1)
        pending_windows = {}
        for candidate in pendings:
            if str(candidate.get('status') or '') == 'cancelled' or candidate.get('all_day'):
                continue
            window = _review_interval(candidate.get('start'), candidate.get('end'), zone)
            if window:
                pending_windows[candidate['id']] = window
        # Pending reviews carry no date filter, so a clash partner can sit far
        # outside the 3-day display window. Check each pending's own interval.
        approved_by_pending: dict[str, list] = {}
        for candidate in pendings:
            window = pending_windows.get(candidate['id'])
            if not window:
                continue
            try:
                neighbours = calendar.query(window[0], window[1], details=True, limit=-1)
            except (ValueError, KeyError, OSError, sqlite3.Error):
                neighbours = []
            approved_by_pending[candidate['id']] = [
                approved for approved in neighbours
                if not approved.get('draft') and not approved.get('all_day')
                and approved.get('status') != 'cancelled']
        for pending in pendings:
            title, facts = calendar_review_copy(pending, zone, ui)
            window = pending_windows.get(pending['id'])
            if window:
                clashes = []
                for approved in approved_by_pending.get(pending['id'], []):
                    clashes.append(_clash_label(approved.get('subject'), approved.get('start'),
                                                approved.get('end'), approved.get('all_day'), zone))
                for other in pendings:
                    if other['id'] == pending['id']:
                        continue
                    sibling = pending_windows.get(other['id'])
                    if sibling and window[0] < sibling[1] and sibling[0] < window[1]:
                        clashes.append(_clash_label(other.get('subject'), other.get('start'),
                                                    other.get('end'), other.get('all_day'), zone))
                seen = set()
                unique = [entry for entry in clashes if entry and not (entry in seen or seen.add(entry))]
                if unique:
                    clash_text = ui.text('Schedule clash needs review: overlaps {events}',
                                         events='; '.join(unique))
                    facts = (facts + ' · ' + clash_text) if facts else clash_text
            result['reviews'].append({'id': pending['id'], 'revision': pending['revision'], 'title': title,
                                      'questions': [facts], 'needs_review': True, 'owner': 'attention'})
        result['timezone'] = zone
    except (ValueError, KeyError, OSError, sqlite3.Error):
        result['warnings'].append('Calendar unavailable; saved tasks do not establish free time.')
    finally:
        if calendar:
            calendar.close()
    if store:
        result['items'].extend(confirmed_drafts(store, start_day.isoformat(), end_day.isoformat(), converted))
        indexed = {row['id']: row for row in result['items']}
        for task in store.all():
            event = indexed.get(task['calendar_event_id'])
            if not event or event.get('draft') or not task['planned_date'] or task['status'] in ('done', 'cancelled'):
                continue
            from goodmorning.calendar.calendar_store import endpoints
            from zoneinfo import ZoneInfo
            begin, finish = [p.astimezone(ZoneInfo(zone)) for p in endpoints(event)]
            target = dt.datetime.combine(dt.date.fromisoformat(task['planned_date']), dt.time(), ZoneInfo(zone))
            if begin < target + dt.timedelta(days=1) and finish > target:
                linked = task_row(task, task['planned_date'], store.occurrence(task, task['planned_date']), 'planned')
                event.setdefault('linked_actions', []).append(linked)
    result['owned_tasks'] = [(row['id'], row['occurrence_id']) for event in result['items'] for row in event.get('linked_actions', [])]
    if result.get('timezone'):
        result['items'].sort(key=lambda r: (event_cells(r, result['timezone'])[0],
                                           2 if r.get('draft') else 0 if r.get('all_day') else 1,
                                           event_cells(r, result['timezone'])[1]))
    result['total'] = len(result['items'])
    result['next_offset'] = offset + limit if limit is not None and offset + limit < result['total'] else None
    result['items'] = result['items'][offset:offset + limit] if limit is not None else result['items']
    return result


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
                    'attention': attention(store, today, offset, limit, agenda['reviews']),
                    'schedule': {k: v for k, v in agenda.items() if k not in ('reviews', 'owned_tasks')}, 'warnings': []}
            outcomes = reported_day(store, today) if kind == 'gn' else []
            result['today'] = outcomes[offset:offset + limit]
            result['today_total'] = len(outcomes)
            result['today_next_offset'] = offset + limit if offset + limit < len(outcomes) else None
            result['blocks'] = {
                'tasks': ['actions', [action_cells(r) for r in result['tasks']['items']]],
                'schedule': ['events', [[r['id'], r['revision'], *event_cells(r, events_timezone(runtime))] for r in result['schedule']['items']]],
                'attention': ['decisions', [[r['id'], r['revision'], r['title'], '\n'.join(r['questions']) or 'Review the supplied details.'] for r in result['attention']['items']]],
                'today': ['actions', [action_cells(r) for r in result['today'] if r['status'] != 'open']]}
            return result
    finally:
        inbox.close()


def validate_sources(runtime, document, today, kind):
    """Validate source-linked rows before publish/save, never on historical reads."""
    if document['v'] != 2:
        return
    if not any(block[0] in ('actions', 'events', 'decisions') for section in document['sections'] for block in section[1]):
        return
    # One consistent task snapshot; approved calendar is another read-only store.
    inbox = InboxStore(runtime)
    from goodmorning.web import language as ui
    token = ui.CURRENT.set(document.get('lang', 'en'))
    try:
        store = TaskStore(inbox)
        inbox.db.execute('BEGIN')
        agenda = schedule(runtime, today, kind, store, limit=None)
        eligible = task_view(store, today, kind, limit=1000000, owned=agenda['owned_tasks'])['items']
        tasks = {(r['id'], r['occurrence_id']): r for r in eligible}
        outcomes = {(r['id'], r['occurrence_id']): r for r in reported_day(store, today)}
        events = {r['id']: r for r in agenda['items']}
        decisions = {r['id']: r for r in attention(store, today, limit=1000000, calendar_reviews=agenda['reviews'])['items']}
        for section in document['sections']:
            for block in section[1]:
                tag = block[0]
                if tag == 'actions':
                    available = outcomes if section[0] == 'today' else tasks
                    for row in block[1]:
                        identifier, revision, occ, day, status, title, detail = row
                        source = available.get((identifier, occ))
                        if not source or [revision, day, status, title] != [source['revision'], source['date'], source['status'], source['title']]:
                            raise ValueError('source_conflict: action identity, date, title, status or revision is unsupported')
                elif tag == 'events':
                    for identifier, revision, *cells in block[1]:
                        source = events.get(identifier)
                        if not source or revision != source['revision'] or cells != event_cells(source, events_timezone(runtime)):
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


def action_cells(row):
    from goodmorning.web import language as ui
    cleaned = clean_task_detail(row.get('title', ''), row.get('detail', ''))
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
    return [row['id'], row['revision'], row['occurrence_id'], row['date'], row['status'], row['title'], ' · '.join(detail)]


def event_cells(event, timezone):
    from goodmorning.calendar.calendar_store import endpoints
    from goodmorning.calendar.calendar_safety import clean_preparation
    from zoneinfo import ZoneInfo
    from goodmorning.web import language as ui
    if event.get('draft'):
        return [event['date'], ui.text('TBC'), event['title'], event['location'], event['detail']]
    start, end = [p.astimezone(ZoneInfo(timezone)) for p in endpoints(event)]
    if event['all_day']:
        clock = ui.text('All day')
        if (end.date() - start.date()).days > 1:
            clock = ui.text('All day through {date}', date=(end.date() - dt.timedelta(days=1)).isoformat())
    else:
        finish = (end.date().isoformat() + ' ' if end.date() != start.date() else '') + end.strftime('%H:%M')
        clock = start.strftime('%H:%M') + '–' + finish
    notes = clean_preparation(event.get('notes', '')) if event.get('notes') else ''
    prep = [notes] if notes else []
    for action in event.get('linked_actions', []):
        prep.append(action['title'] + ('\n' + action['detail'] if action['detail'] else ''))
    return [start.date().isoformat(), clock, event['subject'], event.get('location', ''), '\n'.join(prep)]
