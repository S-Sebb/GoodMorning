"""Read small, session-owned change receipts, never commands or private tool output."""
from datetime import datetime
import sqlite3

from goodmorning.runtime_files import calendar_path
from goodmorning.records.inbox_store import InboxStore
from goodmorning.calendar.calendar_store import CalendarStore

LIMIT = 30


def change(source, row):
    return {'id': f'action:{source}:{row["seq"]}', 'role': 'assistant', 'kind': 'action',
            'text': row['title'] or '', 'action': {'operation': row['operation'], 'target': row['target']},
            'at': row['at']}


def read_changes(runtime, session, *, aliases=()):
    """Project only committed receipts; missing stores are normal for new accounts."""
    # Callers supply aliases only from this account's selected conversation,
    # never from a browser request or an unverified label in an audit record.
    owners = tuple(dict.fromkeys((session, *aliases)))
    placeholders = ','.join('?' for _ in owners)
    changes, unavailable = [], False
    if (runtime / 'inbox.sqlite').exists():
        store = None
        try:
            store = InboxStore(runtime)
            rows = store.db.execute(f"""
                SELECT e.seq,e.created_at at,
                    CASE WHEN e.action='add' THEN 'added'
                         WHEN json_extract(e.changes,'$.status')='done' THEN 'completed'
                         ELSE 'updated' END operation,
                    CASE WHEN json_extract(e.changes,'$.kind')='idea' THEN 'idea'
                         WHEN json_extract(e.receipt,'$.task_id') IS NOT NULL THEN 'task'
                         WHEN json_extract(e.receipt,'$.draft_id') IS NOT NULL THEN 'draft'
                         ELSE 'record' END target,
                    substr(coalesce(json_extract(e.changes,'$.task.title'),
                        json_extract(e.changes,'$.draft.title'),json_extract(e.changes,'$.summary'),
                        json_extract(e.changes,'$.raw'),''),1,160) title
                FROM events e WHERE e.session IN ({placeholders}) AND json_extract(e.receipt,'$.saved')=1
                ORDER BY e.seq DESC LIMIT ?
                """, (*owners, LIMIT)).fetchall()
            changes.extend(change('inbox', row) for row in rows)
            if store.version == 2:
                rows = store.db.execute(f"""
                    SELECT seq,at,
                        CASE WHEN action='adopt' THEN 'added'
                             WHEN json_extract(snapshot,'$.input.status')='cancelled'
                               OR json_extract(snapshot,'$.input.state')='withdrawn' THEN 'cancelled'
                             WHEN json_extract(snapshot,'$.input.status')='done' THEN 'completed'
                             ELSE 'updated' END operation,
                        CASE WHEN json_extract(snapshot,'$.item.state') IS NOT NULL THEN 'draft'
                             ELSE 'task' END target,
                        substr(coalesce(json_extract(snapshot,'$.item.title'),''),1,160) title
                    FROM task_events WHERE session IN ({placeholders}) AND action IN ('adopt','update','report')
                        AND json_extract(receipt,'$.saved')=1 ORDER BY seq DESC LIMIT ?
                    """, (*owners, LIMIT)).fetchall()
                changes.extend(change('task', row) for row in rows)
        except (ValueError, OSError, sqlite3.Error):
            unavailable = True
        finally:
            if store:
                store.close()
    store = None
    try:
        path = calendar_path(runtime)
        if path.is_file():
            store = CalendarStore(str(path), readonly=True)
            rows = store.con.execute(f"""
                SELECT seq,at,
                    CASE action WHEN 'cancel' THEN 'cancelled' WHEN 'add' THEN 'added'
                         WHEN 'approve' THEN 'approved' WHEN 'reject' THEN 'declined'
                         ELSE 'updated' END operation,
                    'event' target,
                    substr(CASE WHEN action='reject' THEN json_extract(snapshot,'$.raw.subject')
                        ELSE coalesce(json_extract(snapshot,'$.approved.subject'),
                            json_extract(snapshot,'$.raw.subject'),'') END,1,160) title
                FROM history WHERE actor IN ({placeholders}) AND action IN ('add','update','cancel','approve','reject')
                ORDER BY seq DESC LIMIT ?
                """, (*owners, LIMIT)).fetchall()
            changes.extend(change('calendar', row) for row in rows)
    except (ValueError, OSError, sqlite3.Error):
        unavailable = True
    finally:
        if store:
            store.close()
    # Audit timestamps include offsets; string order is not chronological across zones.
    try:
        changes.sort(key=lambda entry: (datetime.fromisoformat(entry['at']).timestamp(),
                                       entry['id'].split(':')[1], int(entry['id'].split(':')[2])))
    except (ValueError, TypeError):
        return [], True
    return changes[-LIMIT:], unavailable


def action_history(messages, changes, turns, created):
    """Place receipts at the end of their user turn, before the next user message."""
    legacy = any('created' not in turn for turn in turns[1:])
    windows = [(turn['id'], turn.get('created', created)) for index, turn in enumerate(turns)
               if 'created' in turn or index == 0 and not legacy]
    groups = {}
    for entry in changes:
        at = datetime.fromisoformat(entry['at']).timestamp()
        # Inbox helpers record whole seconds; do not drop a fast save just
        # because the browser's turn timestamp has fractional seconds.
        turn = next((identifier for identifier, start in reversed(windows)
                     if (int(start) if '.' not in entry['at'] else start) <= at), None)
        if turn:
            groups.setdefault(turn, []).append(entry)
    result, current = [], None
    for entry in messages:
        turn = entry.get('_turn')
        if turn and turn != current:
            result.extend(groups.pop(current, []))
            current = turn
        result.append({key: value for key, value in entry.items() if key != '_turn'})
    result.extend(groups.get(current, []))
    return result
