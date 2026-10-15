import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from support import TEMP_ROOT
import unittest


HELPER = Path(__file__).resolve().parents[1] / "integrations/projects/project_files.py"


class ProjectFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gm-files-", dir=TEMP_ROOT)
        self.root = Path(self.temp.name)
        self.plan = self.root / "PLAN.md"
        self.plan.write_text("original\n")

    def tearDown(self):
        self.temp.cleanup()

    def command(self, **payload):
        value = {"root": str(self.root), "write_targets": ["PLAN.md"], **payload}
        encoded = base64.b64encode(json.dumps(value).encode()).decode()
        return [sys.executable, str(HELPER), encoded]

    def run_op(self, **payload):
        result = subprocess.run(self.command(**payload), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def test_read_bounded_with_complete_hash(self):
        value = self.run_op(op="read", path="PLAN.md", limit=4)
        self.assertEqual(value["text"], "orig")
        self.assertEqual(value["sha256"], hashlib.sha256(b"original\n").hexdigest())
        self.assertEqual(value["next_offset"], 4)
        self.assertTrue(value["truncated"])
        self.plan.write_text("x" * 100_000)
        self.assertEqual(self.run_op(op="read", path="PLAN.md", limit=4)["text"], "xxxx")

    def test_unicode_cursor_is_characters(self):
        self.plan.write_text("你好世界")
        value = self.run_op(op="read", path="PLAN.md", offset=1, limit=2)
        self.assertEqual(value["text"], "好世")
        self.assertEqual(value["next_offset"], 3)
        self.plan.write_text('WAQI_TOKEN="fake-private-value"\n')
        hidden = self.run_op(op="read", path="PLAN.md", offset=13, limit=5)
        self.assertEqual(hidden["text"], "*****")
        self.assertTrue(hidden["redacted"])

    def test_tail_large_log_is_bounded(self):
        self.plan.write_text("a" * 600_000 + "你好结束")
        value = self.run_op(op="read", path="PLAN.md", limit=4, tail=True)
        self.assertEqual(value["text"], "你好结束")
        self.assertIsNone(value["sha256"])
        self.assertTrue(value["truncated"])
        self.assertEqual(self.run_op(op="read", path="PLAN.md")["error"], "file_too_large")

    def test_listing_pagination_and_secret_names(self):
        for name in ["a.txt", "b.txt", ".env", ".env.production"]:
            (self.root / name).touch()
        value = self.run_op(op="list", path=".", limit=2)
        self.assertEqual(value["total"], 3)
        self.assertEqual(value["next_offset"], 2)
        self.assertNotIn(".env", json.dumps(value))

    def test_path_escape_and_secret_files_are_denied(self):
        for name in ["../PLAN.md", "/etc/passwd", ".env", ".env.production", ".ssh/id_rsa", ".aws/credentials", "server.pem", "credentials.json"]:
            with self.subTest(name=name):
                value = self.run_op(op="read", path=name)
                self.assertFalse(value["ok"])
                self.assertIn(value["error"], ["invalid_path", "secret_path"])

    def test_file_and_directory_symlinks_are_not_followed(self):
        (self.root / "link").symlink_to("/etc/passwd")
        (self.root / "outside").symlink_to("/etc", target_is_directory=True)
        for name in ["link", "outside/passwd"]:
            self.assertFalse(self.run_op(op="read", path=name)["ok"])

    def test_fifo_does_not_block(self):
        os.mkfifo(self.root / "pipe")
        self.assertEqual(self.run_op(op="read", path="pipe")["error"], "not_regular_file")

    def test_compare_and_swap_preserves_mode(self):
        self.plan.chmod(0o640)
        before = self.run_op(op="read", path="PLAN.md")["sha256"]
        value = self.run_op(op="write", path="PLAN.md", expect=before, content="updated\n")
        self.assertTrue(value["ok"])
        self.assertEqual(self.plan.read_text(), "updated\n")
        self.assertEqual(self.plan.stat().st_mode & 0o777, 0o640)
        lock_name = f".gm-write-{hashlib.sha256(b'PLAN.md').hexdigest()}.lock"
        self.assertTrue((self.root / lock_name).is_file())
        self.assertFalse(list(self.root.glob(".gm-write-*.tmp")))

    def test_conflict_does_not_overwrite(self):
        value = self.run_op(op="write", path="PLAN.md", expect="0" * 64, content="bad")
        self.assertEqual(value["error"], "write_conflict")
        self.assertEqual(self.plan.read_text(), "original\n")

    def test_scope_and_missing_hash_are_required(self):
        self.assertEqual(self.run_op(op="write", path="other.md", expect="missing", content="bad")["error"], "write_not_allowed")
        self.assertEqual(self.run_op(op="write", path="PLAN.md", content="bad")["error"], "expected_hash_required")

    def test_missing_is_create_only(self):
        self.assertEqual(self.run_op(op="write", path="PLAN.md", expect="missing", content="bad")["error"], "write_conflict")
        self.plan.unlink()
        self.assertTrue(self.run_op(op="write", path="PLAN.md", expect="missing", content="created")["ok"])

    def test_two_concurrent_writers_only_one_wins(self):
        before = self.run_op(op="read", path="PLAN.md")["sha256"]
        processes = [subprocess.Popen(self.command(op="write", path="PLAN.md", expect=before, content=value), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for value in ["writer one", "writer two"]]
        values = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(stderr, "")
            values.append(json.loads(stdout))
        self.assertEqual(sum(v["ok"] for v in values), 1)
        self.assertEqual([v["error"] for v in values if not v["ok"]], ["write_conflict"])

    def test_invalid_bounds_and_non_utf8(self):
        self.assertEqual(self.run_op(op="read", path="PLAN.md", limit=20_000)["error"], "invalid_bounds")
        self.plan.write_bytes(b"\xff")
        self.assertEqual(self.run_op(op="read", path="PLAN.md")["error"], "invalid_data")

    def test_root_status_is_available_without_listing_contents(self):
        self.assertEqual(self.run_op(op="status"), {"ok": True, "ready": True})


if __name__ == "__main__":
    unittest.main()
