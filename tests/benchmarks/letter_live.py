"""Opt-in paid trials for weekly letters: Sunday's evening section, a missed week's letter, and turning letters off or on in chat.

Real models write a synthetic Sunday evening briefing whose last section saves the week's letter, or
Monday's evening briefing after a skipped Sunday, whose last section saves last week's letter.
Assertions check the saved letter, the briefing card and profile lines; tone, language and grounding
need manual review of the retained letters and transcripts.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from benchmarks.anime_live import account, copy_source
from benchmarks.briefing_tone_live import CheckpointBridge, commands, link_handoff, observe
from benchmarks import trial_engine
from benchmarks.trial_engine import TrialBridge
from benchmarks.task_tone_live import context, matrix_lock, save
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.records import letters
from goodmorning.records.custom_store import CustomStore
from goodmorning.records.inbox_store import InboxStore
from goodmorning.records.task_store import TaskStore
from goodmorning.runtime_files import profile_fields
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import models

# `RUNTIME/letters-fail` makes every read of the week fail, as unreadable records would.
TRIAL_CLI = '''from pathlib import Path
import json, os, sqlite3, sys, uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning.records import letters
from goodmorning.cli import main
runtime = Path(os.environ['SECRETARY_DIR'])
if (runtime/'letters-fail').exists():
    def facts(*args):
        raise sqlite3.DatabaseError('database disk image is malformed')
    letters.facts = facts
call = uuid.uuid4().hex
with (runtime/'trial-commands.jsonl').open('a') as log:
    log.write(json.dumps({'call':call, 'argv':sys.argv[1:]}, ensure_ascii=False)+'\\n')
try:
    code = main()
except SystemExit as error:
    code = error.code if isinstance(error.code, int) else 0 if error.code is None else 1
with (runtime/'trial-commands.jsonl').open('a') as log:
    log.write(json.dumps({'call':call, 'exit':code or 0})+'\\n')
raise SystemExit(code)
'''

ZONE = 'Asia/Shanghai'
WEEK, SUNDAY = '2026-10-19', '2026-10-25'
NOW = datetime(2026, 10, 25, 13, tzinfo=timezone.utc)  # Sunday 21:00 in Shanghai.
MISSED = datetime(2026, 10, 26, 13, tzinfo=timezone.utc)  # Monday 21:00, after a Sunday without a briefing.
# scenario: (week fixture, tone, user name)
BRIEFINGS = {'evening-full': ('full', 'playful', 'Mia'), 'evening-quiet': ('quiet', 'default', ''),
             'evening-failed': ('fail', 'formal', ''), 'evening-saved': ('saved', 'default', ''),
             'evening-missed': ('missed', 'playful', '')}
CHATS = ('turn-off', 'turn-on')
TITLES = {
    'en': {'outline': 'Draft chapter 2 outline', 'figures': 'Send figures to Dr. Lee', 'photo': 'Renew passport photo', 'plants': 'Water the plants',
           'slides': 'Prepare conference slides', 'abstract': 'Submit abstract', 'thesis': 'Thesis', 'home': 'Home', 'idea': 'Try a weekly review with Mia',
           'old': 'An idea from last week', 'stretch': 'Stretching', 'read': 'Reading', 'run': 'Running', 'meeting': 'Group meeting', 'day': 'Day out',
           'dentist': 'Dentist'},
    'zh-CN': {'outline': '写第二章提纲', 'figures': '把图表发给李老师', 'photo': '重拍护照照片', 'plants': '给植物浇水', 'slides': '准备会议幻灯片',
              'abstract': '提交摘要', 'thesis': '毕业论文', 'home': '家里', 'idea': '和小米试试每周复盘', 'old': '上周的一个点子', 'stretch': '拉伸',
              'read': '读书', 'run': '跑步', 'meeting': '组会', 'day': '出去玩一天', 'dentist': '看牙医'}}
# Never in a letter: last week's work, a quiet habit, unlisted plans, and guilt or rating.
FORBIDDEN = {'en': ('figures', 'running', 'slides', 'missed', 'broke', 'behind', 'unfinished', 'still open', 'productive', 'busy week', 'quiet week',
                    'lazy', 'should have', 'little to', 'not much'),
             'zh-CN': ('图表', '跑步', '幻灯片', '没完成', '未完成', '中断', '断了', '落下', '拖延', '高效', '忙碌', '清闲', '偷懒', '应该', '不多', '没什么', '惦记')}


def stamp(day, hour=10):
    return f'{day}T{hour:02d}:00:00+08:00'


def week(runtime, language, full):
    """One synthetic week; a quiet one keeps only last week's records and next week's plans."""
    words = TITLES[language]
    inbox = InboxStore(runtime, write=True)
    tasks = TaskStore(inbox)
    try:
        def add(key, fields):
            return inbox.mutate('add', {'kind': 'todo', 'raw': fields['title'], 'task': {'timezone': ZONE, **fields}},
                                'ses_synthetic', key, stamp('2026-10-12'))['task_id']

        def done(task, day, key, at=None):
            revision = tasks.show(task)['revision']
            tasks.mutate(task, revision, {'status': 'done', 'confirmed_completion': True}, 'ses_synthetic', 'done-' + key,
                         at or stamp(day, 21), day=day if at is None else None)

        done(add('figures', {'title': words['figures'], 'project': words['thesis'], 'planned_date': '2026-10-15'}), '2026-10-15', 'figures')
        inbox.mutate('add', {'kind': 'idea', 'raw': words['old']}, 'ses_synthetic', 'old', stamp('2026-10-14'))
        if full:
            done(add('outline', {'title': words['outline'], 'project': words['thesis'], 'planned_date': '2026-10-20'}), '2026-10-20', 'outline')
            done(add('photo', {'title': words['photo'], 'project': words['home']}), None, 'photo', at=stamp('2026-10-22'))
            plants = add('plants', {'title': words['plants'], 'repeat': {'weekdays': [0, 2, 4], 'start': '2026-10-19'}})
            for day in ('2026-10-19', '2026-10-21', '2026-10-23'):
                done(plants, day, 'plants-' + day)
            inbox.mutate('add', {'kind': 'idea', 'raw': words['idea']}, 'ses_synthetic', 'idea', stamp('2026-10-21'))
        add('slides', {'title': words['slides'], 'planned_date': '2026-10-27'})
        add('abstract', {'title': words['abstract'], 'due_date': '2026-10-28'})
    finally:
        inbox.close()
    custom = CustomStore(runtime, write=True)
    try:
        habits = ((words['stretch'], ('2026-10-06', '2026-10-13') + (('2026-10-19', '2026-10-20', '2026-10-22', '2026-10-24') if full else ())),
                  (words['read'], ('2026-10-07',) + (('2026-10-21',) if full else ())), (words['run'], ('2026-10-15',)))
        for title, days in habits:
            rule = custom.add({'title': title, 'timezone': ZONE, 'policy': {'base': 'weekdays', 'weekdays': [0, 1, 2, 3, 4, 5, 6],
                               'start': '2026-10-01', 'anchor': 'fixed', 'miss_policy': 'fixed'}}, 'ses_synthetic', title, stamp('2026-10-01'))['id']
            for revision, day in enumerate(days, 1):
                custom.report(rule, revision, {'status': 'done', 'confirmed_completion': True}, 'ses_synthetic', title + day, stamp(day, 22), day)
    finally:
        custom.close()
    calendar = CalendarStore(str(runtime/'calendar.sqlite'))
    try:
        calendar.add({'subject': words['meeting'], 'start': '2026-10-26T10:00:00+08:00', 'end': '2026-10-26T11:00:00+08:00'})
        calendar.add({'subject': words['day'], 'start': '2026-10-30', 'end': '2026-10-31', 'all_day': True, 'timezone': ZONE})
        calendar.add({'subject': words['dentist'], 'start': '2026-10-23T14:00:00+08:00', 'end': '2026-10-23T15:00:00+08:00'})
    finally:
        calendar.close()


def source_copy(folder, runtime):
    source = copy_source(folder, runtime)
    (source/'scripts/goodmorning.py').write_text(TRIAL_CLI)
    return source


def form_answer(form):
    """Nothing to report tonight: no completions, no other updates."""
    values = {}
    for field in form['fields']:
        options = [option['value'] for option in field.get('options') or []]
        if field['key'] == 'details' and options:
            values['details'] = options[0]
        else:
            values[field['key']] = ['none'] if 'none' in options else []
    return values


def run_briefing(output, language, selected, scenario):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    kind, tone, name = BRIEFINGS[scenario]
    runtime = account(folder, language, tone, f'user_name: "{name}"\n' if name else '', ZONE)
    week(runtime, language, kind in ('full', 'missed'))
    if kind == 'missed':  # The account was in use last week.
        (runtime/'daily').mkdir(exist_ok=True)
        (runtime/'daily'/'2026-10-21.md').write_text('# 2026-10-21\n')
    if kind == 'fail':
        (runtime/'letters-fail').touch()
    if kind == 'saved':  # Written by an earlier preparation of this Sunday.
        letters.save(runtime, WEEK, {'signoff': 'Saved sign-off.'}, language, SUNDAY)  # A quiet week: code writes the opening.
    before = letters.letter_path(runtime, WEEK).read_bytes() if kind == 'saved' else None
    source = source_copy(folder, runtime)
    bridge = CheckpointBridge(trial_engine.Engine(source, runtime).start(), False, language)
    app = BrowserApp(runtime, bridge, now=lambda: MISSED if kind == 'missed' else NOW, preflight=True)
    day = app.today()
    result = {'scenario': scenario, 'language': language, 'tone': tone, 'model': selected, 'checks': [],
              'review': 'pending manual language/tone/grounding review of letter.json and the transcript'}
    try:
        assert day == ('2026-10-26' if kind == 'missed' else SUNDAY), 'The synthetic evening is not the expected day'
        bridge.verify_scope()
        save(folder/'start-intent.json', {'date': day, 'kind': 'gn'})
        with context(language, selected):
            job = app.start(day, 'gn')['job']
            for form in app.status(job)['forms']:
                app.reply(job, 'form', form['id'], {'answer': form_answer(form)})
        status = observe(app, bridge, job, folder, 'original', language, selected)
        assert status['state'] == 'ready', 'Edition did not finish; inspect preserved status/transcript'
        document = json.loads(app.source(day, 'gn').read_text())
        save(folder/'original.document.json', document)
        section = document['sections'][-1]
        assert section[0] == 'letter' and len(section[1]) == 1, 'Weekly letter was not the last section'
        saved = letters.load(runtime, WEEK)
        if saved:
            save(folder/'letter.json', saved)
        if kind == 'fail':
            assert saved is None, 'A letter was saved from unreadable records'
            assert section[1][0] == ['letter', WEEK, None], 'The card did not say the letter could not be written'
            result['checks'].append('Unavailable card; no letter saved')
        else:
            assert saved, 'No letter was saved'
            assert section[1][0] == ['letter', WEEK, letters.counts(saved)], 'The card does not match the saved letter'
            if kind == 'saved':
                assert letters.letter_path(runtime, WEEK).read_bytes() == before, 'The saved letter changed'
                result['checks'].append('Saved letter kept unchanged; card reused it')
            else:
                assert letters.counts(saved) == ([0, 0, 0] if kind == 'quiet' else [5, 2, 1]), 'Unexpected week counts'
                assert saved['lang'] == language, 'Letter saved in another language'
                assert ('open' in saved) == (kind != 'missed'), 'Only a letter written before its week ended stays open'
                words = (saved['opening'] + ' ' + saved['signoff']).casefold()
                result['letter'] = {'opening': saved['opening'], 'signoff': saved['signoff']}
                result['forbidden'] = [word for word in FORBIDDEN[language] if word in words]
                assert not result['forbidden'], 'The letter mentioned something it must not'
                # Next week belongs only in the opening: no event or deadline title, nor an event's time, in the sign-off.
                upcoming = [title for *_, title in saved['next']['events'] + saved['next']['deadlines']] + \
                    [clock for _, clock, _ in saved['next']['events'] if clock]
                result['signoff_next'] = [word for word in upcoming if word.casefold() in saved['signoff'].casefold()]
                assert not result['signoff_next'], 'The sign-off mentioned next week'
                result['checks'].append('Letter saved from the week with only allowed mentions')
        result['letter_reads'] = [entry for entry in commands(runtime) if entry['argv'][:1] == ['letter']]
        assert link_handoff(folder, 'original', f'/d/{day}/gn'), 'Final reply was not a briefing-link handoff'
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
    tone = {'turn-off': 'playful', 'turn-on': 'formal'}[scenario]
    runtime = account(folder, language, tone, 'weekly_letter: "false"\n' if scenario == 'turn-on' else '', ZONE)
    letters.save(runtime, '2026-10-12', {'signoff': 'See you.'}, language, SUNDAY)
    kept = letters.letter_path(runtime, '2026-10-12').read_bytes()
    source = source_copy(folder, runtime)
    before = (runtime/'profile.md').read_text()
    bridge = TrialBridge(trial_engine.Engine(source, runtime).start())
    app = BrowserApp(runtime, bridge)
    chat = uuid.uuid4().hex
    message = {('turn-off', 'en'): "I don't want the Sunday letters anymore, please stop writing them.",
               ('turn-off', 'zh-CN'): '周日的来信先别写了，帮我关掉吧。',
               ('turn-on', 'en'): 'Could you start writing my weekly letters again?',
               ('turn-on', 'zh-CN'): '能不能重新开始给我写每周来信？'}[scenario, language]
    result = {'scenario': scenario, 'language': language, 'tone': tone, 'model': selected, 'message': message, 'turns': [],
              'review': 'pending manual language/tone review; no other notifications may be promised'}

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
        seen = 0
        for _ in range(4):
            status = wait()
            replies = [m['text'] for m in status['messages'][seen:] if m['role'] == 'assistant' and m['text'].strip()]
            seen = len(status['messages'])
            result['turns'].append({'assistant': replies, 'forms': status['forms'],
                                    'weekly_letter': profile_fields(runtime).get('weekly_letter')})
            save(folder/'result.json', result)
            if not status['forms']:
                break
            raise AssertionError('A clear request asked a question: ' + json.dumps(status['forms'], ensure_ascii=False)[:500])
        save(folder/'messages.json', status['messages'])
        expected = 'false' if scenario == 'turn-off' else 'true'
        assert profile_fields(runtime).get('weekly_letter') == expected, 'weekly_letter was not set to ' + expected
        after = (runtime/'profile.md').read_text().splitlines()
        assert [line for line in before.splitlines() if not line.startswith('weekly_letter')] == \
            [line for line in after if not line.startswith('weekly_letter')], 'Unrelated profile lines changed'
        assert letters.letter_path(runtime, '2026-10-12').read_bytes() == kept, 'A saved letter changed'
        result['checks'] = ['weekly_letter saved as asked; unrelated lines and saved letters unchanged']
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
            'A fixed synthetic Sunday (and Monday after a skipped Sunday) in Shanghai; no public deployment.',
            'One sample per scenario and model; prose needs manual review.']})
        if not all(result.get('functional_complete') for result in results):
            raise SystemExit(1)


if __name__ == '__main__':
    main()
