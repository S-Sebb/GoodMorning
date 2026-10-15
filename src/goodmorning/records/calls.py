"""Secretary-call operations: manual scan first, then explicit approved writes."""
import argparse
import json
import os
import sqlite3
import sys

from goodmorning.runtime_files import secretary_path
from .inbox_store import encode, stamp
from .calls_store import CallsStore, scan


def decode_input(args):
    text = args.input_json if args.input_json is not None else sys.stdin.read(100001) if args.input_stdin else None
    if text is None or len(text) > 100000:
        raise ValueError("input_required: supply bounded JSON")
    return json.loads(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secretary-dir")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--scan", action="store_true")
    actions.add_argument("--add", action="store_true")
    actions.add_argument("--show")
    actions.add_argument("--list", action="store_true")
    actions.add_argument("--resolve")
    actions.add_argument("--dismiss")
    parser.add_argument("--status", default="")
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
        if args.scan:
            candidates = scan(runtime)
            print(encode({"candidates": candidates, "total": len(candidates)}))
            return 0
        if args.show:
            store = CallsStore(runtime, write=False)
            print(encode(store.show(args.show)))
            return 0
        if args.list:
            try:
                store = CallsStore(runtime, write=False)
            except ValueError as error:
                if "setup_required" in str(error):
                    print(encode({"calls": [], "total": 0, "open": 0}))
                    return 0
                raise
            items = store.all(args.status)
            public = [{k: item[k] for k in ("id", "revision", "created_at", "updated_at", "title",
                                            "reason", "question", "kind", "target_type",
                                            "target_id", "target_revision", "chat_id", "status")}
                      for item in items]
            print(encode({"calls": public, "total": len(public),
                          "open": sum(1 for item in public if item["status"] == "open")}))
            return 0
        writing = bool(args.add or args.resolve or args.dismiss)
        if writing and not (args.session and args.request_key):
            raise ValueError("input_required: writes need actual session and stable request key")
        store = CallsStore(runtime, write=writing)
        payload = decode_input(args) if (args.add or args.resolve or args.dismiss) else {}
        now = stamp(runtime)
        if args.add:
            result = store.add(payload, args.session, args.request_key, now)
        elif args.resolve:
            if args.expect_revision is None:
                raise ValueError("revision_required: supply revision from calls --show")
            result = store.resolve(args.resolve, args.expect_revision, payload, args.session, args.request_key, now)
        else:
            if args.expect_revision is None:
                raise ValueError("revision_required: supply revision from calls --show")
            result = store.dismiss(args.dismiss, args.expect_revision, payload, args.session, args.request_key, now)
        print(encode(result))
        return 0
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as error:
        message = str(error) if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError) else "calls_unavailable: preserve storage and inspect input/schema"
        print(encode({"error": message.split(":", 1)[0], "next": message}))
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    sys.exit(main())
