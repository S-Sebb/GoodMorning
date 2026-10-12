"""Native attachments, streamed limits and account isolation using synthetic files."""
from http.server import ThreadingHTTPServer
import io
import itertools
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web.chat_uploads import Uploads, MAX_UPLOAD_BYTES, UploadReader, upload_name
from goodmorning.web.briefing_chat import Chats, MODES
from goodmorning.web.briefing_server import BrowserApp, serve_live
from goodmorning.web.bridge_json import read_json
from test_briefing_chat import MockChamber, ImmediateThread
import test_briefing_gateway as gateway_tests


class RepeatedBytes:
    def __init__(self, size):
        self.remaining = size
        self.largest_read = 0

    def read(self, size):
        self.largest_read = max(self.largest_read, size)
        count = min(size, self.remaining)
        self.remaining -= count
        return b'x' * count


class BridgeJSONTests(unittest.TestCase):
    def test_native_file_data_is_discarded_but_envelopes_and_escaped_text_survive(self):
        value = {'data': [{'text': 'Literal "data": "keep this" and \\ and 中文',
                          'files': [{'data': 'abc\\\"def', 'name': 'a.txt'}]}], 'cursor': {'next': None}}
        expected = {'data': [{'text': value['data'][0]['text'], 'files': [{'data': '', 'name': 'a.txt'}]}],
                    'cursor': {'next': None}}
        raw = json.dumps(value).encode()
        for size in range(1, 34):
            chunks = iter(raw[index:index + size] for index in range(0, len(raw), size))
            class Reader:
                def read(self, _):
                    return next(chunks, b'')
            self.assertEqual(read_json(Reader(), attachment_data=True), expected)

    def test_large_attachment_receipt_stays_small_and_text_limit_still_applies(self):
        chunks = iter(itertools.chain([b'{"data":{"id":"msg_synthetic","payload":{"files":[{"data":"'],
            itertools.repeat(b'e' * 65536, 1100), [b'","name":"large.txt"}]}}}']))
        class Reader:
            def read(self, _):
                return next(chunks, b'')
        result = read_json(Reader(), limit=200, attachment_data=True)
        self.assertEqual(result['data']['id'], 'msg_synthetic')
        self.assertEqual(result['data']['payload']['files'][0]['data'], '')
        with self.assertRaises(ValueError):
            read_json(io.BytesIO(json.dumps({'text': 'x' * 201}).encode()), limit=200, attachment_data=True)
        self.assertEqual(read_json(io.BytesIO(b'{"data":"ordinary response"}')), {'data': 'ordinary response'})


class UploadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.uploads = Uploads(self.root)
        self.file_id = 'f' * 32

    def upload(self, name='notes.txt', data=b'Synthetic notes', identifier=None):
        return self.uploads.receive(identifier or self.file_id, name, io.BytesIO(data), len(data))

    def chats(self):
        chamber = MockChamber(self.root)
        return Chats(self.root, chamber), chamber

    def test_exact_limit_streams_and_larger_upload_is_rejected_before_read(self):
        data = RepeatedBytes(MAX_UPLOAD_BYTES)
        entry = self.uploads.receive(self.file_id, 'large.txt', data, MAX_UPLOAD_BYTES)
        self.assertEqual(entry['size'], MAX_UPLOAD_BYTES)
        self.assertLessEqual(data.largest_read, 65536)
        with self.assertRaises(ValueError):
            self.uploads.receive('a' * 32, 'large.txt', data, MAX_UPLOAD_BYTES + 1)
        self.assertFalse((self.uploads.directory / ('a' * 32)).exists())
        self.upload(identifier='a' * 32, data=b'x')
        chats, _ = self.chats()
        with patch('goodmorning.web.briefing_chat.threading.Thread', ImmediateThread):
            chats.start({'id': 'b' * 32, 'mode': 'secretary', 'text': '',
                         'attachments': [self.file_id, 'a' * 32]})
        self.assertEqual(chats.status('b' * 32)['state'], 'idle')
        self.assertEqual(sum(entry['size'] for entry in chats.get('b' * 32)['turns'][0]['attachments']), MAX_UPLOAD_BYTES + 1)

    def test_private_permissions_empty_files_restart_and_idempotent_upload(self):
        entry = self.upload(data=b'')
        self.assertEqual(self.upload(data=b''), entry)
        self.assertEqual(Uploads(self.root).get(self.file_id), entry)
        directory = self.uploads.directory / self.file_id
        for path in (directory, directory / 'files'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
        for path in (directory / 'metadata.json', directory / 'files' / 'notes.txt'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            self.upload(data=b'Different data')
        self.assertEqual((directory / 'files' / 'notes.txt').read_bytes(), b'')

    def test_partial_upload_does_not_leave_a_file_or_attachment(self):
        with self.assertRaises(ValueError):
            self.uploads.receive(self.file_id, 'notes.txt', io.BytesIO(b'partial'), 100)
        self.assertFalse((self.uploads.directory / self.file_id).exists())
        with self.assertRaises(ValueError):
            UploadReader(io.BytesIO(b''), 1).read(10)

    def test_paths_remote_urls_symlinks_and_cross_account_ids_are_rejected(self):
        for name in ('../secret', '..', '/etc/passwd', 'a\\b', 'a\x00b', 'a\nb'):
            with self.assertRaises(ValueError):
                upload_name('name=' + quote(name, safe=''))
        self.upload()
        other = self.root / 'other'; other.mkdir()
        with self.assertRaises(ValueError):
            Uploads(other).get(self.file_id)
        chats, chamber = self.chats()
        for values in ([self.file_id, self.file_id], ['file:///etc/passwd'], ['https://example.test/file'], [{}]):
            with self.assertRaises(ValueError):
                chats.start({'id': 'a' * 32, 'mode': 'secretary', 'text': '', 'attachments': values})
        self.assertEqual(chamber.calls, [])
        path = self.uploads.directory / self.file_id / 'files' / 'notes.txt'
        path.unlink(); path.symlink_to(self.root / 'other')
        with self.assertRaises(ValueError):
            self.uploads.get(self.file_id)

    def test_all_modes_send_native_files_without_leaking_paths_to_browser(self):
        self.upload(name='资料 <img>.txt')
        chats, chamber = self.chats()
        with patch('goodmorning.web.briefing_chat.threading.Thread', ImmediateThread):
            for index, mode in enumerate(MODES):
                chat = format(index, '032x')
                body = {'id': chat, 'mode': mode, 'text': '', 'attachments': [self.file_id]}
                chats.start(body); chats.start(body)
                path, payload = chamber.replies[-1]
                self.assertTrue(path.endswith('/prompt'))
                self.assertEqual(payload['files'], self.uploads.files([self.file_id]))
                status = chats.status(chat)
                self.assertEqual(status['state'], 'idle')
                self.assertEqual(status['messages'][0]['attachments'][0]['name'], '资料 <img>.txt')
                self.assertNotIn(str(self.root), json.dumps(status))
                self.assertEqual(len(chamber.replies), index + 1)
                with self.assertRaises(ValueError):
                    chats.start({**body, 'attachments': []})
            chat = '0' * 32
            body = {'id': 'a' * 32, 'text': 'Please review', 'attachments': [self.file_id]}
            chats.send(chat, body); chats.send(chat, body)
            self.assertEqual(len(chamber.replies), 5)
            self.assertIn('Please review', chats.status(chat)['messages'][-2]['text'])
            self.upload(name='second.txt', data=b'Second file', identifier='e' * 32)
            chats.send(chat, {'id': 'b' * 32, 'text': '', 'attachments': ['e' * 32]})
            chats.send(chat, {'id': 'c' * 32, 'text': '', 'attachments': [self.file_id]})
            messages = chats.status(chat)['messages']
            self.assertEqual(messages[-4]['attachments'][0]['name'], 'second.txt')
            self.assertEqual(messages[-2]['attachments'][0]['name'], '资料 <img>.txt')
            self.assertEqual(Chats(self.root, chamber).status(chat)['state'], 'idle')

    def test_uncertain_native_dispatch_is_not_replayed(self):
        self.upload()
        chats, chamber = self.chats(); chamber.fail = True
        body = {'id': 'a' * 32, 'mode': 'secretary', 'text': 'Review', 'attachments': [self.file_id]}
        with patch('goodmorning.web.briefing_chat.threading.Thread', ImmediateThread):
            chats.start(body)
            self.assertEqual(chats.status(body['id'])['state'], 'uncertain')
            chats.start(body)
            self.assertEqual(sum(action == 'session.create' for action, _ in chamber.calls), 1)


class UploadHTTPTests(unittest.TestCase):
    def setUp(self):
        self.fixture = gateway_tests.GatewayTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.runtime = self.fixture.root / 'secretary'; self.runtime.mkdir()
        self.chamber = MockChamber(self.runtime)
        self.app = BrowserApp(self.runtime, self.chamber)
        ready = threading.Event()
        servers = []
        def server(*args):
            created = ThreadingHTTPServer(*args)
            servers.append(created); ready.set()
            return created
        with patch('goodmorning.web.briefing_server.ThreadingHTTPServer', server), patch('builtins.print'):
            worker = threading.Thread(target=serve_live, args=(self.app, 0), kwargs={
                'gateway_key': self.fixture.key, 'public_origins': ('https://gm.example.test',)}, daemon=True)
            worker.start()
            self.assertTrue(ready.wait(2))
        self.backend = servers[0]
        self.addCleanup(self.backend.server_close); self.addCleanup(self.backend.shutdown)
        (self.fixture.root / 'backends.json').write_text(json.dumps({self.fixture.id: {
            'port': self.backend.server_port, 'key': self.fixture.key}}))

    def request_upload(self, data=b'Synthetic upload', *, name='notes.txt', headers=None, identifier='f' * 32):
        fixture = self.fixture
        values = {'Host': 'gm.example.test', 'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1',
            'Cookie': fixture.cookie or '', 'Origin': 'https://gm.example.test',
            'X-Briefing-CSRF': fixture.csrf or '', 'Content-Type': 'application/octet-stream'}
        values.update(headers or {})
        path = '/api/chat-uploads/' + identifier + '?name=' + quote(name, safe='')
        try:
            response = fixture.opener.open(Request(f'http://127.0.0.1:{fixture.server.server_port}' + path,
                data=data, headers=values), timeout=10)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_gateway_upload_and_native_chat_roundtrip_preserve_json_limits(self):
        self.fixture.permanent()
        status, entry = self.request_upload()
        self.assertEqual(status, 201)
        self.assertIsNone(self.fixture.gateway.ticket())
        self.assertEqual(self.app.chats.uploads.get(entry['id']), entry)
        with patch('goodmorning.web.briefing_chat.threading.Thread', ImmediateThread):
            status, _, _ = self.fixture.request('/api/chats', {
                'id': 'a' * 32, 'mode': 'secretary', 'text': 'Read this', 'attachments': [entry['id']]})
        self.assertEqual(status, 202)
        status, _, raw = self.fixture.request('/api/chats/' + 'a' * 32)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['messages'][0]['attachments'], [entry])
        self.assertEqual(self.fixture.request('/api/avatar', {'avatar': 'x' * 20000})[0], 400)
        self.assertEqual(self.fixture.request('/api/fs/upload', {'path': '/tmp/unsafe'})[0], 403)

    def test_authentication_origin_csrf_size_and_filename_boundaries(self):
        self.assertEqual(self.request_upload()[0], 403)
        session = self.fixture.login(); self.fixture.csrf = session['csrf']
        self.assertEqual(self.request_upload()[0], 403)
        self.fixture.cookie = None; self.fixture.permanent()
        for headers in ({'Origin': 'https://evil.test'}, {'X-Briefing-CSRF': 'wrong'},
                        {'Cookie': ''}, {'Host': 'evil.test'}):
            self.assertEqual(self.request_upload(headers=headers)[0], 403)
        self.assertEqual(self.request_upload(b'', headers={'Content-Length': str(MAX_UPLOAD_BYTES + 1)})[0], 413)
        self.assertEqual(self.request_upload(name='../private.txt')[0], 400)
        self.assertEqual(list(self.app.chats.uploads.directory.iterdir()), [])
        self.assertEqual(self.fixture.request('/api/chat-uploads/' + 'f' * 32)[0], 403)

    def test_fifty_megabytes_cross_gateway_and_backend_without_whole_file_buffer(self):
        self.fixture.permanent()
        data = RepeatedBytes(MAX_UPLOAD_BYTES)
        status, entry = self.request_upload(data, headers={'Content-Length': str(MAX_UPLOAD_BYTES)})
        self.assertEqual(status, 201)
        self.assertEqual(entry['size'], MAX_UPLOAD_BYTES)
        self.assertLessEqual(data.largest_read, 65536)

    def test_backend_also_rejects_oversize_and_foreign_upload_ids(self):
        self.fixture.permanent()
        headers = {'Authorization': 'Bearer ' + self.fixture.key, 'X-GoodMorning-Origin': 'https://gm.example.test',
            'Content-Type': 'application/octet-stream', 'Content-Length': str(MAX_UPLOAD_BYTES + 1)}
        with self.assertRaises(HTTPError) as error:
            self.fixture.opener.open(Request(f'http://127.0.0.1:{self.backend.server_port}/api/chat-uploads/'
                + 'f' * 32 + '?name=notes.txt', data=b'', headers=headers), timeout=3)
        self.assertEqual(error.exception.code, 413); error.exception.close()
        self.assertEqual(self.fixture.request('/api/chats', {
            'id': 'a' * 32, 'mode': 'secretary', 'text': 'Read', 'attachments': ['f' * 32]})[0], 400)
        self.assertEqual(self.chamber.calls, [])


if __name__ == '__main__':
    unittest.main()
