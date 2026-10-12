"""Code-owned browser workflow context and incremental authoring commands."""
import argparse
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import shlex
import sqlite3
import sys

from . import briefing_document as native
from .briefing_stream import DEFAULT_PLANS, bounded_json, load, paths, publish, require_final
from goodmorning.runtime_files import atomic_text, runtime_lock, secretary_path
from goodmorning.web import language as ui


def context_path(runtime, identifier):
    directory, _, _ = paths(runtime, identifier)
    return directory / (identifier + '.context.json')


def owned(runtime, identifier, session):
    directory, target, job = paths(runtime, identifier)
    if not session or session != job.get('session'):
        raise ValueError('This browser job belongs to a different session')
    if job['state'] == 'complete':
        raise ValueError('This browser job is complete; stop without fetching or rewriting it')
    context = bounded_json(context_path(runtime, identifier), 300_000)
    if (context['date'], context['workflow']) != (job['date'], job['kind']):
        raise ValueError('Browser context does not match its job')
    if context.get('awaiting'):
        raise ValueError('Browser feedback is still required')
    if context.get('cancelled'):
        raise ValueError('This browser job was cancelled; stop')
    return directory, target, job, context


def default_plan(context):
    plan = deepcopy(DEFAULT_PLANS[context['workflow']])
    selected=context.get('website_language','en')
    for item in plan:
        item[1]=ui.text(item[1],lang=selected)
        if item[0] == 'news':
            item[1] += ' — ' + context['yesterday']
    if context.get('news', {}).get('latest_enabled'):
        plan.insert(2, ['news', ui.text('Latest news — {date}',lang=selected,date=context['date'])])
    return plan


def next_step(runtime, identifier, session, context, checkpoint):
    """One compact recipe; no speculative flags or whole-briefing fetching."""
    command = ['python', 'scripts/goodmorning.py', 'job', '--secretary-dir', str(runtime), '--job', identifier, '--session', session]
    if not checkpoint:
        return {'action':'init', 'command':shlex.join(command + ['init']),
                'input':{'greeting':'…','opening':'…','plan':default_plan(context)},
                'instruction':'Initialize now, before any provider or additional record reads. Translate plan titles if needed.'}
    position = len(checkpoint['outcomes'])
    if position == len(checkpoint['plan']):
        return {'action':'finish', 'command':shlex.join(command + ['finish']), 'input':{}}
    tag, title = checkpoint['plan'][position]
    reads = []
    selected = context['paths']
    if tag == 'weather':
        reads.append(shlex.join(['python','scripts/goodmorning.py','weather','--secretary-dir',str(runtime),
                                '--city',context['city'],'--cache-dir',selected['cache']]))
    elif tag == 'news':
        latest = any(entry[0] == 'news' for entry in checkpoint['plan'][:position])
        if latest and not context['news']['latest_enabled']:
            return {'action':'publish','command':shlex.join(command + ['publish']), 'position':position,
                    'section':[tag,title], 'instruction':'No same-day collection is authorized. Use only the explicitly approved dated news window.'}
        for country in context['news']['countries']:
            base = ['python','scripts/goodmorning.py','news','--secretary-dir',str(runtime),'--country',country,
                    '--timezone',context['timezone'],'--cache-dir',selected['cache']]
            if context['news'].get('sources'):
                base += ['--sources',context['news']['sources']]
            reads.append(shlex.join(base + (['--latest','--format','json'] if latest else ['--backfill','--today',context['date']])))
            if not latest:
                reads.append(shlex.join(base + ['--show',context['yesterday'],'--view','candidates','--limit','10']))
    elif tag in ('schedule','tomorrow') and selected.get('calendar_db'):
        reads.append(shlex.join(['python','scripts/goodmorning.py','calendar','--secretary-dir',str(runtime),
            '--db',selected['calendar_db'],'--from',context['tomorrow'] if tag == 'tomorrow' else context['date'],
            '--days','1' if tag == 'tomorrow' else '3','--timezone',context['timezone'],'--json','--details']))
    return {'action':'publish','command':shlex.join(command + ['publish']), 'position':position,
            'section':[tag,title], 'read':reads,
            'instruction':'Gather only this section; follow returned pages/review requirements, then publish immediately. Use saved context first.'}


def image_previews(runtime, job, context, checkpoint):
    if context.get('integration_policy', {}).get('publisher_images') is not True:
        # No fetch without consent. Name the disabled state so a future
        # all-placeholder briefing is offered as a choice, never silent.
        urls = native.news_urls(checkpoint['document'])
        if not urls:
            return None
        return {'cached': 0, 'unavailable': len(urls), 'disabled': True,
                'next': 'Publisher previews are disabled by policy; keep honest placeholders and offer the choice separately.'}
    from .briefing_images import cache_previews
    urls = native.news_urls(checkpoint['document'])
    if not urls:
        return None
    try:
        entries = cache_previews(urls, Path(runtime)/'browser-images'/job['date'], Path(runtime)/'browser-images/objects')
        return {'cached':sum(entry['status'] == 'cached' for entry in entries.values()),
                'unavailable':sum(entry['status'] == 'unavailable' for entry in entries.values())}
    except (ValueError, OSError, ImportError, sqlite3.Error):
        return {'unavailable':True, 'next':'Keep honest placeholders; preserve the image cache and inspect it separately.'}


def act(runtime, identifier, session, action, payload=None):
    directory, target, job, context = owned(runtime, identifier, session)
    with runtime_lock(directory, identifier + '.workflow.lock'):
        checkpoint = load(target)
        if not checkpoint and native.source_path(runtime, job['date'], job['kind']).exists():
            raise ValueError('A saved edition already exists; stop and inspect its owning run, without fetching or rewriting')
        def receipt(value):
            return {**value, 'next':next_step(runtime, identifier, session, context, load(target))}
        if action == 'prepare':
            # Preparation is saved once by the server, not reread by the agent.
            return receipt({**{k:v for k,v in context.items() if k not in ('form','browser_answer','awaiting')}, 'job': identifier, 'session': session,
                    'next_position': len(checkpoint['outcomes']) if checkpoint else 0})
        if action == 'init':
            if not isinstance(payload, dict) or not {'greeting','opening'} <= payload.keys() or set(payload) - {'greeting', 'opening', 'lang', 'plan'}:
                raise ValueError('Initialize with greeting, opening, optional lang and plan')
            selected=context.get('website_language','en')
            if 'lang' in payload and payload['lang']!=selected:raise ValueError('Use this job’s pinned website language')
            document = {'v': 1, 'greeting': payload['greeting'], 'opening': payload['opening'], 'sections': [],'lang':selected}
            plan = payload.get('plan', default_plan(context))
            if checkpoint:
                if checkpoint['plan'] != plan or {k:v for k,v in checkpoint['document'].items() if k not in ('sections','closing')} != {k:v for k,v in document.items() if k != 'sections'}:
                    raise ValueError('An existing preview cannot be reinitialized differently')
                return receipt({'resolved':len(checkpoint['outcomes']), 'planned':len(plan), 'saved':False})
            return receipt(publish(runtime, identifier, document, plan))
        if not checkpoint:
            raise ValueError('Initialize the preview first')
        document = deepcopy(checkpoint['document'])
        position = len(checkpoint['outcomes'])
        if action in ('publish', 'skip'):
            if not isinstance(payload, dict) or set(payload) != ({'position','section'} if action == 'publish' else {'position'}):
                raise ValueError('Supply the section position and, for publish, one section')
            requested = payload['position']
            if type(requested) is not int or requested < 0:
                raise ValueError('Invalid section position')
            if requested < position:
                outcome = checkpoint['outcomes'][requested]
                sections = iter(document['sections'])
                previous = [next(sections) if value == 'ready' else None for value in checkpoint['outcomes']]
                if (action == 'skip' and outcome == 'skipped') or (action == 'publish' and outcome == 'ready' and previous[requested] == payload['section']):
                    return receipt({'resolved':position,'planned':len(checkpoint['plan']),'saved':False,'reused':True})
                raise ValueError('Published sections cannot change')
            if requested != position or position == len(checkpoint['plan']):
                raise ValueError('Publish only the next unresolved section')
            if action == 'skip':
                if checkpoint['plan'][position][0] in ('weather','news','schedule','today','tomorrow'):
                    raise ValueError('Publish material unavailability; do not skip a required section')
                return receipt(publish(runtime, identifier, skip=True, position=position))
            document['sections'].append(payload['section'])
            result = publish(runtime, identifier, document, position=position)
            if payload['section'][0] == 'news':
                images = image_previews(runtime, job, context, load(target))
                if images is not None:
                    result['images'] = images
            return receipt(result)
        if action == 'finish':
            if not isinstance(payload, dict) or set(payload) - {'closing'}:
                raise ValueError('Finish accepts only an optional closing')
            if 'closing' in payload:
                document['closing'] = payload['closing']
            source = native.source_path(runtime, job['date'], job['kind'])
            if source.exists():
                if native.parse(source.read_text()) != document:
                    raise ValueError('An existing saved edition does not match this job; preserve it')
            else:
                publish(runtime, identifier, document, position=position)
            require_final(runtime, identifier, job['date'], job['kind'], session, document)
            # Code assembles the cumulative draft; the model never re-emits its prefix.
            draft = directory / (identifier + '.draft.json')
            atomic_text(draft, native.encode(document))
            from goodmorning.records.state import main as save
            output = io.StringIO()
            with redirect_stdout(output):
                code = save(['--secretary-dir',str(runtime),'--today',job['date'],'--mark-'+job['kind'],
                             '--session',session,'--browser-job',identifier,
                             '--answer-file',str(draft),'--json'])
            if code:
                raise ValueError('Final save was not confirmed: '+output.getvalue().strip())
            draft.unlink()  # Only this confirmed job's temporary cumulative input.
            return {'saved':True,'date':job['date'],'kind':job['kind'], 'next':'Return the browser link; stop without rewriting or acknowledging news.'}
        raise ValueError('Unknown browser workflow action')


def decode_input(raw):
    def pairs(entries):
        value = {}
        for key, item in entries:
            if key in value:
                raise ValueError('Duplicate JSON object key; serialize one object with json.dumps')
            value[key] = item
        return value
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: native.fail('input','non-finite numbers are not allowed'))
    except json.JSONDecodeError as error:
        raise ValueError(f'Invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}. Serialize with json.dumps; do not hand-escape text.') from None
    except (UnicodeError, RecursionError):
        raise ValueError('Input must be bounded UTF-8 JSON') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secretary-dir')
    parser.add_argument('--job', required=True)
    parser.add_argument('--session', default=os.environ.get('OPENCODE_SESSION_ID'))
    parser.add_argument('action', choices=('prepare','init','publish','skip','finish'))
    args = parser.parse_args()
    try:
        payload = None
        if args.action != 'prepare':
            raw = sys.stdin.buffer.read(native.MAX_BYTES + 1)
            if len(raw) > native.MAX_BYTES:
                raise ValueError('Authoring input exceeds its size limit')
            payload = decode_input(raw)
        print(json.dumps(act(secretary_path(args.secretary_dir), args.job, args.session, args.action, payload), ensure_ascii=False, separators=(',',':')))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'error':'browser_workflow_unavailable','next':str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
