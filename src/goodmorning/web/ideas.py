"""Idea cards on briefing pages: close an idea with one tap, or reopen it, without the secretary.

Saved briefings are snapshots, so the page asks for each idea's live state when it loads."""
from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo

ENTRY = re.compile(r'ib_[0-9a-f]{16}')


def states(app, ids):
    """Live state of the pending or closed ideas among these inbox IDs.

    Other entries, unknown IDs and ideas organized into tasks are left out, so their cards get no button."""
    if len(ids) > 50 or not all(ENTRY.fullmatch(identifier) for identifier in ids):
        raise ValueError('Invalid idea list')
    if not ids or not (app.runtime / 'inbox.sqlite').exists():
        return {'ideas': {}}
    from goodmorning.records.inbox_store import InboxStore
    inbox = InboxStore(app.runtime)
    try:
        rows = inbox.db.execute(f"SELECT id,revision,status FROM entries WHERE kind='idea' AND status IN ('pending','done') AND id IN ({','.join('?' * len(ids))})", ids)
        return {'ideas': {row['id']: {'revision': row['revision'], 'closed': row['status'] == 'done'} for row in rows}}
    finally:
        inbox.close()


def close(app, body):
    """Close an idea, or reopen it for Undo. The key is the caller's own random retry key."""
    if (not isinstance(body, dict) or set(body) != {'id', 'revision', 'closed', 'key'} or not isinstance(body['id'], str)
            or not ENTRY.fullmatch(body['id']) or type(body['revision']) is not int or type(body['closed']) is not bool
            or not isinstance(body['key'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', body['key'])):
        raise ValueError('Invalid idea tap')
    zone = app.profile().get('timezone')
    if not zone:
        raise ValueError('Initialize your profile timezone first')
    now = (app.now() if app.now else datetime.now(timezone.utc)).astimezone(ZoneInfo(zone))
    from goodmorning.records.inbox_store import InboxStore
    inbox = InboxStore(app.runtime, write=True)
    try:
        entry = inbox.show(body['id'])
        if entry['kind'] != 'idea' or entry['status'] == 'confirmed':
            raise ValueError('not_found: only pending or closed ideas change from a briefing')
        # Closing from the page is the user's own decision, so it also settles any details the secretary hasn't read.
        payload = {'status': 'done', 'reviewed': True} if body['closed'] else {'status': 'pending'}
        receipt = inbox.mutate('update', payload, 'briefing', 'idea-tap:' + body['key'], now.isoformat(timespec='seconds'),
                               body['id'], body['revision'])
    finally:
        inbox.close()
    return {'saved': True, 'id': body['id'], 'closed': body['closed'], 'revision': receipt['revision']}
