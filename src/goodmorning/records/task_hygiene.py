"""One-time task-detail hygiene for existing runtimes (dry-run by default).

Strips title repetition and duplicated project/deadline text from task `detail`
fields so Tasks group cleanly by project. Display-time cleanup in
`routing.clean_task_detail` already covers presentation; this rewrites the
canonical store so payloads stay small and future edits start clean.

Safety: per-runtime only, revision-checked, detail-only, never deletes tasks.
Every write uses a stable `hygiene:<task_id>:<revision>` request key and is
recorded in `task_events`; reruns are idempotent. Cancelled tasks are skipped
to preserve history verbatim. Run without --apply first and review the diff.

Usage:
  python -m goodmorning.records.task_hygiene --secretary-dir RUNTIME [--apply] [--session NAME]
"""

import argparse
import sys
from pathlib import Path

from goodmorning.records.inbox_store import InboxStore, stamp
from goodmorning.records.routing import clean_task_detail
from goodmorning.records.task_store import TaskStore
from goodmorning.runtime_files import secretary_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secretary-dir', required=True)
    parser.add_argument('--apply', action='store_true', help='Write cleaned details; default is dry-run')
    parser.add_argument('--session', default='hygiene-cleanup')
    args = parser.parse_args(argv)

    runtime = secretary_path(args.secretary_dir)
    inbox = InboxStore(runtime, write=args.apply)
    try:
        store = TaskStore(inbox)
        changed, skipped, total = [], [], 0
        for task in store.all():
            total += 1
            if task.get('status') == 'cancelled':
                continue
            original = task.get('detail') or ''
            cleaned = clean_task_detail(task.get('title', ''), original)
            if cleaned != original:
                changed.append({'id': task['id'], 'revision': task['revision'],
                                'status': task['status'], 'title': task['title'],
                                'from': original, 'to': cleaned})
        if not args.apply:
            print(f'dry-run: {len(changed)} of {total} tasks would be cleaned in {runtime}')
            for item in changed[:50]:
                print(f"- {item['id']} r{item['revision']} [{item['status']}] {item['title'][:80]}")
                print(f"  from: {item['from'][:200]}")
                print(f"  to:   {item['to'][:200]}")
            if len(changed) > 50:
                print(f'... and {len(changed) - 50} more (list truncated)')
            print('Re-run with --apply to write with stable hygiene request keys.')
            return 0
        now = stamp(runtime)
        applied = 0
        for item in changed:
            key = f"hygiene:{item['id']}:{item['revision']}"
            try:
                store.mutate(item['id'], item['revision'], {'detail': item['to']},
                             args.session, key, now)
                applied += 1
            except ValueError as error:
                skipped.append({'id': item['id'], 'next': str(error)})
        print(f'applied: {applied} cleaned, {len(skipped)} skipped, {total} total in {runtime}')
        for item in skipped[:20]:
            print(f"- {item['id']}: {item['next']}")
        return 0 if not skipped else 1
    finally:
        inbox.close()


if __name__ == '__main__':
    raise SystemExit(main())
