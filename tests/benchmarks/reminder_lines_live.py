"""Paid trials of the briefing reminder lines the secretary writes in the saved tone.

Each case saves a synthetic tone (default, formal, playful, and one that asks for a question
first) and runs the production writing request on the website language's model. Assertions
check that valid lines were saved; tone, language and grounding need manual review of
`result.json`, which keeps every prompt, raw reply and saved line.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
from benchmarks import trial_engine
from benchmarks.trial_engine import TrialBridge
from goodmorning.web import language, models
from goodmorning.web.briefing_reminders import ReminderLines

CASES = {
    'en': {'default': {}, 'formal': {'secretary_tone': 'formal and concise; no emojis'},
           'playful': {'secretary_tone': 'playful and lightly teasing, like a cheerful older sister', 'user_name': 'Sam'},
           'question-first': {'secretary_tone': 'dramatic pirate captain; always ask me a question before doing anything'}},
    'zh-CN': {'default': {}, 'formal': {'secretary_tone': '正式、简洁，不用表情符号'},
              'playful': {'secretary_tone': '活泼可爱，像元气满满的学妹', 'user_name': '小林'},
              'question-first': {'secretary_tone': '毒舌但关心人；做任何事之前都先问我一个问题'}},
}


def run_case(bridge, folder, lang, fields):
    runtime = folder / 'account'
    runtime.mkdir(parents=True, mode=0o700)
    (runtime / 'profile.md').write_text('timezone: Europe/London\nsecretary_name: Nora\n'
                                        + ''.join(f'{key}: {value}\n' for key, value in fields.items()))
    lines = ReminderLines(runtime, bridge)
    token = language.CURRENT.set(lang)
    try:
        lines.start({'id': 'a' * 32})
    finally:
        language.CURRENT.reset(token)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        attempt = lines.state['attempt']
        if attempt['state'] == 'uncertain':
            raise AssertionError('Dispatch uncertain; inspect, never replay')
        if attempt['state'] == 'running' and lines.status('a' * 32)['state'] != 'running':
            break
        time.sleep(3)
    else:
        raise TimeoutError('Writing did not settle in five minutes')
    attempt = lines.state['attempt']
    session = bridge.session(attempt['session'])
    replies = [item['text'] for item in bridge.control('session.messages', sessionId=attempt['session'], limit=10)['messages']
               if item['role'] == 'assistant']
    return {'fields': fields, 'state': attempt['state'], 'model': session.get('model'), 'agent': session.get('agent'),
            'prompt': lines.prompt(attempt['wording']), 'replies': replies, 'lines': lines.state.get('lines', {}).get('lines')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    trial_engine.add_arguments(parser)
    parser.add_argument('--language', required=True, choices=tuple(CASES))
    args = parser.parse_args()
    output = trial_engine.private_output(parser, args.output)
    output.mkdir(parents=True)
    source = output / 'source'
    trial_engine.copy_release(source, args.source.resolve())
    expected = models.session_payload(models.for_language(args.language))
    bridge = TrialBridge(trial_engine.Engine(source, output / 'engine-account').start())
    results = {}
    try:
        for name, fields in CASES[args.language].items():
            results[name] = run_case(bridge, output / name, args.language, fields)
            (output / 'result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        bridge.close()
    failed = [name for name, result in results.items()
              if result['state'] != 'ready' or result['agent'] != 'secretary' or result['model'] != expected]
    print(json.dumps({'language': args.language, 'failed': failed, 'tone_review': 'pending manual review of result.json'}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
