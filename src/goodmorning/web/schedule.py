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
from .briefing_resources import favicon_links
from .chat_theme import clock_theme


def week_offset(query):
    if set(query) - {'week'} or len(query.get('week', ['0'])) != 1:
        raise ValueError('Invalid schedule week')
    value = query.get('week', ['0'])[0]
    if value not in ('-3', '-2', '-1', '0', '1', '2', '3'):
        raise ValueError('Schedule outside the seven-week window')
    return int(value)


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
        from goodmorning.records.routing import planned_day, confirmed_drafts
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
                    day['tasks'] = [dict(r, id=r['occurrence_id'], text=r['title'], done=r['status'] == 'done',
                        section='nice-to-do' if r['optional'] else 'flexible')
                        for r in safe_value(planned_day(store, day['date']))]
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
    source = ui.ui('Custom calendar') if event['source'] == 'custom' else '<span data-content>' + html.escape(event['source']) + '</span>'
    return ('<details class="schedule-event" id="event-' + day + '-' + html.escape(event['id'], quote=True) + '">'
            '<summary id="summary-' + day + '-' + html.escape(event['id'], quote=True) + '"><span class="event-time">' + label + '</span><span class="event-title" data-content>' + html.escape(event['subject']) + '</span>'
            + location_html + ('<span class="review-dot" aria-label="Change awaiting review"></span>' if pending else '') + '</summary>'
            '<div class="event-detail">' + duration + notes + pending + '<p class="event-source">' + ui.ui('Calendar') + ' · ' + source + '</p></div></details>')


def task_card(task):
    state = task.get('status', 'done' if task['done'] else 'open')
    metadata = []
    if task.get('project'):
        metadata.append('<small class="task-project">' + ui.ui('Project: {name}', name=task['project']) + '</small>')
    if task['section'] == 'nice-to-do':
        metadata.append('<small class="task-kind">' + ui.ui('Optional') + '</small>')
    if state in ('partial', 'blocked'):
        metadata.append('<small class="task-progress">' + ui.ui(state.capitalize()) + '</small>')
    if task.get('due_date'):
        deadline = task.get('due_at') or task['due_date']
        metadata.append('<small class="task-deadline">' + ui.ui('Soft target: {date}' if task.get('due_soft') else 'Due: {date}', date=deadline) + '</small>')
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
    if part == 'day':
        label = str(value.day)
    elif part == 'weekday':
        label = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][value.weekday()] if ui.current() == 'zh-CN' else value.strftime('%a')
    elif part == 'month':
        label = f'{value.year}年{value.month}月' if ui.current() == 'zh-CN' else value.strftime('%B %Y')
    else:
        label = f'{value.month}月{value.day}日' if ui.current() == 'zh-CN' else value.strftime('%d %b').lstrip('0')
    return '<span data-content data-schedule-date="' + day + '" data-schedule-part="' + part + '">' + html.escape(label) + '</span>'


def view(data, checked):
    days, offset = data['days'], data['offset']
    def navigation(step, label, symbol):
        if not -3 <= offset + step <= 3:
            return '<span class="week-arrow is-disabled" aria-disabled="true" aria-label="' + label + '">' + symbol + '</span>'
        return '<a id="week-' + ('previous' if step < 0 else 'next') + '" class="week-arrow" data-week="' + str(offset + step) + '" href="/schedule?week=' + str(offset + step) + '" aria-label="' + label + '">' + symbol + '</a>'
    label = {0: 'This week', -1: 'Last week', 1: 'Next week'}.get(offset, '{count} weeks earlier' if offset < 0 else '{count} weeks ahead')
    total_events = len({event['id'] for day in days for event in day['events']})
    total_tasks = sum(len(day['tasks']) for day in days)
    done = sum(task['done'] for day in days for task in day['tasks'])
    same_month = days[0]['date'][:7] == days[-1]['date'][:7]
    first = date_part(days[0]['date'], 'day' if same_month else 'short')
    last = date_part(days[-1]['date'], 'day' if same_month else 'short')
    if days[0]['date'][:4] != days[-1]['date'][:4]:
        last += ' <span data-content>' + days[-1]['date'][:4] + '</span>'
    refresh = ('<button id="schedule-refresh" class="schedule-icon" type="button" aria-label="Refresh saved plans" title="Refresh saved plans">'
               '<svg viewBox="0 0 20 20" width="18" height="18" fill="none" aria-hidden="true"><path d="M16 8a6 6 0 1 0 .2 3M16 3v5h-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></button>')
    review_marker = '<span class="schedule-review-dot" aria-hidden="true"></span>' if data['pending'] else ''
    review_description = ' aria-describedby="schedule-review-count"' if data['pending'] else ''
    review_count = '<span id="schedule-review-count" hidden>' + ui.ui('Calendar review: {count} pending', count=data['pending']) + '</span>' if data['pending'] else ''
    info = ('<details class="schedule-info" id="schedule-info"><summary class="schedule-icon" aria-label="Schedule details" title="Schedule details"' + review_description + '>'
            '<svg viewBox="0 0 20 20" width="18" height="18" fill="currentColor" aria-hidden="true"><circle cx="4" cy="10" r="1.4"/><circle cx="10" cy="10" r="1.4"/><circle cx="16" cy="10" r="1.4"/></svg>'
            + review_marker + '</summary>' + review_count + '<div class="schedule-info-panel"><h2>' + ui.ui('Week details') + '</h2><dl>'
            '<dt>' + ui.ui('Events') + '</dt><dd>' + str(total_events) + '</dd>'
            '<dt>' + ui.ui('To-dos') + '</dt><dd>' + str(total_tasks) + ' · ' + ui.ui('{done} completed', done=done) + '</dd>'
            '<dt>' + ui.ui('Time zone') + '</dt><dd data-content>' + html.escape(data['timezone']) + '</dd>'
            '<dt>' + ui.ui('Saved records') + '</dt><dd id="schedule-status">' + ui.ui('Checked at {time}', time=checked) + '</dd></dl>')
    if data['pending']:
        info += ('<div class="schedule-review-note"><p>' + ui.ui('1 calendar change awaits review. New imports stay hidden until approved.' if data['pending'] == 1 else '{count} calendar changes await review. New imports stay hidden until approved.', count=data['pending'])
                 + '</p><a href="/chat">' + ui.ui('Review with your secretary') + ' ↗</a></div>')
    info += '</div></details>'
    controls = ('<div class="schedule-toolbar"><div class="schedule-date"><h1 id="week-heading">' + date_part(days[0]['date'], 'month') + '</h1>'
                '<p class="schedule-range">' + first + '<span class="range-dash">–</span>' + last + '<span class="range-dot"> · </span>' + ui.ui(label, count=abs(offset)) + '</p></div>'
                '<nav class="schedule-navigation" aria-label="Week navigation">' + navigation(-1, 'Previous week', '‹')
                + '<a id="week-current" class="current-week" data-week="0" href="/schedule">' + ui.ui('This week') + '</a>'
                + navigation(1, 'Next week', '›') + '<span class="schedule-tools">' + refresh + info + '</span></nav></div>')
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
            columns += '<ul class="schedule-tasks">' + ''.join(task_card(task) for task in day['tasks']) + '</ul>'
        if day['plan_error']:
            columns += '<p class="schedule-empty">' + ui.ui('Task records unavailable' if day['plan_error'] == 'tasks' else 'Daily plan unavailable') + '</p>'
        elif not day['tasks']:
            columns += '<span class="schedule-empty" role="img" aria-label="No to-dos saved" title="No to-dos saved">—</span>'
        columns += '</div></section>'
    notice = ''.join('<p class="schedule-warning" role="status">' + ui.ui(warning) + '</p>' for warning in data['warnings'])
    return controls + notice + overview + '</nav>' + columns + '</div>'


def snapshot(app, offset):
    zone = app.profile().get('timezone')
    if not zone:
        raise ValueError('Initialize your profile timezone first')
    now = app.now() if app.now else datetime.now(timezone.utc)
    data = saved_week(app.runtime, zone, now, offset)
    parser = ui.InterfaceHTML()
    checked = now.astimezone(ZoneInfo(zone)).strftime('%H:%M')
    parser.feed(view(data, checked))
    parser.close()
    markup = ''.join(parser.parts)
    revision = hashlib.sha256(json.dumps([data, ui.current()], sort_keys=True).encode()).hexdigest()
    return {'view': markup, 'revision': revision,
            'week': offset, 'today': data['today'], 'theme': clock_theme(zone, now)['theme'],
            'checked': checked}


def page(app, offset):
    zone = app.profile().get('timezone')
    theme = clock_theme(zone, app.now() if app.now else None)['theme']
    if zone:
        result = snapshot(app, offset)
        content = result['view']
    else:
        result = {'week': offset, 'revision': None, 'checked': None}
        content = '<div class="schedule-setup"><h2>Let’s make this yours.</h2><p>Set your timezone to see your weekly schedule. Your saved records stay unchanged.</p><a href="/chat?mode=initialize">Initialize my secretary</a></div>'
    config = html.escape(json.dumps({'week': offset, 'revision': result['revision'], 'checked': result['checked'], 'ready': bool(zone)}), quote=True)
    source = ('<!doctype html><html lang="en" data-edition="' + theme + '"><head><meta charset="utf-8">'
              '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Schedule — GoodMorning</title>'
              + favicon_links('secretary') + '<link rel="stylesheet" href="/briefing.css"><link rel="stylesheet" href="/schedule.css">'
              '<link rel="stylesheet" href="/scroll-rails.css"><script src="/scroll-rails.js" defer></script></head><body class="schedule-page">'
              '<a class="skip-link" href="#schedule-view">Skip to schedule</a><header class="masthead"><a class="wordmark" href="/gm.html">GoodMorning<span>A little space to think, plan, and begin.</span></a>'
              '<nav class="edition-switch" aria-label="Your desk"><a class="edition-link" href="/gm.html">Morning</a><a class="edition-link" href="/gn.html">Evening</a>'
              '<a class="edition-link selected" href="/schedule" aria-current="page">Schedule</a><a class="edition-link" href="/chat">Secretary</a></nav></header>'
              '<main><div id="schedule-view">' + content + '</div><p id="schedule-error" role="alert"></p>'
              '<noscript>Navigation and saved plans work without JavaScript. Reload to see updates.</noscript></main>'
              '<div id="schedule-config" hidden data-config="' + config + '"></div><script src="/schedule.js" defer></script></body></html>')
    return app.resources.rewrite(ui.page(source, app.csrf, '/schedule')).encode()
