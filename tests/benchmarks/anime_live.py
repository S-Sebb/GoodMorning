"""Opt-in paid trials for new-episode updates: the evening section and turning it on in chat.

Real models work through a private source copy whose CLI swaps AniList and Bangumi
for synthetic fixtures, so no live provider or account is contacted. Assertions
check records and documents; tone, language and grounding need manual review of
the retained transcripts.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import os
import shutil
import sys
import time
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from benchmarks.briefing_tone_live import CheckpointBridge, commands, link_handoff, observe, trial_config
from benchmarks.native_bridge import NativeBridge
from benchmarks.task_tone_live import context, matrix_lock, save, TONES
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.records.inbox_store import initialize
from goodmorning.runtime_files import profile_fields
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import models

# The fixture's providers: `RUNTIME/anime-fixture.json` picks episodes, empty or fail.
TRIAL_CLI = '''from pathlib import Path
import json, os, sys, uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning import anime
from goodmorning.cli import main
runtime = Path(os.environ['SECRETARY_DIR'])
fixture = json.loads((runtime/'anime-fixture.json').read_text())
call = uuid.uuid4().hex
with (runtime/'trial-commands.jsonl').open('a') as log:
    log.write(json.dumps({'call':call, 'argv':sys.argv[1:]}, ensure_ascii=False)+'\\n')
ANILIST = {195516: ('Kusuriya no Hitorigoto 3rd Season', 'The Apothecary Diaries Season 3', '薬屋のひとりごと 第3期', 2026),
           176301: ('Kusuriya no Hitorigoto 2nd Season', 'The Apothecary Diaries Season 2', '薬屋のひとりごと 第2期', 2025),
           161645: ('Kusuriya no Hitorigoto', 'The Apothecary Diaries', '薬屋のひとりごと', 2023),
           235: ('Meitantei Conan', 'Detective Conan', '名探偵コナン', 1996),
           177046: ("Meitantei Conan x McDonald's", None, '「名探偵コナン」×マクドナルド', None)}
BANGUMI = {568244: ('薬屋のひとりごと 第3期', '药屋少女的呢喃 第三季', '2026-10-02'), 486347: ('薬屋のひとりごと 第2期', '药屋少女的呢喃 第二季', '2025-01-10'),
           420628: ('薬屋のひとりごと', '药屋少女的呢喃', '2023-10-21'), 899: ('名探偵コナン', '名侦探柯南', '1996-01-08'),
           823: ('名探偵コナン 瞳の中の暗殺者', '名侦探柯南 瞳孔中的暗杀者', '2000-04-22')}
def matches(text):
    text = text.casefold()
    if any(word in text for word in ('conan', '柯南', 'コナン')):
        return 'conan'
    if any(word in text for word in ('apothecary', 'kusuriya', '药屋', '薬屋', '藥屋')):
        return 'apothecary'
def media(identifier):
    romaji, english, native, year = ANILIST[identifier]
    return {'id':identifier, 'title':{'romaji':romaji, 'english':english, 'native':native}, 'seasonYear':year,
            'format':'TV' if year else 'SPECIAL', 'status':'RELEASING' if identifier in (195516, 235) else 'FINISHED',
            'coverImage':{'large':'https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx%d.jpg' % identifier}}
def subject(identifier):
    name, name_cn, day = BANGUMI[identifier]
    return {'id':identifier, 'name':name, 'name_cn':name_cn, 'date':day, 'eps':12,
            'images':{'common':'https://lain.bgm.tv/r/400/pic/cover/l/%d.jpg' % identifier}}
def request(url, body=None, cache=None):
    if url == anime.ANILIST:
        values = body['variables']
        if 'u' in values:
            if values['u'] != 'maomao':
                raise anime.AnimeError('not_found')
            return {'data':{'MediaListCollection':{'lists':[{'entries':[{'media':media(195516)}]}]}}}
        if 's' in values:
            found = {'conan':[235, 177046], 'apothecary':[161645, 176301, 195516]}.get(matches(values['s']), [])
            return {'data':{'Page':{'media':[media(i) for i in found]}}}
        if fixture['mode'] == 'fail':
            raise anime.AnimeError('HTTP 503')
        rows = [] if fixture['mode'] == 'empty' else [
            {'episode':episode, 'airingAt':at, 'media':media(identifier)} for identifier, episode, at in fixture['anilist']
            if identifier in values['ids']]
        return {'data':{'Page':{'pageInfo':{'hasNextPage':False}, 'airingSchedules':rows}}}
    if '/collections' in url:
        if '/users/maomao/' not in url:
            raise anime.AnimeError('not_found')
        return {'total':1, 'data':[{'subject_id':568244, 'subject':subject(568244)}]}
    if '/search/subjects' in url:
        found = {'conan':[899, 823], 'apothecary':[420628, 486347, 568244]}.get(matches(body['keyword']), [])
        return {'data':[subject(i) for i in found]}
    if '/v0/subjects/' in url:
        return subject(int(url.rsplit('/', 1)[1]))
    if fixture['mode'] == 'fail':
        raise anime.AnimeError('HTTP 503')
    identifier = int(url.split('subject_id=')[1].split('&')[0])
    episodes = [] if fixture['mode'] == 'empty' else fixture['bangumi'].get(str(identifier), [])
    return {'total':len(episodes), 'data':episodes}
anime.request = request
try:
    code = main()
except SystemExit as error:
    code = error.code if isinstance(error.code, int) else 0 if error.code is None else 1
with (runtime/'trial-commands.jsonl').open('a') as log:
    log.write(json.dumps({'call':call, 'exit':code or 0})+'\\n')
raise SystemExit(code)
'''

BRIEFINGS = {'evening-episodes': ('episodes', 'playful'), 'evening-empty': ('empty', 'default'),
             'evening-failed': ('fail', 'formal')}
CHATS = ('enable-clear', 'enable-ambiguous')
WATCH_WORDS = ('crunchyroll', 'netflix', 'bilibili', 'hulu', 'watch it on', 'stream it on', '哔哩', 'b站', '在哪看', '爱奇艺', '腾讯视频')


def copy_source(folder, runtime):
    source = folder/'source'
    source.mkdir()
    for name in ('src', 'scripts', 'docs', 'templates', 'assets', 'skill-source', '.opencode'):
        shutil.copytree(ROOT/name, source/name, ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('AGENTS.md', 'AGENT-PROMPT-GUIDE.md', 'SERVER-USER-GUIDE.md', 'SERVER-DATA-GUIDE.md'):
        shutil.copyfile(ROOT/name, source/name)
    shutil.copyfile(ROOT/'skill-source/goodmorning.md', source/'goodmorning.md')
    config = trial_config(runtime)
    config['permissions'] = config['agents']['build']['permissions']
    (source/'opencode.json').write_text(json.dumps(config))
    (source/'scripts/goodmorning.py').write_text(TRIAL_CLI)
    return source


def account(folder, language, tone, anime_lines, zone):
    runtime = folder/'account'
    runtime.mkdir(mode=0o700)
    profile = (f'city: {"Shanghai, CN" if zone == "Asia/Shanghai" else "London, GB"}\ntimezone: {zone}\n'
               f'news_country: {"CN" if zone == "Asia/Shanghai" else "GB"}\nsecretary_name: Nora\ncalendar_source: custom\n')
    if TONES[tone]:
        profile += 'secretary_tone: ' + TONES[tone] + '\n'
    (runtime/'profile.md').write_text(profile + anime_lines)
    (runtime/'browser-policy.json').write_text(json.dumps({key:False for key in (
        'live_project_access', 'calendar_sync', 'publisher_images', 'news_acknowledgement')}))
    initialize(runtime)
    CalendarStore(str(runtime/'calendar.sqlite')).close()
    return runtime


def fixture(runtime, mode, zone, now):
    """Two episodes aired since the previous night briefing, which was saved yesterday at 21:30."""
    from goodmorning.briefings.briefing_day import briefing_day
    today = datetime.fromisoformat(briefing_day(zone, now)).date()  # 04:00 rollover, as the website counts days.
    yesterday = today - timedelta(days=1)
    previous = runtime/'daily'/(yesterday.isoformat() + '.gn.json')
    previous.parent.mkdir(exist_ok=True)
    previous.write_text(json.dumps({'v':2, 'lang':'en', 'greeting':'Evening.', 'opening':'A quiet review.',
                                    'sections':[['today', [['p', 'A quiet day.']]]]}) + '\n')
    saved = datetime.combine(yesterday, datetime.min.time(), ZoneInfo(zone)).replace(hour=21, minute=30).timestamp()
    os.utime(previous, (saved, saved))
    hours = lambda n: int((now - timedelta(hours=n)).timestamp())
    save(runtime/'anime-fixture.json', {'mode':mode, 'anilist':[[195516, 3, hours(20)], [235, 1217, hours(3)]],
         'bangumi':{'568244':[{'ep':3, 'name':'麺麭がなければ', 'name_cn':'何不食肉糜', 'airdate':yesterday.isoformat()}],
                    '899':[{'ep':1217, 'name':'背中を押す手', 'name_cn':'推向后背的手', 'airdate':today.isoformat()}]}})


def run_briefing(output, language, selected, scenario, now):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    mode, tone = BRIEFINGS[scenario]
    source_name, titles = ('anilist', '195516, 235') if language == 'en' else ('bangumi', '568244, 899')
    zone = 'Europe/London' if language == 'en' else 'Asia/Shanghai'
    runtime = account(folder, language, tone, f'anime_updates: "true"\nanime_source: "{source_name}"\n'
                      f'anime_account: ""\nanime_titles: "{titles}"\n', zone)
    fixture(runtime, mode, zone, now)
    source = copy_source(folder, runtime)
    bridge = CheckpointBridge(source, runtime, False, language)
    app = BrowserApp(runtime, bridge, now=lambda: now, preflight=True)
    day = app.today()
    result = {'scenario':scenario, 'language':language, 'tone':tone, 'model':selected, 'source':source_name,
              'checks':[], 'review':'pending manual language/tone/grounding review'}
    try:
        bridge.verify_scope()
        save(folder/'start-intent.json', {'date':day, 'kind':'gn'})
        with context(language, selected):
            job = app.start(day, 'gn')['job']
            form = app.status(job)['forms'][0]
            option = next(o['value'] for f in form['fields'] if f['key'] == 'details' for o in f['options'])
            app.reply(job, 'form', form['id'], {'answer':{'details':option}})
        status = observe(app, bridge, job, folder, 'original', language, selected)
        assert status['state'] == 'ready', 'Edition did not finish; inspect preserved status/transcript'
        document = json.loads(app.source(day, 'gn').read_text())
        save(folder/'original.document.json', document)
        section = document['sections'][-1]
        assert section[0] == 'anime', 'New episodes was not the last section'
        blocks = section[1]
        if mode == 'episodes':
            returned = json.loads((runtime/'browser-anime'/(day + '.json')).read_text())
            assert len(returned) == 2, 'Fixture episodes were not returned by the read'
            assert blocks[0] == ['episodes', returned], 'Episode block was not copied unchanged'
            assert section[2:3] and section[2].strip(), 'Episodes published without a short note'
            result['checks'].append('Read block copied unchanged with a note')
        else:
            assert [block[0] for block in blocks] == ['p'], 'Empty or failed read did not publish one paragraph'
            result['checks'].append(('Nothing-new' if mode == 'empty' else 'Unavailable') + ' line published, section not skipped')
        text = json.dumps(section, ensure_ascii=False).casefold()
        result['where_to_watch'] = [word for word in WATCH_WORDS if word in text]
        assert not result['where_to_watch'], 'The section named somewhere to watch'
        reads = [entry for entry in commands(runtime) if entry['argv'][:1] == ['anime']]
        result['anime_reads'] = [entry['argv'] for entry in reads]
        assert link_handoff(folder, 'original', f'/d/{day}/gn.html'), 'Final reply was not a briefing-link handoff'
        result['checks'].append('Short saved-briefing link handoff')
        result['functional_complete'] = True
        print(f'{language} {selected} {scenario}: {len(result["checks"])} checks passed', flush=True)
    except Exception as error:
        result['failure'] = str(error)[:1500]
        result['functional_complete'] = False
        print(f'{language} {selected} {scenario}: INCOMPLETE — {result["failure"]}', flush=True)
    finally:
        save(folder/'result.json', result)
    return result


def anime_settings(runtime):
    fields = profile_fields(runtime)
    values = {key:fields.get(key) for key in ('anime_updates', 'anime_source', 'anime_account', 'anime_titles')}
    if values['anime_source']:
        values['anime_source'] = values['anime_source'].casefold()  # The read accepts either case.
    return values


def answer(form, language):
    """Answer only what these fixtures ask: the source, the season, and no extra account or shows."""
    picks = (('anilist',) if language == 'en' else ('bangumi',)) + ('season 3', '3rd season', '1996', 'tv', '第3期', '第三季', 'no account',
             "don't follow", 'just this', 'skip', 'none', '不用', '不关联', '跳过', '只加', '只要',
             'save', 'yes', 'go ahead', '保存', '确认')
    sentence = ('AniList, please. No account to follow, just Season 3 of The Apothecary Diaries.' if language == 'en' else
                '用 Bangumi 吧。不用关联账号，只加《药屋少女的呢喃》第三季。')
    values = {}
    for field in form['fields']:
        options = field.get('options') or []
        labels = [(option.get('label', '') + ' ' + str(option.get('value', ''))).casefold() for option in options]
        chosen = next((option['value'] for word in picks for option, label in zip(options, labels) if word in label), None)
        if chosen is not None:
            values[field['key']] = [chosen] if field.get('type') == 'multiselect' else chosen
        elif field.get('type') == 'string' or field.get('custom'):
            values[field['key']] = sentence
        else:
            raise AssertionError('Unsupported synthetic question; inspect it instead of guessing: ' + json.dumps(field, ensure_ascii=False)[:500])
    return values


def run_chat(output, language, selected, scenario, now):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    zone = 'Europe/London' if language == 'en' else 'Asia/Shanghai'
    tone = 'playful' if scenario == 'enable-clear' else 'default'
    runtime = account(folder, language, tone, '', zone)
    fixture(runtime, 'episodes', zone, now)
    source = copy_source(folder, runtime)
    before = (runtime/'profile.md').read_text()
    bridge = NativeBridge(source, runtime)
    app = BrowserApp(runtime, bridge)
    chat = uuid.uuid4().hex
    message = {('enable-clear', 'en'): "I'd love my night briefing to show new episodes of the anime I'm watching. Use AniList, my username is maomao, and please add Detective Conan too.",
               ('enable-clear', 'zh-CN'): '想让晚间简报显示我在追的番剧更新。用 Bangumi，我的用户名是 maomao，另外把《名侦探柯南》也加上。',
               ('enable-ambiguous', 'en'): 'Can my night briefing tell me when The Apothecary Diaries gets a new episode?',
               ('enable-ambiguous', 'zh-CN'): '晚间简报能告诉我《药屋少女的呢喃》出新集了吗？'}[scenario, language]
    result = {'scenario':scenario, 'language':language, 'tone':tone, 'model':selected, 'message':message, 'turns':[],
              'review':'pending manual language/tone review'}

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
            app.chats.start({'id':chat, 'mode':'secretary', 'text':message})
        seen = 0
        for _ in range(4):
            status = wait()
            replies = [m['text'] for m in status['messages'][seen:] if m['role'] == 'assistant' and m['text'].strip()]
            seen = len(status['messages'])
            turn = {'assistant':replies, 'forms':status['forms'], 'settings':anime_settings(runtime)}
            result['turns'].append(turn)
            save(folder/'result.json', result)
            if not status['forms']:
                break
            turn['answered'] = answer(status['forms'][0], language)
            with context(language, selected):
                app.chats.reply(chat, 'form', status['forms'][0]['id'], {'answer':turn['answered']})
        save(folder/'messages.json', status['messages'])
        settings = anime_settings(runtime)
        result['settings'] = settings
        titles = sorted(int(part) for part in (settings['anime_titles'] or '').replace(',', ' ').split())
        if scenario == 'enable-clear':
            expected = ('anilist', [235]) if language == 'en' else ('bangumi', [899])
            assert (settings['anime_updates'], settings['anime_source'], settings['anime_account']) == ('true', expected[0], 'maomao'), \
                'Clear request did not save the source and verified account'
            assert titles == expected[1], 'Detective Conan was not saved as exactly the TV series'
        else:
            first = result['turns'][0]
            assert first['forms'], 'Request without a source did not ask first'
            assert first['settings'] == anime_settings_empty(), 'Settings were written before the source was chosen'
            expected = ('anilist', [195516]) if language == 'en' else ('bangumi', [568244])
            assert (settings['anime_updates'], settings['anime_source']) == ('true', expected[0]), 'Chosen source was not saved'
            assert not settings['anime_account'], 'An account was saved that the user never gave'
            assert titles == expected[1], 'The season the user chose was not the one saved'
        after = (runtime/'profile.md').read_text().splitlines()
        assert [line for line in before.splitlines()] == [line for line in after if not line.startswith('anime_')], \
            'Unrelated profile lines changed'
        result['checks'] = ['Profile lines saved as requested; unrelated lines unchanged']
        result['functional_complete'] = True
        print(f'{language} {selected} {scenario}: passed', flush=True)
    except Exception as error:
        result['failure'] = str(error)[:1500]
        result['functional_complete'] = False
        print(f'{language} {selected} {scenario}: INCOMPLETE — {result["failure"]}', flush=True)
    finally:
        save(folder/'result.json', result)
    return result


def anime_settings_empty():
    return {key:None for key in ('anime_updates', 'anime_source', 'anime_account', 'anime_titles')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--language', choices=('en', 'zh-CN'), required=True)
    parser.add_argument('--model', choices=tuple(models.MODELS), help='Defaults to the production model for the language')
    parser.add_argument('--only', nargs='*', choices=(*BRIEFINGS, *CHATS))
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to('/tmp/opencode'):
        parser.error('Synthetic output must stay beneath /tmp/opencode')
    selected = args.model or models.for_language(args.language)
    with matrix_lock(output):
        output.mkdir(mode=0o700)
        now = datetime.now(timezone.utc)
        chosen = args.only or (*BRIEFINGS, *CHATS)
        results = [(run_briefing if name in BRIEFINGS else run_chat)(output, args.language, selected, name, now) for name in chosen]
        save(output/'matrix.json', {'model':selected, 'language':args.language, 'cases':results, 'limitations':[
            'Synthetic AniList/Bangumi fixtures; no live provider, cover download or public deployment.',
            'One sample per scenario and model; prose needs manual review.']})
        if not all(result.get('functional_complete') for result in results):
            raise SystemExit(1)


if __name__ == '__main__':
    main()
