"""Guarded GoodMorning release helper, run as root on the server.

stage ARCHIVE NAME  Unpack, verify and test a release while the website stays live.
switch NAME         With the website paused, wait for idle, then make a staged
                    release live. Keeps previous releases, credentials and private files.

Exit status 3 means switch changed nothing because the website never became idle.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = Path('/srv/goodmorning/live')
ACCOUNTS = BASE/'accounts'
CURRENT = Path('/opt/goodmorning/current')
RELEASES = Path('/opt/goodmorning/releases')
PYTHON = '/opt/goodmorning/python/bin/python'
NODE = '/opt/goodmorning/engine/bin/node'
HOST = 'gm.love765.me'
ALLOWED = frozenset({'.gitignore', 'LICENSE', 'README.md', 'AGENTS.md', 'AGENT-PROMPT-GUIDE.md',
                     'SERVER-USER-GUIDE.md', 'SERVER-DATA-GUIDE.md', 'config.example.md', 'skill-source',
                     'scripts', 'src', 'assets', 'integrations', 'vendor', 'requirements', 'docs',
                     'templates', 'deploy', 'tests'})
UNITS = ('goodmorning-account@.service', 'goodmorning-viewer@.service',
         'goodmorning-gateway.service', 'goodmorning-vault@.service')
NGINX = Path('/etc/nginx/conf.d/goodmorning.conf')
HOOK = Path('/etc/letsencrypt/renewal-hooks/deploy/goodmorning-reload-nginx')
SCHEMA = {'users': {'id', 'name', 'salt', 'digest', 'revision', 'temporary', 'enabled'},
          'sessions': {'hash', 'user_id', 'revision', 'csrf', 'host', 'created', 'touched', 'expires', 'remembered'},
          'attempts': {'key', 'started', 'count'}, 'metadata': {'key', 'value'}}
IDLE_TIMEOUT = 600
NOT_IDLE = 3


class Busy(Exception):
    """Work is still running; nothing has changed yet."""


def command(args, timeout=90, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout, **kwargs)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def release_path(name):
    if not re.fullmatch(r'\d{8}-[a-z0-9]+(?:-[a-z0-9]+)*', name):
        raise ValueError('Release names look like YYYYMMDD-ship-<short hash>')
    return RELEASES/name


def marker_path(name):
    return ACCOUNTS/(name+'-staged.json')


def check_members(members):
    """Only regular public files; the archive filter must already have run."""
    names = [item.name for item in members]
    assert len(set(names)) == len(names), 'Duplicate archive members'
    for item in members:
        path = Path(item.name)
        assert item.isfile() and not path.is_absolute() and '..' not in path.parts, 'Unsafe archive member'
        assert path.parts[0] in ALLOWED and '__pycache__' not in path.parts, 'Non-public archive member'
        assert not path.name.startswith('.env'), 'Environment file in archive'


def read_db():
    return sqlite3.connect('file:'+str(ACCOUNTS/'accounts.sqlite')+'?mode=ro', uri=True)


def metadata(db, key):
    row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else None


def require_schema(db):
    assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    for table, columns in SCHEMA.items():
        assert {row[1] for row in db.execute('PRAGMA table_info('+table+')')} == columns, 'Live schema needs explicit review'


def require_paused(db):
    assert (metadata(db, 'maintenance') or {}).get('enabled') is True, 'Deployment requires an enabled website pause'


def require_no_work(db):
    if metadata(db, 'generation'):
        raise Busy('A reservation is held')
    if metadata(db, 'generation_queue') not in (None, []):
        raise Busy('Queued requests are waiting')
    if metadata(db, 'generation_waiting') not in (None, []):
        raise Busy('Suspended input is waiting for its owner')


def stage(archive, name):
    """Safe while live: writes only the new release directory and a private marker."""
    release = release_path(name)
    archive_hash = digest(archive)
    marker = marker_path(name)
    if release.exists():
        staged = json.loads(marker.read_text()) if marker.is_file() else {}
        assert staged.get('archive') == archive_hash, 'Never overwrite a release'
        print(json.dumps({'release': str(release), 'alreadyStaged': True}))
        return
    with tarfile.open(archive) as source:
        members = source.getmembers()
        check_members(members)
        release.mkdir(mode=0o755)
        source.extractall(release, filter='data')
        files = {item.name: hashlib.sha256(source.extractfile(item).read()).hexdigest() for item in members}
    for name_, value in files.items():
        assert digest(release/name_) == value, 'Extracted file differs from the archive'
        (release/name_).chmod(0o644)
    assert {p.name for p in (release/'scripts').iterdir()} == {'goodmorning.py', 'projects.mjs'}
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    python = subprocess.run([PYTHON, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-q'],
                            cwd=release, env=env, capture_output=True, text=True, timeout=900)
    if python.returncode:
        raise RuntimeError('Release tests failed: '+python.stderr[-5000:])
    node = command([NODE, '--test', '--test-reporter=tap', str(release/'tests/test_projects.mjs')], cwd=release)
    with read_db() as db:
        require_schema(db)
    result = {'archive': archive_hash, 'files': files,
              'pythonTests': int(re.search(r'Ran (\d+) tests', python.stderr)[1]),
              'nodeTests': int(re.search(r'# tests (\d+)', node.stdout)[1])}
    marker.write_text(json.dumps(result))
    marker.chmod(0o600)
    print(json.dumps({'release': str(release), 'publicFiles': len(files),
                      'pythonTests': result['pythonTests'], 'nodeTests': result['nodeTests']}))


def install(source, target, backup):
    """Copy only when different; return whether a rollback copy was taken."""
    if target.is_file() and target.read_bytes() == source.read_bytes():
        return False
    shutil.copy2(target, backup/target.name)
    shutil.copy2(source, target)
    return True


def write_nginx(data):
    """Atomic replacement keeping the live file's owner and mode."""
    state = NGINX.stat()
    temporary = NGINX.with_name('.goodmorning-native-switch.tmp')
    with temporary.open('xb') as target:
        target.write(data)
    temporary.chmod(state.st_mode & 0o777)
    os.chown(temporary, state.st_uid, state.st_gid)
    temporary.replace(NGINX)


def staged_record(name):
    """The stage marker, or for a release that was live before, its deployment report."""
    if marker_path(name).is_file():
        return json.loads(marker_path(name).read_text())
    deployed = json.loads((ACCOUNTS/(name+'-deployment.json')).read_text())
    report = deployed['report']
    return {'files': deployed['files'],
            'pythonTests': report.get('stagedPythonTests', report.get('candidatePythonTests')),
            'nodeTests': report.get('stagedNodeTests', report.get('candidateNodeTests'))}


def switch(name):
    release = release_path(name)
    staged = staged_record(name)
    assert release.is_dir() and CURRENT.resolve() != release, 'Stage a new release first'
    for path, value in staged['files'].items():
        assert digest(release/path) == value, 'Staged release changed after staging'
    old = CURRENT.resolve()

    with read_db() as db:
        require_schema(db)
        require_paused(db)
        enabled = [row[0] for row in db.execute('SELECT id FROM users WHERE enabled=1 ORDER BY id')]

    # An enabled login can exist before its private backend is provisioned.
    # Leave wholly unprovisioned accounts untouched; reject partial provisioning.
    registry_path = ACCOUNTS/'backends.json'
    registry = json.loads(registry_path.read_text())
    registry_hash = digest(registry_path)
    identifiers = [identifier for identifier in enabled if identifier in registry]
    unprovisioned = [identifier for identifier in enabled if identifier not in registry]
    for identifier in identifiers + unprovisioned:
        assert re.fullmatch('[a-f0-9]{32}', identifier)
    for identifier in unprovisioned:
        assert not (BASE/identifier).exists(), 'Review a partially provisioned private runtime'
        for kind in ('vault', 'account', 'viewer'):
            state = subprocess.run(['systemctl', 'is-active', f'goodmorning-{kind}@{identifier}.service'],
                                   capture_output=True, text=True, timeout=10).stdout.strip()
            assert state == 'inactive', 'Review an unregistered account service'

    # The incumbent release's clients only inspect sessions; they never dispatch.
    sys.path.insert(0, str(old/'src'))
    from goodmorning.security.briefing_accounts import Accounts
    from goodmorning.security.briefing_gateway import Gateway
    from goodmorning.security.briefing_runtime import LocalBridge
    store = Accounts(ACCOUNTS)
    gateway = Gateway(store, {HOST: 'gm'})
    configs = {identifier: json.loads((BASE/identifier/'engine.json').read_text()) for identifier in identifiers}
    bridges = {identifier: LocalBridge('http://127.0.0.1:'+str(config['chamberPort']), str(old), config['uiPassword'])
               for identifier, config in configs.items()}

    def idle():
        with store.db() as db:
            require_paused(db)
            require_no_work(db)
        for identifier, bridge in bridges.items():
            active = bridge.request('/api/session/active')
            if active.get('data', active):
                raise Busy('An account has an active session')
            sessions = set()
            for registry_file in ('browser-jobs/jobs.json', 'browser-chats/chats.json'):
                path = BASE/identifier/'secretary'/registry_file
                if path.is_file():
                    sessions.update(item['session'] for item in json.loads(path.read_text()).values() if item.get('session'))
            for session in sessions:
                if bridge.control('session.status', sessionId=session)['sessionStatus']['type'] != 'idle':
                    raise Busy('A session is busy')
                if bridge.pending(session) != ([], []):
                    raise Busy('Pending owner input prevents deployment')

    deadline = time.monotonic()+IDLE_TIMEOUT
    while True:
        try:
            idle()
            break
        except Busy as error:
            if time.monotonic() >= deadline:
                print(json.dumps({'notIdle': str(error), 'changed': False}))
                sys.exit(NOT_IDLE)
            time.sleep(5)

    probe = '''import json, sys
from pathlib import Path
from goodmorning.runtime_files import profile_fields
from goodmorning.setup_check import profile_status
from goodmorning.briefings.briefing_document import parse
root=Path(sys.argv[1])
status=profile_status(root,profile_fields(root),website_language='en')
count=0
for pattern in ('*.gm.json','*.gn.json'):
 for path in (root/'daily').glob(pattern):
  assert not path.is_symlink()
  parse(path.read_text());count+=1
print(json.dumps({'profileReady':status['profile_ready'],'nativeEditions':count}))
'''
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(release/'src'))
    profiles = [json.loads(command([PYTHON, '-B', '-c', probe, str(BASE/identifier/'secretary')],
                                   cwd=release, env=env).stdout) for identifier in identifiers]

    def passwords():
        with store.db() as db:
            return [tuple(row) for row in db.execute('SELECT id,salt,digest,revision,temporary,enabled FROM users ORDER BY id')]

    def languages():
        with store.db() as db:
            return [tuple(row) for row in db.execute("SELECT key,value FROM metadata WHERE key LIKE 'website-%' ORDER BY key")]

    before, before_languages = passwords(), languages()
    protected_paths = [registry_path]
    for identifier in identifiers:
        volume = BASE/identifier
        protected_paths.extend(p for p in (volume/'secretary').rglob('*') if p.is_file() and not p.is_symlink())
        protected_paths.append(volume/'engine.json')
        protected_paths.extend((volume/'home/.config/openchamber').glob('*settings*.json'))
        protected_paths.append(volume/'home/.config/openchamber/preferences.json')
    protected_paths += [Path('/home/ubuntu/.config/openchamber/settings.json'),
                        Path('/home/ubuntu/.config/openchamber/preferences.json')]
    protected = {str(p): digest(p) for p in protected_paths if p.is_file()}

    def unchanged():
        return (passwords() == before and languages() == before_languages
                and all(digest(path) == value for path, value in protected.items())
                and digest(registry_path) == registry_hash
                and all(not (BASE/identifier).exists() for identifier in unprovisioned))

    def wait_ready():
        deadline = time.monotonic()+75
        while True:
            try:
                for identifier, bridge in bridges.items():
                    bridge.token, bridge.directory = None, str(release)
                    bridge.request('/api/session/active')
                    config = configs[identifier]
                    request = Request('http://127.0.0.1:'+str(config['viewerPort'])+'/chat', headers={
                        'Authorization': 'Bearer '+config['gatewayKey'], 'X-GoodMorning-Origin': 'https://'+HOST})
                    with urlopen(request, timeout=5) as response:
                        assert response.status == 200 and b'/icons/secretary.svg' in response.read()
                try:
                    response = urlopen('https://'+HOST+'/login', timeout=8)
                except HTTPError as error:
                    response = error
                with response:
                    assert response.status == 503 and b'maintenance-status' in response.read()
                    assert response.headers.get('Retry-After') == '60'
                return
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)

    backup = ACCOUNTS/f'{name}-unit-backup-{int(time.time())}'
    backup.mkdir(mode=0o700)
    candidate_nginx = (release/'deploy/nginx-goodmorning.conf').read_bytes()
    assert NGINX.is_file() and not NGINX.is_symlink() and HOOK.is_file() and not HOOK.is_symlink()
    accounts = [f'goodmorning-account@{identifier}.service' for identifier in identifiers]
    viewers = [f'goodmorning-viewer@{identifier}.service' for identifier in identifiers]
    services = accounts+viewers+['goodmorning-gateway.service']
    ticket = {'deployment': name}
    try:
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            require_paused(db)
            require_no_work(db)
            db.execute('INSERT INTO metadata VALUES (?,?)', ('generation', json.dumps(ticket, separators=(',', ':'))))
    except Busy as error:
        print(json.dumps({'notIdle': str(error), 'changed': False}))
        sys.exit(NOT_IDLE)
    installed, switched, nginx_changed = [], False, False
    started = time.monotonic()
    try:
        command(['systemctl', 'stop', 'goodmorning-gateway.service', *viewers])
        idle()
        assert unchanged()
        command(['systemctl', 'stop', *accounts])
        for unit in UNITS:
            if install(release/'deploy'/unit, Path('/etc/systemd/system')/unit, backup):
                installed.append(Path('/etc/systemd/system')/unit)
        if install(release/'deploy/goodmorning-certbot-hook.py', HOOK, backup):
            installed.append(HOOK)
            HOOK.chmod(0o755)
        pointer = CURRENT.with_name('current-native-switch')
        assert not pointer.exists() and not pointer.is_symlink()
        pointer.symlink_to(release)
        pointer.replace(CURRENT)
        switched = True
        command(['systemctl', 'daemon-reload'])
        if NGINX.read_bytes() != candidate_nginx:
            shutil.copy2(NGINX, backup/'nginx-goodmorning.conf')
            write_nginx(candidate_nginx)
            nginx_changed = True
            command(['nginx', '-t'])
            command(['systemctl', 'reload', 'nginx'])
        command(['systemctl', 'start', *services])
        wait_ready()
        idle()
        assert unchanged(), 'Protected records, passwords or preferences changed'
        for unit in services:
            command(['systemctl', 'is-active', '--quiet', unit])
        for identifier in identifiers:
            pid = command(['systemctl', 'show', '--property=MainPID', '--value',
                           f'goodmorning-account@{identifier}.service']).stdout.strip()
            assert (Path('/proc')/pid/'cwd').resolve() == release, 'Agent must use the new release directory'
        gateway.clear_ticket(ticket)
        assert not gateway.ticket()
        with store.db() as db:
            require_paused(db)
    except Exception:
        command(['systemctl', 'stop', 'goodmorning-gateway.service', *viewers, *accounts])
        if switched:
            pointer = CURRENT.with_name('current-native-rollback')
            pointer.symlink_to(old)
            pointer.replace(CURRENT)
        for target in installed:
            shutil.copy2(backup/target.name, target)
        if nginx_changed:
            write_nginx((backup/'nginx-goodmorning.conf').read_bytes())
            command(['nginx', '-t'])
            command(['systemctl', 'reload', 'nginx'])
        command(['systemctl', 'daemon-reload'])
        command(['systemctl', 'start', *services])
        gateway.clear_ticket(ticket)
        raise
    report = {'release': str(release), 'previousReleasePreserved': str(old), 'verifiedPublicFiles': len(staged['files']),
              'stagedPythonTests': staged['pythonTests'], 'stagedNodeTests': staged['nodeTests'],
              'protectedPrivateFiles': len(protected), 'recordsPasswordsAndPreferencesUnchanged': True,
              'idleAccountsRestarted': len(accounts), 'unprovisionedAccountsUntouched': len(unprovisioned),
              'vaultsNotRestarted': True, 'modelCalls': 0, 'profiles': profiles,
              'updatedFiles': [str(path) for path in installed]+([str(NGINX)] if nginx_changed else []),
              'switchSeconds': round(time.monotonic()-started)}
    path = ACCOUNTS/(name+'-deployment.json')
    path.write_text(json.dumps({'report': report, 'files': staged['files'], 'protectedHashes': protected}, indent=2))
    path.chmod(0o600)
    print(json.dumps(report))


def main(argv):
    assert os.geteuid() == 0, 'Run as root'
    sys.dont_write_bytecode = True
    if argv[:1] == ['stage'] and len(argv) == 3:
        stage(Path(argv[1]), argv[2])
    elif argv[:1] == ['switch'] and len(argv) == 2:
        switch(argv[1])
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
