"""Opt-in paid check: does a real model publish every news category its read filled?

Runs one morning briefing through the real browser job helpers with a real model.
The template directory supplies a minimal `profile.md` (synthetic, or an
owner-approved private copy). Weather and the past 24 hours of news are fetched
live. Output stays in the private directory you name.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from benchmarks.briefing_tone_live import CheckpointBridge, TRIAL_CLI, commands, observe, trial_config
from benchmarks.task_tone_live import context, save
from goodmorning.records.inbox_store import initialize
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web.models import MODELS, session_payload

# The real CLI with command logging only: no provider faults or synthetic weather.
FAULTS = ("if argv[:1]==['weather']:", "if argv[:1]==['news'] else", "if sys.argv[1:2]==['weather']:", "elif sys.argv[1:2]==['news']:")
assert all(TRIAL_CLI.count(fault) == 1 for fault in FAULTS), 'Trial CLI changed; update the fault switches'
LOGGING_CLI = TRIAL_CLI
for fault in FAULTS:
    LOGGING_CLI = LOGGING_CLI.replace(fault, fault.split('if', 1)[0] + 'if False' + (' else' if fault.endswith('else') else ':'))


def source_copy(folder):
    source = folder/'source'
    source.mkdir()
    for name in ('src', 'scripts', 'docs', 'templates', 'assets', 'skill-source', '.opencode'):
        shutil.copytree(ROOT/name, source/name, ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('AGENTS.md', 'AGENT-PROMPT-GUIDE.md', 'SERVER-USER-GUIDE.md', 'SERVER-DATA-GUIDE.md'):
        shutil.copyfile(ROOT/name, source/name)
    shutil.copyfile(ROOT/'skill-source/goodmorning.md', source/'goodmorning.md')
    (source/'scripts/goodmorning.py').write_text(LOGGING_CLI)
    return source


def news_blocks(document):
    section = next(section for section in document['sections'] if section[0] == 'news')
    return [[block[1], len(block[2]), block[3] if len(block) > 3 else None] if block[0] == 'news' else [block[0]]
            for block in section[1]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New private directory')
    parser.add_argument('--template', type=Path, required=True, help='Directory with profile.md')
    parser.add_argument('--language', choices=('en', 'zh-CN'), default='en')
    parser.add_argument('--model', choices=MODELS, default='muse-spark')
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(mode=0o700)
    runtime = folder/'account'
    runtime.mkdir(mode=0o700)
    source = source_copy(folder)
    (source/'opencode.json').write_text(json.dumps(trial_config(runtime)))
    (runtime/'profile.md').write_text((args.template/'profile.md').read_text() + 'calendar_source: custom\n')
    (runtime/'browser-policy.json').write_text(json.dumps({key: False for key in (
        'live_project_access', 'calendar_sync', 'publisher_images', 'news_acknowledgement')}))
    initialize(runtime)
    CalendarStore(str(runtime/'calendar.sqlite')).close()
    bridge = CheckpointBridge(source, runtime, False, args.language)
    instant = datetime.now(timezone.utc)
    app = BrowserApp(runtime, bridge, now=lambda: instant, preflight=True)
    day = app.today()
    result = {'language': args.language, 'model': session_payload(args.model), 'date': day}
    try:
        bridge.verify_scope()
        with context(args.language, args.model):
            job = app.start(day, 'gm')['job']
        status = observe(app, bridge, job, folder, 'original', args.language, args.model)
        log = commands(runtime)
        news_publishes = [entry for entry in log if entry['argv'][:1] == ['job'] and 'publish' in entry['argv']
                          and (entry.get('input') or {}).get('section', [''])[:1] == ['news']]
        result.update(state=status['state'],
                      news_publish_attempts=[{'exit': entry.get('exit'), 'error': entry.get('error'),
                                              'blocks': news_blocks({'sections': [entry['input']['section']]})}
                                             for entry in news_publishes],
                      news_reads=[' '.join(entry['argv']) for entry in log if entry['argv'][:1] == ['news']],
                      acknowledged=any('--ack' in entry['argv'] for entry in log))
        if status['state'] == 'ready':
            document = json.loads(app.source(day, 'gm').read_text())
            save(folder/'document.json', document)
            result['published_news'] = news_blocks(document)
            result['news_title'] = next(section for section in document['sections'] if section[0] == 'news')[3]
    except Exception as error:
        result['failure'] = str(error)[:1500]
    finally:
        save(folder/'result.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
