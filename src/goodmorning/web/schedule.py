"""Read-only account-local events, confirmed TBC appointments and planned task occurrences."""
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import html
import json
import sqlite3
from zoneinfo import ZoneInfo

from goodmorning.calendar.calendar_store import CalendarStore, endpoints
from goodmorning.calendar.calendar_safety import safe_value
from goodmorning.records.daily import inspect, read_record, record_path
from goodmorning.records.routing import converted_draft_ids
from . import language as ui
from . import quick_chat
from .briefing_resources import favicon_links
from .chat_theme import clock_theme


def week_offset(query):
    if set(query) - {'week'} or len(query.get('week', ['0'])) != 1:
        raise ValueError('Invalid schedule week')
    value = query.get('week', ['0'])[0]
    if value not in ('-3', '-2', '-1', '0', '1', '2', '3'):
        raise ValueError('Schedule outside the seven-week window')
    return int(value)


DAY_RANGE = 21  # Day steps stay inside the seven-week window.


def schedule_query(query):
    """Return ('week', week offset) or ('day', days from today)."""
    if 'view' not in query:
        return 'week', week_offset(query)
    if set(query) - {'view', 'day'} or query['view'] != ['day'] or len(query.get('day', ['0'])) != 1:
        raise ValueError('Invalid schedule view')
    value = query.get('day', ['0'])[0]
    if value not in {str(step) for step in range(-DAY_RANGE, DAY_RANGE + 1)}:
        raise ValueError('Schedule outside the seven-week window')
    return 'day', int(value)


def saved_day(runtime, zone, now, offset):
    if type(offset) is not int or not -DAY_RANGE <= offset <= DAY_RANGE:
        raise ValueError('Schedule outside the seven-week window')
    today = now.astimezone(ZoneInfo(zone)).date()
    target = today + timedelta(days=offset)
    week = (target - timedelta(days=target.weekday()) - (today - timedelta(days=today.weekday()))).days // 7
    data = saved_week(runtime, zone, now, week)
    return {**data, 'offset': offset, 'week': week, 'days': [data['days'][target.weekday()]]}


def saved_week(runtime, zone, now, offset):
    if type(offset) is not int or not -3 <= offset <= 3:
        raise ValueError('Schedule outside the seven-week window')
    local = now.astimezone(ZoneInfo(zone))
    today = local.date()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    days = [{'date': (monday + timedelta(days=i)).isoformat(), 'events': [], 'tasks': [],
             'plan_error': False} for i in range(7)]
    warnings = []
    pending = 0
    converted = set()
    calendar_error = False
    calendar = runtime / 'calendar.sqlite'
    try:
        if calendar.is_symlink():
            raise ValueError('Unsafe calendar')
        if calendar.exists():
            store = CalendarStore(str(calendar), readonly=True)
            try:
                store.con.execute('BEGIN')
                start = datetime.combine(monday, time(), local.tzinfo)
                end = datetime.combine(monday + timedelta(days=7), time(), local.tzinfo)
                events = safe_value(store.query(start, end, limit=-1, details=True))
                converted = converted_draft_ids(store)
                pending = store.stats()['pending']
                for event in events:
                    begins, ends = endpoints(event)
                    for day in days:
                        day_start = datetime.combine(date.fromisoformat(day['date']), time(), local.tzinfo)
                        day_end = datetime.combine(day_start.date() + timedelta(days=1), time(), local.tzinfo)
                        if begins < day_end and ends > day_start:
                            day['events'].append(event)
            finally:
                store.close()
    except (ValueError, OSError, KeyError, sqlite3.Error):
        calendar_error = True
        warnings.append('Calendar records could not be read. Other saved plans are still shown.')
    for day in days:
        try:
            text, _ = read_record(record_path(runtime, day['date']))
            _, _, tasks = inspect(text, day['date'])
            seen = set()
            for task in safe_value(tasks):
                key = task['ref'] or ' '.join(task['text'].split())
                if key not in seen:
                    day['tasks'].append({k: task[k] for k in ('id', 'section', 'text', 'done')})
                    seen.add(key)
        except (ValueError, OSError, UnicodeError):
            day['plan_error'] = True
    if (runtime/'inbox.sqlite').exists():
        from goodmorning.records.inbox_store import InboxStore
        from goodmorning.records.task_store import TaskStore
        from goodmorning.records.routing import planned_day, confirmed_drafts, calendar_day_extras
        inbox = None
        try:
            inbox = InboxStore(runtime)
            if inbox.version == 2:
                store = TaskStore(inbox)
                inbox.db.execute('BEGIN')
                drafts = safe_value(confirmed_drafts(store, monday.isoformat(),
                    (monday + timedelta(days=7)).isoformat(), converted))
                for day in days:
                    day['plan_error'] = False  # Legacy history is not a canonical source failure.
                    rows = planned_day(store, day['date']) + calendar_day_extras(store, day['date'], today.isoformat())
                    day['tasks'] = [dict(r, id=r['occurrence_id'] or r['id'] + ':due', text=r['title'], done=r['status'] == 'done',
                        section='nice-to-do' if r['optional'] else 'flexible')
                        for r in safe_value(rows)]
                    day['events'].extend(draft for draft in drafts if draft['date'] == day['date'])
        except (ValueError, OSError, sqlite3.Error, KeyError, TypeError):
            warnings.append('Task records could not be read; no availability is inferred.')
            for day in days:
                day['plan_error'] = 'tasks'
                day['tasks'] = []
        finally:
            if inbox:
                inbox.close()
    return {'today': today.isoformat(), 'start': monday.isoformat(), 'offset': offset,
            'timezone': zone, 'days': days, 'pending': pending, 'warnings': warnings, 'calendar_error': calendar_error}


def event_card(event, day, zone):
    if event.get('draft'):
        identifier = html.escape(event['id'], quote=True)
        location = '<span class="event-location" data-content>' + html.escape(event['location']) + '</span>' if event['location'] else ''
        notes = '<p class="event-notes" data-content>' + html.escape(event['detail']) + '</p>' if event['detail'] else ''
        return ('<details class="schedule-event is-tbc" id="event-' + day + '-' + identifier + '">'
            '<summary id="summary-' + day + '-' + identifier + '"><span class="event-time">' + ui.ui('TBC') + '</span>'
            '<span class="event-title" data-content>' + html.escape(event['title']) + '</span>' + location + '</summary>'
            '<div class="event-detail"><p>' + ui.ui('Appointment time not yet confirmed') + '</p>' + notes
            + '<p class="event-source">' + ui.ui('Time zone') + ' · <span data-content>' + html.escape(event['timezone']) + '</span></p></div></details>')
    begins, ends = (point.astimezone(ZoneInfo(zone)) for point in endpoints(event))
    label = ui.ui('All day') if event['all_day'] else html.escape(begins.strftime('%H:%M') if begins.date().isoformat() == day else ui.text('Continues'))
    end_label = ends.strftime('%H:%M')
    if begins.date() != ends.date():
        end_label = ui.text('{date} at {time}', date=ends.date().isoformat(), time=end_label)
    duration = '' if event['all_day'] else '<p class="event-end">' + ui.ui('Until {time}', time=end_label) + '</p>'
    location = event.get('location') or event.get('online')
    location_html = '<span class="event-location" data-content>' + html.escape(location) + '</span>' if location else ''
    notes = '<p class="event-notes" data-content>' + html.escape(event['notes']) + '</p>' if event.get('notes') else ''
    pending = '<p class="event-review">' + ui.ui('Change awaiting review · last approved version') + '</p>' if event.get('pending_change') else ''
    source = '' if event['source'] == 'custom' else '<p class="event-source">' + ui.ui('Calendar') + ' · <span data-content>' + html.escape(event['source']) + '</span></p>'
    return ('<details class="schedule-event" id="event-' + day + '-' + html.escape(event['id'], quote=True) + '">'
            '<summary id="summary-' + day + '-' + html.escape(event['id'], quote=True) + '"><span class="event-time">' + label + '</span><span class="event-title" data-content>' + html.escape(event['subject']) + '</span>'
            + location_html + ('<span class="review-dot" aria-label="Change awaiting review"></span>' if pending else '') + '</summary>'
            '<div class="event-detail">' + duration + notes + pending + source + '</div></details>')


def task_card(task, day=None):
    state = task.get('status', 'done' if task['done'] else 'open')
    metadata = []
    if task.get('marker') == 'due':
        metadata.append('<small class="task-marker">' + ui.ui('Deadline · no workday assigned') + '</small>')
    elif task.get('marker') == 'flexible':
        metadata.append('<small class="task-marker">' + ui.ui('Flexible habit · moves with what you actually do') + '</small>')
    if task.get('project'):
        metadata.append('<small class="task-project">' + ui.ui('Project: {name}', name=task['project']) + '</small>')
    if task['section'] == 'nice-to-do':
        metadata.append('<small class="task-kind">' + ui.ui('Optional') + '</small>')
    if state in ('partial', 'blocked'):
        metadata.append('<small class="task-progress">' + ui.ui(state.capitalize()) + '</small>')
    if task.get('due_date') and (task.get('marker') != 'due' or task.get('due_at')):
        deadline = task.get('due_at') or task['due_date']
        metadata.append('<small class="task-deadline">' + ui.ui('Soft target: {date}' if task.get('due_soft') else 'Due: {date}', date=ui.human_dates(deadline, day)) + '</small>')
    if (task.get('when') or {}).get('morning_before'):
        metadata.append('<small class="task-trigger">' + ui.ui('Reminder trigger: morning starts before {time} ({zone})',
            time=task['when']['morning_before'], zone=task['timezone']) + '</small>')
    detail = ' · '.join(value for value in (task.get('detail'), task.get('report_detail')) if value)
    if detail:
        metadata.append('<small class="task-detail" data-content>' + html.escape(detail) + '</small>')
    label = {'done': 'Done', 'partial': 'Partial', 'blocked': 'Blocked'}.get(state, 'Not completed')
    return ('<li class="schedule-task is-' + state + '"><span class="task-state" aria-label="'
            + html.escape(ui.text(label), quote=True) + '">' + ('✓' if task['done'] else '○') + '</span>'
            '<div><span class="task-title" data-content>' + html.escape(task['text']) + '</span>' + ''.join(metadata) + '</div></li>')


def date_part(day, part):
    value = date.fromisoformat(day)
    weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    if part == 'day':
        label = str(value.day)
    elif part == 'weekday':
        label = weekdays[value.weekday()] if ui.current() == 'zh-CN' else value.strftime('%a')
    elif part == 'month':
        label = f'{value.year}年{value.month}月' if ui.current() == 'zh-CN' else value.strftime('%B %Y')
    elif part == 'full':
        label = (f'{value.month}月{value.day}日星期' + '一二三四五六日'[value.weekday()] if ui.current() == 'zh-CN'
                 else value.strftime('%A, %B ') + str(value.day))
    else:
        label = f'{value.month}月{value.day}日' if ui.current() == 'zh-CN' else f'{value:%b} {value.day}'
    return '<span data-content data-schedule-date="' + day + '" data-schedule-part="' + part + '">' + html.escape(label) + '</span>'


def step_link(link_id, href, label, symbol, enabled):
    if not enabled:
        return '<span class="week-arrow is-disabled" aria-disabled="true" aria-label="' + label + '">' + symbol + '</span>'
    return '<a id="' + link_id + '" class="week-arrow" data-schedule-nav href="' + href + '" aria-label="' + label + '">' + symbol + '</a>'


def mode_switch(mode, week):
    links = (('week', 'Week', '/schedule?week=' + str(week)), ('day', 'Day', '/schedule?view=day'))
    return ('<div class="schedule-mode" role="group" aria-label="Schedule view">' + ''.join(
        '<a class="schedule-mode-link" data-schedule-nav data-schedule-mode="' + name + '" href="' + href + '"'
        + (' aria-current="true"' if name == mode else '') + '>' + ui.ui(label) + '</a>' for name, label, href in links) + '</div>')


def tools(data, checked, heading, events, tasks, done):
    refresh = ('<button id="schedule-refresh" class="schedule-icon" type="button" aria-label="Refresh saved plans" title="Refresh saved plans">'
               '<svg viewBox="0 0 20 20" width="18" height="18" fill="none" aria-hidden="true"><path d="M16 8a6 6 0 1 0 .2 3M16 3v5h-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></button>')
    info = ('<details class="schedule-info" id="schedule-info"><summary class="schedule-icon" aria-label="Schedule details" title="Schedule details">'
            '<svg viewBox="0 0 20 20" width="18" height="18" fill="currentColor" aria-hidden="true"><circle cx="4" cy="10" r="1.4"/><circle cx="10" cy="10" r="1.4"/><circle cx="16" cy="10" r="1.4"/></svg>'
            '</summary><div class="schedule-info-panel"><h2>' + ui.ui(heading) + '</h2><dl>'
            '<dt>' + ui.ui('Events') + '</dt><dd>' + str(events) + '</dd>'
            '<dt>' + ui.ui('To-dos') + '</dt><dd>' + str(tasks) + ' · ' + ui.ui('{done} completed', done=done) + '</dd>'
            '<dt>' + ui.ui('Time zone') + '</dt><dd data-content>' + html.escape(data['timezone']) + '</dd>'
            '<dt>' + ui.ui('Saved records') + '</dt><dd id="schedule-status">' + ui.ui('Checked at {time}', time=checked) + '</dd></dl>')
    return '<span class="schedule-tools">' + refresh + info + '</div></details></span>'


def notices(data):
    # Calendar changes waiting for approval stay in view, not behind the details menu.
    review = ('<p class="schedule-review" role="status"><span>' + ui.ui('1 calendar change awaits review. New imports stay hidden until approved.' if data['pending'] == 1 else '{count} calendar changes await review. New imports stay hidden until approved.', count=data['pending'])
              + '</span> <a href="/chat" data-quick-ask="Let’s review the calendar changes waiting for me.">' + ui.ui('Review with your secretary') + '</a></p>') if data['pending'] else ''
    return review + ''.join('<p class="schedule-warning" role="status">' + ui.ui(warning) + '</p>' for warning in data['warnings'])


def view(data, checked):
    days, offset = data['days'], data['offset']
    label = {0: 'This week', -1: 'Last week', 1: 'Next week'}.get(offset, '{count} weeks earlier' if offset < 0 else '{count} weeks ahead')
    total_events = len({event['id'] for day in days for event in day['events']})
    total_tasks = sum(len(day['tasks']) for day in days)
    done = sum(task['done'] for day in days for task in day['tasks'])
    same_month = days[0]['date'][:7] == days[-1]['date'][:7]
    first = date_part(days[0]['date'], 'day' if same_month else 'short')
    last = date_part(days[-1]['date'], 'day' if same_month else 'short')
    if days[0]['date'][:4] != days[-1]['date'][:4]:
        last += ' <span data-content>' + days[-1]['date'][:4] + '</span>'
    controls = ('<div class="schedule-toolbar"><div class="schedule-date"><h1 id="week-heading">' + date_part(days[0]['date'], 'month') + '</h1>'
                '<p class="schedule-range">' + first + '<span class="range-dash">–</span>' + last + (('<span class="range-dot"> · </span>' + ui.ui(label, count=abs(offset))) if offset else '') + '</p></div>'
                '<nav class="schedule-navigation" aria-label="Week navigation">' + mode_switch('week', offset)
                + step_link('week-previous', '/schedule?week=' + str(offset - 1), 'Previous week', '‹', offset > -3)
                + '<a id="week-current" class="current-week" data-schedule-nav href="/schedule">' + ui.ui('This week') + '</a>'
                + step_link('week-next', '/schedule?week=' + str(offset + 1), 'Next week', '›', offset < 3)
                + tools(data, checked, 'Week details', total_events, total_tasks, done) + '</nav></div>')
    overview = '<nav class="schedule-day-strip" aria-label="Jump to a day">'
    columns = '<div class="schedule-grid">'
    for day in days:
        today = day['date'] == data['today']
        marker = '<span class="schedule-today">' + ui.ui('Today') + '</span>' if today else '<span class="schedule-today" aria-hidden="true"></span>'
        overview += ('<a href="#day-' + day['date'] + '"' + (' aria-current="date"' if today else '') + '>'
                     + date_part(day['date'], 'weekday') + '<strong>' + date_part(day['date'], 'day') + '</strong></a>')
        columns += ('<section id="day-' + day['date'] + '" class="schedule-day' + (' is-today' if today else '') + '" aria-labelledby="heading-' + day['date'] + '">'
                    '<header class="schedule-day-heading"><h3 id="heading-' + day['date'] + '"><span class="schedule-weekday">' + date_part(day['date'], 'weekday')
                    + '</span><span class="schedule-day-number">' + date_part(day['date'], 'day') + '</span></h3>' + marker + '</header>'
                    '<div class="schedule-calendar"><h4>' + ui.ui('Events') + '</h4>')
        if day['events']:
            columns += ''.join(event_card(event, day['date'], data['timezone']) for event in day['events'])
        else:
            empty_label = 'Calendar unavailable' if data.get('calendar_error') else 'No calendar events saved'
            columns += '<span class="schedule-empty" role="img" aria-label="' + empty_label + '" title="' + empty_label + '">—</span>'
        columns += '</div><div class="schedule-work"><h4>' + ui.ui('To-dos') + '</h4>'
        if day['tasks']:
            columns += '<ul class="schedule-tasks">' + ''.join(task_card(task, day['date']) for task in sorted(day['tasks'], key=lambda task: bool(task['done']))) + '</ul>'
        if day['plan_error']:
            columns += '<p class="schedule-empty">' + ui.ui('Task records unavailable' if day['plan_error'] == 'tasks' else 'Daily plan unavailable') + '</p>'
        elif not day['tasks']:
            columns += '<span class="schedule-empty" role="img" aria-label="No to-dos saved" title="No to-dos saved">—</span>'
        columns += '</div></section>'
    notice = notices(data)
    return controls + notice + overview + '</nav>' + columns + '</div>'


def day_event(event, day, zone, now):
    """One event with its times spelled out; on the current day it also says whether it ended."""
    if event.get('draft'):
        place, notes = event['location'], event['detail']
        start, until, state, sort = ui.ui('TBC'), ui.ui('Appointment time not yet confirmed'), 'tbc', ''
        source = '<p class="event-source">' + ui.ui('Time zone') + ' · <span data-content>' + html.escape(event['timezone']) + '</span></p>'
        title, review = event['title'], ''
    else:
        begins, ends = (point.astimezone(ZoneInfo(zone)) for point in endpoints(event))
        local = now.astimezone(ZoneInfo(zone))
        if event['all_day']:
            start, until, state, sort = ui.ui('All day'), '', 'all-day', ''
        else:
            # Untimed and continuing entries come first; the rest follow by start time.
            sort = begins.isoformat() if begins.date().isoformat() == day else ''
            start = html.escape(begins.strftime('%H:%M')) if sort else ui.ui('Continues')
            end_label = ends.strftime('%H:%M')
            if begins.date() != ends.date():
                end_label = ui.text('{date} at {time}', date=ends.date().isoformat(), time=end_label)
            until = ui.ui('Until {time}', time=end_label)
            state = '' if day != local.date().isoformat() else 'past' if ends <= local else 'now' if begins <= local else 'next'
        place, notes = event.get('location') or event.get('online'), event.get('notes')
        source = '' if event['source'] == 'custom' else '<p class="event-source">' + ui.ui('Calendar') + ' · <span data-content>' + html.escape(event['source']) + '</span></p>'
        title = event['subject']
        review = '<p class="event-review">' + ui.ui('Change awaiting review · last approved version') + '</p>' if event.get('pending_change') else ''
    badge = {'now': '<span class="day-badge is-now">' + ui.ui('Now') + '</span>',
             'past': '<span class="day-badge">' + ui.ui('Ended') + '</span>'}.get(state, '')
    body = ('<span class="event-title" data-content>' + html.escape(title) + '</span>'
            + ('<span class="event-location" data-content>' + html.escape(place) + '</span>' if place else '')
            + ('<p class="event-notes" data-content>' + html.escape(notes) + '</p>' if notes else '')
            + review + source)
    return {'start': start, 'until': until, 'state': state, 'badge': badge, 'body': body, 'title': title, 'sort': sort}


def day_tasks(day):
    if day['plan_error']:
        return '<p class="schedule-empty">' + ui.ui('Task records unavailable' if day['plan_error'] == 'tasks' else 'Daily plan unavailable') + '</p>'
    if not day['tasks']:
        return '<p class="schedule-empty">' + ui.ui('No to-dos saved') + '</p>'
    return '<ul class="schedule-tasks">' + ''.join(task_card(task, day['date']) for task in sorted(day['tasks'], key=lambda task: bool(task['done']))) + '</ul>'


def day_view(data, checked, now):
    day, offset = data['days'][0], data['offset']
    events = sorted((day_event(event, day['date'], data['timezone'], now) for event in day['events']), key=lambda item: item['sort'])
    done = sum(task['done'] for task in day['tasks'])
    relative = ({-1: ui.ui('Yesterday'), 0: ui.ui('Today'), 1: ui.ui('Tomorrow')}.get(offset)
                or ui.ui('In {count} days' if offset > 0 else '{count} days ago', count=abs(offset)))
    counts = [ui.ui('1 event' if len(events) == 1 else '{count} events', count=len(events)),
              ui.ui('1 to-do' if len(day['tasks']) == 1 else '{count} to-dos', count=len(day['tasks']))]
    if day['tasks']:
        counts.append(ui.ui('{done} completed', done=done))
    upcoming = next((item for item in events if item['state'] == 'next'), None)
    if upcoming:
        counts.append('<span class="day-next">' + ui.ui('Next') + ' · ' + upcoming['start'] + ' <span data-content>' + html.escape(upcoming['title']) + '</span></span>')
    controls = ('<div class="schedule-toolbar"><div class="schedule-date"><h1 id="week-heading">' + date_part(day['date'], 'full') + '</h1>'
                '<p class="schedule-range">' + relative + '<span class="range-dot"> · </span>' + '<span class="range-dot"> · </span>'.join(counts) + '</p></div>'
                '<nav class="schedule-navigation" aria-label="Day navigation">' + mode_switch('day', data['week'])
                + step_link('day-previous', '/schedule?view=day&day=' + str(offset - 1), 'Previous day', '‹', offset > -DAY_RANGE)
                + '<a id="day-current" class="current-week" data-schedule-nav href="/schedule?view=day">' + ui.ui('Today') + '</a>'
                + step_link('day-next', '/schedule?view=day&day=' + str(offset + 1), 'Next day', '›', offset < DAY_RANGE)
                + tools(data, checked, 'Day details', len(events), len(day['tasks']), done) + '</nav></div>')
    notice = notices(data)
    empty_events = '<p class="schedule-empty">' + ui.ui('Calendar unavailable' if data.get('calendar_error') else 'No calendar events saved') + '</p>'
    today = ' is-today' if day['date'] == data['today'] else ''
    cards = ''.join('<li class="focus-event' + (' is-' + item['state'] if item['state'] else '') + '"><div class="focus-time"><strong>' + item['start'] + '</strong>'
                    + ('<span>' + item['until'] + '</span>' if item['until'] else '') + '</div><div class="focus-body">' + item['badge'] + item['body'] + '</div></li>'
                    for item in events)
    body = ('<div id="day-' + day['date'] + '" class="schedule-focus' + today + '">'
            '<section class="focus-panel schedule-calendar"><h2>' + ui.ui('Events') + '</h2>' + ('<ol class="focus-events">' + cards + '</ol>' if events else empty_events) + '</section>'
            '<section class="focus-panel schedule-work"><h2>' + ui.ui('To-dos') + '</h2>' + day_tasks(day) + '</section></div>')
    return controls + notice + body, [item['state'] for item in events]


def snapshot(app, offset, mode='week'):
    zone = app.profile().get('timezone')
    if not zone:
        raise ValueError('Initialize your profile timezone first')
    now = app.now() if app.now else datetime.now(timezone.utc)
    data = (saved_day if mode == 'day' else saved_week)(app.runtime, zone, now, offset)
    parser = ui.InterfaceHTML()
    checked = now.astimezone(ZoneInfo(zone)).strftime('%H:%M')
    markup, states = day_view(data, checked, now) if mode == 'day' else (view(data, checked), [])
    parser.feed(markup)
    parser.close()
    markup = ''.join(parser.parts)
    revision = hashlib.sha256(json.dumps([data, ui.current(), mode, states], sort_keys=True).encode()).hexdigest()
    return {'view': markup, 'revision': revision, 'mode': mode,
            'week': data.get('week', offset), 'today': data['today'], 'theme': clock_theme(zone, now)['theme'],
            'checked': checked}


def page(app, offset, mode='week'):
    zone = app.profile().get('timezone')
    theme = clock_theme(zone, app.now() if app.now else None)['theme']
    if zone:
        result = snapshot(app, offset, mode)
        content = result['view']
    else:
        result = {'revision': None, 'checked': None}
        content = '<div class="schedule-setup"><h2>Let’s make this yours.</h2><p>Set your timezone to see your weekly schedule. Your saved records stay unchanged.</p><a href="/chat?mode=initialize">Initialize my secretary</a></div>'
    config = html.escape(json.dumps({'mode': mode, 'revision': result['revision'], 'checked': result['checked'], 'ready': bool(zone)}), quote=True)
    source = ('<!doctype html><html lang="en" data-edition="' + theme + '"><head><meta charset="utf-8">'
              '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Schedule — GoodMorning</title>'
              '<script src="/schedule-mode.js"></script>'
              + favicon_links('secretary') + '<link rel="stylesheet" href="/briefing.css"><link rel="stylesheet" href="/schedule.css">'
              '<link rel="stylesheet" href="/scroll-rails.css"><script src="/scroll-rails.js" defer></script></head><body class="schedule-page">'
              '<a class="skip-link" href="#schedule-view">Skip to schedule</a><header class="masthead"><a class="wordmark" href="/gm.html">GoodMorning<span>A personal secretary just for you</span></a>'
              '<nav class="edition-switch" aria-label="Your desk"><a class="edition-link" href="/gm.html">Morning</a><a class="edition-link" href="/gn.html">Evening</a>'
              '<a class="edition-link selected" href="/schedule" aria-current="page">Schedule</a><a class="edition-link" href="/chat">Secretary</a></nav></header>'
              '<main><div id="schedule-view">' + content + '</div><p id="schedule-error" role="alert"></p>'
              '<noscript>Navigation and saved plans work without JavaScript. Reload to see updates.</noscript></main>'
              '<div id="schedule-config" hidden data-config="' + config + '"></div><script src="/schedule.js" defer></script></body></html>')
    return app.resources.rewrite(ui.page(quick_chat.widget(source, app.csrf), app.csrf, '/schedule')).encode()
