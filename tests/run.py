"""Run every tests/test_*.py module in parallel groups, one unittest process per group.

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


def main():
    started = time.monotonic()
    modules = sorted(path.stem for path in TESTS.glob('test_*.py'))
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
