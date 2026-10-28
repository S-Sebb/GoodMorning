"""Opt-in paid trials for secretary memory: the note the secretary keeps in chat, its evening tidy and briefing use.

Chat scenarios check the saved note, records and the chat's memory marker; the briefings check that
the note stays out of the opening and sections, that the evening tidy takes in a new chat message, and that
Sunday's letter is saved. Tone, language, grounding and whether the note reads like a friend's memory (not
creepy, not a diagnosis) need manual review of the retained transcripts, `memory.json` and the documents.
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
EVENINGS = {'evening': datetime(2026, 10, 26, 13, tzinfo=timezone.utc), 'sunday': datetime(2026, 10, 25, 13, tzinfo=timezone.utc)}
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


def run_briefing(output, language, selected, scenario):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    runtime = account(folder, language, 'playful', '', ZONE)
    seed(runtime, language, 'full', True)
    source = source_copy(folder, runtime)
    bridge = CheckpointBridge(trial_engine.Engine(source, runtime).start(), False, language)
    app = BrowserApp(runtime, bridge, now=lambda: EVENINGS[scenario], preflight=True)
    # Earlier today the user mentioned something new in chat; the evening tidy should take it in.
    (runtime/'browser-chats'/'chats.json').write_text(json.dumps({'a' * 32: {
        'id': 'a' * 32, 'mode': 'secretary', 'title': 'Secretary', 'state': 'idle', 'created': time.time() - 3600,
        'turns': [{'id': 'a' * 32, 'text': TIDY[language]}]}}, ensure_ascii=False))
    day = app.today()
    result = {'scenario': scenario, 'language': language, 'model': selected, 'checks': [], 'before': note(runtime),
              'review': 'pending manual review: greeting, closing and letter sign-off reflect at most one thing, lightly and '
                        'accurately; the tidied note keeps its voice and drops the move that is over'}
    try:
        bridge.verify_scope()
        with context(language, selected):
            job = app.start(day, 'gn')['job']
            for form in app.status(job)['forms']:
                app.reply(job, 'form', form['id'], {'answer': form_answer(form)})
        status = observe(app, bridge, job, folder, 'original', language, selected)
        assert status['state'] == 'ready', 'Edition did not finish; inspect preserved status/transcript'
        document = json.loads(app.source(day, 'gn').read_text())
        save(folder/'original.document.json', document)
        result['greeting'], result['closing'] = document['greeting'], document.get('closing')
        keywords = ('mochi', 'marathon', 'vegetarian', '马拉松', '吃素', '十点', 'lena')
        body = json.dumps([document['opening'], document['sections']], ensure_ascii=False).casefold()
        assert not [word for word in keywords if word in body], 'The note reached the opening or a section'
        result['checks'].append('The note stayed out of the opening and sections')
        result['after'] = note(runtime)
        save(folder/'memory.json', memory.load(runtime))
        assert 'lena' in ' '.join(result['after'].values()).casefold(), 'The evening tidy did not take in the new chat message'
        result['checks'].append('The evening tidy took in the chat message')
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
