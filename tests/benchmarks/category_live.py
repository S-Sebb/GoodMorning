"""Paid live trials for item categories. Synthetic accounts; real website models.

Each scenario is a real usage pattern: a fresh account, one browser chat, the
user's message, generic answers to any native questions, then the saved records
are checked directly. Saying "saved" proves nothing; only stored fields count.
Transcripts are kept for manual tone and wording review.
"""
import argparse
import fcntl
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
from benchmarks.native_bridge import NativeBridge
from goodmorning.records.inbox_store import InboxStore, initialize
from goodmorning.records.task_store import TaskStore
from goodmorning.records.custom_store import CustomStore
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import language, models

ZONE = 'Europe/London'


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


@contextmanager
def context(lang, selected):
    a, b = language.CURRENT.set(lang), models.CURRENT.set(selected)
    try:
        yield
    finally:
        language.CURRENT.reset(a)
        models.CURRENT.reset(b)


def tasks(runtime):
    inbox = InboxStore(runtime)
    try:
        store = TaskStore(inbox)
        return list(store.all()), list(store.all(draft=True))
    finally:
        inbox.close()


def calendar_events(runtime):
    store = CalendarStore(str(runtime / 'calendar.sqlite'), readonly=True)
    try:
        return [json.loads(r[0]) for r in store.con.execute(
            "SELECT approved_json FROM events WHERE source='custom' AND approved_json IS NOT NULL")]
    finally:
        store.close()


def next_weekday(today, weekday):
    return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)


def scenarios(today):
    saturday = next_weekday(today, 5)
    nov1 = date(today.year, 11, 1).isoformat()

    def only(rows, **checks):
        assert len(rows) == 1, f'expected one task, got {len(rows)}'
        return rows[0]

    def nudge_habit(runtime, setup):
        rows, _ = tasks(runtime)
        row = only([r for r in rows if r['status'] != 'cancelled'])
        assert row['category'] == 'nudge', row
        assert (row.get('when') or {}).get('custom_rule_id') == setup['rule'], row.get('when')

    def reference(runtime, setup):
        rows, _ = tasks(runtime)
        row = only(rows)
        assert row['category'] == 'reference' and row.get('trigger'), row
        assert not (row['planned_date'] or row['due_date'] or row['repeat'] or row['defer_until']), row
        assert 'Impact' in row['detail'] or 'Impact' in row['title'], 'brand detail must be kept'

    def until_done(runtime, setup):
        row = only(tasks(runtime)[0])
        assert row.get('follow_up') == 'until-done' and not row['repeat'], row

    def window_until_done(runtime, setup):
        row = only(tasks(runtime)[0])
        assert row.get('follow_up') == 'until-done' and not row['repeat'], row
        assert nov1 in (row['defer_until'], row['planned_date']), row

    def birthdays(runtime, setup):
        events = calendar_events(runtime)
        assert len(events) == 2, f'expected two birthdays, got {len(events)}'
        assert all(e['all_day'] and (e.get('repeat') or {}).get('yearly') for e in events), events
        assert not tasks(runtime)[0], 'birthdays are occasions, not tasks'

    def tbc_series(runtime, setup):
        rows, drafts = tasks(runtime)
        assert not rows, 'a class is an appointment, not a task'
        draft = only(drafts)
        rule = draft.get('repeat') or {}
        assert draft['confirmed_day'] and rule.get('weekdays') == [5], draft
        assert draft['date'] == '2026-10-31' and rule.get('until') == '2026-12-26', draft

    def prep_linked(runtime, setup):
        row = only(tasks(runtime)[0])
        rule = row['repeat'] or {}
        assert rule.get('event_subject', '').casefold() == 'spatial transcriptomics discussion', rule
        assert rule.get('offset_days') == -1, rule

    def split(runtime, setup):
        rows, _ = tasks(runtime)
        kinds = sorted(r['category'] for r in rows)
        assert 'nudge' in kinds and len(rows) == 2, kinds
        assert len({r['source_entry_id'] for r in rows}) == 1, 'one capture, two siblings'

    def project_after(runtime, setup):
        rows = [r for r in tasks(runtime)[0] if r['id'] != setup['first']]
        row = only(rows)
        assert row.get('after') == setup['first'] and row['project'], row

    def routine_and_deadline(runtime, setup):
        rows = tasks(runtime)[0]
        assert any(r['repeat'] for r in rows), 'weekly check-in needs a routine'
        deadline = [r for r in rows if r['due_date'] == '2027-02-10' and not r['repeat'] and not r.get('due_soft')]
        assert deadline, 'the final date is a hard deadline on its own item'

    def day_task(runtime, setup):
        row = only(tasks(runtime)[0])
        assert row['planned_date'] == saturday.isoformat() and not row['due_date'], row

    def deadline_window(runtime, setup):
        row = only(tasks(runtime)[0])
        assert row['due_date'] == '2026-10-28' and row['defer_until'] == '2026-10-23', row
        assert not row['planned_date'], row

    def with_habit(runtime):
        store = CustomStore(runtime, write=True)
        try:
            rule = store.add({'title': 'Strength training', 'timezone': ZONE, 'policy': {
                'base': 'interval_days', 'interval_days': 2, 'start': today.isoformat(), 'anchor': 'fixed',
                'miss_policy': 'chase', 'nightly': 'due_only'}}, 'trial-setup', 'setup-habit', datetime.now(timezone.utc).isoformat())
        finally:
            store.close()
        return {'rule': rule['id']}

    def with_meetings(runtime):
        calendar = CalendarStore(str(runtime / 'calendar.sqlite'))
        try:
            for week in range(4):
                day = next_weekday(today, 3) + timedelta(weeks=week)
                start = datetime.combine(day, datetime.min.time().replace(hour=14), ZoneInfo(ZONE))
                calendar.add({'subject': 'Spatial Transcriptomics Discussion', 'start': start.isoformat(),
                              'end': (start + timedelta(hours=1)).isoformat(), 'timezone': ZONE, 'location': 'Teams'})
        finally:
            calendar.close()
        return {}

    def with_first_step(runtime):
        inbox = InboxStore(runtime, write=True)
        try:
            receipt = inbox.mutate('add', {'kind': 'todo', 'raw': 'Transform the plasmid and plate the bacteria',
                'task': {'title': 'Transform the plasmid and plate the bacteria', 'project': 'HL60 rescue'}},
                'trial-setup', 'setup-step', datetime.now(timezone.utc).isoformat())
        finally:
            inbox.close()
        return {'first': receipt['task_id']}

    return [
        ('nudge_habit', 'secretary', with_habit,
         'On my strength-training days, remind me in the morning to bring my gym clothes.',
         '在我力量训练的日子，早报里提醒我带运动衣服。', nudge_habit),
        ('reference', 'secretary', None,
         'When my protein powder runs out, remind me to rebuy it: Myprotein Impact Whey, vanilla, one scoop after training.',
         '蛋白粉吃完的时候提醒我回购：Myprotein Impact Whey 香草味，训练后一勺。', reference),
        ('until_done', 'todo', None,
         'Remind me every day after I wake up to buy the ointment, until I have bought it.',
         '每天醒来后提醒我买软膏，直到买到为止。', until_done),
        ('window_until_done', 'secretary', None,
         'From November 1, remind me every day to settle the Beijing trip dates with Ruoxi until it is decided.',
         '从11月1日起每天提醒我和若熙确定北京行程，直到定下来为止。', window_until_done),
        ('birthdays', 'secretary', None,
         'Please add these birthdays to my calendar so I hear about them every year: 6 January Yoshi, 24 January Mum.',
         '把这些生日加到日历里，每年都提醒我：1月6日 Yoshi 生日，1月24日 妈妈生日。', birthdays),
        ('tbc_series', 'secretary', None,
         'I have archery class every Saturday evening from 31 October to 26 December at Hongqiao Sports Park. The exact time is not confirmed yet.',
         '10月31日到12月26日每周六晚上在虹桥体育公园上弓道课，具体时间还没定。', tbc_series),
        ('prep_linked', 'secretary', with_meetings,
         'Whenever I have the Spatial Transcriptomics Discussion, I need to prepare a project-update presentation the day before.',
         '每次有 Spatial Transcriptomics Discussion 会议，我都要在前一天准备项目进展汇报。', prep_linked),
        ('split', 'secretary', None,
         'Keep an eye on the SIHOO M18 chair price in my morning briefings, and I will buy it once it drops below £130.',
         '在早报里帮我留意 SIHOO M18 椅子的价格，低于130英镑我就买。', split),
        ('project_after', 'secretary', with_first_step,
         'Add an HL60 rescue step: once the plasmid transformation and plating is done, take the plates out and send them for sequencing.',
         '给 HL60 rescue 加一步：质粒转化和铺板完成后，取出菌板送测序。', project_after),
        ('routine_and_deadline', 'secretary', None,
         'Every week I need to follow up on visiting the new theatres and negotiating terms. The whole thing must be finished by 10 February 2027.',
         '每周跟进一次新剧场的考察和商务谈判，整件事必须在2027年2月10日前完成。', routine_and_deadline),
        ('day_task', 'todo', None, f'Pass the HL60 cells on Saturday.', '周六传代HL60细胞。', day_task),
        ('deadline_window', 'todo', None, 'Buy the hand warmer at Bailian ZX sometime between 23 and 28 October.',
         '10月23日到28日之间去百联ZX买暖娃。', deadline_window),
    ]


def run_scenario(output, lang, selected, today, scenario, rounds, source=ROOT):
    name, mode, setup, english, chinese, check = scenario
    folder = output / f'{lang}-{name}'
    target = folder / 'result.json'
    if target.exists():
        previous = json.loads(target.read_text())
        if previous.get('complete'):
            return previous
        if previous.get('dispatched'):
            return {**previous, 'complete': False, 'note': 'preserved in-flight attempt; inspect, never replay'}
    runtime = folder / 'account'
    runtime.mkdir(parents=True, mode=0o700, exist_ok=True)
    (runtime / 'profile.md').write_text('city: London, GB\ntimezone: Europe/London\nnews_country: GB\n'
                                        'secretary_language: English\nsecretary_name: Nora\ncalendar_source: custom\n')
    (runtime / 'browser-policy.json').write_text(json.dumps({k: False for k in (
        'live_project_access', 'calendar_sync', 'publisher_images', 'news_acknowledgement')}))
    initialize(runtime)
    CalendarStore(str(runtime / 'calendar.sqlite')).close()
    facts = setup(runtime) if setup else {}
    message = chinese if lang == 'zh-CN' else english
    result = {'scenario': name, 'language': lang, 'model': selected, 'mode': mode, 'message': message,
              'turns': [], 'complete': False, 'passed': None, 'dispatched': True}
    save(target, result)
    bridge = NativeBridge(source, runtime)
    app = BrowserApp(runtime, bridge)
    chat = uuid.uuid4().hex

    def wait():
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            with context(lang, selected):
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
        with context(lang, selected):
            app.chats.start({'id': chat, 'mode': mode, 'text': message})
        seen = 0
        for _ in range(rounds):
            status = wait()
            replies = [m['text'] for m in status['messages'][seen:] if m['role'] == 'assistant' and m['text'].strip()]
            seen = len(status['messages'])
            turn = {'assistant': replies, 'forms': status['forms']}
            result['turns'].append(turn)
            save(target, result)
            if not status['forms']:
                break
            form = status['forms'][0]
            values = {}
            for field in form['fields']:
                options = field.get('options') or []
                if field.get('format') == 'date':
                    values[field['key']] = today.isoformat()
                elif options:
                    first = options[0]['value'] if isinstance(options[0], dict) else options[0]
                    values[field['key']] = [first] if field.get('type') == 'multiselect' else first
                elif field.get('type') == 'boolean':
                    values[field['key']] = True
                else:
                    values[field['key']] = 'Yes, please go ahead as you proposed.' if lang == 'en' else '可以，就按你说的办。'
            turn['answered'] = values
            save(target, result)
            with context(lang, selected):
                app.chats.reply(chat, 'form', form['id'], {'answer': values})
        check(runtime, facts)
        result['passed'] = True
    except AssertionError as error:
        result['passed'] = False
        result['failure'] = str(error)
    except Exception as error:
        result['passed'] = False
        result['failure'] = type(error).__name__ + ': ' + str(error)
    result['records'] = {'tasks': [{k: v for k, v in t.items() if k not in ('detail',)} for t in tasks(runtime)[0]],
                         'drafts': tasks(runtime)[1], 'calendar': calendar_events(runtime)}
    result['complete'] = True
    save(target, result)
    print(f"{lang} {name}: {'PASS' if result['passed'] else 'FAIL ' + result.get('failure', '')}", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--language', required=True, choices=('en', 'zh-CN'))
    parser.add_argument('--model', choices=tuple(models.MODELS), help='Defaults to the production model for the language')
    parser.add_argument('--only', nargs='*', help='Scenario names to run')
    parser.add_argument('--parallel', type=int, default=4)
    parser.add_argument('--rounds', type=int, default=4, help='Native question rounds answered per scenario')
    parser.add_argument('--source', type=Path, default=ROOT, help='Release the agent reads, e.g. a main checkout for a baseline')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    selected = args.model or models.for_language(args.language)
    today = datetime.now(ZoneInfo(ZONE)).date()
    chosen = [s for s in scenarios(today) if not args.only or s[0] in args.only]
    lock_path = output.parent / ('.' + output.name + '.lock')
    with lock_path.open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('This output already has an active runner')
        with ThreadPoolExecutor(args.parallel) as pool:
            results = list(pool.map(lambda s: run_scenario(output, args.language, selected, today, s, args.rounds, args.source.resolve()), chosen))
    summary = {'language': args.language, 'model': selected, 'source': str(args.source.resolve()), 'passed': sum(bool(r.get('passed')) for r in results),
               'total': len(results), 'failed': {r['scenario']: r.get('failure') for r in results if not r.get('passed')}}
    save(output / f'summary-{args.language}.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    sys.exit(main())
