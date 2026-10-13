"""Inbox safety, bounded reads and constant-size capture."""

import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from goodmorning.records import inbox
from goodmorning.records.inbox_store import InboxStore, encode, initialize
from goodmorning.records import state

NOW = "2026-10-10T12:00:00+01:00"


class InboxFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "profile.md").write_text('timezone: "Europe/London"\n')

    def store(self):
        initialize(self.root)
        store = InboxStore(self.root, write=True)
        self.addCleanup(store.close)
        return store

    def add(self, store, raw="Buy milk", key="first", **extra):
        return store.mutate("add", {"kind": "todo", "raw": raw, **extra},
                            "ses-test", key, NOW)

    def cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = inbox.main(["--secretary-dir", str(self.root), *args])
        return code, json.loads(output.getvalue())


class InboxTests(InboxFixture):
    def test_read_never_initializes_missing_runtime_or_store(self):
        before = set(self.root.iterdir())
        self.assertEqual(self.cli("--list")[0], 1)
        self.assertEqual(set(self.root.iterdir()), before)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(inbox.main(["--secretary-dir", str(self.root / "missing"), "--stats"]), 1)
        self.assertFalse((self.root / "missing").exists())

    def test_initialization_is_private_idempotent_and_preserves_unrelated_text(self):
        legacy = self.root / "inbox.md"
        legacy.write_text("# Existing inbox\n")
        self.assertEqual(self.cli("--init")[0], 0)
        self.assertEqual(self.cli("--init")[0], 0)
        self.assertEqual((self.root / "inbox.sqlite").stat().st_mode & 0o777, 0o600)
        self.assertEqual(legacy.read_text(), '# Existing inbox\n')
        with sqlite3.connect(self.root / 'inbox.sqlite') as db:
            self.assertNotIn('migration', {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")})

    def test_capture_preserves_unicode_multiline_and_pipes(self):
        store = self.store()
        raw = 'Email A | B\n"中文" ☀️'
        receipt = self.add(store, raw=raw, context="Keep the attachment.")
        self.assertLess(len(encode(receipt)), 150)
        self.assertNotIn(raw, encode(receipt))
        self.assertEqual(store.text(receipt["id"])["text"], raw)
        current = store.show(receipt["id"])
        self.assertNotIn("raw", current)
        self.assertEqual(current["context"], "Keep the attachment.")
        self.assertEqual(current["raw_chars"], len(raw))

    def test_idempotent_retries_and_reused_key_conflict(self):
        store = self.store()
        first = self.add(store)
        self.assertEqual(self.add(store)["id"], first["id"])
        self.assertTrue(self.add(store)["replayed"])
        with self.assertRaisesRegex(ValueError, "request_conflict"):
            self.add(store, raw="Different task")
        self.assertEqual(store.stats()["total"], 1)
        self.assertEqual(len(store.history(first["id"])["items"]), 1)

    def test_followup_capture_without_reading_or_revision_check(self):
        store = self.store()
        identifier = self.add(store)["id"]
        store.mutate("update", {"status": "done", "confirmed_completion": True}, "ses-test", "close", NOW, identifier, 1)
        receipt = store.mutate("append", {"detail": "Also buy bread."},
                               "ses-test", "followup", NOW, identifier)
        self.assertEqual(receipt["revision"], 3)
        current = store.show(identifier)
        self.assertEqual(current["status"], "done")
        self.assertEqual(current["unreviewed_details"], 1)
        self.assertTrue(current["needs_review"])
        self.assertEqual(store.list()["items"][0]["id"], identifier)
        self.assertEqual(store.stats()["pending"], 1)
        self.assertEqual(store.text(receipt["event"], event=True)["text"], "Also buy bread.")

    def test_revision_conflicts_and_review_preserve_unseen_followups(self):
        store = self.store()
        identifier = self.add(store)["id"]
        store.mutate("append", {"detail": "Get lactose-free milk."}, "ses-test", "detail", NOW, identifier)
        with self.assertRaisesRegex(ValueError, "write_conflict"):
            store.mutate("update", {"context": "Old plan"}, "ses-test", "stale", NOW, identifier, 1)
        with self.assertRaisesRegex(ValueError, "unreviewed_details"):
            store.mutate("update", {"status": "done"}, "ses-test", "close", NOW, identifier, 2)
        self.assertEqual(store.show(identifier)["revision"], 2)
        receipt = store.mutate("update", {"context": "Buy lactose-free milk.", "reviewed": True},
                               "ses-test", "review", NOW, identifier, 2)
        current = store.show(identifier)
        self.assertFalse(current["needs_review"])
        self.assertEqual(current["unreviewed_details"], 0)
        replay = store.mutate("update", {"context": "Buy lactose-free milk.", "reviewed": True},
                              "ses-test", "review", NOW, identifier, 2)
        self.assertEqual(replay["revision"], receipt["revision"])
        self.assertTrue(replay["replayed"])

    def test_current_state_replaces_not_accumulates_and_raw_stays_immutable(self):
        store = self.store()
        identifier = self.add(store, context="Initial constraints")["id"]
        store.mutate("update", {"context": "Final constraints", "questions": []},
                     "ses-test", "revise", NOW, identifier, 1)
        self.assertEqual(store.show(identifier)["context"], "Final constraints")
        self.assertNotIn("Initial constraints", encode(store.show(identifier)))
        self.assertIn("Initial constraints", store.text(1, event=True)["text"])
        with self.assertRaisesRegex(ValueError, "invalid_input"):
            store.mutate("update", {"raw": "Changed wording"}, "ses-test", "bad", NOW, identifier, 2)
        self.assertEqual(store.text(identifier)["text"], "Buy milk")

    def test_filters_stable_paging_and_completed_history_exclusion(self):
        store = self.store()
        ids = []
        for number in range(15):
            identifier = self.add(store, key=str(number), project="Demo" if number % 2 else "Other")["id"]
            ids.append(identifier)
        store.mutate("update", {"status": "done", "confirmed_completion": True}, "ses-test", "complete", NOW, ids[0], 1)
        first = store.list(limit=7)
        second = store.list(after=first["next_after"], limit=7)
        self.assertEqual([x["id"] for x in first["items"] + second["items"]], ids[1:])
        self.assertIsNone(second["next_after"])
        self.assertEqual(store.list(project="Demo", kind="todo")["total"], 7)
        self.assertEqual(store.list(status="done")["items"][0]["id"], ids[0])
        self.assertEqual(store.list(status="all")["total"], 15)

    def test_list_budget_preserves_whole_questions_and_excludes_context_raw(self):
        store = self.store()
        for n in range(7):
            store.mutate('add', {'kind':'idea', 'raw':'x' * 60000, 'context':'C' * 6000,
                                'questions':['Q' * 1000, 'R' * 1000]}, 'ses-test', str(n), NOW)
        page = store.list(budget=4096)
        self.assertLess(len(encode(page)), 4096)
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["items"][0]["questions"], ["Q" * 1000, "R" * 1000])
        self.assertEqual(page["next_after"], 1)
        self.assertNotIn("context", page["items"][0])
        self.assertNotIn("raw", page["items"][0])

    def test_literal_search_finds_constraints_without_loading_the_corpus(self):
        store = self.store()
        first = self.add(store, raw="Buy an office chair", context="Only below £130", key="chair")
        self.add(store, raw="Buy 100% cotton shirts", key="shirts")
        self.add(store, raw="Use literal _underscore_", key="underscore")
        self.assertEqual(store.list(search="£130")["items"][0]["id"], first["id"])
        self.assertEqual(store.list(search="100%")["total"], 1)
        self.assertEqual(store.list(search="_underscore_")["total"], 1)
        self.assertEqual(store.list(search="nonexistent")["items"], [])
        self.assertFalse(store.db.in_transaction)

    def test_current_reads_finish_a_snapshot_even_on_failure(self):
        store = self.store()
        with self.assertRaises(ValueError):
            store.show("missing")
        self.assertFalse(store.db.in_transaction)
        with store.transaction():
            self.assertEqual(store.list()["total"], 0)
            self.assertTrue(store.db.in_transaction)

    def test_raw_and_event_history_are_explicit_and_paged(self):
        store = self.store()
        raw = "中文\n" * 2000
        receipt = self.add(store, raw=raw)
        parts, offset = [], 0
        while True:
            page = store.text(receipt["id"], offset=offset, chars=1500)
            parts.append(page["text"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        self.assertEqual("".join(parts), raw)
        history = store.history(receipt["id"])
        self.assertNotIn(raw, encode(history))
        self.assertGreater(history["items"][0]["changes_chars"], len(raw))

    def test_validation_never_writes_secret_unknown_or_oversized_payloads(self):
        store = self.store()
        for payload in ({"kind": "todo", "raw": "token=supersecret"},
                        {"kind": "todo", "raw": "https://example.com/?access_token=secret"},
                        {"kind": "task", "raw": "task"}, {"kind": "todo", "raw": ""},
                        {"kind": "todo", "raw": "task", "summary": "x" * 281},
                        {"kind": "todo", "raw": "task", "questions": "a question"},
                        {"kind": "todo", "raw": "task", "unknown": "field"}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                store.mutate("add", payload, "ses-test", "bad", NOW)
        self.assertEqual(store.stats()["total"], 0)

    def test_sql_transaction_rolls_back_entry_when_event_write_fails(self):
        store = self.store()
        store.db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON events BEGIN SELECT RAISE(FAIL,'test'); END")
        with self.assertRaises(sqlite3.Error):
            self.add(store)
        self.assertEqual(store.stats()["total"], 0)

    def test_concurrent_writer_is_busy_not_a_lost_update(self):
        store = self.store()
        other = InboxStore(self.root, write=True)
        self.addCleanup(other.close)
        with store.transaction():
            with self.assertRaises(sqlite3.OperationalError):
                self.add(other)
        self.assertEqual(self.add(other)["revision"], 1)

    def test_future_or_corrupt_schema_is_refused_and_preserved(self):
        self.store()
        path = self.root / "inbox.sqlite"
        db = sqlite3.connect(path)
        db.execute("PRAGMA user_version=999")
        db.close()
        before = path.read_bytes()
        self.assertEqual(self.cli("--stats")[1]["error"], "unsupported_schema")
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(ValueError):
            state.scan_inbox(str(self.root))

    def test_cli_requires_actor_request_key_revision_and_valid_json(self):
        self.store()
        code, receipt = self.cli("--add", "--session", "ses-test", "--request-key", "cli-first",
                                 "--input-json", '{"kind":"todo","raw":"Buy milk"}')
        self.assertEqual(code, 0)
        self.assertEqual(self.cli("--update", receipt["id"], "--session", "ses-test", "--request-key", "u",
                                  "--input-json", '{"status":"done"}')[1]["error"], "revision_required")
        self.assertEqual(self.cli("--append", receipt["id"], "--session", "ses-test",
                                  "--input-json", '{"detail":"Bread"}')[1]["error"], "request_key_required")
        self.assertEqual(self.cli("--add", "--session", "ses-test", "--request-key", "bad-json",
                                  "--input-json", '{"raw":')[1]["error"], "invalid_input")
        self.assertEqual(self.cli("--list", "--input-json", '{}')[1]["error"], "invalid_input")

    def test_state_counts_database_without_opening_legacy_or_history(self):
        store = self.store()
        self.add(store)
        (self.root / "inbox.md").write_text("Do not read this archive pointer")
        with patch("builtins.open", side_effect=AssertionError("legacy read")):
            self.assertEqual(state.scan_inbox(str(self.root)),
                             {"pending": 1, "oldest_pending_date": "2026-10-10", "total": 1})


if __name__ == "__main__":
    unittest.main()
