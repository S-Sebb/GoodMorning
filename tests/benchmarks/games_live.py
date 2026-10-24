"""Opt-in paid trials for game-sale updates: the evening section and turning it on in chat.

Real models work through a private source copy whose CLI swaps the Steam store for
synthetic fixtures, so no live store or account is contacted. Assertions check
records and documents; tone, language and grounding need manual review of the
retained transcripts.
"""
import argparse
from datetime import datetime, timedelta, timezone
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
from goodmorning.runtime_files import profile_fields
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import models

# The fixture's store: `RUNTIME/games-fixture.json` picks deals, none or fail.
TRIAL_CLI = '''from pathlib import Path
import json, os, sys, uuid
from urllib.parse import parse_qs, urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning import games
from goodmorning.cli import main
runtime = Path(os.environ['SECRETARY_DIR'])
fixture = json.loads((runtime/'games-fixture.json').read_text())
call = uuid.uuid4().hex
with (runtime/'trial-commands.jsonl').open('a') as log:
    log.write(json.dumps({'call':call, 'argv':sys.argv[1:]}, ensure_ascii=False)+'\\n')
APPS = {292030: ('The Witcher 3: Wild Hunt', '巫师3：狂猎', 80, 3999), 378649: ('The Witcher 3: Wild Hunt - Hearts of Stone', '巫师3：狂猎 - 石之心', 0, 799),
        378648: ('The Witcher 3: Wild Hunt - Blood and Wine', '巫师3：狂猎 - 血与酒', 0, 1499), 20920: ('The Witcher 2: Assassins of Kings Enhanced Edition', '巫师2：国王刺客 加强版', 0, 1499),
        582010: ('Monster Hunter: World', '怪物猎人：世界', 67, 2498), 1118010: ('Monster Hunter World: Iceborne', '怪物猎人：世界 - 冰原', 0, 3499),
        912540: ('Monster Hunter: World Original Soundtrack', '怪物猎人：世界 原声音乐', 0, 1599), 1245620: ('ELDEN RING', '艾尔登法环', 40, 4999)}
def money(cents, country):
    return ('¥ %.2f' if country == 'CN' else '£%.2f') % (cents / (200 if country == 'CN' else 100))
def request(url, cache=None, raw=False):
    if 'steamcommunity.com/id/' in url:
        known = {'geralt':'76561198000000001', 'ciri':'76561198000000002'}.get(url.split('/id/')[1].split('/')[0])
        return '<profile><steamID64>%s</steamID64></profile>' % known if known else '<response><error>none</error></response>'
    if 'GetWishlist' in url:  # ciri's wishlist is private, which reads as empty.
        return {'response':{'items':[{'appid':1245620, 'priority':1}, {'appid':292030, 'priority':2}]} if '76561198000000001' in url else {}}
    if 'storesearch' in url:
        term = parse_qs(urlsplit(url).query)['term'][0].casefold()
        chinese = parse_qs(urlsplit(url).query)['l'][0] == 'schinese'
        found = ([292030, 378649, 378648, 20920] if any(w in term for w in ('witcher', '巫师')) else
                 [582010, 1118010, 912540] if any(w in term for w in ('monster hunter', '怪物猎人')) else [])
        return {'items':[{'type':'app', 'id':i, 'name':APPS[i][1 if chinese else 0]} for i in found]}
    if fixture['mode'] == 'fail':
        raise games.GameError('HTTP 503')
    query = json.loads(parse_qs(urlsplit(url).query)['input_json'][0])
    chinese, country = query['context']['language'] == 'schinese', query['context']['country_code']
    items = []
    for entry in query['ids']:
        english, local, discount, cents = APPS[entry['appid']]
        discount = 0 if fixture['mode'] == 'none' else discount
        price = {'formatted_final_price':money(cents * (100 - discount) // 100, country)}
        if discount:
            price.update(discount_pct=discount, formatted_original_price=money(cents, country), active_discounts=[{'discount_end_date':fixture['ends']}])
        items.append({'appid':entry['appid'], 'success':1, 'name':local if chinese else english, 'best_purchase_option':price,
                      'assets':{'asset_url_format':'steam/apps/%d/${FILENAME}' % entry['appid'], 'header':'header.jpg'}})
    return {'response':{'store_items':items}}
games.request = request
try:
    code = main()
except SystemExit as error:
    code = error.code if isinstance(error.code, int) else 0 if error.code is None else 1
with (runtime/'trial-commands.jsonl').open('a') as log:
    log.write(json.dumps({'call':call, 'exit':code or 0})+'\\n')
raise SystemExit(code)
'''

BRIEFINGS = {'evening-deals': ('deals', 'playful'), 'evening-none': ('none', 'default'), 'evening-failed': ('fail', 'formal')}
CHATS = ('enable-clear', 'enable-ambiguous', 'wishlist-display-name', 'wishlist-private')
LINK = 'https://steamcommunity.com/id/geralt/'
PUSH_WORDS = ('buy now', 'grab it', "don't miss", 'will drop', 'lowest ever', 'all-time low', 'store.steampowered', '赶紧入手', '快入手', '史低', '还会降', '别错过')
FIELDS = ('game_sales', 'game_country', 'game_account', 'game_threshold', 'game_titles')


def fixture(runtime, mode, now):
    save(runtime/'games-fixture.json', {'mode':mode, 'ends':int((now + timedelta(days=4)).timestamp())})


def source_copy(folder, runtime):
    source = copy_source(folder, runtime)
    (source/'scripts/goodmorning.py').write_text(TRIAL_CLI)
    return source


def run_briefing(output, language, selected, scenario, now):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    mode, tone = BRIEFINGS[scenario]
    zone, country = ('Europe/London', 'GB') if language == 'en' else ('Asia/Shanghai', 'CN')
    runtime = account(folder, language, tone, f'game_sales: "true"\ngame_country: "{country}"\ngame_account: ""\n'
                      'game_threshold: "50"\ngame_titles: "292030, 582010"\n', zone)
    fixture(runtime, mode, now)
    source = source_copy(folder, runtime)
    bridge = CheckpointBridge(trial_engine.Engine(source, runtime).start(), False, language)
    app = BrowserApp(runtime, bridge, now=lambda: now, preflight=True)
    day = app.today()
    result = {'scenario':scenario, 'language':language, 'tone':tone, 'model':selected, 'checks':[],
              'review':'pending manual language/tone/grounding review'}
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
        assert section[0] == 'games', 'Game sales was not the last section'
        blocks = section[1]
        if mode == 'deals':
            returned = json.loads((runtime/'browser-games'/(day + '.json')).read_text())
            assert len(returned) == 2, 'Fixture deals were not returned by the read'
            assert blocks[0] == ['deals', returned], 'Deal block was not copied unchanged'
            assert section[2:3] and section[2].strip(), 'Deals published without a short note'
            result['checks'].append('Read block copied unchanged with a note')
        else:
            assert [block[0] for block in blocks] == ['p'], 'Empty or failed read did not publish one paragraph'
            result['checks'].append(('Nothing-on-sale' if mode == 'none' else 'Unavailable') + ' line published, section not skipped')
        text = json.dumps(section, ensure_ascii=False).casefold()
        result['push_words'] = [word for word in PUSH_WORDS if word in text]
        assert not result['push_words'], 'The section urged buying, predicted prices or linked the store'
        result['games_reads'] = [entry['argv'] for entry in commands(runtime) if entry['argv'][:1] == ['games']]
        assert link_handoff(folder, 'original', f'/d/{day}/gn.html'), 'Final reply was not a briefing-link handoff'
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


def game_settings(runtime):
    fields = profile_fields(runtime)
    values = {key:fields.get(key) for key in FIELDS}
    if values['game_country']:
        values['game_country'] = values['game_country'].upper()  # The read accepts either case.
    return values


def titles(value):
    return sorted(part for part in (value or '').replace(',', ' ').split())


FOLLOW_UPS = {('wishlist-display-name', 'en'): 'Here it is: ' + LINK, ('wishlist-display-name', 'zh-CN'): '给你：' + LINK,
              ('wishlist-private', 'en'): "Keep following it — I'll make it public.", ('wishlist-private', 'zh-CN'): '继续关注吧，我去把它设成公开。'}


def answer(form, language, scenario):
    """Answer only what these fixtures ask: the store region, 50% off, no extra wishlist, and confirmations."""
    picks = (('keep', 'continue', '保留', '继续') if scenario == 'wishlist-private' else ()) + (('united kingdom', 'uk', 'gb', '英国') if language == 'en' else ('china', 'cn', '中国', '国区')) + (
        '50%', '五折', '5 折', 'wild hunt', '狂猎', 'just', 'only', 'no —', 'no -', 'no,', 'no wishlist', "don't", 'skip', '不用', '不关注', '跳过', '只',
        'set it up', 'save', 'yes', 'go ahead', '就这样', '存吧', '保存', '确认', '好')
    sentence = {('enable-clear', 'en'): 'Yes, exactly as I said: save it.', ('enable-clear', 'zh-CN'): '对，就按我说的存吧。',
                ('enable-ambiguous', 'en'): 'The UK store, 50% off or more, and no wishlist — just The Witcher 3.',
                ('enable-ambiguous', 'zh-CN'): '国区，打五折或更低就提醒，不用关注愿望单，只加《巫师3》。',
                **FOLLOW_UPS}[scenario, language]
    values = {}
    for field in form['fields']:
        if scenario == 'wishlist-display-name' and (field.get('type') == 'string' or field.get('custom')):
            values[field['key']] = sentence  # The link, never a canned option.
            continue
        options = field.get('options') or []
        labels = [(option.get('label', '') + ' ' + str(option.get('value', ''))).casefold() for option in options]
        chosen = next((option['value'] for word in picks for option, label in zip(options, labels) if word in label), None)
        if chosen is not None:
            values[field['key']] = [chosen] if field.get('type') == 'multiselect' else chosen
        elif field.get('type') == 'multiselect':
            values[field['key']] = []  # Neither the wishlist nor more games.
        elif field.get('type') == 'string' or field.get('custom'):
            values[field['key']] = sentence
        else:
            raise AssertionError('Unsupported synthetic question; inspect it instead of guessing: ' + json.dumps(field, ensure_ascii=False)[:500])
    return values


def run_chat(output, language, selected, scenario, now):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    zone, country = ('Europe/London', 'GB') if language == 'en' else ('Asia/Shanghai', 'CN')
    tone = {'enable-clear':'playful', 'wishlist-display-name':'formal', 'wishlist-private':'playful'}.get(scenario, 'default')
    runtime = account(folder, language, tone, '', zone)
    fixture(runtime, 'deals', now)
    source = source_copy(folder, runtime)
    before = (runtime/'profile.md').read_text()
    bridge = TrialBridge(trial_engine.Engine(source, runtime).start())
    app = BrowserApp(runtime, bridge)
    chat = uuid.uuid4().hex
    # 七折 means paying 70%, i.e. 30% off.
    message = {('enable-clear', 'en'): "Tell me in my night briefing when games on my Steam wishlist are 50% off or more, UK store. My Steam profile is geralt. Also add Monster Hunter: World, but for that one 30% off is enough.",
               ('enable-clear', 'zh-CN'): '想在晚间简报里看到 Steam 愿望单游戏打五折或更低的提醒，用国区价格。我的 Steam 主页是 geralt。另外加上《怪物猎人：世界》，它打七折就提醒我。',
               ('enable-ambiguous', 'en'): 'Can my night briefing tell me when The Witcher 3 goes on sale?',
               ('enable-ambiguous', 'zh-CN'): '晚间简报能告诉我《巫师3》打折了吗？',
               ('wishlist-display-name', 'en'): 'Show me in my night briefing when games on my Steam wishlist are 50% off or more, UK store. My Steam name is Geralt of Rivia.',
               ('wishlist-display-name', 'zh-CN'): '想在晚间简报里看到 Steam 愿望单游戏打五折或更低的提醒，用国区价格。我的 Steam 名字是 利维亚的杰洛特。',
               ('wishlist-private', 'en'): "Show me in my night briefing when games on my Steam wishlist are 50% off or more, UK store. Here's my Steam profile: https://steamcommunity.com/id/ciri/",
               ('wishlist-private', 'zh-CN'): '想在晚间简报里看到 Steam 愿望单游戏打五折或更低的提醒，用国区价格。这是我的 Steam 主页：https://steamcommunity.com/id/ciri/'}[scenario, language]
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
        seen, followed = 0, False
        for _ in range(6):
            status = wait()
            replies = [m['text'] for m in status['messages'][seen:] if m['role'] == 'assistant' and m['text'].strip()]
            seen = len(status['messages'])
            turn = {'assistant':replies, 'forms':status['forms'], 'settings':game_settings(runtime)}
            result['turns'].append(turn)
            save(folder/'result.json', result)
            if not status['forms']:
                if scenario in ('wishlist-display-name', 'wishlist-private') and not followed and not turn['settings']['game_sales']:
                    followed = turn['followed_up'] = True  # A plain-text question gets one plain reply.
                    with context(language, selected):
                        app.chats.send(chat, {'id':uuid.uuid4().hex, 'text':FOLLOW_UPS[scenario, language]})
                    continue
                break
            turn['answered'] = answer(status['forms'][0], language, scenario)
            with context(language, selected):
                app.chats.reply(chat, 'form', status['forms'][0]['id'], {'answer':turn['answered']})
        save(folder/'messages.json', status['messages'])
        settings = game_settings(runtime)
        result['settings'] = settings
        if scenario == 'enable-clear':
            assert (settings['game_sales'], settings['game_country'], settings['game_account'], settings['game_threshold']) == \
                ('true', country, '76561198000000001', '50'), 'Clear request did not save the region, resolved account and threshold'
            assert titles(settings['game_titles']) == ['582010:30'], 'Monster Hunter: World was not saved with its own 30% off'
        elif scenario.startswith('wishlist-'):
            guidance = ' '.join(a for t in result['turns'] for a in t['assistant']) + json.dumps([t['forms'] for t in result['turns']], ensure_ascii=False)
            guidance = guidance.casefold()
            if scenario == 'wishlist-display-name':
                words = (('profile',), ('link', 'address', 'url')) if language == 'en' else (('主页', '个人资料'), ('链接', '地址', '网址'))
                expected = '76561198000000001'
            else:
                words = (('game details',), ('my profile',)) if language == 'en' else (('游戏详情',), ('我的个人资料',))
                expected = '76561198000000002'
            assert all(any(word in guidance for word in group) for group in words), 'Missing guidance: ' + repr(words)
            assert (settings['game_sales'], settings['game_country'], settings['game_account'], settings['game_threshold']) == \
                ('true', country, expected, '50'), 'Wishlist account, region or threshold not saved as resolved'
            assert not titles(settings['game_titles']), 'Games were added that the user never named'
        else:
            first = result['turns'][0]
            assert first['forms'], 'Request without a region or discount did not ask first'
            assert first['settings'] == {key:None for key in FIELDS}, 'Settings were written before the questions were answered'
            assert (settings['game_sales'], settings['game_country'], settings['game_threshold']) == ('true', country, '50'), \
                'Chosen region and discount were not saved'
            assert not settings['game_account'], 'An account was saved that the user never gave'
            assert titles(settings['game_titles']) == ['292030'], 'The base game was not the one saved'
        after = (runtime/'profile.md').read_text().splitlines()
        assert before.splitlines() == [line for line in after if not line.startswith('game_')], 'Unrelated profile lines changed'
        result['checks'] = ['Profile lines saved as requested; unrelated lines unchanged']
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
        now = datetime.now(timezone.utc)
        chosen = args.only or (*BRIEFINGS, *CHATS)
        results = [(run_briefing if name in BRIEFINGS else run_chat)(output, args.language, selected, name, now) for name in chosen]
        save(output/'matrix.json', {'model':selected, 'language':args.language, 'cases':results, 'limitations':[
            'Synthetic Steam store fixtures; no live store, cover download or public deployment.',
            'One sample per scenario and model; prose needs manual review.']})
        if not all(result.get('functional_complete') for result in results):
            raise SystemExit(1)


if __name__ == '__main__':
    main()
