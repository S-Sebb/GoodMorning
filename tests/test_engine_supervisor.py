"""The account engine supervisor relays its socket to `opencode serve` and stops only when idle."""
from pathlib import Path
import socket
import sys
import tempfile
import textwrap
import threading
import unittest
from urllib.request import Request, urlopen

from support import TEMP_ROOT
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning.security.briefing_runtime import Supervisor

# A stand-in for `opencode serve`: it echoes its password, and reports a
# running session while the file named by its first argument exists.
FAKE = textwrap.dedent('''
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
''')


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root/'fake.py').write_text(FAKE)
        self.busy = self.root/'busy'
        self.listener = socket.create_server(('127.0.0.1', 0))
        self.addCleanup(self.listener.close)
        self.supervisor = Supervisor(self.listener, [sys.executable, str(self.root/'fake.py'), str(self.busy)],
                                     {}, 'synthetic-password', str(self.root), idle=0)
        self.addCleanup(self.supervisor.stop)

    def get(self, path):
        import json
        with urlopen(Request(f'http://127.0.0.1:{self.listener.getsockname()[1]}{path}'), timeout=30) as response:
            return json.loads(response.read())

    def test_relays_to_the_password_protected_engine_and_stops_when_idle(self):
        result = {}
        runner = threading.Thread(target=lambda: result.setdefault('code', self.supervisor.run(check=0.1)))
        self.busy.touch()
        runner.start()
        self.assertEqual(self.get('/doc')['password'], 'synthetic-password')
        # A running session, such as a parked question, keeps the engine up.
        runner.join(3)
        self.assertTrue(runner.is_alive())
        self.busy.unlink()
        runner.join(30)
        self.assertEqual(result['code'], 0)
        self.assertIsNotNone(self.supervisor.process.poll())


if __name__ == '__main__':
    unittest.main()
