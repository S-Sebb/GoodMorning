"""Opt-in paid trials for public holidays: briefings on holiday days and choosing holidays in chat.

Real models write a synthetic National Day morning and the evening before a make-up workday, set
`holiday_countries` from a clear request, an ambiguous one, a reply to the announcement note
and a setup review. Assertions check documents and profile lines; tone, language and whether a
note counts a holiday as an appointment need manual review of the retained transcripts.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from benchmarks.anime_live import account, copy_source
from benchmarks.briefing_tone_live import CheckpointBridge, link_handoff, observe
from benchmarks.letter_live import form_answer
from benchmarks import trial_engine
from benchmarks.trial_engine import TrialBridge
from benchmarks.task_tone_live import context, matrix_lock, save
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.runtime_files import profile_fields
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import language as ui
from goodmorning.web import models

TRIAL_CLI = '''from pathlib import Path
import json, os, sys, uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning.cli import main
runtime = Path(os.environ['SECRETARY_DIR'])
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
# scenario: (kind, focus day, now) — National Day, then Friday evening before Saturday's make-up workday.
BRIEFINGS = {'morning-holiday': ('gm', '2026-10-01', datetime(2026, 10, 1, 0, 30, tzinfo=timezone.utc)),
             'evening-workday': ('gn', '2026-10-09', datetime(2026, 10, 9, 13, tzinfo=timezone.utc))}
CHATS = ('clear', 'ambiguous', 'note-reply', 'setup')
# England and Wales share their holidays, so offering them together is a fair answer.
SAVED = {'clear': ('CN, GB-SCT',), 'ambiguous': ('GB-ENG', 'GB-ENG, GB-WLS'), 'note-reply': ('CN, US',), 'setup': ('CN',)}
MESSAGES = {('clear', 'en'): "Please show Chinese public holidays and Scotland's bank holidays on my calendar.",
            ('clear', 'zh-CN'): '日历上帮我显示中国和英国苏格兰的公共假期。',
            ('ambiguous', 'en'): 'Can you show UK public holidays on my schedule?',
            ('ambiguous', 'zh-CN'): '能在日程里显示英国的公共假期吗？',
            ('note-reply', 'en'): 'China and the US, please.',
            ('note-reply', 'zh-CN'): '中国和美国的都要。'}
# The announcement as sent to hosted accounts, in the secretary's voice.
NOTE = {'en': ('Public holidays on your calendar',
               "Good news: your Schedule and briefings can now show public holidays, and for China the make-up workdays too. "
               "They follow the countries you choose, not your city or news settings, so none appear until you pick some. "
               "Pick them on About me (in the Account menu) under Public holidays, or just reply here with the countries you'd "
               "like (more than one is fine) and I'll save them."),
        'zh-CN': ('日历上可以看到公共假期啦',
                  '好消息～日程页和简报现在可以显示公共假期啦，中国的调休上班日也会一起标出来。假期只按你选的国家显示，不跟随城市或新闻设置，'
                  '所以选好之前不会出现哦。可以在账户菜单的「关于我」里找到「公共假期」来选，也可以直接回复想看的国家（选几个都行），我来帮你保存。')}
HOLIDAY_WORDS = ('holiday', '假')
# Setup review: holidays get the case's answer; everything else is kept as saved.
ANSWERS = {'ambiguous': ('england', '英格兰'), 'setup': ('china', '中国')}
KEEP = ('keep', 'looks good', 'no change', 'continue', 'confirm', 'agree', 'allow', 'yes', 'skip', 'done', 'that’s all', "that's all",
        '保留', '不变', '不用改', '继续', '确认', '同意', '允许', '可以', '跳过', '好', '完成', '就这样')
SENTENCE = {'en': 'Keep it as it is.', 'zh-CN': '保持原样就好。'}


def source_copy(folder, runtime):
    source = copy_source(folder, runtime)
    (source/'scripts/goodmorning.py').write_text(TRIAL_CLI)
    return source


def run_briefing(output, language, selected, scenario):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    kind, day, now = BRIEFINGS[scenario]
    runtime = account(folder, language, 'default', 'holiday_countries: "CN"\n', ZONE)
    calendar = CalendarStore(str(runtime/'calendar.sqlite'))
    try:
        calendar.add({'subject': 'Family dinner' if language == 'en' else '家庭聚餐',
                      'start': '2026-10-01T18:00:00+08:00', 'end': '2026-10-01T20:00:00+08:00'})
    finally:
        calendar.close()
    source = source_copy(folder, runtime)
    bridge = CheckpointBridge(trial_engine.Engine(source, runtime).start(), False, language)
    app = BrowserApp(runtime, bridge, now=lambda: now, preflight=True)
    result = {'scenario': scenario, 'language': language, 'model': selected, 'checks': [],
              'review': 'pending manual review: the note may name the holiday or workday but must not count it as an appointment or free time'}
    try:
        assert app.today() == day, 'The synthetic day is not ' + day
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
        schedule = [section for section in document['sections'] if section[0] == 'schedule']
        result['schedule'] = schedule
        assert schedule and re.search(r'"hd_[0-9a-f]{16}"', json.dumps(schedule)), 'No holiday card in the schedule section'
        result['checks'].append('Holiday card in the schedule section')
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


def about_holidays(field):
    text = ' '.join([field.get('title', ''), field.get('description', '')]).casefold()
    return any(word in text for word in HOLIDAY_WORDS)


def answer(form, language, scenario):
    values = {}
    for field in form['fields']:
        options = field.get('options') or []
        labels = [(option.get('label', '') + ' ' + str(option.get('value', ''))).casefold() for option in options]
        picks = ANSWERS[scenario] if about_holidays(field) else KEEP
        chosen = next((option['value'] for word in picks for option, label in zip(options, labels) if word in label), None)
        if chosen is not None:
            values[field['key']] = [chosen] if field.get('type') == 'multiselect' else chosen
        elif about_holidays(field) and (field.get('type') == 'string' or field.get('custom')):
            values[field['key']] = {'ambiguous': {'en': 'England', 'zh-CN': '英格兰'}, 'setup': {'en': 'China', 'zh-CN': '中国'}}[scenario][language]
        elif field.get('type') == 'multiselect' and not about_holidays(field):
            values[field['key']] = []
        elif field.get('type') == 'string' or field.get('custom'):
            values[field['key']] = SENTENCE[language]
        else:
            raise AssertionError('Unsupported synthetic question; inspect it instead of guessing: ' + json.dumps(field, ensure_ascii=False)[:500])
    return values


def run_chat(output, language, selected, scenario):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    tone = {'clear': 'playful', 'ambiguous': 'formal'}.get(scenario, 'default')
    runtime = account(folder, language, tone, '', ZONE)
    source = source_copy(folder, runtime)
    before, fields = (runtime/'profile.md').read_text(), profile_fields(runtime)
    bridge = TrialBridge(trial_engine.Engine(source, runtime).start())
    app = BrowserApp(runtime, bridge)
    chat = uuid.uuid4().hex
    result = {'scenario': scenario, 'language': language, 'tone': tone, 'model': selected, 'turns': [],
              'review': 'pending manual language/tone review; places named in everyday words, no codes or field names'}

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
            if scenario == 'setup':
                result['message'] = ui.text('Start the initialization process with me.', lang=language)
                app.chats.start({'id': chat, 'mode': 'initialize', 'text': result['message']})
            else:
                if scenario == 'note-reply':
                    title, note = NOTE[language]
                    app.chats.outreach({'id': chat, 'text': note, 'title': title})
                    app.chats.send(chat, {'id': uuid.uuid4().hex, 'text': MESSAGES[scenario, language]})
                else:
                    app.chats.start({'id': chat, 'mode': 'secretary', 'text': MESSAGES[scenario, language]})
                result['message'] = MESSAGES[scenario, language]
        seen = 0
        for _ in range(20):
            status = wait()
            replies = [m['text'] for m in status['messages'][seen:] if m['role'] == 'assistant' and m['text'].strip()]
            seen = len(status['messages'])
            turn = {'assistant': replies, 'forms': status['forms'], 'holiday_countries': profile_fields(runtime).get('holiday_countries')}
            result['turns'].append(turn)
            save(folder/'result.json', result)
            if not status['forms']:
                break
            if scenario in ('clear', 'note-reply'):
                raise AssertionError('A clear request asked a question: ' + json.dumps(status['forms'], ensure_ascii=False)[:500])
            turn['answered'] = answer(status['forms'][0], language, scenario)
            with context(language, selected):
                app.chats.reply(chat, 'form', status['forms'][0]['id'], {'answer': turn['answered']})
        save(folder/'messages.json', status['messages'])
        saved = profile_fields(runtime).get('holiday_countries')
        assert saved in SAVED[scenario], f'holiday_countries is {saved!r}, not one of {SAVED[scenario]!r}'
        if scenario == 'ambiguous':
            assert result['turns'][0]['forms'] and not result['turns'][0]['holiday_countries'], 'Saved before asking which UK nation'
        if scenario == 'setup':
            asked = [form for turn in result['turns'] for form in turn['forms'] if any(map(about_holidays, form['fields']))]
            assert asked and all(len(form['fields']) == 1 for form in asked), 'Holidays were not asked alone'
            after = profile_fields(runtime)
            assert all(after.get(key) == fields.get(key) for key in ('city', 'timezone', 'news_country')), 'City or news settings changed'
        else:
            after = (runtime/'profile.md').read_text().splitlines()
            assert before.splitlines() == [line for line in after if not line.startswith('holiday_countries')], 'Unrelated profile lines changed'
        result['checks'] = ['holiday_countries saved as asked; unrelated lines unchanged']
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
            'A fixed synthetic October in Shanghai; no public deployment.',
            'One sample per scenario and model; prose needs manual review.']})
        if not all(result.get('functional_complete') for result in results):
            raise SystemExit(1)


if __name__ == '__main__':
    main()
