"""Custom-schedule operations: ask until unambiguous, then save once with a receipt."""
import argparse
import json
import os
import sqlite3
import sys

from goodmorning.runtime_files import secretary_path
from .inbox_store import encode, stamp
from .custom_store import CustomStore


def decode_input(args):
    text = args.input_json if args.input_json is not None else sys.stdin.read(100001) if args.input_stdin else None
    if text is None or len(text) > 100000:
        raise ValueError("input_required: supply bounded JSON")
    return json.loads(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog="JSON input fields and tested examples: docs/helper-inputs.md")
    parser.add_argument("--secretary-dir")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--add", action="store_true")
    actions.add_argument("--show")
    actions.add_argument("--update")
    actions.add_argument("--report")
    actions.add_argument("--briefing", choices=("gm", "gn"))
    parser.add_argument("--date")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--session", default=os.environ.get("OPENCODE_SESSION_ID"))
    parser.add_argument("--request-key")
    parser.add_argument("--expect-revision", type=int)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--input-stdin", action="store_true")
    inputs.add_argument("--input-json")
    args = parser.parse_args(argv)
    store = None
    try:
        runtime = secretary_path(args.secretary_dir)
        if args.briefing:
            if not args.date:
                raise ValueError("date_required: custom briefing needs its pinned date")
            store = CustomStore(runtime, write=False)
            rows = store.briefing(args.date, args.briefing)
            result = {"items": rows, "total": len(rows),
                      "block": ["list", [f"{r['title']} — {'due' if r['due'] else r['reason']}"
                                        + (f" (this week: {r['weekly_count']})" if r["weekly_count"] else "")
                                        for r in rows]] if rows else None}
            print(encode(result))
            return 0
        if args.show:
            store = CustomStore(runtime, write=False)
            print(encode(store.show(args.show)))
            return 0
        writing = bool(args.add or args.update or args.report)
        if writing and not (args.session and args.request_key):
            raise ValueError("input_required: writes need actual session and stable request key")
        store = CustomStore(runtime, write=writing)
        payload = decode_input(args) if (args.add or args.update or args.report) else {}
        now = stamp(runtime)
        if args.add:
            result = store.add(payload, args.session, args.request_key, now)
        elif args.update:
            if args.expect_revision is None:
                raise ValueError("revision_required: supply revision from custom --show")
            result = store.update(args.update, args.expect_revision, payload, args.session, args.request_key, now)
        else:
            if args.expect_revision is None or not args.date:
                raise ValueError("date_required: custom report needs revision and its actual date")
            result = store.report(args.report, args.expect_revision, payload, args.session, args.request_key, now, args.date)
        print(encode(result))
        return 0
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as error:
        message = (f'invalid_input: malformed JSON ({error.msg}, line {error.lineno} column {error.colno}); nothing was saved'
                   if isinstance(error, json.JSONDecodeError) else str(error) if isinstance(error, ValueError) else "custom_unavailable: preserve storage and inspect input/schema")
        print(encode({"error": message.split(":", 1)[0], "next": message}))
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    sys.exit(main())
