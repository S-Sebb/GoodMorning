"""Every documented helper input example saves through the real command-line helper."""

import contextlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from goodmorning.records import custom, inbox, task, workflow
from goodmorning.records.inbox_store import initialize, stamp

EXAMPLE = re.compile(r"^ *```json ([^\n]+)\n(.*?)^ *```", re.M | re.S)
NUDGE = {"raw": "Water the plants", "task": {"title": "Water the plants"}}


def examples(path):
    return [(command, json.loads(body)) for command, body in EXAMPLE.findall(path.read_text())]


class HelperInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {"SECRETARY_DIR": str(self.root)}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        (self.root / "profile.md").write_text('city: "London, GB"\ntimezone: "Europe/London"\n'
            'news_country: "GB"\nsecretary_language: "English"\nnews_latest: "false"\n')
        initialize(self.root)
        self.keys = 0

    def run_helper(self, main, args, payload=None):
        self.keys += 1
        args = [*args, "--session", "ses-test", "--request-key", f"key-{self.keys}"]
        if payload is not None:
            args.append("--input-stdin")
        with patch("sys.stdin", io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(io.StringIO()) as out:
            main(args)
        receipt = json.loads(out.getvalue())
        self.assertTrue(receipt.get("saved"), receipt)
        return receipt

    def save(self, command, payload):
        """Run one example, creating the record it changes when the command needs one."""
        today = stamp(self.root)[:10]
        operation = command.split()[:2]
        if operation[0] == "workflow":
            return self.run_helper(workflow.main, command.split()[1:], payload)
        if operation == ["task", "--update"] or operation == ["task", "--report"]:
            repeat = {"timezone": "Europe/London", "repeat": {"weekdays": list(range(7)), "start": today}}
            created = self.run_helper(task.main, ["--add"], {**NUDGE, "task": {**NUDGE["task"],
                                      **(repeat if operation[1] == "--report" else {})}})
            day = ["--date", today] if operation[1] == "--report" else []
            return self.run_helper(task.main, [operation[1], created["task_id"], "--expect-revision", "1", *day], payload)
        if operation[0] == "task":
            return self.run_helper(task.main, operation[1:], payload)
        if operation[0] == "inbox":
            created = self.run_helper(workflow.main, ["--capture", "eureka"], {"raw": "Weekly mood line"})
            revision = ["--expect-revision", str(created["revision"])] if operation[1] == "--update" else []
            return self.run_helper(inbox.main, [operation[1], created["id"], *revision], payload)
        if operation == ["custom", "--add"]:
            return self.run_helper(custom.main, ["--add"], payload)
        if operation == ["custom", "--report"]:
            created = self.run_helper(custom.main, ["--add"], {"title": "Stretch", "timezone": "Europe/London",
                "policy": {"base": "weekdays", "weekdays": [0], "start": today, "anchor": "fixed", "miss_policy": "fixed"}})
            return self.run_helper(custom.main, ["--report", created["id"], "--expect-revision", "1", "--date", today], payload)
        self.fail("No runner for documented example: " + command)

    def test_every_documented_example_saves(self):
        found = examples(ROOT / "docs" / "helper-inputs.md")
        self.assertGreaterEqual(len(found), 9)
        for command, payload in found:
            with self.subTest(command):
                self.save(command, payload)

    def test_workflow_capture_examples_save(self):
        for name in ("todo", "eureka"):
            found = examples(ROOT / "docs" / "workflows" / f"{name}.md")
            self.assertEqual([command for command, _ in found], [f"workflow --capture {name}"])
            self.save(*found[0])

    def test_malformed_json_is_named_as_an_input_error(self):
        for main, args in ((workflow.main, ["--capture", "todo"]), (task.main, ["--add"]),
                           (custom.main, ["--add"]), (inbox.main, ["--add"])):
            with patch("sys.stdin", io.StringIO('{"raw":"Buy milk"}}')), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main([*args, "--session", "ses-test", "--request-key", "bad-json", "--input-stdin"]), 1)
            self.assertEqual(json.loads(out.getvalue())["error"], "invalid_input", args)

    def test_json_helpers_point_to_the_input_contract(self):
        for main in (workflow.main, task.main, inbox.main, custom.main):
            with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit):
                main(["--help"])
            self.assertIn("docs/helper-inputs.md", out.getvalue())


if __name__ == "__main__":
    unittest.main()
