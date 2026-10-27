"""Run paid live trials detached, observe them, and clean them up.

  trial.py start NAME HARNESS [HARNESS ARGS]   e.g. start en briefing_tone_live --language en
                                               (--resume continues a stopped run of the same NAME)
  trial.py status [--all]                      runs of this checkout (--all: every checkout)
  trial.py wait NAME [--timeout SECONDS]       exit 0 passed, 1 failed or stopped, 2 still running
  trial.py stop NAME                           interrupts its model work and stops its engines
  trial.py clean [NAME]                        deletes one run, or every run of this checkout

Runs live in /var/tmp/goodmorning-trials/<checkout>/NAME and never use the developer's OpenCode
service. They survive engine restarts and the agent's shell ending; after a reboot their
files remain and status reports them stopped.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.trial_engine import ROOT, TRIALS, task_root


def boot():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def files(task, name):
    return {'output':task/name, 'run':task/(name+'.run.json'), 'log':task/(name+'.log'),
            'exit':task/(name+'.exit'), 'lock':task/('.'+name+'.lock')}


def state(task, name):
    paths = files(task, name)
    if paths['exit'].exists():
        code = int(paths['exit'].read_text().strip() or 1)
        return ('passed' if code == 0 else f'failed (exit {code})'), code
    run = json.loads(paths['run'].read_text())
    if run['boot'] == boot():
        try:
            os.killpg(run['pid'], 0)
            return 'running', None
        except ProcessLookupError:
            pass
    return 'stopped', 1


def runs(task):
    return sorted(path.name.removesuffix('.run.json') for path in task.glob('*.run.json'))


def start(name, harness, arguments):
    task = task_root()
    script = ROOT/'tests/benchmarks'/(harness.removesuffix('.py')+'.py')
    if not script.name.endswith('_live.py') or not script.is_file():
        raise SystemExit('Unknown live trial: '+harness)
    paths = files(task, name)
    if paths['run'].exists() and state(task, name)[0] == 'running':
        raise SystemExit(f'{name} is still running; wait for it or stop it first')
    if paths['output'].exists() and '--resume' not in arguments:
        raise SystemExit(f'{name} already exists; choose a new name, clean it first, or pass --resume')
    task.mkdir(parents=True, exist_ok=True)
    paths['exit'].unlink(missing_ok=True)
    command = ['uv', 'run', '--no-project', '--with-requirements', 'requirements/browser.txt', '--with', 'playwright',
               'python', str(script), '--output', str(paths['output']), *arguments]
    environment = dict(os.environ)
    environment.pop('VIRTUAL_ENV', None)  # The launching uv environment may disappear before the detached run starts.
    with paths['log'].open('ab') as log:
        # Its own session: engine restarts and the agent's shell ending do not stop it.
        process = subprocess.Popen(['sh', '-c', '"$@"; echo $? > "$0"', str(paths['exit']), *command], cwd=ROOT,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, env=environment)
    paths['run'].write_text(json.dumps({'pid':process.pid, 'boot':boot(), 'command':command, 'started':time.time()}))
    print(f'{name}: started; log {paths["log"]}')


def status(every):
    for task in (sorted(TRIALS.iterdir()) if TRIALS.is_dir() else []) if every else [task_root()]:
        for name in runs(task) if task.is_dir() else []:
            log = files(task, name)['log']
            lines = log.read_text(errors='replace').splitlines() if log.exists() else []
            print(f'{task.name}/{name}: {state(task, name)[0]}' + (' | '+lines[-1][:200] if lines else ''))


def wait(name, timeout):
    task, deadline = task_root(), time.monotonic()+timeout
    while (current := state(task, name))[0] == 'running' and time.monotonic() < deadline:
        time.sleep(5)
    print(f'{name}: {current[0]}')
    return 2 if current[0] == 'running' else 0 if current[1] == 0 else 1


def stop(name):
    task = task_root()
    if state(task, name)[0] != 'running':
        return print(f'{name}: not running')
    group = json.loads(files(task, name)['run'].read_text())['pid']
    for number, seconds in ((signal.SIGTERM, 60), (signal.SIGKILL, 10)):
        os.killpg(group, number)
        deadline = time.monotonic()+seconds
        while state(task, name)[0] == 'running' and time.monotonic() < deadline:
            time.sleep(1)
        if state(task, name)[0] != 'running':
            break
    print(f'{name}: {state(task, name)[0]}')


def clean(name):
    task = task_root()
    names = [name] if name else runs(task)
    running = [entry for entry in names if files(task, entry)['run'].exists() and state(task, entry)[0] == 'running']
    if running:
        raise SystemExit('Still running: '+', '.join(running)+'; wait for or stop them first')
    for path in files(task, name).values() if name else [task]:
        if path.is_dir():
            shutil.rmtree(path, onexc=writable)
        else:
            path.unlink(missing_ok=True)
    print('removed '+(name or str(task)))


def writable(function, path, _error):
    # Some harnesses make their release copy read-only, like a deployed release.
    os.chmod(os.path.dirname(path), 0o700)
    if os.path.isdir(path) and not os.path.islink(path):
        os.chmod(path, 0o700)
    function(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('start')
    command.add_argument('name')
    command.add_argument('harness')
    command.add_argument('arguments', nargs=argparse.REMAINDER)
    commands.add_parser('status').add_argument('--all', action='store_true')
    command = commands.add_parser('wait')
    command.add_argument('name')
    command.add_argument('--timeout', type=int, default=600)
    commands.add_parser('stop').add_argument('name')
    commands.add_parser('clean').add_argument('name', nargs='?')
    args = parser.parse_args()
    if args.command == 'start':
        return start(args.name, args.harness, args.arguments)
    if args.command == 'status':
        return status(args.all)
    if args.command == 'wait':
        return wait(args.name, args.timeout)
    if args.command == 'stop':
        return stop(args.name)
    return clean(args.name)


if __name__ == '__main__':
    sys.exit(main())
