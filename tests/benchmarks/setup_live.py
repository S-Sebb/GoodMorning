"""Opt-in paid trials for website setup (Initialize) on synthetic accounts.

A persona answers only the questions it is shown, matching each by its content, so the same
persona drives code-led setup (`--arm change`) and the merge-base's prompt-led setup
(`--arm baseline`, which also runs the merge-base's website server code from `--source`).
A turn that ends without a question before setup is done counts as a stall. Results keep
each run's openers, questions, answers, profile and command log; prose needs manual review.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
if '--arm' in sys.argv and sys.argv[sys.argv.index('--arm') + 1] == 'baseline':
    # Import the merge-base's server package first; later imports reuse it from the module cache.
    sys.path.insert(0, str(Path(sys.argv[sys.argv.index('--source') + 1]).resolve()/'src'))
    import goodmorning  # noqa: F401
sys.path.insert(0, str(ROOT/'tests'))
from benchmarks.briefing_tone_live import trial_config
from benchmarks import trial_engine
from benchmarks.trial_engine import TrialBridge
from benchmarks.task_tone_live import context, matrix_lock, save
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.records.inbox_store import initialize
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

SCENARIOS = ('new', 'review-keep', 'review-change', 'reload', 'side-question', 'secretary-tone', 'recovery')
# What the persona says for each topic, and what the profile should then hold.
PERSONA = {
    'en': {'secretary_name': 'Pip', 'user_name': 'Sam', 'birthday': 'March 14', 'city': 'Edinburgh, UK',
           'work_days': 'Monday to Friday', 'work_hours': '9:00–17:30', 'sleep_time': '23:00',
           'secretary_tone': 'warm and helpful', 'occupations': 'Nurse', 'expertise_fields': 'Cardiology',
           'news_country': 'United Kingdom', 'holiday_countries': 'Scotland',
           'moved': 'Glasgow, UK', 'playful': 'playful', 'skip': 'Skip that for now.', 'keep': 'Keep it as it is.',
           'side': 'Quick question first: if I move cities later, can I change this?'},
    'zh-CN': {'secretary_name': '小满', 'user_name': '阿杰', 'birthday': '8月21日', 'city': '杭州',
              'work_days': '周一到周五', 'work_hours': '9:00–18:00', 'sleep_time': '23:30',
              'secretary_tone': '温和一点', 'occupations': '软件工程师', 'expertise_fields': '前端开发',
              'news_country': '中国', 'holiday_countries': '中国',
              'moved': '苏州', 'playful': '活泼一点', 'skip': '这个先跳过。', 'keep': '保持原样就好。',
              'side': '先问一下：以后如果换了城市，这里还能改吗？'}}
EXPECTED = {
    'en': {'secretary_name': 'Pip', 'user_name': 'Sam', 'birthday': '03-14', 'timezone': 'Europe/London',
           'region': 'global', 'news_country': 'GB', 'holiday_countries': 'GB-SCT', 'city': 'Edinburgh'},
    'zh-CN': {'secretary_name': '小满', 'user_name': '阿杰', 'birthday': '08-21', 'timezone': 'Asia/Shanghai',
              'region': 'mainland-china', 'news_country': 'CN', 'holiday_countries': 'CN', 'city': '杭州'}}
MENTIONED = {'en': {'work_days': 'Monday', 'work_hours': '9', 'sleep_time': '23', 'occupations': 'urse',
                    'expertise_fields': 'ardiolog'},
             'zh-CN': {'work_days': '周一', 'work_hours': '9', 'sleep_time': '23', 'occupations': '工程师',
                       'expertise_fields': '前端'}}
# Field topics by keyword, most specific first; a code-built form names its field directly.
TOPICS = (('consent', ('consent', 'agree', 'storage', 'store your', 'save your', 'keeps your', '同意', '存储', '保管', '保存你的')),
          ('birthday', ('birthday', '生日')),
          ('secretary_name', ('call me', 'name for me', 'my name', 'secretary', 'assistant', '叫我', '称呼我', '我的名字', '秘书')),
          ('user_name', ('call you', 'your name', 'address you', '称呼你', '叫你', '你的名字', '怎么称呼', '称呼')),
          ('holiday_countries', ('holiday', '假期', '假日', '节假')),
          ('news_country', ('news', '新闻')),
          ('city', ('city', 'where', 'based', 'located', 'location', 'timezone', 'time zone', '城市', '所在', '哪里', '时区', '位置')),
          ('work_days', ('work day', 'workday', 'days do you work', 'working days', '工作日', '哪几天')),
          ('work_hours', ('hours', 'working time', '工作时间', '上班时间', '几点')),
          ('sleep_time', ('bed', 'sleep', '睡')),
          ('secretary_tone', ('tone', 'talk', 'style', 'speak', '语气', '说话', '风格')),
          ('occupations', ('role', 'occupation', 'job', 'profession', '职业', '身份', '做什么工作')),
          ('expertise_fields', ('field', 'expert', 'know well', 'specialt', '领域', '擅长', '专业')))
KEEP_WORDS = ('keep', 'no change', 'as it is', 'unchanged', '保留', '不变', '保持', '不用改')
SKIP_WORDS = ('skip', 'not now', 'no thanks', 'none', 'no,', "don't", 'later', 'nothing', '跳过', '暂不', '先不', '不用', '不需要', '没有', '以后')
AGREE_WORDS = ('i agree', 'agree', 'allow', 'yes', 'save', 'continue', 'confirm', 'okay', 'ok', '我同意', '同意', '允许', '可以', '保存', '继续', '确认', '好')
REFUSE_WORDS = ("don't", 'do not', 'disagree', 'not agree', 'decline', 'cancel', 'no', '不同意', '不保存', '拒绝', '取消', '暂不')
NEWS_LABELS = {'GB': ('united kingdom', 'uk', 'britain', '英国'), 'CN': ('china', '中国')}
HOLIDAY_LABELS = {'GB-SCT': ('scotland', '苏格兰'), 'CN': ('china', '中国')}
OPENER_FLAGS = re.compile(r'instruction|\bdocs?\b|\.md\b|AGENTS|workflow|contract|receipt|helper|guide|reading|loading|'
                          r'文档|指令|说明|读取|加载|规则|流程|回执', re.I)
CJK = re.compile('[一-鿿]')
PLAYFUL = {'en': 'playful', 'zh-CN': '活泼'}
# A saved city names the place in the user's script or in English.
PLACES = {'Edinburgh': ('Edinburgh',), '杭州': ('杭州', 'Hangzhou'), 'Glasgow, UK': ('Glasgow',), '苏州': ('苏州', 'Suzhou')}


def source_copy(folder, runtime):
    source = folder/'source'
    shutil.copytree(folder.parent.parent/'release', source)
    config = trial_config(runtime)
    config['permissions'] = config['agents']['build']['permissions']
    (source/'opencode.json').write_text(json.dumps(config))
    (source/'scripts/goodmorning.py').write_text(TRIAL_CLI)
    return source


def account(folder, scenario, language):
    """A synthetic runtime: empty for a new user, otherwise a saved profile in the persona's words."""
    runtime = folder/'account'
    runtime.mkdir(mode=0o700)
    (runtime/'browser-policy.json').write_text(json.dumps({key: False for key in (
        'live_project_access', 'calendar_sync', 'publisher_images', 'news_acknowledgement')}))
    if scenario in ('new', 'reload', 'side-question'):
        return runtime
    expected, said = EXPECTED[language], PERSONA[language]
    saved = {**{key: expected[key] for key in ('secretary_name', 'user_name', 'birthday', 'timezone', 'region',
                                                'news_country', 'holiday_countries')},
             'city': 'Edinburgh, Scotland, GB' if language == 'en' else '杭州, 浙江, CN',
             **{key: said[key] for key in ('work_days', 'work_hours', 'sleep_time', 'secretary_tone', 'occupations', 'expertise_fields')}}
    if scenario == 'recovery':
        del saved['news_country'], saved['holiday_countries']
    (runtime/'profile.md').write_text(''.join(f'{key}: {json.dumps(value, ensure_ascii=False)}\n' for key, value in saved.items()))
    initialize(runtime)
    CalendarStore(str(runtime/'calendar.sqlite')).close()
    return runtime


def topics(form, field):
    """The persona's topics a field asks about; a code-built form's key names its one topic."""
    if field['key'] in PERSONA['en'] or field['key'] in ('city', 'news_additional_countries', 'special_needs'):
        return [field['key']]
    text = ' '.join([field.get('title', ''), field.get('description', ''), field['key'],
                     *(option.get('label', '') for option in field.get('options') or [])]).casefold()
    found = [name for name, words in TOPICS if any(word in text for word in words)]
    if not found:
        text = form.get('title', '').casefold()
        found = [name for name, words in TOPICS if any(word in text for word in words)]
    return found


def pick(options, words, avoid=()):
    for word in words:
        for option in options:
            label = (str(option.get('label', '')) + ' ' + str(option.get('value', ''))).casefold()
            if word in label and not any(other in label for other in avoid):
                return option['value']
    return None


def answer(form, language, plan):
    """The persona's answer: kept values stay, planned changes are typed, other topics are skipped."""
    said, values = PERSONA[language], {}
    for field in form['fields']:
        if field.get('hidden'):
            continue
        found, options = topics(form, field), field.get('options') or []
        multiple = field.get('type') == 'multiselect'
        value = None
        if found[:1] == ['consent']:
            value = pick(options, AGREE_WORDS, REFUSE_WORDS) or ('yes' if field.get('type') == 'boolean' else None)
            if field.get('type') == 'boolean':
                value = True
        elif plan.get('keep_all') and pick(options, ('keep everything', '全部保持')):
            value = pick(options, ('keep everything', '全部保持'))
        elif found[:1] in (['news_country'], ['news_additional_countries'], ['holiday_countries']):
            wanted = 'GB' if language == 'en' else 'CN'
            if found[0] == 'holiday_countries':
                value = pick(options, HOLIDAY_LABELS['GB-SCT' if language == 'en' else 'CN'])
            elif found[0] == 'news_country':
                value = pick(options, NEWS_LABELS[wanted])
            elif multiple:
                value = []
            if value is None and not multiple and (field.get('custom') or field.get('type') == 'string'):
                value = said[found[0]] if found[0] != 'news_additional_countries' else said['skip']
            if multiple and value is not None and not isinstance(value, list):
                value = [value]
        elif found and found[0] in plan.get('change', {}):
            value = plan['change'][found[0]]
        elif found and plan.get('keep') and pick(options, KEEP_WORDS):
            value = pick(options, KEEP_WORDS)
        elif found and all(topic in said for topic in found):
            text = ', '.join(said[topic] for topic in found if topic in said)
            value = pick(options, (text.casefold(),)) or (text if field.get('custom') or field.get('type') == 'string' else None)
        if value is None and options:
            value = pick(options, KEEP_WORDS if plan.get('keep') else ()) or pick(options, SKIP_WORDS, AGREE_WORDS[:1])
            if multiple and value is not None:
                value = [value]
        if value is None:
            if multiple:
                value = []
            elif field.get('type') == 'boolean':
                value = False
            elif field.get('custom') or field.get('type') == 'string':
                value = said['keep'] if plan.get('keep') else said['skip']
            else:
                raise AssertionError('Unsupported synthetic question; inspect it instead of guessing: '
                                     + json.dumps(field, ensure_ascii=False)[:500])
        values[field['key']] = value
    return values


def setup_state(runtime, chat):
    target = runtime/'browser-chats'/'setup'/(chat + '.json')
    return json.loads(target.read_text()) if target.exists() else None


def model_messages(messages):
    """Secretary-written messages, not code questions, notes or answers."""
    return [entry for entry in messages if entry['role'] == 'assistant' and entry.get('kind') not in (
        'question', 'skipped', 'note', 'outreach', 'expired') and entry['text'].strip()]


def run(output, language, selected, arm, scenario, index):
    folder = output/scenario/f'run-{index}'
    folder.mkdir(mode=0o700, parents=True)
    runtime = account(folder, scenario, language)
    before = (runtime/'profile.md').read_bytes() if (runtime/'profile.md').exists() else None
    source = source_copy(folder, runtime)
    bridge = TrialBridge(trial_engine.Engine(source, runtime).start())
    app = BrowserApp(runtime, bridge)
    chat = uuid.uuid4().hex
    said = PERSONA[language]
    plan = {'keep': scenario in ('review-keep', 'review-change', 'recovery'), 'keep_all': scenario == 'review-keep',
            'change': {'city': said['moved'], 'secretary_tone': said['playful']} if scenario == 'review-change' else {}}
    result = {'arm': arm, 'language': language, 'model': selected, 'scenario': scenario, 'run': index, 'turns': [],
              'permissions': [], 'review': 'pending manual language/tone review of messages.json'}

    def wait():
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            with context(language, selected):
                status = app.chats.status(chat)
            if status['permissions']:
                # Storage writes in the prompt-led baseline ask for one-time approval; the persona agrees.
                permission = status['permissions'][0]
                result['permissions'].append({**permission, 'turn': len(result['turns'])})
                with context(language, selected):
                    app.chats.reply(chat, 'permission', permission['id'], {'decision': 'once'})
                continue
            if status['state'] in ('idle', 'waiting'):
                return status
            if status['state'] in ('uncertain', 'unavailable'):
                raise AssertionError('Uncertain delivery; inspect, never replay')
            time.sleep(3)
        raise TimeoutError('No settled reply within ten minutes')

    try:
        with context(language, selected):
            if scenario == 'secretary-tone':
                message = {'en': 'From now on, please talk to me in a more playful way.', 'zh-CN': '以后跟我说话活泼一点吧。'}[language]
                app.chats.start({'id': chat, 'mode': 'secretary', 'text': message})
            else:
                app.chats.start({'id': chat, 'mode': 'initialize', 'text': ui.text('Start the initialization process with me.', lang=language)})
        replies, side_asked = 0, False
        for _ in range(60):
            status = wait()
            state = setup_state(runtime, chat)
            turn = {'forms': status['forms'], 'profile_exists': (runtime/'profile.md').exists()}
            result['turns'].append(turn)
            save(folder/'result.json', result)
            if not status['forms']:
                break  # Done, or a stall: the persona answers only questions.
            form = status['forms'][0]
            if scenario == 'side-question' and not side_asked and any(
                    topics(form, field)[:1] == ['city'] for field in form['fields']):
                side_asked, turn['sent'] = True, said['side']
                with context(language, selected):
                    app.chats.send(chat, {'id': uuid.uuid4().hex, 'text': said['side']})
                continue
            turn['answered'] = answer(form, language, plan)
            turn['consent'] = any(topics(form, field)[:1] == ['consent'] for field in form['fields'])
            with context(language, selected):
                app.chats.reply(chat, 'form', form['id'], {'answer': turn['answered']})
            replies += 1
            if scenario == 'reload' and replies == 3:
                app = BrowserApp(runtime, bridge)  # A server restart while setup is under way.
        messages = status['messages']
        save(folder/'messages.json', messages)
        fields = profile_fields(runtime)
        written = model_messages(messages)
        result['opener'] = written[0]['text'] if written else None
        result['opener_flags'] = sorted({match.group(0).casefold() for match in OPENER_FLAGS.finditer(result['opener'] or '')})
        result['opener_wrong_language'] = bool(result['opener']) and (language == 'zh-CN') != bool(CJK.search(result['opener']))
        result['profile'] = {key: fields.get(key, '') for key in (*EXPECTED['en'], *MENTIONED['en'], 'secretary_tone', 'special_needs')}
        result['setup'] = state = setup_state(runtime, chat)
        result['weather_check'] = ((state or {}).get('checks') or {}).get('weather')
        result['stalled'] = bool(status['state'] == 'idle' and scenario != 'secretary-tone' and (
            state['phase'] != 'done' if state else not fields.get('news_country')))
        commands = [json.loads(line) for line in (runtime/'trial-commands.jsonl').read_text().splitlines()] \
            if (runtime/'trial-commands.jsonl').exists() else []
        result['commands'] = [entry['argv'] for entry in commands if 'argv' in entry]
        memory = json.loads((runtime/'memory.json').read_text()) if (runtime/'memory.json').exists() else {'revision': 0}
        result['memory_writes'] = memory['revision']
        result['state_rebuilt'] = (runtime/'state.json').exists() and (runtime/'state.json').stat().st_mtime >= (
            (runtime/'profile.md').stat().st_mtime if (runtime/'profile.md').exists() else 0)
        # Agreeing means a consent question or an approved permission in an earlier turn than the first profile.
        first_write = next((number for number, turn in enumerate(result['turns']) if turn['profile_exists']), None)
        result['consent_before_write'] = before is not None or first_write is None or any(
            turn.get('consent') for turn in result['turns'][:first_write]) or any(
            permission['turn'] <= first_write for permission in result['permissions'])
        if state:
            questions = json.loads((runtime/'browser-chats'/'chats.json').read_text())[chat].get('questions', [])
            steps = {entry['form'].get('setup') for entry in questions} - {None, 'consent'}
            due = max(len(steps) - 1, 0)  # The first step of a blank start is code's own question.
            result['asked_by_model'] = [due - len(state['fallbacks']), due]
        result['checks'] = checks(scenario, language, fields, before, runtime, result)
        result['functional_complete'] = not result['checks']['failed']
        print(f'{arm} {language} {scenario} #{index}: {"passed" if result["functional_complete"] else "FAILED " + "; ".join(result["checks"]["failed"])}', flush=True)
    except Exception as error:
        result['failure'] = str(error)[:1500]
        result['functional_complete'] = False
        print(f'{arm} {language} {scenario} #{index}: INCOMPLETE — {result["failure"]}', flush=True)
    finally:
        bridge.close()
        save(folder/'result.json', result)
    return result


def checks(scenario, language, fields, before, runtime, result):
    """Records against the persona's answers: exact for names, dates, codes; mentioned for free text."""
    expected, failed = dict(EXPECTED[language]), []
    if scenario == 'review-change':
        expected['city'] = PERSONA[language]['moved']
    if scenario == 'secretary-tone':
        changed = [line for line in (runtime/'profile.md').read_text().splitlines()
                   if not line.startswith('secretary_tone') and line not in before.decode().splitlines()]
        if changed:
            failed.append('unrelated profile lines changed: ' + '; '.join(changed)[:300])
        if PLAYFUL[language] not in fields.get('secretary_tone', '').casefold():
            failed.append('tone not saved: ' + repr(fields.get('secretary_tone')))
        return {'failed': failed}
    if result['stalled']:
        failed.append('stalled before setup finished')
    for key, value in expected.items():
        if key == 'city':
            if not any(name in fields.get('city', '') for name in PLACES[value]):
                failed.append(f'city is {fields.get("city")!r}')
        elif fields.get(key, '') != value:
            failed.append(f'{key} is {fields.get(key, "")!r}, not {value!r}')
    if scenario in ('new', 'reload', 'side-question'):
        for key, part in MENTIONED[language].items():
            if part not in fields.get(key, ''):
                failed.append(f'{key} is {fields.get(key, "")!r}')
        if fields.get('special_needs'):
            failed.append('special_needs invented: ' + fields['special_needs'])
    if scenario == 'review-keep' and (runtime/'profile.md').read_bytes() != before:
        failed.append('keeping everything changed the profile')
    if scenario == 'review-change' and PLAYFUL[language] not in fields.get('secretary_tone', '').casefold():
        failed.append('tone change not saved: ' + repr(fields.get('secretary_tone')))
    if not result['state_rebuilt']:
        failed.append('state index not rebuilt after the last save')
    if result['memory_writes']:
        failed.append('memory written during setup')
    if not result['consent_before_write']:
        failed.append('profile written before storage consent')
    return {'failed': failed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    trial_engine.add_arguments(parser)
    parser.add_argument('--language', choices=('en', 'zh-CN'), required=True)
    parser.add_argument('--arm', choices=('change', 'baseline'), required=True)
    parser.add_argument('--model', choices=tuple(models.MODELS), help='Defaults to the production model for the language')
    parser.add_argument('--scenario', nargs='+', choices=SCENARIOS, default=['new'])
    parser.add_argument('--runs', type=int, default=1)
    args = parser.parse_args()
    output = trial_engine.private_output(parser, args.output)
    selected = args.model or models.for_language(args.language)
    with matrix_lock(output):
        output.mkdir(mode=0o700)
        trial_engine.copy_release(output/'release', args.source.resolve())
        results = [run(output, args.language, selected, args.arm, scenario, index)
                   for scenario in args.scenario for index in range(1, args.runs + 1)]
        save(output/'matrix.json', {'model': selected, 'language': args.language, 'arm': args.arm, 'cases': results,
                                    'limitations': ['Synthetic accounts and one persona per language; prose needs manual review.']})
        if not all(result.get('functional_complete') for result in results):
            raise SystemExit(1)


if __name__ == '__main__':
    main()
