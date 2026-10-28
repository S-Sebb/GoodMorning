"""Shared synthetic fixtures; never a personal secretary runtime."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / 'src'))
from goodmorning.security.briefing_accounts import Accounts, REMEMBER_SECONDS, SESSION_SECONDS
from goodmorning.security.briefing_gateway import Gateway, handler_for
from goodmorning.web.briefing_server import Chamber, serve_live

TEMP_ROOT = os.environ.get("GM_TEST_TMPDIR") or (
    "/tmp/opencode" if Path("/tmp/opencode").is_dir() else tempfile.gettempdir())
Path(TEMP_ROOT).mkdir(parents=True, exist_ok=True)


def returning_viewer(runtime):
    """Unrelated browser suites use an account that already dismissed this release."""
    from goodmorning.web.release import patch_notes
    (Path(runtime) / 'release-seen.json').write_text(json.dumps({'version': patch_notes()[0]['version']}))


class QuickServer(ThreadingHTTPServer):
    """Shutdown returns promptly instead of waiting for the default half-second poll."""
    def serve_forever(self, poll_interval=0.02):
        super().serve_forever(poll_interval)


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def start_server(app):
    """Run the real live viewer in-process on a loopback port."""
    ready, servers = threading.Event(), []
    def create(*args):
        server = QuickServer(*args)
        servers.append(server)
        ready.set()
        return server
    with patch('goodmorning.web.briefing_server.ThreadingHTTPServer', side_effect=create):
        threading.Thread(target=serve_live, args=(app, 0), daemon=True).start()
        if not ready.wait(3):
            raise RuntimeError('Synthetic live viewer did not start')
    return servers[0]


class FakeChamber:
    directory = str(TESTS.parent)
    relocate = Chamber.relocate

    def __init__(self):
        self.calls = []
        self.sent = threading.Event()
        self.busy, self.dismissed = True, False
        self.forms = [{'id': 'frm_test', 'sessionID': 'ses_fixture', 'title': 'How did today go?',
                       'fields': [{'key': 'progress', 'title': 'Reported progress', 'type': 'multiselect',
                                   'required': True, 'minItems': 1, 'maxItems': 1, 'custom': True,
                                   'options': [{'value': 'unreported', 'label': 'No completion report'}]}]}]
        self.permissions = [{'id': 'per_fixture', 'sessionID': 'ses_fixture', 'action': 'Read approved schedule', 'resources': ['calendar.sqlite']}]

    def control(self, action, **input):
        self.calls.append((action, input))
        if action == 'session.create':
            return {'sessionId': 'ses_fixture'}
        if action == 'session.send':
            self.sent.set()
            self.dismissed = False  # A new run.
            return {'promptDispatched': True}
        if action == 'session.status':
            return {'sessionStatus': {'type': 'busy' if self.busy else 'idle'}}
        raise AssertionError(action)

    def idle(self):
        """The session finished: no pending inputs and no busy engine."""
        self.forms, self.permissions, self.busy = [], [], False
        return self

    def pending(self, session):
        assert session == 'ses_fixture'
        return self.forms, self.permissions

    def request(self, path, body=None, method=None):
        self.calls.append((path, body))
        if path == '/api/session/ses_fixture':
            return {'data': {'location': {'directory': self.directory}}}
        # As OpenCode does: a closed question ends the run once nothing else in its step waits for the user.
        if method == 'DELETE' and '/form/' in path:
            self.forms, self.dismissed = [], True
        if '/permission/' in path:
            self.permissions = []
        if self.dismissed and not self.forms and not self.permissions:
            self.busy = False
        return {}


class MockChamber(Chamber):
    def __init__(self, runtime):
        self.runtime = runtime
        self.directory = str(runtime)
        self.sessions = {}
        self.calls = []
        self.replies = []
        self.fail = False

    def control(self, action, **body):
        self.calls.append((action, body))
        if action == 'session.create':
            session = 'ses_chat_' + str(len(self.sessions))
            self.sessions[session] = {'messages': [], 'forms': [], 'permissions': [], 'title': body.get('title', ''),
                                      'directory': self.directory}
            return {'sessionId': session}
        session = self.sessions[body['sessionId']]
        if action == 'session.send':
            if self.fail:
                raise OSError('Synthetic dispatch interruption')
            self.add(session, 'user', body['prompt'])
            if re.search('User has answered your questions: "(City|城市)"=', body['prompt']):
                session['permissions'] = [{'id': 'permission_setup', 'action': 'Save confirmed synthetic profile', 'resources': ['Synthetic profile only']}]
            elif body['prompt'].startswith('/initialize') or body['prompt'].endswith('Ask my city'):
                self.add(session, 'assistant', 'Confirm your location; replies follow the website language.')
                session['forms'] = [{'id': 'form_city', 'title': 'Confirm your location', 'metadata': {'tool': {'id': 'prt_city'}}, 'fields': [
                    {'key': 'city', 'title': 'City', 'type': 'string', 'required': True,
                     'options': [{'value': 'London', 'label': 'London'}], 'custom': True}]}]
            else:
                self.add(session, 'assistant', 'Synthetic reply. Your text stays text: <img src=x onerror=alert(1)>')
            return {'promptDispatched': True}
        if action in ('session.messages', 'session.status'):
            return super().control(action, **body)
        raise ValueError('Unexpected control action')

    def add(self, session, role, text):
        session['messages'].append({'id': 'message_' + str(len(session['messages'])), 'role': role, 'text': text})

    def pending(self, session):
        entry = self.sessions[session]
        return entry['forms'], entry['permissions']

    def request(self, path, body=None, method=None):
        if method == 'DELETE':
            # The engine fails the question tool and ends its run, as when a question is dismissed.
            session = self.sessions[path.split('/')[3]]
            form = next(form for form in session['forms'] if form['id'] == path.split('/')[5])
            session['forms'] = [entry for entry in session['forms'] if entry is not form]
            tool = form.get('metadata', {}).get('tool', {}).get('id', 'prt_' + form['id'])
            session['messages'].append({'id': 'message_' + str(len(session['messages'])), 'role': 'assistant', 'text': '',
                'native': {'error': {'type': 'aborted'}, 'content': [{'type': 'tool', 'id': tool, 'name': 'question'}]}})
            return {}
        if path == '/api/session/active':
            return {'data': {key: {'type': 'running'} for key, value in self.sessions.items()
                             if value.get('forms') or value.get('permissions')}}
        if path.endswith('/move'):
            self.replies.append((path, body))
            self.sessions[path.split('/')[3]]['directory'] = body['directory']
            return {}
        if body is None and path.startswith('/api/session/') and len(path.split('/')) == 4:
            session = self.sessions[path.split('/')[3]]
            return {'data': {'location': {'directory': session['directory']}}}
        if path.endswith('/prompt'):
            if self.fail:
                raise OSError('Synthetic dispatch interruption')
            self.replies.append((path, body))
            session = self.sessions[path.split('/')[3]]
            self.add(session, 'user', body['text'])
            self.add(session, 'assistant', 'Synthetic attachment reply')
            return {'data': {'id': 'inbox_synthetic'}}
        if path.endswith('/model'):
            session = self.sessions[path.split('/')[3]]
            session['model'] = body['model']
            return {}
        if path.endswith('/agent'):
            session = self.sessions[path.split('/')[3]]
            session['agent'] = body['agent']
            return {}
        if body is None:
            parsed = urlsplit(path);query = parse_qs(parsed.query)
            limit = int(query['limit'][0])
            if limit > 200:raise ValueError('Expected a value less than or equal to 200')
            if parsed.path == '/api/session':
                offset = int(query.get('cursor', ['0'])[0])
                sessions = list(reversed(list(self.sessions.items())))
                return {'data': [{'id': session, 'title': value.get('title', '')}
                                 for session, value in sessions[offset:offset+limit]],
                        'cursor': {'next': str(offset+limit) if len(sessions)>offset+limit else None}}
            session = self.sessions[parsed.path.split('/')[3]]
            offset = int(query.get('cursor', ['0'])[0])
            rows = list(reversed(session['messages']))
            if query.get('type'):
                rows = [row for row in rows if row['role'] == query['type'][0]]
            rows = rows[offset:offset+limit]
            return {'data': [{'id': row['id'], 'type': row['role'], **({'text': row['text']} if row['role']=='user'
                    else {'content':[{'type':'text','text':row['text']}]}), **row.get('native', {})} for row in rows],
                    'cursor': {'next': str(offset+limit) if len(session['messages'])>offset+limit else None}}
        self.replies.append((path, body))
        session_id = path.split('/')[3]
        session = self.sessions[session_id]
        session['permissions'] = []
        if body['decision'] == 'once':
            (self.runtime / 'profile.md').write_text('city: London\ntimezone: Europe/London\nnews_country: GB\n')
            self.add(session, 'assistant', 'Synthetic setup saved. Provider verification was not performed.')
        else:
            self.add(session, 'assistant', 'Nothing saved.')
        return {}


class ImmediateThread:
    def __init__(self, target, args, **_):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args): return None


class GatewayFixture(unittest.TestCase):
    """Two synthetic accounts behind a real gateway; subclasses add the tests."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=TEMP_ROOT);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=Accounts(self.root,testing=True,n=1024)
        self.id=self.store.create('alice','temporary-alice-secret1')
        self.other=self.store.create('bob','temporary-bob-secret1')
        self.received=[]
        received=self.received
        class Backend(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append((self.path,dict(self.headers)))
                if self.path.startswith('/api/edition/'):
                    self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                    self.wfile.write(b'{"job":null}')
                    return
                self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers()
                self.wfile.write(('<head></head><body><div data-config="{&quot;csrf&quot;: &quot;'+('a'*43)+'&quot;}"></div>Alice private record</body>').encode())
            def do_POST(self):
                received.append((self.path,dict(self.headers)))
                self.send_response(202);self.end_headers();self.wfile.write(b'{"accepted":true}')
            def log_message(self,*_): pass
        self.backend=QuickServer(('127.0.0.1',0),Backend)
        self.serve(self.backend)
        self.key=secrets.token_urlsafe(32)
        (self.root/'backends.json').write_text(json.dumps({self.id:{'port':self.backend.server_port,'key':self.key}}))
        self.gateway=Gateway(self.store,{'gm.example.test':'gm','gn.example.test':'gn'},testing=True)
        self.server=QuickServer(('127.0.0.1',0),handler_for(self.gateway))
        self.serve(self.server)
        self.opener=build_opener(NoRedirect())
        self.cookie=None
        self.csrf=None

    def serve(self,server):
        serve(server)
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)

    def request(self,path='/',body=None,*,headers=None,method=None):
        values={'Host':'gm.example.test','X-Forwarded-Proto':'https','X-Real-IP':'192.0.2.1'}
        if self.cookie: values['Cookie']=self.cookie
        if body is not None:
            values.update({'Origin':'https://gm.example.test','Content-Type':'application/json','X-Briefing-CSRF':self.csrf or ''})
        values.update(headers or {})
        raw=json.dumps(body).encode() if body is not None else None
        try:
            response=self.opener.open(Request(f'http://127.0.0.1:{self.server.server_port}'+path,data=raw,headers=values,method=method),timeout=3)
        except HTTPError as error: response=error
        with response:
            content=response.read()
            return response.status,dict(response.headers),content

    def login(self,remember=False):
        status,headers,content=self.request('/login')
        self.assertEqual(status,200)
        self.cookie=headers['Set-Cookie'].split(';')[0]
        self.csrf=re.search(b'data-csrf="([a-f0-9]+)"',content)[1].decode()
        status,headers,_=self.request('/api/auth/login',{'username':'alice','password':'temporary-alice-secret1','remember':remember})
        self.assertEqual(status,200)
        self.assertIn('Max-Age='+str(REMEMBER_SECONDS if remember else SESSION_SECONDS),headers['Set-Cookie'])
        self.cookie=headers['Set-Cookie'].split(';')[0]
        return self.store.session(self.cookie.split('=',1)[1],'gm.example.test')

    def permanent(self):
        self.login()
        _,_,content=self.request('/password')
        self.csrf=re.search(b'data-csrf="([a-f0-9]+)"',content)[1].decode()
        status,headers,_=self.request('/api/auth/password',{'current':'temporary-alice-secret1','replacement':'permanent-alice-secret1'})
        self.assertEqual(status,200)
        self.cookie=headers['Set-Cookie'].split(';')[0]
        self.csrf=self.store.session(self.cookie.split('=',1)[1],'gm.example.test')['csrf']


class HTTPFixture(unittest.TestCase):
    """A live viewer subprocess with a FakeChamber; subclasses add the tests."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=TEMP_ROOT);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'profile.md').write_text('secretary_language: English\ntimezone: Europe/London\ncity: London, GB\nnews_country: GB\n')
        (self.root/'daily').mkdir()
        self.process=subprocess.Popen([sys.executable,str(TESTS/'test_briefing_server.py'),'--serve-fixture',str(self.root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.address=self.process.stdout.readline().strip().removeprefix('Private live viewer: ')
        self.addCleanup(self.stop)
        with urlopen(self.address+'/gm') as response:
            page=response.read().decode()
        config=json.loads(html.unescape(re.search(r'data-config="([^"]+)"',page)[1]))
        self.csrf=config['csrf'];self.date=config['date']

    def stop(self):
        self.process.terminate();self.process.communicate(timeout=5)

    def request(self,path,body=None,headers=None):
        defaults={'Content-Type':'application/json','Origin':self.address,'X-Briefing-CSRF':self.csrf}
        defaults.update(headers or {})
        with urlopen(Request(self.address+path,data=json.dumps(body).encode() if body is not None else None,headers=defaults)) as response:
            return json.load(response)


def offline_provider_reads(test):
    """Receipts run their section's reads; keep weather and news off the network."""
    from goodmorning.briefings import briefing_job
    real = briefing_job.run_reads
    def reads(commands):
        local = [command for command in commands if command.split()[2] not in ('weather', 'news')]
        done = dict(zip(local, real(local)))
        return [done.get(command) or {'command': command, 'exit': 1, 'output': {'error': 'provider_unavailable'}}
                for command in commands]
    patcher = patch.object(briefing_job, 'run_reads', reads)
    patcher.start()
    test.addCleanup(patcher.stop)


def complete_profile(root):
    """A synthetic profile with every field briefing setup requires."""
    (Path(root)/'profile.md').write_text('secretary_language: English\ntimezone: Europe/London\ncity: London, GB\nnews_country: GB\n')


HOSTS = ('gm.example.test', 'gn.example.test', 'sec.example.test')


def selected(variable, value):
    """Set a website context variable (language, model, palette) for one block."""
    from contextlib import contextmanager
    @contextmanager
    def scope():
        token = variable.set(value)
        try: yield
        finally: variable.reset(token)
    return scope()


def gateway(test):
    """A GatewayFixture serving every edition host, cleaned up with the test."""
    fixture = GatewayFixture(); fixture.setUp(); test.addCleanup(fixture.doCleanups)
    fixture.gateway.hosts['sec.example.test'] = 'sec'
    return fixture


def session_cookie(fixture, user, host='gm.example.test'):
    """A fresh signed-in cookie for one synthetic account on one host."""
    with fixture.store.db() as db:
        row = db.execute('SELECT * FROM users WHERE id=?', (user,)).fetchone()
        token, _ = fixture.store.issue(db, host, row)
    return '__Host-GoodMorning=' + token


def form_post(fixture, path, fields):
    """A no-JavaScript form submission with the fixture's session; returns (status, headers)."""
    from urllib.parse import urlencode
    headers = {'Host': 'gm.example.test', 'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1', 'Cookie': fixture.cookie,
               'Origin': 'https://gm.example.test', 'Content-Type': 'application/x-www-form-urlencoded'}
    try: response = fixture.opener.open(Request(f'http://127.0.0.1:{fixture.server.server_port}' + path,
                                                data=urlencode(fields).encode(), headers=headers), timeout=3)
    except HTTPError as error: response = error
    with response: return response.status, dict(response.headers)


def frozen_datetime(instant):
    """A datetime class whose now() is the aware ``instant``; patch it over a module's datetime."""
    from datetime import datetime
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(instant.timestamp(), tz or instant.tzinfo)
    return Frozen
