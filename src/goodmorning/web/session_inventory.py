"""Organized OpenChamber session bookkeeping for website chats and briefings.

Every GoodMorning conversation or briefing owns exactly one OpenChamber
session. Follow-up messages reuse that session; a new conversation, briefing
date or explicitly regenerated briefing creates another one. Briefing titles carry
a fixed ``GoodMorning ·`` prefix; chat titles come from native AI auto-titling.

Local registries stay bounded: old briefing jobs are pruned and old chats move
to a preserved local archive. Engine sessions are never deleted here; the
inventory only reports which engine sessions are still referenced so an
administrator can review them in the engine dashboard.
"""
import argparse
import json
import time
from pathlib import Path

PREFIX = 'GoodMorning · '
ARCHIVE_LIMIT_BYTES = 8_000_000
REGISTRY_LIMIT_BYTES = 8_000_000
JOB_REGISTRY_LIMIT_BYTES = 2_000_000


def chat_session_title(mode_label, topic):
    label = (mode_label or '').strip() or 'Chat'
    topic = ' '.join((topic or '').split())
    return (PREFIX + label + (' · ' + topic[:48] if topic else ''))[:120]


def job_session_title(kind_label, date):
    return (PREFIX + (kind_label or '').strip() + ' briefing · ' + (date or '').strip())[:120]


def _read_json(path, limit):
    if not path.exists():
        return {}
    if path.is_symlink() or path.resolve() != path:
        raise ValueError('Unsafe session registry')
    if path.stat().st_size > limit:
        raise ValueError('Session registry exceeds its limit')
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError('Invalid session registry')
    return data


def owned_sessions(runtime):
    """Map engine session IDs to their owning chat or job. Read-only."""
    runtime = Path(runtime).expanduser().resolve()
    owned = {}
    for chat_id, item in _read_json(runtime / 'browser-chats' / 'chats.json', REGISTRY_LIMIT_BYTES).items():
        session = item.get('session') if isinstance(item, dict) else None
        if session:
            owned[session] = {'owner': 'chat:' + chat_id, 'kind': 'chat',
                              'mode': item.get('mode'), 'title': item.get('title'),
                              'state': item.get('state')}
    for key, job in _read_json(runtime / 'browser-jobs' / 'jobs.json', JOB_REGISTRY_LIMIT_BYTES).items():
        session = job.get('session') if isinstance(job, dict) else None
        if session:
            owned[session] = {'owner': 'job:' + key, 'kind': 'job',
                              'date': job.get('date'), 'edition': job.get('kind'),
                              'state': job.get('state')}
    return owned


def summarize_local(runtime):
    """Counted local inventory without contacting any engine. Read-only."""
    runtime = Path(runtime).expanduser().resolve()
    chats = _read_json(runtime / 'browser-chats' / 'chats.json', REGISTRY_LIMIT_BYTES)
    archived = _read_json(runtime / 'browser-chats' / 'archive.json', ARCHIVE_LIMIT_BYTES)
    jobs = _read_json(runtime / 'browser-jobs' / 'jobs.json', JOB_REGISTRY_LIMIT_BYTES)
    by_state = {}
    for item in chats.values():
        by_state[item.get('state', 'unknown')] = by_state.get(item.get('state', 'unknown'), 0) + 1
    job_states = {}
    for job in jobs.values():
        job_states[job.get('state', 'unknown')] = job_states.get(job.get('state', 'unknown'), 0) + 1
    return {'chats': len(chats), 'chat_states': by_state, 'archived_chats': len(archived),
            'jobs': len(jobs), 'job_states': job_states,
            'engine_sessions_owned': len(owned_sessions(runtime))}


def _job_transients(runtime, identifier):
    directory = Path(runtime).expanduser().resolve() / 'browser-jobs'
    return [directory / (identifier + suffix)
            for suffix in ('.context.json', '.preview.json', '.draft.json')] + \
        sorted(directory.glob(identifier + '.context-r*.json'))


def prune_jobs(runtime, older_than_days=14, today=None, apply=False):
    """Drop old terminal job entries and their transient files.

    Saved editions (daily/*.gm.json) are never touched. Only jobs whose stored
    state is complete/stopped and whose date is older than the window are
    candidates. Jobs without a valid ISO date are left alone for review.
    """
    from datetime import date as Date
    runtime = Path(runtime).expanduser().resolve()
    directory = runtime / 'browser-jobs'
    registry = directory / 'jobs.json'
    jobs = _read_json(registry, JOB_REGISTRY_LIMIT_BYTES)
    if today is None:
        today = Date.today().isoformat()
    candidates = []
    for key, job in jobs.items():
        if not isinstance(job, dict) or job.get('state') not in ('complete', 'stopped', 'superseded'):
            continue
        day = job.get('date')
        try:
            age = (Date.fromisoformat(today) - Date.fromisoformat(day)).days
        except (ValueError, TypeError):
            continue
        if age > older_than_days and day != today:
            candidates.append(key)
    report = {'candidates': sorted(candidates), 'pruned': [], 'transients_removed': 0, 'applied': bool(apply)}
    if not apply:
        return report
    if directory.is_symlink() or registry.is_symlink():
        raise ValueError('Unsafe session registry')
    remaining = {key: job for key, job in jobs.items() if key not in candidates}
    raw = json.dumps(remaining) + '\n'
    if len(raw.encode()) > JOB_REGISTRY_LIMIT_BYTES:
        raise ValueError('Session registry exceeds its limit')
    removed = 0
    for key in candidates:
        identifier = jobs[key].get('id')
        if identifier:
            for path in _job_transients(runtime, identifier):
                if path.exists() and not path.is_symlink() and path.resolve() == path:
                    path.unlink()
                    removed += 1
    from goodmorning.runtime_files import atomic_text
    atomic_text(str(registry), raw)
    report.update(pruned=sorted(candidates), transients_removed=removed)
    return report


def archive_chats(runtime, keep=200, older_than_days=90, now=None, apply=False):
    """Move old idle chats to a preserved local archive.

    The newest ``keep`` chats are always retained. Older chats are archived
    only when idle and older than the window (or missing timestamps, treated as
    oldest). Non-idle chats are never archived; engine sessions are never
    deleted here.
    """
    runtime = Path(runtime).expanduser().resolve()
    directory = runtime / 'browser-chats'
    path = directory / 'chats.json'
    archived_path = directory / 'archive.json'
    chats = _read_json(path, REGISTRY_LIMIT_BYTES)
    archived = _read_json(archived_path, ARCHIVE_LIMIT_BYTES)
    now = time.time() if now is None else now
    ordered = list(chats)
    protected = set(ordered[-keep:] if keep > 0 else [])
    candidates = []
    retained = []
    for chat_id in ordered:
        if chat_id in protected:
            continue
        item = chats[chat_id]
        state = item.get('state') if isinstance(item, dict) else None
        if state != 'idle':
            retained.append(chat_id)
            continue
        created = item.get('created') if isinstance(item, dict) else None
        age_days = (now - created) / 86400 if isinstance(created, (int, float)) else float('inf')
        if age_days > older_than_days:
            candidates.append(chat_id)
    report = {'candidates': candidates, 'retained_non_idle': retained,
              'archived': [], 'applied': bool(apply)}
    if not apply or not candidates:
        return report
    if directory.is_symlink() or path.is_symlink() or archived_path.is_symlink():
        raise ValueError('Unsafe session registry')
    for chat_id in candidates:
        archived[chat_id] = chats.pop(chat_id)
    for payload, target in ((chats, path), (archived, archived_path)):
        raw = json.dumps(payload, ensure_ascii=False) + '\n'
        if len(raw.encode()) > (REGISTRY_LIMIT_BYTES if target == path else ARCHIVE_LIMIT_BYTES):
            raise ValueError('Session registry exceeds its limit')
    from goodmorning.runtime_files import atomic_text
    atomic_text(str(path), json.dumps(chats, ensure_ascii=False) + '\n')
    atomic_text(str(archived_path), json.dumps(archived, ensure_ascii=False) + '\n')
    report['archived'] = candidates
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secretary-dir')
    parser.add_argument('--list', action='store_true', help='Show the local session inventory (default)')
    parser.add_argument('--storage', action='store_true', help='Read-only filesystem sizes; never load file contents or contact models')
    parser.add_argument('--cache-dir', type=Path)
    parser.add_argument('--prune-jobs', action='store_true')
    parser.add_argument('--archive-chats', action='store_true')
    parser.add_argument('--keep', type=int, default=200)
    parser.add_argument('--older-than-days', type=int, default=90)
    parser.add_argument('--jobs-older-than-days', type=int, default=14)
    parser.add_argument('--apply', action='store_true',
                        help='Apply pruning/archival. Without it, only report candidates.')
    args = parser.parse_args(argv)
    from goodmorning.runtime_files import secretary_path
    try:
        if sum([bool(args.prune_jobs), bool(args.archive_chats), bool(args.storage)]) > 1:
            raise ValueError('Choose only one maintenance action')
        if args.keep < 0 or not 0 < args.older_than_days <= 3650 or not 0 < args.jobs_older_than_days <= 3650:
            raise ValueError('Use a non-negative keep count and a 1-3650 day window')
        runtime = secretary_path(args.secretary_dir)
        if args.storage:
            from goodmorning.storage_usage import inventory
            result = inventory(runtime, args.cache_dir)
        elif args.prune_jobs:
            result = prune_jobs(runtime, args.jobs_older_than_days, apply=args.apply)
        elif args.archive_chats:
            result = archive_chats(runtime, args.keep, args.older_than_days, apply=args.apply)
        else:
            result = summarize_local(runtime)
            result = {**result, 'briefing_title_prefix': PREFIX.strip()}
        print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'error': 'sessions_unavailable', 'next': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
