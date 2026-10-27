"""Root-only hosted account provisioning; every step resumes from what already exists.

Prints usernames, IDs, file names and ports, never passwords or keys."""
import json
import os
from pathlib import Path
import pwd
import secrets
import socket
import string
import subprocess
import time

from .briefing_accounts import username
from .briefing_admin import backend_status, server_defaults
from . import briefing_vault

SOURCE = '/opt/goodmorning/current'
UNITS = Path('/etc/systemd/system')
# Gateway.backend accepts only 43-character keys.
GATEWAY_KEY_BYTES = 32


def temporary_password():
    alphabet = string.ascii_letters + string.digits
    while True:
        value = ''.join(secrets.choice(alphabet) for _ in range(24))
        if any(c.isalpha() for c in value) and any(c.isdigit() for c in value):
            return value


def private_write(path, text, owner=None):
    """Atomically replace one private file; the temporary file never exists with wider permissions."""
    temporary = path.with_name('.'+path.name+'.tmp')
    with os.fdopen(os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'w') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    if owner:
        os.chown(temporary, *owner)
    os.replace(temporary, path)


def systemctl(*args):
    subprocess.run(['systemctl', *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)


def login(store, name, defaults):
    """Reuse an existing login by its immutable ID; a new one gets a random temporary password in a handover file."""
    with store.db() as db:
        row = db.execute('SELECT id FROM users WHERE name=?', (name,)).fetchone()
    if row:
        print(f'Login exists: {name} {row["id"]}; its password is unchanged')
        return row['id']
    secret = temporary_password()
    identifier = store.create(name, secret)
    store.website_model(identifier, defaults['model'])
    handover = store.directory/f'{name}-initial-password-{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}.txt'
    with os.fdopen(os.open(handover, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'w') as stream:
        stream.write(f'{name} {secret}\n')
    print(f'Login created: {name} {identifier}; temporary password in {handover}')
    return identifier


def used_ports(live, registry):
    ports = {entry['port'] for entry in registry.values()}
    for path in live.glob('*/engine.json'):
        config = json.loads(path.read_text())
        ports |= {config['chamberPort'], config['viewerPort']}
    return ports


def free_port(start, used):
    port = start
    while True:
        if port not in used:
            with socket.socket() as probe:
                try:
                    probe.bind(('127.0.0.1', port))
                except OSError:
                    pass
                else:
                    used.add(port)
                    return port
        port += 1


def runtime(volume, owner, defaults, used):
    """Write engine.json and the OpenCode model once; a rerun keeps the existing ports and keys."""
    from goodmorning.web.models import MODELS
    path = volume/'engine.json'
    if path.exists():
        config = json.loads(path.read_text())
    else:
        config = {'chamberPort': free_port(3011, used), 'viewerPort': free_port(18766, used),
                  'uiPassword': secrets.token_urlsafe(48), 'gatewayKey': secrets.token_urlsafe(GATEWAY_KEY_BYTES)}
        private_write(path, json.dumps(config), owner)
    folder = volume/'home'
    for part in ('.config', 'opencode'):
        folder = folder/part
        folder.mkdir(mode=0o700, exist_ok=True)
        os.chown(folder, *owner)
    if not (folder/'opencode.json').exists():
        selected = MODELS[defaults['model']]
        private_write(folder/'opencode.json', json.dumps({'model': selected['providerID']+'/'+selected['id']}), owner)
    return config


def services(identifier, user):
    for unit, extra in (('account', 'SupplementaryGroups=goodmorning-engine\n'), ('viewer', '')):
        folder = UNITS/f'goodmorning-{unit}@{identifier}.service.d'
        folder.mkdir(mode=0o755, exist_ok=True)
        (folder/'identity.conf').write_text(f'[Service]\nUser={user}\nGroup={user}\n{extra}')
    systemctl('daemon-reload')
    systemctl('enable', '--now', f'goodmorning-account@{identifier}.service', f'goodmorning-viewer@{identifier}.service')


def offered(bridge):
    from goodmorning.web.models import MODELS
    available = {(entry.get('providerID'), entry.get('id')) for entry in bridge.request('/api/model')['data']}
    return all((entry['providerID'], entry['id']) in available for entry in MODELS.values())


def connect(config, defaults, wait=180):
    """Register the server-default credential only after a read-only check shows it is missing."""
    from .briefing_runtime import LocalBridge
    bridge = LocalBridge(f'http://127.0.0.1:{config["chamberPort"]}', SOURCE, config['uiPassword'])
    deadline = time.monotonic()+wait
    while True:
        try:
            ready = offered(bridge)
            break
        except OSError:
            if time.monotonic() > deadline:
                raise RuntimeError('Engine did not become ready; inspect goodmorning-account@ID over SSH')
            time.sleep(2)
    if ready:
        print('Provider already connected; credential unchanged')
        return
    if json.dumps(defaults['providerID']) not in json.dumps(bridge.request('/api/integration')):
        raise RuntimeError('Engine does not offer the server-default provider integration')
    bridge.request('/api/credential', {'integrationID': defaults['providerID'], 'value': defaults['credential'], 'activate': True})
    # Model discovery finishes asynchronously after a provider connects.
    deadline = time.monotonic()+wait
    while not offered(bridge):
        if time.monotonic() > deadline:
            raise RuntimeError('Provider models are not offered yet; inspect the engine before rerunning')
        time.sleep(2)
    print('Provider connected; all website models are offered')


def provision(store, name, host, *, root=Path('/srv/goodmorning')):
    name = username(name)
    defaults = server_defaults(store)
    identifier = login(store, name, defaults)
    if not briefing_vault.locations(root, identifier)[0].exists():
        briefing_vault.initialize(root, identifier)
    systemctl('enable', '--now', f'goodmorning-vault@{identifier}.service')
    user = briefing_vault.provision_user(root, identifier)
    account = pwd.getpwnam(user)
    path = store.directory/'backends.json'
    used = used_ports(root/'live', json.loads(path.read_text()))
    config = runtime(root/'live'/identifier, (account.pw_uid, account.pw_gid), defaults, used)
    print(f'Runtime: Linux user {user}, engine port {config["chamberPort"]}, viewer port {config["viewerPort"]}')
    services(identifier, user)
    connect(config, defaults)
    entry = {'port': config['viewerPort'], 'key': config['gatewayKey']}
    registry = json.loads(path.read_text())
    if registry.get(identifier) != entry:
        private_write(path, json.dumps({**registry, identifier: entry}))
        print('Backend registered')
    return backend_status(store, name, host)
