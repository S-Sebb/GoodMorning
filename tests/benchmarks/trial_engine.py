"""Private, production-like engines for paid website-model trials.

Each synthetic account gets its own OpenChamber and OpenCode, started the way a hosted
account's engine is (`goodmorning.security.briefing_runtime`): a fresh HOME and database, the
copied release as working directory, and the production `LocalBridge` client. Trial sessions
never reach the developer's OpenCode service, sidebar or notifications, and agents load only
the copied release's instructions and skills: no git checkout, home directory or developer
configuration sits above it.
"""
import atexit
from contextlib import closing
import ctypes
import fcntl
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from goodmorning.security.briefing_runtime import LocalBridge
from goodmorning.web import models

# On disk, unlike tmpfs /tmp, and outside any home directory or git checkout.
TRIALS = Path('/var/tmp/goodmorning-trials')
ENGINES = Path.home()/'.cache/goodmorning/trial-engines'
REGISTRY = 'https://registry.npmjs.org'
PROVIDER = 'opencode-go'
RELEASE_DIRECTORIES = ('src', 'scripts', 'docs', 'templates', 'assets', 'skill-source', '.opencode')
RELEASE_FILES = ('AGENTS.md', 'AGENT-PROMPT-GUIDE.md', 'SERVER-USER-GUIDE.md', 'SERVER-DATA-GUIDE.md')
LIVE = set()


def task_root():
    """Every run of this checkout's task lives here; `trial.py clean` removes it as a whole."""
    return TRIALS/ROOT.name


def add_arguments(parser):
    handle_signals()
    parser.add_argument('--output', type=Path, required=True, help=f'New run directory beneath {task_root()}')
    parser.add_argument('--source', type=Path, default=ROOT,
                        help='Checkout whose release the agent runs, e.g. a merge-base worktree for a baseline')


def private_output(parser, path):
    output = Path(path).resolve()
    if not output.is_relative_to(task_root()) or output == task_root():
        parser.error(f'Trial output must be a new directory beneath {task_root()}')
    return output


def copy_release(destination, source=ROOT):
    """The public files an account engine runs from, with the skill at the release root."""
    destination.mkdir(parents=True)
    for name in RELEASE_DIRECTORIES:
        shutil.copytree(source/name, destination/name, ignore=shutil.ignore_patterns('__pycache__'))
    for name in RELEASE_FILES:
        shutil.copyfile(source/name, destination/name)
    shutil.copyfile(source/'skill-source/goodmorning.md', destination/'goodmorning.md')
    (destination/'opencode.json').write_text(json.dumps({'skills':['.']}))


def engine_versions():
    """Latest OpenChamber and the OpenCode it pins, chosen once per task so every run compares alike."""
    pinned = task_root()/'engine.json'
    if not pinned.exists():
        with urlopen(REGISTRY+'/@openchamber%2fweb/latest', timeout=30) as response:
            manifest = json.load(response)
        pinned.parent.mkdir(parents=True, exist_ok=True)
        pinned.write_text(json.dumps({'openchamber':manifest['version'],
                                      'opencode':manifest['dependencies']['@opencode/client'],
                                      'node':manifest['engines']['node']}))
    return json.loads(pinned.read_text())


def engine_tree():
    versions = engine_versions()
    tree = ENGINES/(versions['openchamber']+'-'+versions['opencode'])
    ENGINES.mkdir(parents=True, exist_ok=True)
    with (ENGINES/'.install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (tree/'bin/node').exists():
            temporary = ENGINES/('.'+tree.name+'.partial')
            shutil.rmtree(temporary, ignore_errors=True)
            npm = ['npm', '--global', '--prefix', str(temporary), '--registry', REGISTRY, '--no-audit', '--no-fund']
            major = versions['node'].lstrip('>=^~').split('.')[0]
            # Only the OpenCode binary and Node runtime packages run install scripts.
            subprocess.run(npm+['install', '--ignore-scripts', '@openchamber/web@'+versions['openchamber'],
                                '@opencode/cli@'+versions['opencode'], 'node@'+major],
                           check=True, capture_output=True, timeout=900)
            subprocess.run(npm+['rebuild', '@opencode/cli', 'node'], check=True, capture_output=True, timeout=900)
            temporary.rename(tree)
    return tree


def developer_credential():
    """The developer's own OpenCode Go key, read in-process and handed only to private engines."""
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')
    with closing(sqlite3.connect(f'file:{data/"opencode/opencode.db"}?mode=ro', uri=True)) as db:
        row = db.execute('SELECT value FROM credential WHERE integration_id=? AND active=1', (PROVIDER,)).fetchone()
    if not row:
        raise RuntimeError('Connect OpenCode Go in your own OpenCode before running paid trials')
    return json.loads(row[0])


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def die_with_parent():
    # PR_SET_PDEATHSIG: an engine never outlives a killed runner.
    ctypes.CDLL(None).prctl(1, signal.SIGTERM)


def stop_all(*_):
    for engine in list(LIVE):
        engine.stop()


def terminate(number, _frame):
    stop_all()
    raise SystemExit(128+number)


def handle_signals():
    """`trial.py stop` sends SIGTERM: stop every engine, then exit through the harness's cleanup."""
    if threading.current_thread() is threading.main_thread():
        for number in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(number, terminate)


atexit.register(stop_all)


class Engine:
    """One synthetic account's OpenChamber and OpenCode on a fresh loopback port.

    Its HOME and database live in `engine/` beside the account's runtime folder."""
    def __init__(self, release, runtime):
        self.release, self.runtime = Path(release), Path(runtime)
        self.folder = self.runtime.parent/'engine'
        self.process = None

    def environment(self, tree):
        """The cleared environment a hosted account engine gets, with this account's paths."""
        home = self.folder/'home'
        return {'HOME':str(home), 'USER':os.environ['USER'], 'LOGNAME':os.environ['USER'],
                'PATH':str(tree/'bin')+':/usr/local/bin:/usr/bin:/bin',
                'XDG_CONFIG_HOME':str(home/'.config'), 'XDG_DATA_HOME':str(home/'.local/share'),
                'XDG_CACHE_HOME':str(home/'.cache'), 'XDG_STATE_HOME':str(home/'.local/state'),
                'XDG_RUNTIME_DIR':str(self.folder/'run'), 'TMPDIR':str(self.runtime/'tmp'),
                'SECRETARY_DIR':str(self.runtime), 'GM_CACHE_DIR':str(self.runtime/'cache'),
                'PYTHONDONTWRITEBYTECODE':'1', 'OPENCODE_BINARY':str(tree/'bin/opencode'),
                'OPENCHAMBER_UI_PASSWORD':self.password, 'OPENCHAMBER_DATA_DIR':str(home/'.config/openchamber')}

    def start(self):
        tree = engine_tree()
        home = self.folder/'home'
        for path in (home/'.config/opencode', home/'.local/share', home/'.cache', home/'.local/state',
                     self.folder/'run', self.runtime/'tmp', self.runtime/'cache'):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        # As provisioned for a hosted account; GoodMorning applies the variant per session.
        default = models.MODELS[models.DEFAULT]
        (home/'.config/opencode/opencode.json').write_text(json.dumps({'model':default['providerID']+'/'+default['id']}))
        self.password, self.url = secrets.token_urlsafe(48), 'http://127.0.0.1:'+str(free_port())
        env = self.environment(tree)
        handle_signals()
        with (self.folder/'engine.log').open('ab') as log:
            self.process = subprocess.Popen([str(tree/'bin/node'), str(tree/'lib/node_modules/@openchamber/web/bin/cli.js'),
                                             'serve', '--foreground', '--api-only', '--host', '127.0.0.1',
                                             '--port', self.url.rsplit(':', 1)[1]],
                                            cwd=self.release, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                            start_new_session=True, preexec_fn=die_with_parent)
        LIVE.add(self)
        (self.folder/'engine.json').write_text(json.dumps({'pid':self.process.pid, 'url':self.url}))
        bridge = LocalBridge(self.url, str(self.release), self.password)
        deadline = time.monotonic()+180
        while True:
            if self.process.poll() is not None:
                raise RuntimeError('Trial engine exited; see '+str(self.folder/'engine.log'))
            try:
                bridge.request('/api/provider')
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError('Trial engine did not become ready; see '+str(self.folder/'engine.log'))
                time.sleep(1)
        # The same registration a hosted account gets at provisioning; the key stays in this
        # engine's own database, which `trial.py clean` deletes with the run.
        bridge.request('/api/credential', {'integrationID':PROVIDER, 'value':developer_credential(), 'activate':True})
        offered = {(entry.get('providerID'), entry.get('id')) for entry in bridge.request('/api/model')['data']}
        missing = [entry['id'] for entry in models.MODELS.values() if (entry['providerID'], entry['id']) not in offered]
        if missing:
            raise RuntimeError('Trial engine does not offer '+', '.join(missing))
        return self

    def stop(self):
        """Interrupt any running work, then stop the engine and its OpenCode."""
        if not self.process or self.process.poll() is not None:
            LIVE.discard(self)
            return
        try:
            bridge = LocalBridge(self.url, str(self.release), self.password)
            for session in bridge.request('/api/session/active').get('data', {}):
                bridge.request(f'/api/session/{session}/interrupt', {})
        except Exception:
            pass  # Stopping the engine below ends its work regardless.
        for number, wait in ((signal.SIGTERM, 20), (signal.SIGKILL, 5)):
            try:
                os.killpg(self.process.pid, number)
                self.process.wait(wait)
                break
            except (ProcessLookupError, subprocess.TimeoutExpired):
                continue
        LIVE.discard(self)


class TrialBridge(LocalBridge):
    """The production account bridge to a started engine, recording the sessions it creates.

    `agent` pins an experimental agent and confirms it before any prompt is sent."""
    def __init__(self, engine, *, agent=None):
        super().__init__(engine.url, str(engine.release), engine.password)
        self.engine, self.agent, self.sessions = engine, agent, []

    def close(self):
        self.engine.stop()

    def control(self, action, **parameters):
        if action == 'session.create' and self.agent:
            parameters['agent'] = self.agent
        result = super().control(action, **parameters)
        if action == 'session.create':
            session = result['sessionId']
            self.sessions.append(session)
            # OpenChamber records a created session's agent only at its first prompt; set it now
            # so the pin is confirmed before any model work.
            if self.agent:
                self.request(f'/api/session/{session}/agent', {'agent':self.agent})
                if self.session(session).get('agent') != self.agent:
                    raise ValueError('Requested agent was not confirmed before model work')
        return result

    def session(self, session):
        return self.request(f'/api/session/{session}')['data']
