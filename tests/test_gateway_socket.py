"""Exercise the production Unix listener's bounded connection and worker queues."""
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.security.briefing_gateway import Server


class GatewaySocketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'gateway.sock')

    def test_listener_accepts_a_browser_asset_burst_before_servicing_connections(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(handler):
                handler.send_response(200)
                handler.send_header('Content-Length', '0')
                handler.end_headers()
            def log_message(self, *_):
                pass
        server = Server(self.path, Handler)
        self.addCleanup(server.server_close)
        clients = []
        for _ in range(30):  # Fits the existing public NGINX burst limit.
            client = socket.socket(socket.AF_UNIX)
            self.addCleanup(client.close)
            client.setblocking(False)
            client.connect(self.path)
            clients.append(client)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        for client in clients:
            client.settimeout(2)
            client.sendall(b'GET /auth.js HTTP/1.0\r\n\r\n')
            self.assertIn(b' 200 ', client.recv(1024).split(b'\r\n', 1)[0])

    def test_busy_workers_queue_an_asset_without_increasing_worker_count(self):
        release = threading.Event()
        condition = threading.Condition()
        active = 0
        peak = 0
        total = 0
        class Handler(BaseHTTPRequestHandler):
            def do_GET(handler):
                nonlocal active, peak, total
                with condition:
                    active += 1
                    peak = max(peak, active)
                    total += 1
                    condition.notify_all()
                try:
                    if handler.path == '/held':
                        if not release.wait(5):
                            return
                    handler.send_response(200)
                    handler.send_header('Content-Length', '0')
                    handler.end_headers()
                finally:
                    with condition:
                        active -= 1
                        condition.notify_all()
            def log_message(self, *_):
                pass
        server = Server(self.path, Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        clients = []
        try:
            for index in range(16):
                client = socket.socket(socket.AF_UNIX)
                clients.append(client)
                client.settimeout(2)
                client.connect(self.path)
                client.sendall(b'GET /held HTTP/1.0\r\n\r\n')
                with condition:
                    self.assertTrue(condition.wait_for(lambda: total > index, timeout=2))
            asset = socket.socket(socket.AF_UNIX)
            clients.append(asset)
            asset.settimeout(0.05)
            asset.connect(self.path)
            asset.sendall(b'GET /auth.js HTTP/1.0\r\n\r\n')
            # It must remain connected while the bounded workers finish, not reset.
            with self.assertRaises(socket.timeout):
                asset.recv(1024)
            release.set()
            asset.settimeout(2)
            self.assertIn(b' 200 ', asset.recv(1024).split(b'\r\n', 1)[0])
            self.assertLessEqual(peak, 16)
            for client in clients[:-1]:
                client.recv(1024)
        finally:
            release.set()
            for client in clients:
                try:
                    client.settimeout(0.2)
                    client.recv(1024)
                except OSError:
                    pass
                client.close()
            server.shutdown()
            server.server_close()
            worker.join(2)

    def test_sustained_overload_returns_http_503_without_dispatching_or_releasing_a_slot(self):
        server = Server(self.path, BaseHTTPRequestHandler)
        self.addCleanup(server.server_close)
        server.request_wait_seconds = 0
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        with patch.object(server, 'slots') as slots, patch.object(server, 'finish_request') as dispatch:
            slots.acquire.return_value = False
            server.process_request(left, '')
            response = right.recv(2048)
            self.assertIn(b'503 Service Unavailable', response)
            self.assertIn(b'Cache-Control: no-store', response)
            self.assertIn(b'Retry-After: 1', response)
            self.assertIn('error', json.loads(response.split(b'\r\n\r\n', 1)[1]))
            slots.acquire.assert_called_once_with(timeout=0)
            slots.release.assert_not_called()
            dispatch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
