"""Opt-in paid trials for secretary memory: the note the secretary keeps in chat, its evening tidy and briefing use.

Chat scenarios check the saved note, records and the chat's memory marker; the briefings check that
the note stays out of the opening and sections, that the evening tidy takes in a new chat message, and that
Sunday's letter is saved. `patterns` gives the evening tidy two weeks of records and check-ins, counts the
patterns and people it saves, and fails when it copies a one-off record into the note. Tone, language, grounding and whether the note reads like a friend's memory (not
creepy, not a diagnosis) need manual review of the retained transcripts, `memory.json` and the documents.
"""
import argparse
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from benchmarks.anime_live import account
from benchmarks.briefing_tone_live import CheckpointBridge, link_handoff, observe
from benchmarks.letter_live import form_answer, source_copy
from benchmarks import trial_engine
from benchmarks.trial_engine import TrialBridge
from benchmarks.task_tone_live import context, matrix_lock, save
from goodmorning.records import letters, memory
from goodmorning.records.inbox_store import InboxStore
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import models

ZONE = 'Asia/Shanghai'
# Monday 21:00 in Shanghai (no weekly letter), and Sunday 21:00 (with the letter).
EVENINGS = {'evening': datetime(2026, 10, 26, 13, tzinfo=timezone.utc), 'sunday': datetime(2026, 10, 25, 13, tzinfo=timezone.utc),
            'upcoming': datetime(2026, 10, 26, 13, tzinfo=timezone.utc),
            'patterns': datetime(2026, 10, 26, 13, tzinfo=timezone.utc)}
NOTES = {'en': {'life': 'You have a dog, Mochi, and head home early after work to walk him. You are vegetarian.',
                'likes': 'You would rather not have meetings before 10.',
                'lately': 'You are training for a marathon in March. You are moving house on the weekend of 24–25 October.'},
         'zh-CN': {'life': '你养了一只叫 Mochi 的狗，下班后会早点回家遛它。你吃素。',
                   'likes': '你不喜欢上午十点前开会。',
                   'lately': '你在为三月的马拉松做训练。你 10 月 24–25 日那个周末搬家。'}}
NAMES = ('Ada', 'Ben', 'Chloe', 'Dev', 'Eli', 'Fay', 'Gus', 'Hana', 'Ivan', 'Jun', 'Kai', 'Lin', 'Mia', 'Noor', 'Omar',
         'Pia', 'Quinn', 'Rui', 'Sara', 'Tom', 'Uma', 'Vic', 'Wen', 'Yara', 'Zoe')
# Distinct synthetic friends that bring a note near its limit.
FRIENDS = {'en': [f' {name} is a friend from your {place} days.' for place in ('school', 'college', 'first job', 'running club', 'choir')
                  for name in NAMES],
           'zh-CN': [f'{name}是你{place}时认识的朋友。' for place in ('上学', '大学', '第一份工作', '跑步俱乐部', '合唱团') for name in NAMES]}
TIDY = {'en': 'My sister Lena is coming to stay next weekend, so I will be cleaning all week.',
        'zh-CN': '我姐姐 Lena 下周末来家里住，所以这周都要大扫除。'}
# An undated anticipation already in the note, and the chat message that gave the event's date (Friday 30 October).
UPCOMING = {'en': ('You are looking forward to the Starfall 2 full reveal stream.',
                   'The Starfall 2 full reveal stream is this Friday at 21:30 and I really want to catch it.'),
            'zh-CN': ('你很期待《星落 2》的完整发布直播。', '《星落 2》完整发布直播就在这周五晚上 21:30，我很想看。')}
# scenario: (tone, seeded note: none, full or near the limit, memory on, first message per language)
CHATS = {
    'picks-up': ('playful', None, True, {
        'en': "I have a dog called Mochi, so I can't stay out late after work. Add a to-do to buy dog food on Saturday.",
        'zh-CN': '我家有只狗叫 Mochi，所以下班后不能在外面待太晚。帮我加个待办：周六买狗粮。'}),
    'remember': ('default', None, True, {'en': "Please remember that I'm vegetarian.", 'zh-CN': '请记住我吃素。'}),
    'feelings': ('default', None, True, {
        'en': "I'm a nurse and I've done night shifts all week. Ugh, I'm worn out. What's on my list?",
        'zh-CN': '我是护士，这周一直在上夜班，唉，累坏了。我清单上有什么？'}),
    'sensitive': ('default', None, True, {
        'en': "I've started seeing a therapist for my anxiety. Anyway, what's on my list today?",
        'zh-CN': '我开始看心理咨询师了，因为焦虑。对了，我今天清单上有什么？'}),
    'forget': ('default', 'full', True, {'en': "Forget that I'm vegetarian, please. I eat fish now.",
                                         'zh-CN': '把我吃素这条忘掉吧，我现在也吃鱼了。'}),
    'use': ('playful', 'full', True, {'en': "I'm free all Thursday. When should I put a one-hour call with Sam? Just suggest, don't save.",
                                      'zh-CN': '我周四一整天都有空，和 Sam 的一小时电话放什么时候好？只给建议，不用保存。'}),
    'off': ('default', 'full', False, {'en': 'Remember that I have a cat named Bean.', 'zh-CN': '记住我有只猫叫 Bean。'}),
    'near-limit': ('default', 'long', True, {'en': "Please remember I'm allergic to peanuts.", 'zh-CN': '请记住我对花生过敏。'}),
}
BRIEFINGS = tuple(EVENINGS)
# Two weeks of records ending Monday 26 October: workouts planned every Monday morning, game ideas saved late at
# night, a stretching habit, one-off errands, and check-ins that name a running friend.
WORKOUT = {'en': 'Plan this week’s workouts', 'zh-CN': '安排这周的锻炼'}
GAME_IDEAS = {'en': ('Game idea: a cozy farming roguelike', 'Game idea: tower defense with cats', 'Game idea: a rhythm puzzle about trains'),
              'zh-CN': ('游戏点子：温馨的种田肉鸽', '游戏点子：猫咪塔防', '游戏点子：关于火车的节奏解谜')}
ONE_OFFS = {'en': (('Buy dog food', '2026-10-24'), ('Renew passport photo', '2026-10-21'), ('Call the dentist to reschedule', '2026-10-29')),
            'zh-CN': (('买狗粮', '2026-10-24'), ('补拍护照照片', '2026-10-21'), ('给牙医打电话改约', '2026-10-29'))}
OAT = {'en': 'Try oat milk in my latte', 'zh-CN': '拿铁试试燕麦奶'}
STRETCH = {'en': 'Stretching', 'zh-CN': '拉伸'}
CHECKINS = {'en': {'2026-10-19': 'Long run with Priya from running club; my legs are done.',
                   '2026-10-22': 'Easy run with Priya again, then an early night.'},
            'zh-CN': {'2026-10-19': '和跑步俱乐部的 Priya 一起长跑，腿都废了。',
                      '2026-10-22': '又和 Priya 轻松跑了一圈，然后早早睡了。'}}
TONIGHT = {'en': 'Signed up for the Shanghai half marathon in December with Priya.',
           'zh-CN': '和 Priya 一起报名了十二月的上海半程马拉松。'}
# Saved items: a pattern across days, or a person; each is a list of alternatives that all must match one sentence.
USEFUL = {'monday workouts': (('workout', 'exercise', 'training', '锻炼', '训练', '健身', '运动'), ('monday', '周一', '星期一', '每周一')),
          'late-night game ideas': (('game', '游戏'), ('night', 'evening', 'late', '晚', '夜')),
          'priya': (('priya',),), 'half marathon': (('half', '半马', '半程'),)}
LEAKS = ('dog food', 'passport', 'dentist', 'oat milk', 'farming', 'tower', 'rhythm', '狗粮', '护照', '牙医', '燕麦', '种田', '塔防', '节奏')
SENSITIVE = ('therap', 'anxi', '心理', '焦虑', '咨询')


def seed(runtime, language, kind, enabled):
    if kind:
        note = dict(NOTES[language])
        for friend in FRIENDS[language] if kind == 'long' else ():
            if sum(map(len, note.values())) + len(friend) > memory.LENGTH - 15:
                break
            note['life'] += friend
        memory.change(runtime, 0, note=note)
    if not enabled:
        memory.change(runtime, memory.load(runtime)['revision'], enabled=False)


def note(runtime):
    return memory.load(runtime)['note']


def records(runtime):
    inbox = InboxStore(runtime)
    try:
        return inbox.db.execute('SELECT count(*) FROM entries').fetchone()[0]
    finally:
        inbox.close()


def check_chat(scenario, language, runtime, before, result, messages):
    after = note(runtime)
    words = ' '.join(after.values()).casefold()
    replies = ' '.join(a for turn in result['turns'] for a in turn['assistant']).casefold()
    marked = any(m.get('kind') == 'action' and m['action']['target'] == 'memory' for m in messages)
    assert marked == (after != before), 'The memory marker does not match whether the note changed'
    # Keywords only flag the common wordings; review replies for other promises of later recall or use.
    promises = ('keep it in mind', 'keep that in mind', 'keep this in mind', '记在心里', '我会记得', '我会记住', '我记着', '我会留意')
    assert not [p for p in promises if p in replies], 'The reply promised to remember something later'
    if scenario == 'picks-up':
        assert records(runtime) == 1, 'The dog-food to-do was not saved once'
        assert 'mochi' in words, 'The dog was not remembered'
    elif scenario == 'remember':
        assert records(runtime) == 0, 'A memory request saved a to-do or idea'
        assert 'vegetarian' in words or '素' in words, 'Vegetarian was not remembered'
    elif scenario == 'feelings':
        assert records(runtime) == 0, 'A question saved a record'
        assert 'night' in after['lately'].casefold() or '夜班' in after['lately'], 'The week of night shifts is not in lately'
        result['nurse_in_note'] = 'nurse' in words or '护士' in words
    elif scenario == 'sensitive':
        assert not [word for word in SENSITIVE if word in words], 'A sensitive topic was remembered unasked: ' + repr(after)
    elif scenario == 'forget':
        assert not ('vegetarian' in words and 'no longer' not in words) and '吃素。' not in words.replace('不再吃素', ''), 'Vegetarian is still remembered'
        assert 'mochi' in words, 'An unrelated part of the note was lost'
    elif scenario == 'use':
        assert records(runtime) == 0, 'A suggestion saved a record'
        recited = ('i remember', 'you told me', 'you mentioned', '我记得', '你说过', '你提到')
        result['recited'] = [word for word in recited if word in replies]
    elif scenario == 'off':
        assert after == before, 'The note changed while memory was off'
        assert 'about me' in replies or '关于我' in replies, 'The reply did not say where to turn memory on'
    elif scenario == 'near-limit':
        assert 'peanut' in words or '花生' in words, 'The allergy was not remembered'
        assert sum(map(len, after.values())) <= memory.LENGTH
        assert 'mochi' in words, 'Trimming lost the dog'


def run_chat(output, language, selected, scenario):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    tone, kind, enabled, messages = CHATS[scenario]
    runtime = account(folder, language, tone, '', ZONE)
    seed(runtime, language, kind, enabled)
    before = note(runtime)
    source = source_copy(folder, runtime)
    bridge = TrialBridge(trial_engine.Engine(source, runtime).start())
    app = BrowserApp(runtime, bridge)
    chat = uuid.uuid4().hex
    result = {'scenario': scenario, 'language': language, 'tone': tone, 'model': selected, 'message': messages[language],
              'before': before, 'turns': [],
              'review': 'pending manual review: tone, language, no recital; the note reads like a friend remembering, never a diagnosis'}

    def wait():
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            with context(language, selected):
                status = app.chats.status(chat)
            if status['permissions']:
                raise AssertionError('Unexpected permission; not auto-approved: ' + json.dumps(status['permissions'])[:500])
            # An idle chat can briefly report no reply before the engine's last message lands.
            replied = any(m['role'] == 'assistant' and m['text'].strip() for m in status.get('messages', []))
            if status['state'] == 'waiting' or status['state'] == 'idle' and replied:
                return status
            if status['state'] in ('uncertain', 'unavailable'):
                raise AssertionError('Uncertain delivery; inspect, never replay')
            time.sleep(3)
        raise TimeoutError('No settled reply within ten minutes')

    try:
        with context(language, selected):
            app.chats.start({'id': chat, 'mode': 'secretary', 'text': messages[language]})
        status = wait()
        result['turns'].append({'assistant': [m['text'] for m in status['messages'] if m['role'] == 'assistant' and m['text'].strip()],
                                'forms': status['forms']})
        result['after'] = note(runtime)
        save(folder/'messages.json', status['messages'])
        if memory.path(runtime).exists():
            save(folder/'memory.json', memory.load(runtime))
        check_chat(scenario, language, runtime, before, result, status['messages'])
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


def history(runtime, language):
    from goodmorning.records.custom_store import CustomStore
    from goodmorning.records.task_store import TaskStore
    at = lambda day, clock: f'{day}T{clock}:00+08:00'
    inbox = InboxStore(runtime, write=True)
    tasks = TaskStore(inbox)
    try:
        def add(key, title, day, created, done=True):
            task = inbox.mutate('add', {'kind': 'todo', 'raw': title, 'task': {'timezone': ZONE, 'title': title, 'planned_date': day}},
                                'ses_synthetic', key, created)['task_id']
            if done:
                tasks.mutate(task, tasks.show(task)['revision'], {'status': 'done', 'confirmed_completion': True},
                             'ses_synthetic', 'done-' + key, at(day, '20:00'), day=day)
        for day in ('2026-10-12', '2026-10-19', '2026-10-26'):
            add('workout-' + day, WORKOUT[language], day, at(day, '08:40'))
        for (title, day), created in zip(ONE_OFFS[language], ('2026-10-20', '2026-10-15', '2026-10-25')):
            add(title, title, day, at(created, '12:30'), done=day < '2026-10-26')
        for raw, day in zip(GAME_IDEAS[language], ('2026-10-14', '2026-10-18', '2026-10-23')):
            inbox.mutate('add', {'kind': 'idea', 'raw': raw}, 'ses_synthetic', raw, at(day, '23:20'))
        inbox.mutate('add', {'kind': 'idea', 'raw': OAT[language]}, 'ses_synthetic', 'oat', at('2026-10-16', '10:00'))
    finally:
        inbox.close()
    custom = CustomStore(runtime, write=True)
    try:
        rule = custom.add({'title': STRETCH[language], 'timezone': ZONE, 'policy': {'base': 'weekdays', 'weekdays': [0, 1, 2, 3, 4, 5, 6],
                           'start': '2026-10-01', 'anchor': 'fixed', 'miss_policy': 'fixed'}}, 'ses_synthetic', 'stretch', at('2026-10-01', '09:00'))['id']
        for revision, day in enumerate(('2026-10-13', '2026-10-15', '2026-10-17', '2026-10-20', '2026-10-22', '2026-10-24'), 1):
            custom.report(rule, revision, {'status': 'done', 'confirmed_completion': True}, 'ses_synthetic', 'stretch' + day, at(day, '22:00'), day)
    finally:
        custom.close()
    (runtime/'daily').mkdir(exist_ok=True)
    for day, words in CHECKINS[language].items():
        (runtime/'daily'/(day + '.md')).write_text(f'# {day}\n\n## feedback\n- Other updates: {words}\n')


def tally(after):
    sentences = [part for text in after.values() for part in re.split(r'[.。!！;；\n]', text) if part.strip()]
    useful = [name for name, groups in USEFUL.items()
              if any(all(any(word in sentence.casefold() for word in group) for group in groups) for sentence in sentences)]
    return useful, [word for word in LEAKS if word in ' '.join(after.values()).casefold()]


def run_briefing(output, language, selected, scenario):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    runtime = account(folder, language, 'playful', '', ZONE)
    seed(runtime, language, 'full', True)
    message = TIDY[language]
    if scenario == 'upcoming':
        memory.change(runtime, 1, note={'life': '', 'lately': UPCOMING[language][0]})
        message = UPCOMING[language][1]
    if scenario == 'patterns':
        history(runtime, language)
    source = source_copy(folder, runtime)
    bridge = CheckpointBridge(trial_engine.Engine(source, runtime).start(), False, language)
    app = BrowserApp(runtime, bridge, now=lambda: EVENINGS[scenario], preflight=True)
    # Earlier today the user mentioned something new in chat; the evening tidy should take it in.
    (runtime/'browser-chats'/'chats.json').write_text(json.dumps({'a' * 32: {
        'id': 'a' * 32, 'mode': 'secretary', 'title': 'Secretary', 'state': 'idle', 'created': time.time() - 3600,
        'turns': [{'id': 'a' * 32, 'text': message}]}}, ensure_ascii=False))
    day = app.today()
    result = {'scenario': scenario, 'language': language, 'model': selected, 'checks': [], 'before': note(runtime),
              'review': 'pending manual review: greeting, closing and letter sign-off reflect at most one thing, lightly and '
                        'accurately; the tidied note keeps its voice and drops the move that is over; upcoming: a '
                        'greeting or closing mentioning the stream speaks of it as still ahead, and lately keeps its date'}
    try:
        bridge.verify_scope()
        with context(language, selected):
            job = app.start(day, 'gn')['job']
            for form in app.status(job)['forms']:
                values = form_answer(form)
                if scenario == 'patterns' and 'details' in values:
                    values['details'] = TONIGHT[language]
                app.reply(job, 'form', form['id'], {'answer': values})
        status = observe(app, bridge, job, folder, 'original', language, selected)
        assert status['state'] == 'ready', 'Edition did not finish; inspect preserved status/transcript'
        document = json.loads(app.source(day, 'gn').read_text())
        save(folder/'original.document.json', document)
        result['greeting'], result['closing'] = document['greeting'], document.get('closing')
        keywords = ('mochi', 'vegetarian', '吃素', '十点', 'lena') + (() if scenario == 'patterns' else ('marathon', '马拉松'))  # Tonight's check-in names a half marathon.
        body = json.dumps([document['opening'], document['sections']], ensure_ascii=False).casefold()
        assert not [word for word in keywords if word in body], 'The note reached the opening or a section'
        result['checks'].append('The note stayed out of the opening and sections')
        result['after'] = note(runtime)
        save(folder/'memory.json', memory.load(runtime))
        expected = {'upcoming': ('starfall', '星落')}.get(scenario, ('lena',))
        assert any(word in ' '.join(result['after'].values()).casefold() for word in expected), \
            'The evening tidy did not take in the new chat message'
        result['checks'].append('The evening tidy took in the chat message')
        if scenario == 'patterns':
            result['useful'], result['leaks'] = tally(result['after'])
            assert not result['leaks'], 'The tidy copied one-off records into the note: ' + ', '.join(result['leaks'])
            result['checks'].append('No one-off record reached the note')
        if scenario == 'sunday':
            letter = letters.load(runtime, '2026-10-19')
            assert letter, 'The weekly letter was not saved'
            result['letter'] = {key: letter.get(key) for key in ('opening', 'signoff')}
            result['checks'].append('The weekly letter was saved')
        assert link_handoff(folder, 'original', f'/d/{day}/gn'), 'Final reply was not a briefing-link handoff'
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
    parser.add_argument('--only', nargs='*', choices=(*CHATS, *BRIEFINGS))
    args = parser.parse_args()
    output = trial_engine.private_output(parser, args.output)
    selected = args.model or models.for_language(args.language)
    with matrix_lock(output):
        output.mkdir(mode=0o700)
        trial_engine.copy_release(output/'release', args.source.resolve())
        chosen = args.only or (*CHATS, *BRIEFINGS)
        results = [(run_briefing if name in BRIEFINGS else run_chat)(output, args.language, selected, name) for name in chosen]
        save(output/'matrix.json', {'model': selected, 'language': args.language, 'cases': results, 'limitations': [
            'A synthetic account in Shanghai; no public deployment.',
            'One sample per scenario and model; prose and memory wording need manual review.']})
        if not all(result.get('functional_complete') for result in results):
            raise SystemExit(1)


if __name__ == '__main__':
    main()
