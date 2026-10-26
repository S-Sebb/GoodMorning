"""Celebrations: the user's birthday, GoodMorning anniversaries and finished-task milestones.

Code finds each celebration from saved records when a briefing job is prepared; the briefing's
first section shows them on one card, worded by code, with a short wish from the secretary.
They show in the morning briefing, or in the evening one when no morning briefing was saved
that day. A milestone shows once: the day it first showed is kept in celebrations.json, so a
regenerated briefing that day shows it again and later briefings never repeat it.
"""
import calendar
from datetime import date as Date
import json
from pathlib import Path
import re
import sqlite3

from goodmorning.runtime_files import atomic_text, profile_fields, runtime_lock

HEADLINES = {'birthday': 'Happy birthday! 🎂', 'days': '100 days of GoodMorning! 🌱',
             'years': 'Happy GoodMorning anniversary! 🎉', 'tasks': '{count} tasks done! ✨'}
LINES = {'days': 'Your very first briefing was on {date}, 100 days ago today.',
         'year': 'Your very first briefing was on {date}, one year ago today.',
         'years': 'Your very first briefing was on {date}, {count} years ago today.',
         'tasks': 'You’ve ticked off {count} tasks in GoodMorning so far.'}


def birthday(text):
    """A profile birthday as "MM-DD", or "" for none; anything else raises ValueError."""
    text = (text or '').strip()
    if not text:
        return ''
    try:
        if not re.fullmatch(r'\d{2}-\d{2}', text):
            raise ValueError
        Date.fromisoformat('2000-' + text)  # A leap year, so 02-29 is a real birthday.
    except ValueError:
        raise ValueError('birthday must be a real month and day written MM-DD, such as 02-13') from None
    return text


def yearly(day, month_day):
    """Whether a yearly MM-DD falls on this day; 29 February is kept on 28 February in other years."""
    if month_day == '02-29' and not calendar.isleap(day.year):
        month_day = '02-28'
    return f'{day:%m-%d}' == month_day


def first_briefing(runtime):
    """The day of the earliest saved briefing, or None before the first one."""
    days = [path.name[:10] for path in (Path(runtime) / 'daily').glob('????-??-??.g[mn].*')
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}\.g[mn]\.(json|md)', path.name)]
    return min(days, default=None)


def tasks_done(runtime, zone):
    """Every task the user confirmed done, counted as the weekly letter counts them."""
    from zoneinfo import ZoneInfo
    from .inbox_store import InboxStore
    from .letters import finished
    if not (Path(runtime) / 'inbox.sqlite').exists():
        return 0
    inbox = InboxStore(runtime)
    try:
        inbox.db.execute('BEGIN')
        groups = finished(inbox, ZoneInfo(zone), '0001-01-01', '9999-12-31', 'en')
    finally:
        inbox.close()
    return sum(count for _, items in groups for _, count in items)


def milestones(total):
    """Finished-task counts worth celebrating, up to total: 100, 250, 500, 1,000, then every 1,000."""
    return [count for count in (100, 250, 500) if count <= total] + list(range(1000, total + 1, 1000))


def state_path(runtime):
    path = Path(runtime) / 'celebrations.json'
    if path.is_symlink():
        raise ValueError('Unsafe celebrations path')
    return path


def shown(runtime):
    """Milestones already celebrated: {"tasks": {"100": "YYYY-MM-DD"}}, the day each first showed."""
    path = state_path(runtime)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'tasks': {}}


def found(runtime, day, kind):
    """Today's celebrations, in card order: [["birthday"]], ["days",100,first], ["years",n,first], ["tasks",count,total]."""
    from goodmorning.briefings.briefing_document import source_path
    if kind == 'gn' and source_path(runtime, day, 'gm').exists():
        return []  # The morning briefing already celebrated today.
    fields, today, result = profile_fields(runtime), Date.fromisoformat(day), []
    try:
        if birthday(fields.get('birthday')) and yearly(today, fields['birthday']):
            result.append(['birthday'])
    except ValueError:
        pass  # An unreadable birthday shows no card; the secretary fixes it when asked.
    first = first_briefing(runtime)
    if first and first < day:
        start = Date.fromisoformat(first)
        if (today - start).days == 100:
            result.append(['days', 100, first])
        if today.year > start.year and yearly(today, first[5:]):
            result.append(['years', today.year - start.year, first])
    try:
        total = tasks_done(runtime, fields['timezone'])
        earlier = shown(runtime)['tasks']
    except (ValueError, OSError, KeyError, sqlite3.Error):
        return result  # Unreadable records skip the milestone, never invent one.
    due = [count for count in milestones(total) if earlier.get(str(count), day) == day]
    if due:
        result.append(['tasks', due[-1], total])
    return result


def remember(runtime, day, items):
    """Keep the day a milestone first showed; smaller milestones passed with it are never shown later."""
    totals = [item[2] for item in items if item[0] == 'tasks']
    if not totals:
        return
    with runtime_lock(runtime, '.celebrations.lock'):
        state = shown(runtime)
        earlier = state.setdefault('tasks', {})
        missing = {str(count): day for count in milestones(totals[0]) if str(count) not in earlier}
        if missing:
            earlier.update(missing)
            atomic_text(state_path(runtime), json.dumps(state, sort_keys=True, separators=(',', ':')) + '\n')


def long_date(day, lang):
    value = Date.fromisoformat(day)
    return f'{value.year}年{value.month}月{value.day}日' if lang == 'zh-CN' else f'{value:%B} {value.day}, {value.year}'


def words(item, say, lang):
    """The card's headline and factual line for one celebration; `say` translates them."""
    kind = item[0]
    if kind == 'birthday':
        return say(HEADLINES[kind]), ''
    if kind == 'days':
        return say(HEADLINES[kind]), say(LINES['days'], date=long_date(item[2], lang))
    if kind == 'years':
        line = LINES['year'] if item[1] == 1 else LINES['years']
        return say(HEADLINES[kind]), say(line, date=long_date(item[2], lang), count=item[1])
    return say(HEADLINES[kind], count=f'{item[1]:,}'), say(LINES['tasks'], count=f'{item[2]:,}')
