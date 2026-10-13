"""Publish validated, append-only browser previews; never mark runs or news delivery."""
import argparse
import json
from pathlib import Path
import re

from . import briefing_document as native
from goodmorning.runtime_files import atomic_text, runtime_lock

DEFAULT_PLANS = {
    'gm': [[tag, native.TITLES[tag]] for tag in ('weather', 'news', 'schedule', 'tasks', 'attention')],
    'gn': [[tag, native.TITLES[tag]] for tag in ('today', 'schedule', 'tasks', 'attention')],
}
LEGACY_PLANS = {
    'gm': [[tag, native.TITLES[tag]] for tag in ('weather', 'news', 'schedule', 'must-do', 'nice-to-do', 'reminders')],
    'gn': [[tag, native.TITLES[tag]] for tag in ('today', 'still-open', 'tomorrow', 'must-do', 'nice-to-do', 'notes')],
}
MAX_CHECKPOINT = native.MAX_BYTES + 30_000


def bounded_json(path, limit=MAX_CHECKPOINT):
    if path.is_symlink() or path.resolve() != path:
        raise ValueError('Unsafe preview path')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Preview exceeds size limit')
    return json.loads(raw)


def paths(runtime, identifier):
    if not re.fullmatch('[0-9a-f]{32}', identifier):
        raise ValueError('Invalid job')
    directory = Path(runtime).expanduser().resolve() / 'browser-jobs'
    registry = directory / 'jobs.json'
    target = directory / (identifier + '.preview.json')
    for path in (directory, registry, target, directory / (identifier + '.preview.lock')):
        if path.is_symlink() or path.resolve() != path:
            raise ValueError('Unsafe preview path')
    jobs = bounded_json(registry, 2_000_000)
    job = next((item for item in jobs.values() if item.get('id') == identifier), None)
    if not job:
        raise ValueError('Unknown job')
    if job['state'] == 'superseded':
        raise ValueError('This browser job was replaced; stop without fetching or rewriting it')
    return directory, target, job


def validate(checkpoint):
    if not isinstance(checkpoint, dict) or set(checkpoint) != {'plan', 'outcomes', 'document'}:
        raise ValueError('Invalid preview checkpoint')
    plan, outcomes, document = (checkpoint[key] for key in ('plan', 'outcomes', 'document'))
    native.sequence(plan, 'plan', 1, 80)
    for item in plan:
        native.sequence(item, 'plan entry', 2, 2)
        if not isinstance(item[0], str) or item[0] not in native.TITLES:
            raise ValueError('Unknown planned section')
        native.text(item[1], 'planned title', 200)
    native.sequence(outcomes, 'outcomes', 0, len(plan))
    if any(item not in ('ready', 'skipped') for item in outcomes):
        raise ValueError('Invalid preview outcome')
    native.validate(document, partial=True)
    if len(json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode()) + 1 > native.MAX_BYTES:
        raise ValueError('Preview document exceeds native size limit')
    if len(document['sections']) != outcomes.count('ready'):
        raise ValueError('Preview section count does not match outcomes')
    sections = iter(document['sections'])
    for item, outcome in zip(plan, outcomes):
        if outcome == 'ready' and next(sections)[0] != item[0]:
            raise ValueError('Preview section does not match plan')
    if 'closing' in document and len(outcomes) != len(plan):
        raise ValueError('Closing waits until all sections are resolved')
    return checkpoint


def load(target):
    if target.is_symlink() or target.resolve() != target:
        raise ValueError('Unsafe preview path')
    return validate(bounded_json(target)) if target.exists() else None


def publish(runtime, identifier, document=None, plan=None, skip=False, *, position=None):
    directory, target, job = paths(runtime, identifier)
    if job['state'] not in ('starting', 'running', 'uncertain'):
        raise ValueError('Job no longer accepts previews')
    with runtime_lock(directory, identifier + '.preview.lock'):
        _, _, job = paths(runtime, identifier)
        from .briefing_replacement import check
        replacement = check(runtime, job)
        if not replacement and native.source_path(Path(runtime).expanduser().resolve(), job['date'], job['kind']).exists():
            raise ValueError('A saved edition already exists')
        old = load(target)
        if position is not None and (old is None or len(old['outcomes']) != position):
            raise ValueError('Preview advanced; reread the current section position before retrying')
        if old is None:
            if plan is None or document is None or skip or document.get('sections') != []:
                raise ValueError('Initialize with a plan and an empty-section draft')
            checkpoint = {'plan': plan, 'outcomes': [], 'document': document}
        else:
            if plan is not None and plan != old['plan']:
                raise ValueError('Published plan cannot change')
            previous = old['document']
            document = previous if skip else document
            if document is None:
                raise ValueError('Supply the cumulative draft')
            if {k: v for k, v in document.items() if k not in ('sections', 'closing')} != {k: v for k, v in previous.items() if k not in ('sections', 'closing')}:
                raise ValueError('Published greeting, opening and language cannot change')
            prefix = previous['sections']
            if document['sections'][:len(prefix)] != prefix:
                raise ValueError('Published sections cannot change')
            if 'closing' in previous and document.get('closing') != previous['closing']:
                raise ValueError('Published closing cannot change')
            outcomes = list(old['outcomes'])
            remaining = len(outcomes) < len(old['plan'])
            if skip:
                if not remaining:
                    raise ValueError('No remaining section to skip')
                outcomes.append('skipped')
            elif len(document['sections']) == len(prefix) + 1 and remaining:
                outcomes.append('ready')
            elif document != previous and (remaining or document['sections'] != prefix):
                raise ValueError('Publish exactly one next section at a time')
            checkpoint = {'plan': old['plan'], 'outcomes': outcomes, 'document': document}
        validate(checkpoint)
        native.validate_task_ownership(document)
        from goodmorning.records.routing import validate_sources
        validate_sources(runtime, document, job['date'], job['kind'])
        from goodmorning.reply_policy import boilerplate_categories
        if any(boilerplate_categories(value) for value in native.strings(document)):
            raise ValueError('Remove noncritical boilerplate before publishing; keep material warnings')
        if job['kind'] == 'gm':
            from goodmorning.records.daily import planned_tasks
            planned_tasks(document, job['date'])
        if len(checkpoint['outcomes']) == len(checkpoint['plan']) and not document['sections']:
            raise ValueError('Publish at least one section before resolving the plan')
        for entry, section in zip((item for item, outcome in zip(checkpoint['plan'], checkpoint['outcomes']) if outcome == 'ready'), document['sections']):
            if native.section_title(section, job['date'],document.get('lang','en')) != entry[1]:
                raise ValueError('Published section title must match its plan')
        source = json.dumps(checkpoint, ensure_ascii=False, separators=(',', ':')) + '\n'
        if len(source.encode()) > MAX_CHECKPOINT:
            raise ValueError('Preview exceeds size limit')
        atomic_text(target, source)
    return {'resolved': len(checkpoint['outcomes']), 'planned': len(checkpoint['plan']), 'saved': False}


def require_final(runtime, identifier, date, kind, session, document):
    _, target, job = paths(runtime, identifier)
    checkpoint = load(target)
    if (job['date'], job['kind'], job.get('session')) != (date, kind, session):
        raise ValueError('Preview belongs to a different date, edition or session')
    if not checkpoint or len(checkpoint['outcomes']) != len(checkpoint['plan']):
        raise ValueError('Resolve all preview sections before saving')
    if checkpoint['document'] != document:
        raise ValueError('Final edition must match the published preview')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secretary-dir', type=Path, required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--plan-file', type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--answer-file', type=Path)
    action.add_argument('--skip-next', action='store_true')
    args = parser.parse_args()
    try:
        document = None
        if args.answer_file:
            # Restrict drafts to the authorized runtime, including parent symlinks.
            path = args.answer_file.expanduser().absolute()
            if path.resolve() != path or not path.is_relative_to(args.secretary_dir.expanduser().resolve()):
                raise ValueError('Draft must be inside the selected runtime')
            with path.open('rb') as stream:
                document = native.parse(stream.read(native.MAX_BYTES + 1).decode('utf-8'), partial=True)
        plan = None
        if args.plan_file:
            path = args.plan_file.expanduser().absolute()
            if not path.is_relative_to(args.secretary_dir.expanduser().resolve()):
                raise ValueError('Plan must be inside the selected runtime')
            plan = bounded_json(path, 30_000)
        print(json.dumps(publish(args.secretary_dir, args.job, document, plan, args.skip_next)))
    except (ValueError, OSError, UnicodeError, TypeError, KeyError) as error:
        print(json.dumps({'error': 'preview_unavailable', 'next': str(error)}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
