"""Task/draft operations with explicit timing, revision checks and save receipts."""
import argparse
import json
import os
import sqlite3
import sys

from goodmorning.runtime_files import secretary_path
from .inbox_store import InboxStore, encode, stamp
from .task_store import TaskStore, migrate


def decode_input(args):
    text = args.input_json if args.input_json is not None else sys.stdin.read(100001) if args.input_stdin else None
    if text is None or len(text) > 100000:
        raise ValueError('input_required: supply bounded JSON')
    return json.loads(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog="JSON input fields and tested examples: docs/helper-inputs.md")
    parser.add_argument('--secretary-dir')
    parser.add_argument('--website-language', choices=('en', 'zh-CN'))
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--add', action='store_true')
    actions.add_argument('--capture-draft', action='store_true')
    actions.add_argument('--migrate', action='store_true')
    actions.add_argument('--briefing', choices=('gm', 'gn'))
    parser.add_argument('--section', choices=('schedule', 'tasks', 'attention', 'today'), help='Return only this briefing section and its continuation')
    parser.add_argument('--browser-job', help='Bind a browser section read to its owning job and next position')
    for name in ('show', 'update', 'report', 'adopt', 'convert'):
        actions.add_argument('--' + name)
    parser.add_argument('--draft', action='store_true')
    parser.add_argument('--date')
    parser.add_argument('--actual', action='store_true', help='Confirmed completion on its actual date, even outside the planned recurrence')
    parser.add_argument('--confirm', action='store_true')
    parser.add_argument('--session', default=os.environ.get('OPENCODE_SESSION_ID'))
    parser.add_argument('--request-key')
    parser.add_argument('--expect-revision', type=int)
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=7)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--input-stdin', action='store_true')
    inputs.add_argument('--input-json')
    args = parser.parse_args(argv)
    inbox = None
    language_token = None
    try:
        if args.website_language:
            from goodmorning.web import language as ui
            language_token = ui.CURRENT.set(args.website_language)
        runtime = secretary_path(args.secretary_dir)
        if args.browser_job and not args.briefing:
            raise ValueError('invalid_input: --browser-job applies only to --briefing')
        if args.actual and not args.report:
            raise ValueError('invalid_input: --actual applies only to --report')
        if args.offset < 0 or not 1 <= args.limit <= 200:
            raise ValueError('invalid_input: invalid page size')
        if args.migrate:
            review = decode_input(args) if (args.input_json or args.input_stdin) else None
            if review is not None and (not isinstance(review,dict) or set(review)!={'reviewed_tasks'}):
                raise ValueError('invalid_input: reviewed migration accepts only reviewed_tasks')
            result = migrate(runtime, args.confirm, reviewed_tasks=review['reviewed_tasks'] if review is not None else None,
                             session=args.session, now=stamp(runtime) if review is not None else None)
        elif args.briefing:
            from .routing import prepare
            if not args.date:
                raise ValueError('date_required: briefing query needs its pinned date')
            from goodmorning.briefings.briefing_job import session_job, require_section
            browser_job = args.browser_job or session_job(runtime, os.environ.get('OPENCODE_SESSION_ID') or args.session)
            if browser_job:
                selected = require_section(runtime, browser_job, args.session, args.briefing, args.date, args.section)
                if args.website_language and args.website_language != selected:
                    raise ValueError('browser_section_scope: use the job\'s pinned website language')
                if not args.website_language:
                    from goodmorning.web import language as ui
                    language_token = ui.CURRENT.set(selected)
            result = prepare(runtime, args.date, args.briefing, args.offset, args.limit)
            if args.section:
                if args.section == 'today':
                    page = {'items': result.get('today', []), 'total': result.get('today_total', 0),
                            'next_offset': result.get('today_next_offset')}
                else:
                    page = result[args.section]
                result = {**page, 'block': result.get('blocks', {}).get(args.section),
                           'warnings': result.get('warnings', []) + result['schedule'].get('warnings', []),
                           'timezone': result['schedule'].get('timezone')}
                if args.section == 'schedule' and not result.get('total') and not result['warnings']:
                    from goodmorning.web import language as ui
                    window = result['window']
                    result['block'] = ['p', ui.text('No saved appointments for {date} ({timezone}).',
                        date=ui.day_text(window['start']), timezone=result['timezone'])]
        else:
            writing = bool(args.add or args.capture_draft or args.update or args.report or args.adopt or args.convert)
            if writing and not (args.session and args.request_key):
                raise ValueError('input_required: writes need actual session and stable request key')
            inbox = InboxStore(runtime, write=writing)
            store = TaskStore(inbox)
            if args.show:
                result = store.show(args.show, args.draft)
            else:
                payload = decode_input(args)
                now = stamp(runtime)
                if args.add or args.capture_draft:
                    result = inbox.mutate('add', {**payload, 'kind': 'event_proposal' if args.capture_draft else 'todo'}, args.session, args.request_key, now)
                elif args.adopt or args.convert:
                    if not args.confirm or args.expect_revision is None:
                        raise ValueError('confirmation_required: adoption needs explicit organization consent and entry revision')
                    result = (store.adopt(args.adopt, args.expect_revision, payload, args.session, args.request_key, now)
                              if args.adopt else store.convert(runtime, args.convert, args.expect_revision, payload, args.session, args.request_key, now))
                else:
                    if args.expect_revision is None:
                        raise ValueError('revision_required: supply revision from task --show')
                    if args.report and not args.date:
                        raise ValueError('date_required: occurrence reporting needs its agreed date')
                    result = store.mutate(args.update or args.report, args.expect_revision, payload, args.session,
                                          args.request_key, now, day=args.date if args.report else None, draft=args.draft, actual=args.actual)
        print(encode(result))
        return 0
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as error:
        message = str(error) if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError) else 'task_unavailable: preserve storage and inspect input/schema'
        print(encode({'error': message.split(':', 1)[0], 'next': message}))
        return 1
    finally:
        if inbox:
            inbox.close()
        if language_token is not None:
            ui.CURRENT.reset(language_token)
