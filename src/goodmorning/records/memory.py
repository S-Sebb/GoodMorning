"""Secretary memory: one short note the secretary keeps about the user, like a friend who remembers.

The secretary rewrites the note in chat as it picks things up, and the evening briefing tidies it
with the day's chat messages. The About me page shows it and lets the user edit it, forget it all
or turn memory off. Unlike other records, forgotten text is deleted, not cancelled.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

from goodmorning.briefings.briefing_day import briefing_day
from goodmorning.runtime_files import atomic_text, profile_fields, runtime_lock, secretary_path
from .inbox_store import encode

PARTS = ('life', 'likes', 'lately')
LENGTH = 2000  # The whole note, about 600 tokens in every conversation.
CHANGES = 30   # Recent chat sessions that changed the note, for the chat's memory marker.
MESSAGES, MESSAGE = 40, 500  # The newest user messages the evening tidy rereads, and each one's length.


def path(runtime):
    target = Path(runtime) / 'memory.json'
    if target.is_symlink():
        raise ValueError('unsafe_path: memory must not be a symlink')
    return target


def load(runtime):
    target = path(runtime)
    if not target.exists():
        return {'enabled': True, 'revision': 0, 'note': dict.fromkeys(PARTS, ''), 'changes': []}
    return json.loads(target.read_text(encoding='utf-8'))


def context(runtime):
    """What a conversation or briefing sees: the note, or only that memory is off."""
    data = load(runtime)
    if not data['enabled']:
        return {'enabled': False, 'revision': data['revision']}
    return {'enabled': True, 'revision': data['revision'], 'note': data['note'],
            **({'updated': data['updated']} if 'updated' in data else {})}


def checked(note):
    if not isinstance(note, dict) or not note or set(note) - set(PARTS):
        raise ValueError('invalid_input: supply a JSON object with any of life, likes and lately')
    for part, text in note.items():
        if not isinstance(text, str) or any(ord(c) < 32 and c != '\n' for c in text):
            raise ValueError(f'invalid_input: {part} is plain text')
    return {part: text.strip() for part, text in note.items()}


def conversations(runtime):
    chats = Path(runtime) / 'browser-chats' / 'chats.json'
    if chats.is_symlink():
        raise ValueError('unsafe_path: conversations must belong to this runtime')
    return json.loads(chats.read_text(encoding='utf-8')).values() if chats.exists() else []


def remembered(item, turn):
    """Setup answers are settings, not memories, and a message held for storage consent never reached the secretary."""
    return bool(turn.get('text')) and item['mode'] != 'initialize' and not turn.get('local')


def chinese(text):
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def change(runtime, revision, *, note=None, enabled=None, session=None):
    """Rewrite parts of the note or switch memory on or off, checked against the revision."""
    item = next((item for item in conversations(runtime) if session and item.get('session') == session), None)
    if note is not None and item and item['mode'] == 'initialize':
        raise ValueError('memory_setup: setup chats keep no memories; setup saves its answers itself, so write nothing')
    with runtime_lock(runtime, 'memory.lock'):
        data = load(runtime)
        if revision != data['revision']:
            raise ValueError(f'revision_conflict: memory changed (now revision {data["revision"]}); run memory --show and write again')
        if enabled is not None:
            data['enabled'] = enabled
        else:
            if not data['enabled']:
                raise ValueError('memory_off: the user turned memory off on the About me page; write nothing')
            merged = data['note'] | checked(note)
            if item and item['turns'] and item['turns'][-1].get('language') == 'zh-CN' and any(
                    text and text != data['note'][part] and not chinese(text) for part, text in merged.items()):
                raise ValueError('memory_language: write each changed part in Simplified Chinese, the website language; nothing was saved')
            size = sum(len(text) for text in merged.values())
            if size > LENGTH:
                raise ValueError(f'memory_too_long: the note would be {size} characters; merge and trim it to {LENGTH} and write again')
            if merged == data['note']:
                return {'saved': False, 'revision': data['revision']}
            data['note'] = merged
            data['updated'] = briefing_day(profile_fields(runtime).get('timezone', ''))
        data['revision'] += 1
        if session and note is not None:
            stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
            data['changes'] = [*data['changes'], {'seq': data['revision'], 'session': session, 'at': stamp}][-CHANGES:]
        atomic_text(path(runtime), encode(data))
    return {'saved': True, 'revision': data['revision']}


def tidy(runtime):
    """The user's chat messages since the last tidy, oldest first, and mark them as seen.

    Only the user's own words: the secretary's replies never become memories."""
    zone = profile_fields(runtime).get('timezone', '')
    try:
        zone = ZoneInfo(zone or 'UTC')
    except (ValueError, KeyError):
        zone = timezone.utc
    items = conversations(runtime)
    with runtime_lock(runtime, 'memory.lock'):
        data = load(runtime)
        now = time.time()
        since = data.get('tidied', now - 86400)
        found = sorted((turn.get('created', item['created']), turn['text']) for item in items for turn in item['turns']
                       if remembered(item, turn) and since < turn.get('created', item['created']) <= now)[-MESSAGES:]
        data['tidied'] = now
        atomic_text(path(runtime), encode(data))
    return [{'at': datetime.fromtimestamp(at, zone).strftime('%a %H:%M'), 'text': text[:MESSAGE]} for at, text in found]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog='JSON input fields and tested examples: docs/helper-inputs.md')
    parser.add_argument('--secretary-dir')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--show', action='store_true')
    actions.add_argument('--write', action='store_true')
    parser.add_argument('--expect-revision', type=int)
    parser.add_argument('--session', default=os.environ.get('OPENCODE_SESSION_ID'))
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--input-stdin', action='store_true')
    inputs.add_argument('--input-json')
    args = parser.parse_args(argv)
    try:
        runtime = secretary_path(args.secretary_dir)
        if args.show:
            print(encode(context(runtime)))
            return 0
        if args.expect_revision is None:
            raise ValueError('revision_required: supply the revision from prepare, memory --show or the last receipt')
        text = args.input_json if args.input_json is not None else sys.stdin.read(10001) if args.input_stdin else ''
        if not text or len(text) > 10000:
            raise ValueError('input_required: supply bounded JSON with --input-stdin or --input-json')
        print(encode(change(runtime, args.expect_revision, note=json.loads(text), session=args.session)))
        return 0
    except (ValueError, OSError) as error:
        message = (f'invalid_input: malformed JSON ({error.msg}, line {error.lineno} column {error.colno}); nothing was saved'
                   if isinstance(error, json.JSONDecodeError) else str(error) if isinstance(error, ValueError)
                   else 'memory_unavailable: preserve storage and inspect the runtime')
        print(encode({'error': message.split(':', 1)[0], 'next': message}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
