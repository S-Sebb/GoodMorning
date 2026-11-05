"""Run tests/test_*.py modules in parallel groups, one unittest process per group.

`run.py` runs every module (releases); `run.py --changed BASE` only those for what changed since BASE.

The same tests as `python -m unittest discover -s tests -p 'test_*.py'`. Groups, not one
process per module, because each process repeats the shared imports. Only failing groups
print their output; the last lines keep unittest's `Ran N tests` and `OK` summary.
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import subprocess
import sys
import time

TESTS = Path(__file__).resolve().parent


def run(modules):
    return subprocess.run([sys.executable, '-m', 'unittest', *modules], cwd=TESTS,
                          capture_output=True, text=True)


def changed_modules(base):
    """Changed test modules, plus modules that name a changed file's stem. None means all:
    shared test code changed, or a changed file maps to no module. Docs and android/ (its own
    checks, docs/android-app.md) need none."""
    files = subprocess.run(['git', 'diff', '--name-only', f'{base}...HEAD'], cwd=TESTS.parent,
                           capture_output=True, text=True, check=True).stdout.split()
    texts = {path.stem: path.read_text(encoding='utf-8') for path in TESTS.glob('test_*.py')}
    selected = set()
    for name in files:
        path = Path(name)
        if path.suffix == '.md' or path.parts[0] in ('docs', 'android'):
            continue
        if path.parts[0] == 'tests':
            if path.parent.name == 'tests' and path.stem in texts:
                selected.add(path.stem)
            elif path.parent.name == 'tests' and path.suffix == '.py':
                return None  # run.py, support.py
            continue  # browser, integration and benchmark suites run separately
        hits = {module for module, text in texts.items() if re.search(rf'\b{re.escape(path.stem)}\b', text)}
        if not hits:
            return None
        selected |= hits
    return sorted(selected)


def main():
    started = time.monotonic()
    modules = sorted(path.stem for path in TESTS.glob('test_*.py'))
    if sys.argv[1:2] == ['--changed'] and len(sys.argv) == 3:
        chosen = changed_modules(sys.argv[2])
        if chosen == []:
            print('No test modules for these changes', file=sys.stderr)
            return 0
        modules = chosen or modules
    elif sys.argv[1:]:
        sys.exit('usage: run.py [--changed BASE]')
    workers = os.process_cpu_count() or 1
    count = min(len(modules), 2*workers)
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(run, [modules[i::count] for i in range(count)]))
    failed = [result for result in results if result.returncode]
    for result in failed:
        print(result.stdout+result.stderr, file=sys.stderr)
    tests = sum(int(n) for result in results for n in re.findall(r'^Ran (\d+) tests?', result.stderr, re.M))
    print(f'Ran {tests} tests in {time.monotonic()-started:.1f}s\n\n'
          +(f'FAILED ({len(failed)} of {count} groups)' if failed else 'OK'), file=sys.stderr)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
