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
from benchmarks import trial_engine
from benchmarks.trial_engine import TrialBridge
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


def saved_items(runtime):
    """(kind, id, revision, item) for every task, draft and approved calendar event."""
    rows, drafts = tasks(runtime)
    items = [('task', r['id'], r['revision'], r) for r in rows if r['status'] != 'cancelled' and r.get('kind') != 'reference']
    items += [('draft', d['id'], d['revision'], d) for d in drafts if d.get('state') not in ('withdrawn', 'converted')]
    store = CalendarStore(str(runtime / 'calendar.sqlite'), readonly=True)
    try:
        items += [('event', r[0], r[1], json.loads(r[2])) for r in store.con.execute(
            "SELECT id,revision,approved_json FROM events WHERE review='approved' AND approved_json IS NOT NULL")]
    finally:
        store.close()
    return [entry for entry in items if entry[3].get('status') != 'cancelled']


def worded(runtime, before=frozenset()):
    """Every item the conversation saved or changed carries page wording in both languages (reference notes excepted)."""
    from goodmorning.records.display import fingerprint
    for kind, identifier, revision, item in saved_items(runtime):
        if (kind, identifier, revision) in before:
            continue  # Trial setup, untouched by the conversation.
        display = item.get('display') or {}
        name = item.get('title') or item.get('subject')
        assert {'en', 'zh'} <= set(display), f'{kind} {name!r} saved without wording in both languages'
        assert display.get('source') == fingerprint(kind, item), f'{kind} {name!r} wording is stale'


def entries(runtime, kind):
    inbox = InboxStore(runtime)
    try:
        return [dict(zip(('raw', 'status'), row)) for row in
                inbox.db.execute('SELECT raw,status FROM entries WHERE kind=?', (kind,))]
    finally:
        inbox.close()


# Messages worded as tasks, with no request to save or to act, must be asked about
# (save it, or do it now) before anything is written; the trial answers "save".
ASK_FIRST = {'day_task', 'deadline_window', 'notice_inferred', 'save_or_do_find', 'save_or_do_email', 'save_or_do_tickets'}
SAVE_WORDS = ('save', 'to-do', 'todo', 'remember', '保存', '待办', '记下', '记')


def next_weekday(today, weekday):
    return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)


def scenarios(today):
    # Two days ahead is never today, so the named weekday has one meaning.
    workday = today + timedelta(days=2)
    weekday_en = workday.strftime('%A')
    weekday_zh = '周' + '一二三四五六日'[workday.weekday()]
    names_en = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
    names_zh = tuple('周' + d for d in '一二三四五六日')
    today_en, today_zh = names_en[today.weekday()], names_zh[today.weekday()]
    past_en, past_zh = names_en[(today.weekday() - 1) % 7], names_zh[(today.weekday() - 1) % 7]
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
        assert ('errand' in kinds or 'nudge' in kinds) and len(rows) <= 2, kinds  # "Keep an eye on it" asks the secretary to watch.
        assert len({r['source_entry_id'] for r in rows}) == 1, 'one capture'

    def said(setup):
        return ' '.join(a for turn in setup['turns'] for a in turn['assistant'])

    def errand_blocked(runtime, setup):
        import re
        # Amazon sometimes lets a read through: then the errand is saved with the price it read.
        rows = [r for r in tasks(runtime)[0] if r['status'] != 'cancelled']
        assert len(rows) <= 1, rows
        if any(turn['forms'] for turn in setup['turns']):
            assert re.search(r"couldn.t|could not|can.t|cannot|unable|没能|无法|查不到|没查到", said(setup), re.I), 'did not say it could not check'
        else:
            assert rows and rows[0]['category'] == 'errand' and re.search(r'£\s?\d', rows[0].get('extra', '')), 'saved without a price read or alternatives offered'

    def errand_readable(runtime, setup):
        import re
        row = only([r for r in tasks(runtime)[0] if r['status'] != 'cancelled'])
        assert row['category'] == 'errand', row
        assert re.search(r'12\.71', said(setup)), 'today\'s result not reported at capture'
        assert '12.71' in row.get('extra', ''), 'today\'s result not kept in extra: ' + row.get('extra', '')
        assert len(re.findall(r'[.!?](?:\s|$)|[。！？]', row['detail'])) <= 2, row['detail']

    def errand_vague(runtime, setup):
        assert setup['turns'][0]['forms'], 'saved or tried before asking what "cheap" or which shop means'

    def project_after(runtime, setup):
        rows = [r for r in tasks(runtime)[0] if r['id'] != setup['first']]
        row = only(rows)
        assert row.get('after') == setup['first'] and row['project'], row

    def routine_and_deadline(runtime, setup):
        rows = tasks(runtime)[0]
        assert any(r['repeat'] for r in rows), 'weekly check-in needs a routine'
        deadline = [r for r in rows if r['due_date'] == '2027-02-10' and not r['repeat'] and not r.get('due_soft')]
        assert deadline, 'the final date is a hard deadline on its own item'

    def monthly(runtime, setup):
        # One task, no leftover probe items (even cancelled), and a real monthly rule.
        row = only(tasks(runtime)[0])
        assert (row['repeat'] or {}).get('monthdays') == [28], row['repeat']
        day = today.replace(day=28) if today.day <= 28 else (today.replace(day=1) + timedelta(days=32)).replace(day=28)
        assert shown(runtime, 'gm', day.isoformat())[0], 'not in the morning briefing on the 28th'

    def day_task(runtime, setup):
        row = only(tasks(runtime)[0])
        assert row['planned_date'] == workday.isoformat() and not row['due_date'], row

    def deadline_window(runtime, setup):
        row = only(tasks(runtime)[0])
        assert row['due_date'] == '2026-10-28' and row['defer_until'] == '2026-10-23', row
        assert not row['planned_date'], row

    def shown(runtime, kind, day):
        from goodmorning.records import routing
        view = routing.prepare(runtime, day, kind, limit=200)
        return view['tasks']['items'], view['schedule']['items']

    def notice_stated(runtime, setup):
        # Heard about from 5 mornings before 17 December, not 6.
        assert any(shown(runtime, 'gm', '2026-12-12')), 'nothing 5 mornings before the birthday'
        assert not any(shown(runtime, 'gm', '2026-12-11')), 'shown 6 mornings before'

    def notice_on_day(runtime, setup):
        rows = [r for r in tasks(runtime)[0] if r['status'] != 'cancelled']
        row = only(rows)
        assert (row['repeat'] or {}).get('weekdays') == [4], row
        thursday, friday = (next_weekday(today, 3) + timedelta(weeks=1)).isoformat(), (next_weekday(today, 4) + timedelta(weeks=1)).isoformat()
        assert all(r.get('preview') for r in shown(runtime, 'gm', thursday)[0]), 'tickable before Friday'
        assert shown(runtime, 'gn', thursday)[0], 'no notice the evening before'
        assert [r for r in shown(runtime, 'gm', friday)[0] if not r.get('preview')], 'not actionable on Friday'

    def weekday_today(runtime, setup):
        row = only(tasks(runtime)[0])
        assert row['planned_date'] == today.isoformat(), row

    def weekday_past(runtime, setup):
        row = only(tasks(runtime)[0])
        assert row['due_date'] == (today + timedelta(days=6)).isoformat(), row
        assert not any(turn['forms'] for turn in setup['turns']), 'asked which day a weekday name meant'

    def notice_inferred(runtime, setup):
        tasks_, _ = shown(runtime, 'gm', '2026-12-09')
        assert tasks_, 'the booking task for 12 December is not visible three mornings before'

    def plain_action(runtime, setup):
        row = only([r for r in tasks(runtime)[0] if r['status'] != 'cancelled'])
        assert row['category'] not in ('errand', 'nudge', 'reference'), row

    def said(setup, *words):
        text = ' '.join(' '.join(turn['assistant']) for turn in setup['turns']).lower()
        assert any(word in text for word in words), f'reply never says what it was saved as ({words})'

    def explicit_save(runtime, setup):
        plain_action(runtime, setup)
        assert not entries(runtime, 'idea'), 'a reminder is not an idea'
        said(setup, 'to-do', 'todo', '待办')

    def idea_capture(runtime, setup):
        assert not [r for r in tasks(runtime)[0] if r['status'] != 'cancelled'], 'an idea is not a task'
        assert len(entries(runtime, 'idea')) == 1, 'expected one saved idea'
        said(setup, 'idea', '灵感', '想法')

    def do_now(runtime, setup):
        assert not setup['turns'][0]['forms'], 'a direct question needs no save-or-do question'
        assert not tasks(runtime)[0] and not entries(runtime, 'idea'), 'answering a question saves nothing'

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

    def with_import(runtime):
        calendar = CalendarStore(str(runtime / 'calendar.sqlite'))
        try:
            day = next_weekday(today, 2)
            start = datetime.combine(day, datetime.min.time().replace(hour=15), ZoneInfo(ZONE))
            calendar.import_events('outlook', [{'external_id': 'review-1', 'subject': 'FW: Quarterly budget review - updated invitation',
                'start': start.isoformat(), 'end': (start + timedelta(hours=1)).isoformat(), 'timezone': ZONE,
                'location': 'Room 4.12', 'notes': 'Please bring the Q3 spending sheet.\nJoin Microsoft Teams Meeting\nMeeting ID: 123 456 789'}])
            return {'start': calendar.con.execute("SELECT json_extract(approved_json,'$.start') FROM events").fetchone()[0]}
        finally:
            calendar.close()

    def synced(runtime):
        store = CalendarStore(str(runtime / 'calendar.sqlite'), readonly=True)
        try:
            return [(r[0], json.loads(r[1]), r[2]) for r in store.con.execute("SELECT source,approved_json,revision FROM events")]
        finally:
            store.close()

    def already_scheduled(runtime, setup):
        rows = synced(runtime)
        assert len(rows) == 1, 'the synced invite was added again'
        assert rows[0][1]['start'] == setup['start'] and rows[0][1]['status'] == 'confirmed', 'the synced invite moved or was cancelled'

    def tidied(runtime, setup):
        already_scheduled(runtime, setup)
        source, event, revision = synced(runtime)[0]
        assert revision > 1 and event.get('display'), 'the synced invite was not given page wording'

    def feed_refused(runtime, setup):
        config = runtime / 'calendar.config.json'
        assert not (config.exists() and json.loads(config.read_text()).get('ics_url')), 'a failed calendar link was saved'
        assert not synced(runtime), 'events were saved from a failed sync'

    def with_worded(runtime):
        inbox = InboxStore(runtime, write=True)
        both = lambda en, zh: {'en': en, 'zh': zh}
        try:
            receipt = inbox.mutate('add', {'kind': 'todo', 'raw': 'Return the library books', 'task': {
                'title': 'Return the library books', 'planned_date': next_weekday(today, 2).isoformat(), 'display': both(
                    {'morning': {'title': 'Return the three library books', 'detail': ''}, 'schedule': 'Library books'},
                    {'morning': {'title': '把三本书还到图书馆', 'detail': ''}, 'schedule': '还书'})}},
                'trial-setup', 'setup-worded', datetime.now(timezone.utc).isoformat())
        finally:
            inbox.close()
        return {'task': receipt['task_id']}

    def reworded(runtime, setup):
        row = next(r for r in tasks(runtime)[0] if r['id'] == setup['task'])
        display = row['display']
        assert 'Library run' in display['en']['morning']['title'] or '图书馆跑一趟' in display['zh']['morning']['title'], display
        assert display['en']['morning']['title'] != 'Return the three library books' and display['zh']['morning']['title'] != '把三本书还到图书馆', display
        assert (display['en']['schedule'], display['zh']['schedule']) == ('Library books', '还书'), 'schedule label changed'

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
        ('until_done', 'secretary', None,
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
        ('reword', 'secretary', with_worded,
         'In my morning briefing, show the library books task as "Library run: 3 books" instead.',
         '早报里那条还书的待办，改成显示"图书馆跑一趟：3 本书"。', reworded),
        ('calendar_synced', 'secretary', with_import,
         'Please review the calendar invite that just synced from Outlook and add it if it looks fine.',
         '帮我看一下刚从 Outlook 同步过来的日历邀请，没问题就加上。', already_scheduled),
        ('calendar_tidy', 'secretary', with_import,
         'The budget review that synced from Outlook has a messy forwarded title and Teams joining text. Tidy it up for my briefings.',
         '从 Outlook 同步过来的预算评审，标题带着转发前缀，还有一堆 Teams 入会信息，帮我整理一下，让简报里好看点。', tidied),
        ('calendar_feed_fail', 'secretary', None,
         'Here is my Outlook calendar link, please keep my schedule in sync with it: https://calendar.invalid/owa/calendar.ics',
         '这是我的 Outlook 日历链接，帮我把日程和它保持同步：https://calendar.invalid/owa/calendar.ics', feed_refused),
        ('errand_blocked', 'secretary', None,
         'Check the black SIHOO M18 chair price on Amazon UK for me each morning, and only tell me when it is below £120.',
         '每天早上帮我查一下亚马逊英国上黑色 SIHOO M18 椅子的价格，低于120英镑时再告诉我。', errand_blocked),
        ('errand_readable', 'secretary', None,
         'Every morning, look up the UK National Living Wage on GOV.UK and tell me the hourly rate for people aged 21 and over.',
         '每天早上帮我在 GOV.UK 查一下英国国家生活工资，告诉我21岁及以上的时薪。', errand_readable),
        ('errand_vague', 'secretary', None,
         'Check the SIHOO M18 chair price every day and tell me when it is cheap.',
         '每天帮我查一下 SIHOO M18 椅子的价格，便宜的时候告诉我。', errand_vague),
        ('project_after', 'secretary', with_first_step,
         'Add an HL60 rescue step: once the plasmid transformation and plating is done, take the plates out and send them for sequencing.',
         '给 HL60 rescue 加一步：质粒转化和铺板完成后，取出菌板送测序。', project_after),
        ('routine_and_deadline', 'secretary', None,
         'Every week I need to follow up on visiting the new theatres and negotiating terms. The whole thing must be finished by 10 February 2027.',
         '每周跟进一次新剧场的考察和商务谈判，整件事必须在2027年2月10日前完成。', routine_and_deadline),
        ('monthly', 'secretary', None,
         'Remind me on the 28th of every month to check my Hyperoptic, gas and water bills.',
         '每个月28号提醒我查一下 Hyperoptic 宽带、燃气和水费账单。', monthly),
        ('day_task', 'secretary', None, f'Pass the HL60 cells on {weekday_en}.', f'{weekday_zh}传代HL60细胞。', day_task),
        # A bare weekday name is its next occurrence, today included, never a past day.
        ('weekday_today', 'secretary', None, f'Water the lab plants on {today_en}.', f'{today_zh}给实验室的植物浇水。', weekday_today),
        ('weekday_past', 'secretary', None, f'Send the Atlas report by {past_en}.', f'{past_zh}之前把 Atlas 报告发出去。', weekday_past),
        ('deadline_window', 'secretary', None, 'Buy the hand warmer at Bailian ZX sometime between 23 and 28 October.',
         '10月23日到28日之间去百联ZX买暖娃。', deadline_window),
        ('notice_stated', 'secretary', None,
         "Mum's birthday is on 17 December every year. Tell me 5 days before in my morning briefings so I can get a gift.",
         '妈妈每年12月17日生日。提前5天在早报里提醒我，好准备礼物。', notice_stated),
        ('notice_on_day', 'secretary', None,
         'Every Friday I claim my GTA salary. It can only be submitted on the Friday itself, so tell me the evening before as well.',
         '每周五我要申领助教工资，只能在周五当天提交，前一天晚上也提醒我一下。', notice_on_day),
        ('notice_inferred', 'secretary', None, 'Book a restaurant for our anniversary dinner on 12 December.',
         '给12月12日的纪念日晚餐订餐厅。', notice_inferred),
        # Worded as jobs, with no request to save or act: asked first, then saved.
        ('save_or_do_find', 'secretary', None, 'Find a plumber to fix the leaking kitchen tap.',
         '找个水管工来修厨房漏水的水龙头。', plain_action),
        ('save_or_do_email', 'secretary', None, 'Email Sam the signed lease and ask when he can collect the keys.',
         '给 Sam 发邮件，附上签好的租约，问他什么时候能来拿钥匙。', plain_action),
        ('save_or_do_tickets', 'secretary', None, 'Get two tickets for the Hockney exhibition at the Tate.',
         '买两张泰特美术馆霍克尼展览的门票。', plain_action),
        ('explicit_save', 'secretary', None, 'Remind me to call the dentist on Friday.',
         '提醒我周五给牙医打电话。', explicit_save),
        ('idea_capture', 'secretary', None, 'I had an idea: the Schedule page could show a small weekly mood line.',
         '我有个想法：日程页面可以显示一条每周心情小曲线。', idea_capture),
        ('do_now', 'secretary', None, "What's due this week?", '这周有什么事到期？', do_now),
    ]


def run_scenario(output, lang, selected, today, scenario, rounds, source):
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
        'calendar_sync', 'publisher_images', 'news_acknowledgement')}))
    initialize(runtime)
    CalendarStore(str(runtime / 'calendar.sqlite')).close()
    facts = setup(runtime) if setup else {}
    before = frozenset(entry[:3] for entry in saved_items(runtime))
    message = chinese if lang == 'zh-CN' else english
    result = {'scenario': name, 'language': lang, 'model': selected, 'mode': mode, 'message': message,
              'turns': [], 'complete': False, 'passed': None, 'dispatched': True}
    save(target, result)
    bridge = TrialBridge(trial_engine.Engine(source, runtime).start())
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
            turn['saved_before_answer'] = len(saved_items(runtime)) - len(before) + len(entries(runtime, 'idea'))
            values = {}
            for field in form['fields']:
                options = field.get('options') or []
                if field.get('format') == 'date':
                    values[field['key']] = today.isoformat()
                elif options:
                    labels = [option['value'] if isinstance(option, dict) else option for option in options]
                    preferred = [label for label in labels if any(word in str(label).lower() for word in SAVE_WORDS)]
                    first = preferred[0] if name in ASK_FIRST and len(result['turns']) == 1 and preferred else labels[0]
                    values[field['key']] = [first] if field.get('type') == 'multiselect' else first
                elif field.get('type') == 'boolean':
                    values[field['key']] = True
                else:
                    values[field['key']] = 'Yes, please go ahead as you proposed.' if lang == 'en' else '可以，就按你说的办。'
            turn['answered'] = values
            save(target, result)
            with context(lang, selected):
                app.chats.reply(chat, 'form', form['id'], {'answer': values})
        if name in ASK_FIRST:
            first = result['turns'][0]
            assert first['forms'], 'a message worded as a task needs a save-or-do question first'
            assert first.get('saved_before_answer') == 0, 'something was written before the save-or-do answer'
        check(runtime, {**facts, 'turns': result['turns']})
        worded(runtime, before)
        result['passed'] = True
    except AssertionError as error:
        result['passed'] = False
        result['failure'] = str(error)
    except Exception as error:
        result['passed'] = False
        result['failure'] = type(error).__name__ + ': ' + str(error)
    bridge.close()
    result['records'] = {'tasks': [{k: v for k, v in t.items() if k not in ('detail',)} for t in tasks(runtime)[0]],
                         'drafts': tasks(runtime)[1], 'calendar': calendar_events(runtime)}
    result['complete'] = True
    save(target, result)
    print(f"{lang} {name}: {'PASS' if result['passed'] else 'FAIL ' + result.get('failure', '')}", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    trial_engine.add_arguments(parser)
    parser.add_argument('--language', required=True, choices=('en', 'zh-CN'))
    parser.add_argument('--model', choices=tuple(models.MODELS), help='Defaults to the production model for the language')
    parser.add_argument('--only', nargs='*', help='Scenario names to run')
    parser.add_argument('--parallel', type=int, default=4)
    parser.add_argument('--rounds', type=int, default=4, help='Native question rounds answered per scenario')
    args = parser.parse_args()
    output = trial_engine.private_output(parser, args.output)
    output.mkdir(parents=True, exist_ok=True)
    source = output / 'source'
    if not source.exists():
        trial_engine.copy_release(source, args.source.resolve())
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
            results = list(pool.map(lambda s: run_scenario(output, args.language, selected, today, s, args.rounds, source), chosen))
    summary = {'language': args.language, 'model': selected, 'source': str(args.source.resolve()), 'passed': sum(bool(r.get('passed')) for r in results),
               'total': len(results), 'failed': {r['scenario']: r.get('failure') for r in results if not r.get('passed')}}
    save(output / f'summary-{args.language}.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    sys.exit(main())
