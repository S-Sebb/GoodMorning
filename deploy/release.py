"""Deploy origin/main to the live website in one guarded run.

Run from the primary checkout on an up-to-date main:
    uv run --no-project python deploy/release.py

Order: preflight, public archive, stage and test on the server while live,
pause, switch (waits for idle), paused checks, resume, public login check, tag.
The website is paused only for the switch and the paused checks.
"""
import argparse
from datetime import date
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SERVER = 'TCSFrontEnd'
SERVER_PYTHON = 'sudo -n /opt/goodmorning/python/bin/python -B'
ADMIN = SERVER_PYTHON+' /opt/goodmorning/current/scripts/goodmorning.py admin --account-mount /srv/goodmorning/live/accounts'
UV_BROWSER = ['uv', 'run', '--no-project', '--with-requirements', 'requirements/browser.txt', '--with', 'playwright', 'python']

spec = importlib.util.spec_from_file_location('deploy_native', ROOT/'deploy/deploy_native.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class Stop(Exception):
    """A gate failed; the message says what state the website is in."""


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=True, **kwargs).stdout.strip()


def ssh(script, timeout=120):
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', SERVER, script], text=True, capture_output=True, timeout=timeout)


def server(script, timeout=120):
    result = ssh(script, timeout)
    if result.returncode:
        raise Stop(f'Server command failed ({result.returncode}): {(result.stderr or result.stdout)[-3000:]}')
    return result.stdout.strip()


def build_archive(commit, target):
    """The public archive: only allowlisted regular files from the commit."""
    raw = subprocess.run(['git', 'archive', '--format=tar', commit], cwd=ROOT, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive, tarfile.open(target, 'w:gz') as public:
        members = [item for item in archive.getmembers() if item.isfile() and Path(item.name).parts[0] in helper.ALLOWED]
        helper.check_members(members)
        for item in members:
            public.addfile(item, archive.extractfile(item))
    return len(members)


def fetch(path):
    try:
        response = urlopen('https://'+helper.HOST+path, timeout=15)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


def paused_checks(version):
    status, headers, body = fetch('/')
    assert status == 503 and headers.get('Retry-After') == '60' and headers.get('Cache-Control') == 'no-store', 'Maintenance response'
    for text in ('maintenance-status', '/maintenance.css', 'Please come back later', '请稍后再来'):
        assert text.encode() in body, 'Maintenance page lacks '+text
    for asset in ('/maintenance.css', '/desk-secretary.png', '/icons/gm.svg'):
        assert fetch(asset)[0] == 200, asset+' does not load'
    release = json.loads(fetch('/api/release')[2])['release']
    assert release == version, f'Live release reports {release}, expected {version}'


def preflight():
    if run('git', 'branch', '--show-current') != 'main' or run('git', 'status', '--porcelain'):
        raise Stop('Use a clean primary checkout on main.')
    run('git', 'fetch', '--quiet', 'origin')
    commit = run('git', 'rev-parse', 'HEAD')
    if commit != run('git', 'rev-parse', 'origin/main'):
        raise Stop('Run git pull --ff-only first: HEAD is not origin/main.')
    checks = json.loads(run('gh', 'api', f'repos/{{owner}}/{{repo}}/commits/{commit}/check-runs'))['check_runs']
    if not any(check['name'] == 'contracts' and check['conclusion'] == 'success' for check in checks):
        raise Stop('CI has not passed on this commit yet.')
    sys.path.insert(0, str(ROOT/'src'))
    from goodmorning.web.release import patch_notes
    notes = patch_notes()
    if not notes:
        raise Stop('Patch notes are invalid.')
    if 'Website is live' not in server(ADMIN+' pause-status'):
        raise Stop('The website is already paused: another deployment or incident is in progress. Ask the owner.')
    return commit, notes[0]['version']


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--skip-browser', action='store_true', help='skip the public Chromium login check')
    args = parser.parse_args()
    started = time.monotonic()
    commit, version = preflight()
    name = f'{date.today():%Y%m%d}-ship-{commit[:7]}'
    stage_dir = f'/tmp/opencode/{name}'
    print(f'Deploying {version} as {name}', flush=True)

    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory)/f'{name}.tar.gz'
        files = build_archive(commit, archive)
        server(f'install -d -m 700 {stage_dir}')
        run('scp', '-q', str(archive), str(ROOT/'deploy/deploy_native.py'), f'{SERVER}:{stage_dir}/')
        archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    if archive_hash not in server(f'sha256sum {stage_dir}/{name}.tar.gz'):
        raise Stop('Uploaded archive differs from the local build.')
    helper_command = f'{SERVER_PYTHON} {stage_dir}/deploy_native.py'
    print('Staging and testing on the server; the website stays live...', flush=True)
    staged = json.loads(server(f'{helper_command} stage {stage_dir}/{name}.tar.gz {name}', timeout=1500).splitlines()[-1])

    server(f'{ADMIN} pause --reason "deploy {name}" --by "GoodMorning agent"')
    paused = time.monotonic()
    print('Website paused; switching once idle...', flush=True)
    result = ssh(f'{helper_command} switch {name}', timeout=helper.IDLE_TIMEOUT+600)
    if result.returncode == helper.NOT_IDLE:
        server(ADMIN+' resume')
        raise Stop('Work did not finish within the idle timeout. Nothing changed; the website was resumed.')
    if result.returncode:
        raise Stop('Switch failed and the helper restored the previous release. The website is still paused; '
                   'inspect before resuming:\n'+(result.stderr or result.stdout)[-3000:])
    report = json.loads(result.stdout.splitlines()[-1])
    try:
        paused_checks(version)
    except (AssertionError, OSError, ValueError) as error:
        raise Stop(f'Paused check failed: {error}. The new release is live but the website stays paused; '
                   'inspect, then resume or roll back.') from error
    server(ADMIN+' resume')
    downtime = time.monotonic()-paused
    if 'Website is live' not in server(ADMIN+' pause-status'):
        raise Stop('Resume was not confirmed.')

    if not args.skip_browser:
        with tempfile.TemporaryDirectory() as artifacts:
            login = subprocess.run([*UV_BROWSER, 'tests/browser/login.py', '--artifacts', artifacts],
                                   cwd=ROOT, text=True, capture_output=True, timeout=900)
        if login.returncode:
            server(f'{ADMIN} pause --reason "public check failed after {name}" --by "GoodMorning agent"')
            raise Stop('Public login check failed; the website is paused again. Inspect:\n'+login.stdout[-2000:]+login.stderr[-2000:])

    run('git', 'tag', f'deploy/{name}', commit)
    run('git', 'push', '--quiet', 'origin', f'deploy/{name}')
    print(json.dumps({'release': name, 'version': version, 'publicFiles': files, 'archiveSha256': archive_hash,
                      'stagedTests': {'python': staged['pythonTests'], 'node': staged['nodeTests']},
                      'switch': {key: report[key] for key in ('protectedPrivateFiles', 'idleAccountsRestarted',
                                                               'updatedFiles', 'switchSeconds')},
                      'publicLoginCheck': not args.skip_browser, 'pausedSeconds': round(downtime),
                      'totalSeconds': round(time.monotonic()-started)}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Stop as error:
        sys.exit(f'Stopped: {error}')
