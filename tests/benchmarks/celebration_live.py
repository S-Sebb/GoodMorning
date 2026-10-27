"""Opt-in paid trials for celebrations: the briefing card's wish, a festival, and the user's birthday in chat.

Real models write synthetic briefings on a celebration day; code words the card and the model
writes only the wish. News and weather are unavailable providers. Assertions check the card,
the wish's voice and the saved profile; tone and language need manual review of the transcripts.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from benchmarks.anime_live import account, copy_source
from benchmarks.briefing_tone_live import TRIAL_CLI, CheckpointBridge, link_handoff, observe
from benchmarks.letter_live import form_answer
from benchmarks import trial_engine
from benchmarks.trial_engine import TrialBridge
from benchmarks.task_tone_live import context, matrix_lock, save
from goodmorning.records import celebrations
from goodmorning.records.inbox_store import InboxStore
from goodmorning.records.task_store import TaskStore
from goodmorning.runtime_files import profile_fields
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import models

ZONE = 'Asia/Shanghai'
MORNING = datetime(2026, 10, 25, 23, tzinfo=timezone.utc)  # Monday 26 October, 07:00 in Shanghai.
EVENING = datetime(2026, 10, 26, 13, tzinfo=timezone.utc)  # Monday 21:00.
FESTIVAL = datetime(2026, 9, 24, 23, tzinfo=timezone.utc)  # Mid-Autumn Festival, Friday 25 September, 07:00.
# scenario: (edition, now, tone, user name, extra profile lines, first saved briefing, finished tasks, expected card items)
BRIEFINGS = {
    'morning-playful': ('gm', MORNING, 'playful', 'Mia', 'birthday: "10-26"\n', '2026-07-18', 100,
                        [['birthday'], ['days', 100, '2026-07-18'], ['tasks', 100, 100]]),
    'morning-formal': ('gm', MORNING, 'formal', '', '', '2025-10-26', 0, [['years', 1, '2025-10-26']]),
    'evening-default': ('gn', EVENING, 'default', '', 'birthday: "10-26"\n', '2026-10-20', 0, [['birthday']]),
    'morning-festival': ('gm', FESTIVAL, 'default', '', 'holiday_countries: "CN"\n', '2026-08-01', 0,
                         [['holiday', 'Mid-Autumn Festival', ['China']]]),
}
CHATS = {
    'birthday-save': ('playful', '', {'en': 'By the way, my birthday is February 13!', 'zh-CN': '对了，我的生日是2月13日！'}),
    'birthday-year': ('default', '', {'en': 'I was born on 3 May 1994, can you remember my birthday?',
                                      'zh-CN': '我是1994年5月3日出生的，记一下我的生日吧。'}),
    'turn-off': ('formal', '02-13', {'en': 'Please turn off the birthday and anniversary celebrations in my briefings.',
                                     'zh-CN': '请把简报里的生日和纪念日庆祝关掉。'}),
}
# The wish is the secretary's own: never the team's voice, the user's name, or the card's numbers.
VOICE = {'en': r'\b(we|we\'re|us|our)\b|team', 'zh-CN': r'我们|咱们|团队'}


def source_copy(folder, runtime):
    source = copy_source(folder, runtime)
    (source/'scripts/goodmorning.py').write_text(TRIAL_CLI)
    return source


def records(runtime, first, finished):
    """An earlier saved briefing and `finished` confirmed completions."""
    previous = runtime/'daily'/(first + '.gm.json')
    previous.parent.mkdir(exist_ok=True)
    previous.write_text(json.dumps({'v': 2, 'lang': 'en', 'greeting': 'Morning.', 'opening': 'A quiet start.',
                                    'sections': [['tasks', [['p', 'Nothing planned.']]]]}) + '\n')
    inbox = InboxStore(runtime, write=True)
    tasks = TaskStore(inbox)
    try:
        for number in range(finished):
            task = inbox.mutate('add', {'kind': 'todo', 'raw': f'Task {number}', 'task': {'title': f'Task {number}', 'timezone': ZONE}},
                                'ses_synthetic', f'task-{number}', '2026-10-20T10:00:00+08:00')['task_id']
            tasks.mutate(task, tasks.show(task)['revision'], {'status': 'done', 'confirmed_completion': True},
                         'ses_synthetic', f'done-{number}', '2026-10-22T10:00:00+08:00')
    finally:
        inbox.close()


def events(runtime):
    db = sqlite3.connect(runtime/'calendar.sqlite')
    try:
        return db.execute('SELECT count(*) FROM events').fetchone()[0]
    finally:
        db.close()


def run_briefing(output, language, selected, scenario):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    kind, now, tone, name, extra, first, finished, expected = BRIEFINGS[scenario]
    runtime = account(folder, language, tone, (f'user_name: "{name}"\n' if name else '') + extra, ZONE)
    records(runtime, first, finished)
    source = source_copy(folder, runtime)
    bridge = CheckpointBridge(trial_engine.Engine(source, runtime).start(), False, language)
    app = BrowserApp(runtime, bridge, now=lambda: now, preflight=True)
    day = app.today()
    result = {'scenario': scenario, 'language': language, 'tone': tone, 'model': selected, 'checks': [],
              'review': 'pending manual language/tone review of the wish and the transcript'}
    try:
        bridge.verify_scope()
        save(folder/'start-intent.json', {'date': day, 'kind': kind})
        with context(language, selected):
            job = app.start(day, kind)['job']
            for form in app.status(job)['forms']:
                app.reply(job, 'form', form['id'], {'answer': form_answer(form)})
        status = observe(app, bridge, job, folder, 'original', language, selected)
        assert status['state'] == 'ready', 'Edition did not finish; inspect preserved status/transcript'
        document = json.loads(app.source(day, kind).read_text())
        save(folder/'original.document.json', document)
        section = document['sections'][0]
        assert section[0] == 'celebration' and len(section[1]) == 1, 'The celebration card was not the first section'
        block = section[1][0]
        assert block[1] == expected, 'The card does not list the expected celebrations'
        assert block[3] == 'Nora', 'The card is not signed by the secretary'
        result['checks'].append('Card first, with the expected items and signer')
        wish = block[2]
        result['wish'] = wish
        result['voice'] = re.findall(VOICE[language], wish, re.IGNORECASE)
        assert not result['voice'], 'The wish speaks as "we" or the team'
        assert not re.search(r'\d', wish), 'The wish repeats a number or date'
        assert not name or name.casefold() not in wish.casefold(), 'The wish calls the user by name'
        result['checks'].append('Wish in the secretary\'s own voice, without numbers or the user\'s name')
        if finished:
            assert celebrations.shown(runtime) == {'tasks': {'100': day}}, 'The milestone was not recorded as shown'
            result['checks'].append('Milestone recorded as shown')
        assert link_handoff(folder, 'original', f'/d/{day}/{kind}.html'), 'Final reply was not a briefing-link handoff'
        result['checks'].append('Short saved-briefing link handoff')
        result['functional_complete'] = True
        print(f'{language} {selected} {scenario}: {len(result["checks"])} checks passed', flush=True)
    except Exception as error:
        result['failure'] = str(error)[:1500]
        result['functional_complete'] = False
        print(f'{language} {selected} {scenario}: INCOMPLETE — {result["failure"]}', flush=True)
    finally:
        bridge.close()
        save(folder/'result.json', result)
    return result


def run_chat(output, language, selected, scenario):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    tone, birthday, messages = CHATS[scenario]
    runtime = account(folder, language, tone, f'birthday: "{birthday}"\n' if birthday else '', ZONE)
    source = source_copy(folder, runtime)
    before = (runtime/'profile.md').read_text()
    bridge = TrialBridge(trial_engine.Engine(source, runtime).start())
    app = BrowserApp(runtime, bridge)
    chat = uuid.uuid4().hex
    message = messages[language]
    result = {'scenario': scenario, 'language': language, 'tone': tone, 'model': selected, 'message': message,
              'review': 'pending manual language/tone review; a turn-off reply must say plainly celebrations stay on'}

    def wait():
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            with context(language, selected):
                status = app.chats.status(chat)
            if status['permissions']:
                raise AssertionError('Unexpected permission; not auto-approved: ' + json.dumps(status['permissions'])[:500])
            if status['state'] in ('idle', 'waiting'):
                return status
            if status['state'] in ('uncertain', 'unavailable'):
                raise AssertionError('Uncertain delivery; inspect, never replay')
            time.sleep(3)
        raise TimeoutError('No settled reply within ten minutes')

    try:
        with context(language, selected):
            app.chats.start({'id': chat, 'mode': 'secretary', 'text': message})
        status = wait()
        save(folder/'messages.json', status['messages'])
        result['assistant'] = [m['text'] for m in status['messages'] if m['role'] == 'assistant' and m['text'].strip()]
        result['forms'] = status['forms']
        after = (runtime/'profile.md').read_text()
        result['birthday'] = profile_fields(runtime).get('birthday')
        assert events(runtime) == 0, 'A calendar occasion was created'
        if scenario == 'turn-off':
            assert after == before, 'The profile changed'
            result['checks'] = ['Profile and calendar unchanged']
        else:
            # A clear birthday needs no question.
            assert not status['forms'], 'A clear request asked a question: ' + json.dumps(status['forms'], ensure_ascii=False)[:500]
            assert result['birthday'] == ('02-13' if scenario == 'birthday-save' else '05-03'), 'Birthday not saved as MM-DD'
            assert '1994' not in after, 'The birth year was saved'
            assert [line for line in before.splitlines() if not line.startswith('birthday')] == \
                [line for line in after.splitlines() if not line.startswith('birthday')], 'Unrelated profile lines changed'
            result['checks'] = ['Birthday saved as MM-DD only; no occasion; unrelated lines unchanged']
        result['functional_complete'] = True
        print(f'{language} {selected} {scenario}: passed', flush=True)
    except Exception as error:
        result['failure'] = str(error)[:1500]
        result['functional_complete'] = False
        print(f'{language} {selected} {scenario}: INCOMPLETE — {result["failure"]}', flush=True)
    finally:
        bridge.close()
        save(folder/'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    trial_engine.add_arguments(parser)
    parser.add_argument('--language', choices=('en', 'zh-CN'), required=True)
    parser.add_argument('--model', choices=tuple(models.MODELS), help='Defaults to the production model for the language')
    parser.add_argument('--only', nargs='*', choices=(*BRIEFINGS, *CHATS))
    args = parser.parse_args()
    output = trial_engine.private_output(parser, args.output)
    selected = args.model or models.for_language(args.language)
    with matrix_lock(output):
        output.mkdir(mode=0o700)
        trial_engine.copy_release(output/'release', args.source.resolve())
        chosen = args.only or (*BRIEFINGS, *CHATS)
        results = [(run_briefing if name in BRIEFINGS else run_chat)(output, args.language, selected, name) for name in chosen]
        save(output/'matrix.json', {'model': selected, 'language': args.language, 'cases': results, 'limitations': [
            'Fixed synthetic days in Shanghai with unavailable news and weather; no public deployment.',
            'The setup birthday question is not covered.',
            'One sample per scenario and model; prose needs manual review.']})
        if not all(result.get('functional_complete') for result in results):
            raise SystemExit(1)


if __name__ == '__main__':
    main()
