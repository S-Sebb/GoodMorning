"""Opt-in real-model bridge for synthetic website trials, using the native V2 CLI.

This replaces only OpenChamber's control envelope, not website code or model tools.
It owns freshly created sessions only and never lists another session's history.
"""
import json
import subprocess
import threading
from pathlib import Path
from urllib.parse import quote


class NativeBridge:
    def __init__(self, directory, runtime, *, agent=None):
        self.directory, self.runtime = str(directory), str(runtime)
        self.agent = agent
        self.sessions = {}
        self.parent = None
        if Path(self.runtime).is_dir():
            (Path(self.runtime)/'tmp').mkdir(mode=0o700,exist_ok=True)

    def api(self, method, path, body=None):
        command = ['opencode', 'api', method, path]
        if body is not None:
            command += ['--data', json.dumps(body)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise RuntimeError('Native V2 API request failed: ' + method + ' ' + path)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def request(self, path, body=None):
        if path.startswith('/api/session?'):
            return {'data':[self.api('get', '/api/session/'+s)['data'] for s in self.sessions], 'cursor':{}}
        session = path.split('/')[3] if path.startswith('/api/session/') else None
        if session not in self.sessions:
            raise ValueError('Trial bridge accepts only its own synthetic sessions')
        result = self.api('post' if body is not None else 'get', path, body)
        if body is not None and path.endswith('/reply'):
            self.wait(session)
        return result

    def wait(self, session):
        self.sessions[session]['idle'] = False
        generation = self.sessions[session].get('generation', 0) + 1
        self.sessions[session]['generation'] = generation
        def finish():
            try:
                result = subprocess.run(['opencode','api','post',f'/api/experimental/session/{session}/wait'],
                                        capture_output=True, timeout=900)
                if self.sessions[session]['generation'] == generation:
                    self.sessions[session]['idle'] = result.returncode == 0
            except subprocess.TimeoutExpired:
                if self.sessions[session]['generation'] == generation:
                    self.sessions[session]['idle'] = False  # Preserve uncertainty, never invent completion.
        threading.Thread(target=finish, daemon=True).start()

    def pending(self, session):
        return (self.request(f'/api/session/{session}/form')['data'],
                self.request(f'/api/session/{session}/permission')['data'])

    def control(self, action, **parameters):
        if action == 'session.create':
            agent = self.agent or parameters.get('agent')
            location = {'directory':self.directory}
            # Trials share the user's OpenCode service. OpenChamber skips "ready"
            # notifications for subtasks and hides archived sessions, so each
            # trial runs archived under an archived parent that never runs.
            if not self.parent:
                self.parent = self.api('post', '/api/session', {'location':location,
                    'title':'GoodMorning trial run'})['data']['id']
                self.api('patch', f'/api/session/{self.parent}', {'archived':True})
            result = self.api('post', '/api/session', {'location':location, 'parentID':self.parent,
                **({'agent':agent} if agent else {}),
                **({'title':parameters['title']} if parameters.get('title') else {})})
            session = result['data']['id']
            self.sessions[session] = {'idle':True}
            if agent and result['data'].get('agent')!=agent:
                raise ValueError('Requested agent was not confirmed before model work')
            self.api('patch', f'/api/session/{session}', {'archived':True})
            self.api('put', f'/api/session/{session}/environment', {'variables':{
                'SECRETARY_DIR':self.runtime, 'OPENCODE_SESSION_ID':session,
                'GM_CACHE_DIR':str(Path(self.runtime)/'cache'),'TMPDIR':str(Path(self.runtime)/'tmp'),
                'CALENDAR_DB_PATH':str(Path(self.runtime)/'calendar.sqlite')}})
            return {'sessionId':session}
        session = parameters['sessionId']
        if session not in self.sessions:
            raise ValueError('Not a synthetic trial session')
        if action == 'session.send':
            result = self.request(f'/api/session/{session}/prompt', {'text':parameters['prompt']})
            self.wait(session)
            return {'promptDispatched':bool(result.get('data',{}).get('id'))}
        status = {'sessionStatus':{'type':'idle' if self.sessions[session]['idle'] else 'busy'}}
        if action == 'session.status':
            return status
        if action == 'session.messages':
            messages = []
            cursor, size = None, 10
            # CLI responses have an output ceiling. Small read-only pages avoid
            # truncating tool-heavy transcripts; never retry mutations here.
            for _ in range(100):
                query=f'limit={size}&'+('cursor='+quote(cursor,safe='') if cursor else 'order=desc')
                try:
                    page=self.request(f'/api/session/{session}/message?'+query)
                except json.JSONDecodeError:
                    if size==1:
                        raise ValueError('A single native message exceeds the trial CLI output limit')
                    size=max(1,size//2)
                    continue
                for entry in page['data']:
                    role = entry.get('type')
                    text = entry.get('text','') if role == 'user' else ''.join(
                        part['text'] for part in entry.get('content',[]) if part.get('type')=='text')
                    if role in ('user','assistant') and text.strip():
                        messages.append({'id':entry['id'], 'role':role, 'text':text.strip()})
                if len(messages)>=parameters.get('limit',100):
                    break
                cursor=page.get('cursor',{}).get('next')
                if not cursor:
                    break
            return {**status, 'messages':list(reversed(messages[:parameters.get('limit',100)]))}
        raise ValueError('Unsupported synthetic bridge action: '+action)
