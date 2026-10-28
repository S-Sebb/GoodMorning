"""GoodMorning's hooks for the server's daily maintenance routine, run as root (docs/server-maintenance.md).

hold    Pause the website, wait up to 20 minutes for idle, then hold every account. Exits 75 without
        a hold if a hold already exists, the website is already paused or an account stays busy.
python  Only while held: install GoodMorning Python patch updates. Exits 10 if the version changed,
        so the server reboots.
finish  Release the hold and resume the website. Safe to repeat; the boot unit runs it after a reboot.
status  Show the hold, if any.

Every step logs to the journal.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
from urllib.error import HTTPError
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy_native as native  # noqa: E402

STATE = Path('/var/lib/goodmorning-maintenance')
HOLD = STATE/'hold.json'
BY = 'daily maintenance'
IDLE_WAIT = 20*60
READY_TIMEOUT = 10*60
UV_PYTHON = {'UV_PYTHON_INSTALL_DIR': '/opt/goodmorning/uv/python'}
# EX_TEMPFAIL: no hold, so the server updates without restarting GoodMorning.
NOT_HELD = 75
PYTHON_CHANGED = 10


def log(message):
    print(message, flush=True)


def step(name, action):
    try:
        action()
        log(f'{name}: ok')
        return True
    except Exception:
        log(f'{name}: failed\n{traceback.format_exc()}')
        return False


def clients():
    identifiers, _ = native.provisioned()
    store, gateway, _, bridges = native.live_clients(native.CURRENT, identifiers)
    from goodmorning.security import maintenance as pause
    return identifiers, store, gateway, bridges, pause


def resume(store, pause):
    """Lift only this routine's own pause, never a deployment's or an incident's."""
    if (pause.get_state(store) or {}).get('by') == BY:
        pause.set_state(store, False)
        log('Website resumed')


def hold():
    if HOLD.exists():
        log('Not held: an earlier hold has not finished; run "maintain.py finish" or inspect')
        return NOT_HELD
    identifiers, store, gateway, bridges, pause = clients()
    if pause.get_state(store):
        log('Not held: the website was already paused (deployment or incident)')
        return NOT_HELD
    ticket = {'maintenance': time.strftime('%Y-%m-%d')}
    pause.set_state(store, True, reason='daily server maintenance', by=BY)
    log(f'Website paused; waiting up to {IDLE_WAIT//60} minutes for {len(identifiers)} accounts to be idle')
    try:
        busy = native.wait_idle(lambda: native.check_idle(store, bridges, ticket), IDLE_WAIT)
        if not busy:
            try:
                native.reserve(store, ticket)
            except native.Busy as error:
                busy = str(error)
        if not busy:
            STATE.mkdir(mode=0o700, exist_ok=True)
            HOLD.write_text(json.dumps({'ticket': ticket, 'paused': time.time()}))
            log('Held: every account is idle')
            return 0
    except BaseException:
        gateway.clear_ticket(ticket)
        resume(store, pause)
        raise
    # Busy users keep working; the server updates without restarts.
    log(f'Not held: {busy}')
    resume(store, pause)
    return NOT_HELD


def python_version():
    return subprocess.run([native.PYTHON, '--version'], capture_output=True, text=True, timeout=30).stdout.split()[-1]


def python():
    if not HOLD.exists():
        raise SystemExit('No hold: run "maintain.py hold" first')
    before = python_version()
    subprocess.run(['uv', 'python', 'upgrade', '3.14'], check=True, timeout=10*60, env=dict(os.environ, **UV_PYTHON))
    after = python_version()
    log(f'GoodMorning Python {before} -> {after}')
    return PYTHON_CHANGED if after != before else 0


def wait_ready(identifiers):
    # Engines start on their socket's first connection, so probing them would wake every account at once.
    units = ['goodmorning-gateway.service']+[unit for i in identifiers for unit in
                                             (f'goodmorning-account@{i}.socket', f'goodmorning-viewer@{i}.service')]
    deadline = time.monotonic()+READY_TIMEOUT
    while True:
        try:
            for unit in units:
                native.command(['systemctl', 'is-active', '--quiet', unit], timeout=10)
            return
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(5)


def public_login():
    try:
        response = urlopen('https://'+native.HOST+'/login', timeout=15)
    except HTTPError as error:
        response = error
    with response:
        assert response.status == 200, f'/login returned {response.status}'


def finish():
    """Release the hold, after a reboot or when the server routine is done."""
    if not HOLD.exists():
        return 0
    held = json.loads(HOLD.read_text())
    identifiers, store, gateway, _, pause = clients()
    # Resume even if an account is not ready: the pause would block every account, not only the broken one.
    ready = step('services ready', lambda: wait_ready(identifiers))
    gateway.clear_ticket(held['ticket'])
    resume(store, pause)
    HOLD.unlink()
    log(f'Website paused for {round(time.time()-held["paused"])}s')
    login = step('public login page', public_login)
    return 0 if ready and login else 1


def status():
    print(HOLD.read_text() if HOLD.exists() else 'No hold')
    return 0


def main(argv):
    assert os.geteuid() == 0, 'Run as root'
    sys.dont_write_bytecode = True
    # A stopping unit sends SIGTERM; exit through the cleanup above.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit('Stopped by SIGTERM'))
    commands = {'hold': hold, 'python': python, 'finish': finish, 'status': status}
    if len(argv) != 1 or argv[0] not in commands:
        raise SystemExit(__doc__)
    return commands[argv[0]]()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
