#!/usr/bin/env python3
"""Compact JSON CLI for secretary capture, current memory and explicit history."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfoNotFoundError

from .inbox_store import InboxStore, KINDS, STATUSES, encode, initialize, stamp


def bounded(low, high):
    def parse(value):
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"must be between {low} and {high}")
        return number
    return parse


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secretary-dir", default=os.environ.get("SECRETARY_DIR", "~/.local/share/GoodMorning/secretary"))
    actions = parser.add_mutually_exclusive_group(required=True)
    for name in ("init", "add", "list", "stats"):
        actions.add_argument("--" + name, action="store_true")
    for name in ("append", "update", "show", "raw", "history"):
        actions.add_argument("--" + name, metavar="ID")
    actions.add_argument("--event", type=bounded(1, 2**63 - 1), metavar="EVENT")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--input-json")
    inputs.add_argument("--input-file")
    inputs.add_argument("--input-stdin", action="store_true")
    parser.add_argument("--session", default=os.environ.get("OPENCODE_SESSION_ID"))
    parser.add_argument("--request-key")
    parser.add_argument("--expect-revision", type=bounded(1, 2**63 - 1))
    parser.add_argument("--status", choices=("active", "all", *STATUSES), default="active")
    parser.add_argument("--kind", choices=KINDS)
    parser.add_argument("--project")
    parser.add_argument("--search", help="literal substring in current summary/context or original input; --list only")
    parser.add_argument("--after", type=bounded(0, 2**63 - 1), default=0)
    parser.add_argument("--limit", type=bounded(1, 30), default=7)
    parser.add_argument("--budget", type=bounded(4096, 32000), default=8000)
    parser.add_argument("--offset", type=bounded(0, 2**63 - 1), default=0)
    parser.add_argument("--chars", type=bounded(1, 8000), default=2000)
    args = parser.parse_args(argv)
    directory = Path(args.secretary_dir).expanduser().resolve()
    store = None
    try:
        if not directory.is_dir():
            raise ValueError("setup_required: secretary directory does not exist")
        mutation = args.add or args.append or args.update
        if mutation:
            if not args.session:
                raise ValueError("session_required: supply the current session ID or a confirmed stable label")
        if mutation:
            if not args.request_key:
                raise ValueError("request_key_required: use one unique key per action and reuse it on retries")
            if args.update and args.expect_revision is None:
                raise ValueError("revision_required: updates require --expect-revision from --show")
            if args.input_json is not None:
                text = args.input_json
            elif args.input_file:
                with open(args.input_file, encoding="utf-8") as stream:
                    text = stream.read(100001)
            elif args.input_stdin:
                text = sys.stdin.read(100001)
            else:
                raise ValueError("input_required: supply a JSON payload")
            if len(text) > 100000:
                raise ValueError("invalid_input: JSON payload exceeds 100000 characters")
            payload = json.loads(text)
        elif args.input_json is not None or args.input_file or args.input_stdin:
            raise ValueError("invalid_input: read/setup commands do not accept capture payloads")
        if args.init:
            result = initialize(directory)
        else:
            store = InboxStore(directory, write=bool(mutation))
            if mutation:
                action = "add" if args.add else "append" if args.append else "update"
                result = store.mutate(action, payload, args.session, args.request_key, stamp(directory),
                                      args.append or args.update, args.expect_revision)
            elif args.stats:
                result = store.stats()
            elif args.list:
                result = store.list(args.status, args.kind, args.project, args.after, args.limit, args.budget, args.search)
            elif args.show:
                result = store.show(args.show)
            elif args.history:
                result = store.history(args.history, args.after, args.limit)
            else:
                result = store.text(args.event or args.raw, bool(args.event), args.offset, args.chars)
        print(encode(result))
        return 0
    except (ValueError, OSError, sqlite3.Error, ZoneInfoNotFoundError) as error:
        if isinstance(error, sqlite3.Error):
            if "locked" in str(error) or "busy" in str(error):
                message = "runtime_busy: inbox is in use; retry later with the same request key"
            else:
                message = "inbox_unavailable: missing, unreadable or corrupt database; preserve it and inspect setup"
        elif isinstance(error, json.JSONDecodeError):
            message = "invalid_input: malformed JSON payload"
        elif isinstance(error, ZoneInfoNotFoundError):
            message = "setup_required: profile timezone must be a valid IANA timezone"
        elif isinstance(error, OSError):
            message = "storage_error: cannot access inbox files; inspect permissions and preserve existing data"
        else:
            message = str(error)
        print(encode({"error": message.split(":", 1)[0], "next": message}))
        return 1
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    sys.exit(main())
