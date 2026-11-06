#!/usr/bin/env python3
"""Move one account's legacy profile `## Project roots` into secretary memory (#290). Run as that account's service user.

seed         While memory is on, add an empty memory entry for each root name memory lacks, in profile order (names match ignoring case and
             spacing). Every other memory key stays byte-identical; the revision rises only when an entry is added.
strip-roots  Rewrite each root line `- Name | path | ...` in profile.md to `- Name`; every other byte stays the same.

Lines inside HTML comments, such as the template's `- Name | folder path` example, are never roots. Both modes are
idempotent, hold the store's own lock and replace files atomically. Output is counts only, never names or paths.
    python deploy/migrate_project_memory.py --secretary-dir RUNTIME seed|strip-roots [--dry-run]
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.records import memory  # noqa: E402
from goodmorning.records.inbox_store import encode  # noqa: E402
from goodmorning.runtime_files import atomic_text, runtime_lock  # noqa: E402

SECTION = re.compile(r'^## Project roots[ \t]*\r?$(.*?)(?=^## |\Z)', re.M | re.S)
ROOT = re.compile(r'^- ([^|\r\n]*[^|\s])[ \t]*(\|[^\r\n]*)?(?=\r?$)', re.M)


def roots(text):
    """Each root line's match in the profile's Project roots section, outside HTML comments; a stripped line has no path."""
    block = SECTION.search(text)
    if not block:
        return []
    comments = [match.span() for match in re.finditer(r'<!--.*?(?:-->|\Z)', text, re.S)]
    return [match for match in ROOT.finditer(text, block.start(1), block.end(1))
            if not any(start <= match.start() < end for start, end in comments)]


def seed(runtime, dry_run=False):
    names = [match[1].strip() for match in roots((runtime / 'profile.md').read_bytes().decode('utf-8'))]
    with runtime_lock(runtime, 'memory.lock'):
        target = memory.path(runtime)
        data = json.loads(target.read_text(encoding='utf-8')) if target.exists() else memory.load(runtime)
        if not data['enabled']:
            return {'mode': 'seed', 'skipped': 'memory_off', 'saved': False}  # The user turned memory off: nothing is added.
        entries = list(data.get('projects', []))
        for name in names:
            if not memory.find(entries, name):
                entries.append({'name': memory.project_name(name), 'note': ''})
        added = len(entries) - len(data.get('projects', []))
        if len(entries) > memory.PROJECTS:
            raise ValueError(f'too_many_projects: {len(entries)} entries exceed {memory.PROJECTS}; nothing was saved')
        if added and not dry_run:
            data['projects'] = entries
            data['revision'] += 1
            atomic_text(target, encode(data))
    return {'mode': 'seed', 'roots': len(names), 'added': added, 'projects': len(entries), 'revision': data['revision'],
            'saved': bool(added and not dry_run)}


def strip_roots(runtime, dry_run=False):
    profile = runtime / 'profile.md'
    with runtime_lock(runtime, '.profile.lock'):
        text = profile.read_bytes().decode('utf-8')  # Not read_text: it would turn CRLF into LF.
        found = [match for match in roots(text) if match[2]]
        rewritten = text
        for match in reversed(found):
            rewritten = rewritten[:match.start()] + '- ' + match[1].strip() + rewritten[match.end():]
        if found and not dry_run:
            atomic_text(profile, rewritten)
    return {'mode': 'strip-roots', 'stripped': len(found), 'saved': bool(found and not dry_run)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--secretary-dir', required=True)
    parser.add_argument('mode', choices=('seed', 'strip-roots'))
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    os.umask(0o077)
    runtime = Path(args.secretary_dir).resolve()
    owner = (runtime / 'profile.md').stat().st_uid
    if os.geteuid() != owner or owner == 0:
        print(json.dumps({'error': 'wrong_user', 'next': "run as the account's own service user"}))
        return 1
    try:
        result = (seed if args.mode == 'seed' else strip_roots)(runtime, args.dry_run)
    except ValueError as error:
        print(json.dumps({'error': str(error).split(':', 1)[0], 'next': str(error)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
