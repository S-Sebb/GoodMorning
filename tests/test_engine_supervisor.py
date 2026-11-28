"""The account engine supervisor relays its socket to `opencode serve` and stops only when idle."""

import socket
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from support import TEMP_ROOT

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from goodmorning.security.briefing_runtime import Supervisor

# A stand-in for `opencode serve`: it echoes its password, and reports a
# running session while the file named by its first argument exists.
FAKE = textwrap.dedent("""
    import json, os, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    busy, port = sys.argv[1], int(sys.argv[sys.argv.index('--port')+1])
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/api/session/active':
                body = {'data': {'ses_a': {'type': 'running'}} if os.path.exists(busy) else {}}
            else:
                body = {'password': os.environ['OPENCODE_SERVER_PASSWORD']}
            data = json.dumps(body).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers()
            self.wfile.write(data)
        def log_message(self, *args): pass
    HTTPServer(('127.0.0.1', port), Handler).serve_forever()
""")


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "fake.py").write_text(FAKE)
        self.busy = self.root / "busy"
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(self.listener.close)
        self.supervisor = Supervisor(
            self.listener,
            [sys.executable, str(self.root / "fake.py"), str(self.busy)],
            {},
            "synthetic-password",
            str(self.root),
            idle=0,
        )
        self.addCleanup(self.supervisor.stop)

    def get(self, path):
        import json

        with urlopen(
            Request(f"http://127.0.0.1:{self.listener.getsockname()[1]}{path}"),
            timeout=30,
        ) as response:
            return json.loads(response.read())

    def test_relays_to_the_password_protected_engine_and_stops_when_idle(self):
        result = {}
        runner = threading.Thread(
            target=lambda: result.setdefault("code", self.supervisor.run(check=0.1))
        )
        self.busy.touch()
        runner.start()
        self.assertEqual(self.get("/doc")["password"], "synthetic-password")
        # A running session, such as a parked question, keeps the engine up.
        runner.join(2)
        self.assertTrue(runner.is_alive())
        self.busy.unlink()
        runner.join(30)
        self.assertEqual(result["code"], 0)
        self.assertIsNotNone(self.supervisor.process.poll())


class EngineEnvironmentTests(unittest.TestCase):
    def test_agent_python_is_the_server_interpreter(self):
        """Receipts tell agents to run `python ...`; it must be the interpreter with Pillow (#318)."""
        import json
        import os
        import shutil
        from unittest.mock import patch

        from goodmorning.security import briefing_runtime

        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        volume = Path(temp.name)
        (volume / "engine.json").write_text(
            json.dumps({"chamberPort": 0, "uiPassword": "synthetic"})
        )
        # main() refuses root, and the server stage runs the suite as root.
        owner = volume.stat().st_uid
        if owner == 0:
            owner = 65534
            os.chown(volume, owner, -1)
        started = {}

        def supervisor(listener, command, env, *args):
            started["env"] = dict(env)
            return type(
                "Fake", (), {"run": lambda self: 0, "stop": lambda self: None}
            )()

        with (
            patch.dict(os.environ, {"USER": "synthetic"}),
            patch.object(sys, "argv", ["runtime", "--volume", str(volume), "engine"]),
            patch.object(briefing_runtime, "encrypted_mount", return_value=volume),
            patch.object(briefing_runtime.os, "chdir"),
            patch.object(briefing_runtime.os, "geteuid", return_value=owner),
            patch.object(briefing_runtime.socket, "create_server"),
            patch.object(briefing_runtime, "Supervisor", supervisor),
            patch.object(briefing_runtime.signal, "signal"),
            self.assertRaises(SystemExit),
        ):
            briefing_runtime.main()
        self.assertEqual(
            shutil.which("python", path=started["env"]["PATH"]),
            str(Path(sys.executable).parent / "python"),
        )


class ForeignRipgrepTests(unittest.TestCase):
    """A vault moved from another CPU keeps OpenCode's cached `rg`, which then fails (#347)."""

    def cached(self, machine):
        from goodmorning.security import briefing_runtime

        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        home = Path(temp.name)
        rg = home / ".cache/opencode/bin/rg"
        rg.parent.mkdir(parents=True)
        rg.write_bytes(
            b"\x7fELF\x02\x01" + bytes(12) + machine.to_bytes(2, "little") + bytes(40)
        )
        return briefing_runtime, home, rg

    def test_removes_an_x86_64_rg_on_an_arm_host_and_keeps_a_matching_one(self):
        from unittest.mock import patch

        runtime, home, rg = self.cached(62)
        with patch.object(runtime.platform, "machine", return_value="aarch64"):
            runtime.drop_foreign_ripgrep(home)
        self.assertFalse(rg.exists())
        runtime, home, rg = self.cached(183)
        with patch.object(runtime.platform, "machine", return_value="aarch64"):
            runtime.drop_foreign_ripgrep(home)
        self.assertTrue(rg.exists())


if __name__ == "__main__":
    unittest.main()
