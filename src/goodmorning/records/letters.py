"""Weekly letters: a Monday–Sunday look back, written with Sunday's evening briefing and kept as a memory book.

Code collects every list from saved records: confirmed completions, habit completions, captured
ideas and next week's saved plans. The secretary adds only an opening and a sign-off. A saved
letter is a memory: it never changes, even when the records it came from change later.
"""
import argparse
from datetime import date as Date, datetime, time, timedelta
import json
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

from goodmorning.runtime_files import atomic_text, profile_fields, runtime_lock, secretary_path

MAX_BYTES = 200_000
LIMITS = {'opening': 600, 'signoff': 200}


def week_of(day):
    """The Monday that starts the week holding this ISO date."""
    value = Date.fromisoformat(day)
    return (value - timedelta(days=value.weekday())).isoformat()


def directory(runtime):
    folder = Path(runtime) / 'letters'
    if folder.is_symlink():
        raise ValueError('Unsafe letters path')
    return folder


def letter_path(runtime, week):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', week) or week_of(week) != week:
        raise ValueError('A letter week starts on a Monday')
    path = directory(runtime) / (week + '.json')
    if path.is_symlink():
        raise ValueError('Unsafe letter path')
    return path


def enabled(runtime):
    return profile_fields(runtime).get('weekly_letter', '').casefold() != 'false'


def finished(inbox, zone, start, end, lang):
    """Confirmed work in the week, grouped by project in the order it was finished; repeats are counted."""
    from .display import wording
    from .task_store import TaskStore, UNCHECKED
    store = TaskStore(inbox)
    tasks = {task['id']: task for task in store.all() if task.get('kind') not in UNCHECKED}
    done = {}  # task id -> times finished this week, in first-finished order
    for task_id, in inbox.db.execute("SELECT task_id FROM task_occurrences WHERE status='done' AND date BETWEEN ? AND ? "
                                     "ORDER BY date,rowid", (start, end)):
        if task_id in tasks:
            done[task_id] = done.get(task_id, 0) + 1
    # A one-off finished without a day is dated by the confirmation itself.
    dated = {row[0] for row in inbox.db.execute("SELECT DISTINCT task_id FROM task_occurrences WHERE status='done'")}
    for task_id, at in inbox.db.execute("SELECT item_id,at FROM task_events WHERE action='update' "
                                        "AND json_extract(snapshot,'$.input.status')='done' ORDER BY seq"):
        task = tasks.get(task_id)
        if (task and task['status'] == 'done' and not task['repeat'] and task_id not in dated and task_id not in done
                and start <= datetime.fromisoformat(at).astimezone(zone).date().isoformat() <= end):
            done[task_id] = 1
    groups = {}
    for task_id, count in done.items():
        task = tasks[task_id]
        groups.setdefault(task['project'], []).append([wording(task, 'task', 'schedule', lang) or task['title'], count])
    return [[project, items] for project, items in groups.items() if project] + ([['', groups['']]] if '' in groups else [])


def habits(runtime, start, end):
    """Habits done this week: [title, times this week, weeks in a row with at least one completion]."""
    from .custom_store import CustomStore
    try:
        custom = CustomStore(runtime, write=False)
    except ValueError:
        return []  # No habits saved yet.
    try:
        result = []
        for rule in custom.all():
            days = [row[0] for row in custom.db.execute("SELECT date FROM custom_completions WHERE rule_id=? AND status='done'", (rule['id'],))]
            times = sum(start <= day <= end for day in days)
            if not times:
                continue  # A quiet week is left out, never shown as a break.
            weeks, run, cursor = {week_of(day) for day in days}, 0, Date.fromisoformat(start)
            while cursor.isoformat() in weeks:
                run, cursor = run + 1, cursor - timedelta(weeks=1)
            result.append([rule['title'], times, run])
        return result
    finally:
        custom.close()


def ideas(inbox, start, end):
    return [summary or raw for summary, raw in inbox.db.execute(
        "SELECT summary,raw FROM entries WHERE kind='idea' AND substr(created_at,1,10) BETWEEN ? AND ? ORDER BY seq", (start, end))]


def next_week(runtime, zone, sunday, lang):
    """Next week's saved appointments and deadlines, and how many planned tasks it holds. Nothing is scheduled."""
    from goodmorning.calendar.calendar_store import endpoints
    from goodmorning.web import language as ui
    from goodmorning.web.schedule import saved_week
    token = ui.CURRENT.set(lang)
    try:
        week = saved_week(Path(runtime), zone, datetime.combine(Date.fromisoformat(sunday), time(12), ZoneInfo(zone)), 1)
    finally:
        ui.CURRENT.reset(token)
    events, deadlines, planned = [], [], 0
    for day in week['days']:
        for event in day['events']:
            if event.get('draft'):
                events.append([day['date'], None, event['title']])  # Time not yet confirmed.
                continue
            begins = endpoints(event)[0].astimezone(ZoneInfo(zone))
            if begins.date().isoformat() == day['date']:  # Listed once, on the day it starts.
                events.append([day['date'], '' if event['all_day'] else begins.strftime('%H:%M'), event['subject']])
        for task in day['tasks']:
            if task.get('category') == 'habit':
                continue
            if task.get('marker') == 'due':
                deadlines.append([day['date'], task['text']])
                continue
            planned += 1
            if task.get('due_date') and not task.get('due_soft') and week['start'] <= task['due_date'] <= week['days'][-1]['date'] \
                    and [task['due_date'], task['text']] not in deadlines:
                deadlines.append([task['due_date'], task['text']])
    return {'events': events, 'deadlines': sorted(deadlines), 'planned': planned, 'complete': not week['warnings']}


def facts(runtime, week, lang):
    """Every list a letter shows, read from saved records only."""
    from .inbox_store import InboxStore
    zone = profile_fields(runtime).get('timezone')
    if not zone:
        raise ValueError('setup_required: profile timezone is missing')
    end = (Date.fromisoformat(week) + timedelta(days=6)).isoformat()
    inbox = InboxStore(runtime)
    try:
        inbox.db.execute('BEGIN')
        done, saved = finished(inbox, ZoneInfo(zone), week, end, lang), ideas(inbox, week, end)
    finally:
        inbox.close()
    return {'finished': done, 'habits': habits(runtime, week, end), 'ideas': saved,
            'next': next_week(runtime, zone, end, lang)}


def counts(letter):
    """Things finished, habits kept going and ideas saved: the briefing card's summary."""
    return [sum(count for _, items in letter['finished'] for _, count in items), len(letter['habits']), len(letter['ideas'])]


def check(letter):
    from goodmorning.briefings.briefing_document import text
    if not isinstance(letter, dict) or set(letter) != {'v', 'week', 'lang', 'opening', 'signoff', 'finished', 'habits', 'ideas', 'next'}:
        raise ValueError('Invalid letter')
    for key, limit in LIMITS.items():
        text(letter[key], key, limit)
    return letter


def load(runtime, week):
    path = letter_path(runtime, week)
    if not path.exists():
        return None
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Letter exceeds size limit')
    return check(json.loads(raw))


def save(runtime, week, words, lang):
    """Write the week's letter once from current records; an existing letter is kept and returned."""
    if not isinstance(words, dict) or set(words) != set(LIMITS):
        raise ValueError('Write the letter as {"opening":"…","signoff":"…"}')
    folder = directory(runtime)
    folder.mkdir(mode=0o700, exist_ok=True)
    with runtime_lock(folder, '.letters.lock'):
        saved = load(runtime, week)
        if saved:
            return saved
        letter = check({'v': 1, 'week': week, 'lang': lang, **words, **facts(runtime, week, lang)})
        source = json.dumps(letter, ensure_ascii=False, separators=(',', ':')) + '\n'
        if len(source.encode()) > MAX_BYTES:
            raise ValueError('Letter exceeds size limit')
        atomic_text(letter_path(runtime, week), source)
        return letter


def weeks(runtime):
    """Saved letter weeks, newest first."""
    folder = directory(runtime)
    if not folder.exists():
        return []
    return sorted((path.stem for path in folder.glob('????-??-??.json')), reverse=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secretary-dir')
    parser.add_argument('--week', required=True, help='Monday of the week to look back on')
    parser.add_argument('--website-language', choices=('en', 'zh-CN'), default='en')
    args = parser.parse_args()
    try:
        runtime = secretary_path(args.secretary_dir)
        saved = load(runtime, args.week)
        result = {'week': args.week, 'saved': True, 'counts': counts(saved)} if saved else {
            'week': args.week, 'saved': False, 'letter': facts(runtime, args.week, args.website_language)}
    except (ValueError, OSError, KeyError, sqlite3.Error) as error:
        print(json.dumps({'error': 'letter_unavailable', 'next': str(error)[:300]}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
