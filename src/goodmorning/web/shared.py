"""A friend's version of Schedule, Morning or Evening: only the sections the owner switched on, from saved data.

The gateway decides which sections a viewer may see and asks this account's viewer for exactly those, with
the viewer's time zone. Nothing written by the secretary (greetings, notes, closings) is shown, and events keep
only their title and times: notes, places and calendar sources stay private.
"""
from datetime import date, datetime, timedelta, timezone
import html
import re
from urllib.parse import parse_qs, urlencode
from zoneinfo import ZoneInfo

from goodmorning import anime, games, stocks
from goodmorning.briefings.briefing_document import holdings_markup, render_block
from goodmorning.briefings.briefing_web import section_markup
from goodmorning.calendar.calendar_store import endpoints
from goodmorning.security.friends import PAGE_SECTIONS as PAGES
from . import language as ui
from .briefing_resources import favicon_links
from .chat_theme import clock_theme
from .schedule import DAY_RANGE, date_part, saved_day, saved_week, schedule_query, task_card

EVENING = (('stocks', stocks, 'Stocks'), ('anime', anime, 'New episodes'), ('games', games, 'Game sales'))
LINKS = (('gm', 'Morning', '/gm.html'), ('gn', 'Evening', '/gn.html'), ('schedule', 'Schedule', '/schedule'), ('chat', 'Secretary', '/chat'))


def query(raw):
    """(page, sections, friend name, viewer zone, the rest) from the gateway's request."""
    values = parse_qs(raw, keep_blank_values=True)
    if any(len(value) != 1 for value in values.values()):
        raise ValueError('Invalid shared view')
    values = {key: value[0] for key, value in values.items()}
    page, name, zone = values.pop('page', ''), values.pop('name', ''), values.pop('zone', '')
    chosen = [item for item in values.pop('sections', '').split(',') if item]
    if page not in PAGES or any(item not in PAGES[page] for item in chosen) or not chosen:
        raise ValueError('Invalid shared view')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,39}', name):
        raise ValueError('Invalid shared view')
    try:
        ZoneInfo(zone)
    except (KeyError, ValueError):
        raise ValueError('Invalid shared view') from None
    if page == 'schedule':
        mode, offset = schedule_query({key: [value] for key, value in values.items()})
        return page, chosen, name, zone, {'mode': mode, 'offset': offset}
    if set(values) != {'date', 'today'} or any(date.fromisoformat(values[key]).isoformat() != values[key] for key in values):
        raise ValueError('Invalid shared view')
    return page, chosen, name, zone, values


def link(path, name, **params):
    return html.escape(path + '?' + urlencode({**params, 'friend': name}), quote=True)


def event_time(event, day, zone):
    if event.get('draft'):
        return ui.ui('TBC')
    if event['all_day']:
        return ui.ui('All day')
    begins, ends = (point.astimezone(ZoneInfo(zone)) for point in endpoints(event))
    if begins.date().isoformat() != day:
        return ui.ui('Continues')
    if ends.date() != begins.date():
        return html.escape(begins.strftime('%H:%M')) + '–' + ui.ui('{date} at {time}', date=ends.date().isoformat(), time=ends.strftime('%H:%M'))
    return html.escape(begins.strftime('%H:%M') + '–' + ends.strftime('%H:%M'))


def events(day, data):
    """A day's events as title and time only. All-day events keep their own dates, whatever the viewer's zone."""
    day = {**day, 'events': [event for event in day['events']
                             if not event.get('all_day') or event['start'] <= day['date'] < event['end']]}
    if not day['events']:
        empty = 'Calendar unavailable' if data['calendar_error'] else 'No calendar events saved'
        return '<span class="schedule-empty" role="img" aria-label="' + empty + '" title="' + empty + '">—</span>'
    return ''.join('<div class="schedule-event' + (' is-tbc' if event.get('draft') else '') + '"><span class="event-time">'
                   + event_time(event, day['date'], data['timezone']) + '</span><span class="event-title" data-content>'
                   + html.escape(event.get('title') if event.get('draft') else event['subject']) + '</span></div>' for event in day['events'])


def todos(day):
    """A day's to-dos as title and status only."""
    tasks = [{'text': task['text'], 'done': task['done'], 'section': task['section'], 'status': task.get('status', 'done' if task['done'] else 'open')}
             for task in day['tasks']]
    if tasks:
        return '<ul class="schedule-tasks">' + ''.join(task_card(task) for task in sorted(tasks, key=lambda task: bool(task['done']))) + '</ul>'
    if day['plan_error']:
        return '<p class="schedule-empty">' + ui.ui('Task records unavailable') + '</p>'
    return '<span class="schedule-empty" role="img" aria-label="No to-dos saved" title="No to-dos saved">—</span>'


def arrow(link_id, href, label, symbol):
    if not href:
        return '<span class="week-arrow is-disabled" aria-disabled="true" aria-label="' + label + '">' + symbol + '</span>'
    return '<a id="' + link_id + '" class="week-arrow" href="' + href + '" aria-label="' + label + '">' + symbol + '</a>'


def schedule_view(data, chosen, name, mode, offset):
    days = data['days']
    if mode == 'week':
        label = {0: 'This week', -1: 'Last week', 1: 'Next week'}.get(offset, '{count} weeks earlier' if offset < 0 else '{count} weeks ahead')
        heading = date_part(days[0]['date'], 'month')
        detail = date_part(days[0]['date'], 'short') + '<span class="range-dash">–</span>' + date_part(days[-1]['date'], 'short')
        step = lambda target: link('/schedule', name, week=target) if -3 <= target <= 3 else None
        current = ('week-current', link('/schedule', name), 'This week')
        steps = ('Previous week', 'Next week')
    else:
        label = {-1: 'Yesterday', 0: 'Today', 1: 'Tomorrow'}.get(offset, 'In {count} days' if offset > 0 else '{count} days ago')
        heading, detail = date_part(days[0]['date'], 'full'), ''
        step = lambda target: link('/schedule', name, view='day', day=target) if -DAY_RANGE <= target <= DAY_RANGE else None
        current = ('day-current', link('/schedule', name, view='day'), 'Today')
        steps = ('Previous day', 'Next day')
    modes = ('<div class="schedule-mode" role="group" aria-label="Schedule view">'
             + ''.join('<a class="schedule-mode-link" href="' + href + '"' + (' aria-current="true"' if key == mode else '') + '>' + ui.ui(text) + '</a>'
                       for key, text, href in (('week', 'Week', link('/schedule', name, week=data.get('week', offset))), ('day', 'Day', link('/schedule', name, view='day'))))
             + '</div>')
    controls = ('<div class="schedule-toolbar"><div class="schedule-date"><h1 id="week-heading">' + heading + '</h1>'
                '<p class="schedule-range">' + detail + ('<span class="range-dot"> · </span>' if detail else '') + ui.ui(label, count=abs(offset)) + '</p></div>'
                '<nav class="schedule-navigation" aria-label="' + ('Week navigation' if mode == 'week' else 'Day navigation') + '">' + modes
                + arrow(current[0].split('-')[0] + '-previous', step(offset - 1), steps[0], '‹')
                + '<a id="' + current[0] + '" class="current-week" href="' + current[1] + '">' + ui.ui(current[2]) + '</a>'
                + arrow(current[0].split('-')[0] + '-next', step(offset + 1), steps[1], '›') + '</nav></div>')
    columns = '<div class="schedule-grid' + (' shared-day' if mode == 'day' else '') + '">'
    for day in days:
        today = day['date'] == data['today']
        columns += ('<section class="schedule-day' + (' is-today' if today else '') + '"><header class="schedule-day-heading"><h3>'
                    '<span class="schedule-weekday">' + date_part(day['date'], 'weekday') + '</span><span class="schedule-day-number">'
                    + date_part(day['date'], 'day') + '</span></h3>'
                    + ('<span class="schedule-today">' + ui.ui('Today') + '</span>' if today else '<span class="schedule-today" aria-hidden="true"></span>')
                    + '</header>')
        if 'schedule' in chosen:
            columns += '<div class="schedule-calendar"><h4>' + ui.ui('Events') + '</h4>' + events(day, data) + '</div>'
        if 'todos' in chosen:
            columns += '<div class="schedule-work"><h4>' + ui.ui('To-dos') + '</h4>' + todos(day) + '</div>'
        columns += '</section>'
    return controls + columns + '</div>'


def morning(app, chosen, zone, now, day):
    monday = lambda value: value - timedelta(days=value.weekday())
    weeks = (monday(date.fromisoformat(day)) - monday(now.astimezone(ZoneInfo(zone)).date())).days // 7
    if not -3 <= weeks <= 3:
        return '<p class="shared-empty">' + ui.ui('Only days within three weeks of today can be shown.') + '</p>'
    data = saved_week(app.runtime, zone, now, weeks)
    entry = next(item for item in data['days'] if item['date'] == day)
    parts, number = [], 0
    if 'schedule' in chosen:
        number += 1
        parts.append(section_markup(number, ui.ui('Schedule'), '<div class="shared-list">' + events(entry, data) + '</div>', 'schedule'))
    if 'todos' in chosen:
        number += 1
        parts.append(section_markup(number, ui.ui('To-dos'), todos(entry), 'tasks'))
    return ''.join(parts)


def evening(app, chosen, values):
    parts, number = [], 0
    for key, module, title in EVENING:
        if key not in chosen:
            continue
        number += 1
        rows = module.saved_rows(app.runtime, values['date'])
        if not rows:
            body = '<p class="shared-empty">' + ui.ui('Nothing saved for this evening.') + '</p>'
        elif key == 'stocks':
            body = holdings_markup(rows, values['date'])
        else:
            body = render_block(['episodes' if key == 'anime' else 'deals', rows], {}, values['date'])
        parts.append(section_markup(number, ui.ui(title), body, key))
    return ''.join(parts)


def page(app, raw_query):
    kind, chosen, name, zone, values = query(raw_query)
    now = app.now() if app.now else datetime.now(timezone.utc)
    sections = ui.text(', ').join(ui.text(title) for key, title in (('schedule', 'Schedule'), ('todos', 'To-dos'), ('stocks', 'Stocks'),
                                                         ('anime', 'New episodes'), ('games', 'Game sales')) if key in chosen)
    note = ui.ui('{name} shares {sections} with you.', name=name, sections=sections)
    if kind == 'schedule':
        mode, offset = values['mode'], values['offset']
        data = (saved_day if mode == 'day' else saved_week)(app.runtime, zone, now, offset)
        body = schedule_view(data, chosen, name, mode, offset)
        theme = clock_theme(zone, now)['theme']
        title, path = 'Schedule', '/schedule'
    else:
        day, today = values['date'], values['today']
        later = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        earlier = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
        heading = ('<div class="schedule-toolbar"><div class="schedule-date"><h1 id="week-heading">' + date_part(day, 'full') + '</h1></div>'
                   '<nav class="schedule-navigation" aria-label="Day navigation">'
                   + arrow('day-previous', link(f'/d/{earlier}/{kind}.html', name), 'Previous day', '‹')
                   + '<a id="day-current" class="current-week" href="' + link(f'/{kind}.html', name) + '">' + ui.ui('Today') + '</a>'
                   + arrow('day-next', link(f'/d/{later}/{kind}.html', name) if later <= today else None, 'Next day', '›') + '</nav></div>')
        body = heading + (morning(app, chosen, zone, now, day) if kind == 'gm' else evening(app, chosen, values))
        theme, title, path = kind, 'Morning' if kind == 'gm' else 'Evening', f'/{kind}.html'
    if kind == 'schedule' or kind == 'gm':
        own = app.profile().get('timezone')
        if own and own != zone:
            note += ' ' + ui.ui('Times are in your time zone; {name} is in {zone}.', name=name, zone=own)
    nav = ''.join('<a class="edition-link' + (' selected" aria-current="page' if key == kind else '') + '" href="' + href + '">' + ui.ui(label) + '</a>'
                  for key, label, href in LINKS)
    source = ('<!doctype html><html lang="en" data-edition="' + theme + '"><head><meta charset="utf-8">'
              '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>' + ui.text(title) + ' · ' + html.escape(name) + ' — GoodMorning</title>'
              + favicon_links('gm' if kind == 'gm' else 'gn' if kind == 'gn' else 'secretary') + '<link rel="stylesheet" href="/briefing.css"><link rel="stylesheet" href="/schedule.css"></head>'
              '<body class="schedule-page shared-page"><header class="masthead"><a class="wordmark" href="/gm.html">GoodMorning<span>A personal secretary just for you</span></a>'
              '<nav class="edition-switch" aria-label="Your desk">' + nav + '</nav></header>'
              '<main><p class="shared-note">' + note + '</p><div id="schedule-view" class="shared-sections">' + body + '</div></main></body></html>')
    return app.resources.rewrite(ui.page(source, app.csrf, path)).encode()
