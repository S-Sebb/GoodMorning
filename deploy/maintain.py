"""Daily server maintenance, run as root by goodmorning-maintenance.timer at 05:00 China time.

run           Pause the website and wait up to 20 minutes for idle, then install Ubuntu
              (including Docker), GoodMorning Python and SiYuan updates, and reboot only
              when an update needs it. If an account stays busy, the website resumes at
              once and updates install without restarts, Python updates or a reboot.
finish        Resume the website after the reboot or a failed run. Safe to repeat.
status [DAYS] Recent run reports, newest first, and the next run time.

Every step logs to the journal; each run also writes /var/log/goodmorning-maintenance/<date>.json.
See docs/server-maintenance.md.
"""
import json
import os
from pathlib import Path
import re
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
LOGS = Path('/var/log/goodmorning-maintenance')
KEEP_REPORTS = 90
BY = 'daily maintenance'
IDLE_WAIT = 20*60
# Updates must finish by 05:50 so a reboot and resume fit within the hour.
BUDGET = 50*60
READY_TIMEOUT = 10*60
SIYUAN = Path('/opt/siyuan')
SIYUAN_IMAGE = 'b3log/siyuan:latest'
KEEP_SIYUAN = 3
UV_PYTHON = {'UV_PYTHON_INSTALL_DIR': '/opt/goodmorning/uv/python'}
APT = ['apt-get', '-q', '-y', '-o', 'DPkg::Lock::Timeout=300',
       '-o', 'Dpkg::Options::=--force-confdef', '-o', 'Dpkg::Options::=--force-confold']
# Restarts are this routine's decision: needrestart only reports.
APT_ENV = {'DEBIAN_FRONTEND': 'noninteractive', 'NEEDRESTART_SUSPEND': '1'}
START = time.monotonic()


class OutOfTime(Exception):
    pass


def log(message):
    print(message, flush=True)


def left():
    return BUDGET-(time.monotonic()-START)


def sh(args, env=None, capture=False):
    """Run within the time budget; output streams to the journal unless captured."""
    if left() < 60:
        raise OutOfTime('Maintenance time budget used up')
    return subprocess.run(args, check=True, text=True, timeout=left(), env=dict(os.environ, **(env or {})),
                          capture_output=capture).stdout


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S%z')


def save(report):
    LOGS.mkdir(mode=0o750, exist_ok=True)
    path = LOGS/(report['date']+'.json')
    path.write_text(json.dumps(report, indent=2))
    path.chmod(0o600)
    for old in sorted(LOGS.glob('*.json'))[:-KEEP_REPORTS]:
        old.unlink()
    return path


def step(report, name, action):
    entry = {'step': name}
    log(f'== {name}')
    started = time.monotonic()
    try:
        entry['result'], entry['status'] = action(), 'ok'
    except Exception as error:
        entry['status'], entry['error'] = 'failed', f'{type(error).__name__}: {error}'[:1000]
        log(traceback.format_exc())
    entry['seconds'] = round(time.monotonic()-started)
    report['steps'].append(entry)
    log(f'{name}: {entry["status"]} in {entry["seconds"]}s')
    return entry


def upgradable():
    out = subprocess.run(['apt', 'list', '--upgradable'], capture_output=True, text=True, timeout=120).stdout
    return sorted({line.split('/')[0] for line in out.splitlines() if '/' in line})


def update_apt():
    sh(APT+['update'], APT_ENV)
    pending = upgradable()
    log(f'{len(pending)} packages to upgrade')
    sh(APT+['full-upgrade'], APT_ENV)
    sh(APT+['autoremove'], APT_ENV)
    remaining = upgradable()
    return {'upgraded': sorted(set(pending)-set(remaining)), 'notUpgraded': remaining}


def python_version():
    return subprocess.run([native.PYTHON, '--version'], capture_output=True, text=True, timeout=30).stdout.split()[-1]


def update_python():
    before = python_version()
    sh(['uv', 'python', 'upgrade', '3.14'], UV_PYTHON)
    return {'from': before, 'to': python_version()}


def update_siyuan():
    if not (SIYUAN/'update-siyuan.sh').is_file():
        return {'present': False}
    compose = ['docker', 'compose', '--project-directory', str(SIYUAN)]
    sh(compose+['pull', '--quiet'])
    latest = sh(['docker', 'image', 'inspect', '--format', '{{.Id}}', SIYUAN_IMAGE], capture=True).strip()
    containers = sh(compose+['ps', '-q'], capture=True).split()
    running = {sh(['docker', 'inspect', '--format', '{{.Image}}', c], capture=True).strip() for c in containers}
    if running == {latest}:
        return {'updated': False, 'image': latest[7:19]}
    # The script backs up, recreates the containers and rolls back itself if a health check fails.
    sh([str(SIYUAN/'update-siyuan.sh')])
    backups = sorted((SIYUAN/'backups').glob('siyuan-preupdate-*.tar.gz'))
    for old in backups[:-KEEP_SIYUAN]:
        old.unlink()
        Path(str(old)+'.sha256').unlink(missing_ok=True)
    tags = sh(['docker', 'images', 'siyuan-local-rollback', '--format', '{{.Tag}}'], capture=True).split()
    stamps = sorted({tag.split('-')[0] for tag in tags})
    for tag in tags:
        if tag.split('-')[0] in stamps[:-KEEP_SIYUAN]:
            sh(['docker', 'image', 'rm', 'siyuan-local-rollback:'+tag], capture=True)
    sh(['docker', 'image', 'prune', '--force'], capture=True)
    return {'updated': True, 'from': sorted(image[7:19] for image in running), 'to': latest[7:19]}


def reboot_reasons():
    reasons = []
    if Path('/run/reboot-required').exists():
        packages = Path('/run/reboot-required.pkgs')
        names = sorted(set(packages.read_text().split())) if packages.exists() else []
        reasons.append('Ubuntu requires a reboot' + (': '+', '.join(names) if names else ''))
    out = subprocess.run(['needrestart', '-b', '-r', 'l'], capture_output=True, text=True, timeout=300).stdout
    kernel = re.search(r'NEEDRESTART-KSTA: (\d)', out)
    if kernel and kernel[1] in ('2', '3'):
        reasons.append('A newer kernel is installed')
    services = re.findall(r'NEEDRESTART-SVC: (\S+)', out)
    if services:
        reasons.append('Services use replaced libraries: '+', '.join(services))
    return reasons


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


def run():
    # systemd's timeout sends SIGTERM; exit through the finally blocks below.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit('Stopped by systemd'))
    report = {'date': time.strftime('%Y-%m-%d'), 'started': now(), 'steps': []}
    # This routine owns updates; unattended-upgrades would restart services on its own.
    subprocess.run(['systemctl', 'disable', '--now', 'apt-daily-upgrade.timer'], capture_output=True, timeout=30)
    if HOLD.exists():
        report['result'] = 'skipped: an earlier run has not finished; run "maintain.py finish" or inspect'
        log(report['result'])
        save(report)
        return 1
    identifiers, store, gateway, bridges, pause = clients()
    if pause.get_state(store):
        report['result'] = 'skipped: the website was already paused (deployment or incident)'
        log(report['result'])
        save(report)
        return 0
    ticket = {'maintenance': report['date']}
    hold = {'ticket': ticket, 'paused': time.time(), 'reboot': False, 'boot': boot_id()}
    pause.set_state(store, True, reason='daily server maintenance', by=BY)
    log(f'Website paused; waiting up to {IDLE_WAIT//60} minutes for {len(identifiers)} accounts to be idle')
    held = rebooting = False
    try:
        idle = step(report, 'wait for idle', lambda: native.wait_idle(
            lambda: native.check_idle(store, bridges, ticket), IDLE_WAIT))
        busy = idle.get('error') or idle['result']
        if not busy:
            try:
                native.reserve(store, ticket)
                held = True
                STATE.mkdir(mode=0o700, exist_ok=True)
                HOLD.write_text(json.dumps({**hold, 'report': str(save(report))}))
            except native.Busy as error:
                busy = str(error)
        report['idle'] = held
        if not held:
            # Busy users keep working; updates below install without restarts.
            report['busy'] = busy
            resume(store, pause)
            report['pausedSeconds'] = round(time.time()-hold['paused'])
        apt = step(report, 'ubuntu and docker packages', update_apt)
        if held:
            step(report, 'goodmorning python', update_python)
        step(report, 'siyuan', update_siyuan)
        reasons = reboot_reasons()
        python = next((s for s in report['steps'] if s['step'] == 'goodmorning python' and s['status'] == 'ok'), None)
        if python and python['result']['from'] != python['result']['to']:
            reasons.append('GoodMorning Python changed')
        report['rebootReasons'] = reasons
        failed = [s['step'] for s in report['steps'] if s['status'] != 'ok']
        if reasons and held and apt['status'] == 'ok':
            rebooting = True
            HOLD.write_text(json.dumps({**hold, 'reboot': True, 'report': str(save(report))}))
            report['result'] = 'rebooting'+(' with failed steps: '+', '.join(failed) if failed else '')
            log(f'Rebooting: {"; ".join(reasons)}')
            save(report)
            subprocess.run(['systemctl', 'reboot'], check=True, timeout=30)
            return 0
        if reasons:
            report['restartDeferred'] = True
        report['result'] = 'failed: '+', '.join(failed) if failed else 'ok'
        return 1 if failed else 0
    except BaseException as error:
        report['result'] = f'failed: {type(error).__name__}: {error}'[:1000]
        log(traceback.format_exc())
        raise
    finally:
        if not rebooting:
            if held:
                gateway.clear_ticket(ticket)
                HOLD.unlink(missing_ok=True)
            if 'pausedSeconds' not in report:
                report['pausedSeconds'] = round(time.time()-hold['paused'])
            resume(store, pause)
            report['finished'] = now()
            report['minutes'] = round((time.monotonic()-START)/60, 1)
            log(f'Maintenance {report.get("result")} in {report["minutes"]} minutes')
            save(report)


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


def finish():
    """Release the hold after a reboot, or after a run that ended without releasing it."""
    if not HOLD.exists():
        return 0
    hold = json.loads(HOLD.read_text())
    if hold['reboot'] and hold['boot'] == boot_id():
        return 0  # The reboot is on its way; the boot unit finishes.
    path = Path(hold['report'])
    report = json.loads(path.read_text()) if path.is_file() else {'date': hold['ticket']['maintenance'], 'steps': []}
    identifiers, store, gateway, _, pause = clients()
    report['rebooted'] = hold['reboot']
    # Resume even if an account is not ready: the pause would block every account, not only the broken one.
    ready = step(report, 'services ready after reboot' if hold['reboot'] else 'services ready',
                 lambda: wait_ready(identifiers))
    gateway.clear_ticket(hold['ticket'])
    resume(store, pause)
    HOLD.unlink()
    report['pausedSeconds'] = round(time.time()-hold['paused'])

    def public_login():
        try:
            response = urlopen('https://'+native.HOST+'/login', timeout=15)
        except HTTPError as error:
            response = error
        with response:
            assert response.status == 200, f'/login returned {response.status}'
    login = step(report, 'public login page', public_login)
    failed = [s['step'] for s in report['steps'] if s['status'] != 'ok']
    report['result'] = 'failed: '+', '.join(failed) if failed else 'ok'
    report['finished'] = now()
    log(f'Maintenance {report["result"]}; website paused for {report["pausedSeconds"]}s')
    save(report)
    return 0 if ready['status'] == login['status'] == 'ok' else 1


def status(days=7):
    for path in sorted(LOGS.glob('*.json'), reverse=True)[:days]:
        report = json.loads(path.read_text())
        summary = {key: report.get(key) for key in ('date', 'result', 'minutes', 'pausedSeconds', 'idle',
                                                     'rebooted', 'rebootReasons', 'restartDeferred', 'busy')}
        summary['steps'] = [f'{s["step"]}: {s["status"]} {s.get("seconds")}s'+(f' ({s["error"]})' if 'error' in s else '')
                            for s in report.get('steps', [])]
        upgraded = next((s['result']['upgraded'] for s in report.get('steps', [])
                         if s['step'].startswith('ubuntu') and s['status'] == 'ok'), None)
        summary['packagesUpgraded'] = len(upgraded) if upgraded is not None else None
        print(json.dumps({k: v for k, v in summary.items() if v not in (None, [])}))
    if HOLD.exists():
        print(json.dumps({'unfinishedHold': json.loads(HOLD.read_text())}))
    print(subprocess.run(['systemctl', 'list-timers', '--no-pager', 'goodmorning-maintenance.timer'],
                         capture_output=True, text=True).stdout.strip())


def main(argv):
    assert os.geteuid() == 0, 'Run as root'
    sys.dont_write_bytecode = True
    if argv == ['run']:
        return run()
    if argv == ['finish']:
        return finish()
    if argv[:1] == ['status'] and len(argv) <= 2:
        return status(*map(int, argv[1:]))
    raise SystemExit(__doc__)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
