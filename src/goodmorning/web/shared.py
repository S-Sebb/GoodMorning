"""The read-only page a friend sees: only the sections the owner switched on, built from saved data.

The gateway decides which sections a viewer may see and asks this account's viewer for exactly those.
Nothing written by the secretary (greetings, notes, closings) is shown, and events keep only their
title and times: notes, places and calendar sources stay private.
"""
from datetime import date, datetime, timedelta, timezone
import html
import re
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from goodmorning import anime, games, stocks
from goodmorning.briefings.briefing_document import holdings_markup, render_block
from goodmorning.briefings.briefing_web import section_markup
from goodmorning.calendar.calendar_store import endpoints
from goodmorning.security.friends import SECTIONS
from . import language as ui
from .briefing_resources import favicon_links
from .chat_theme import clock_theme
from .schedule import date_part, saved_week, task_card, week_offset

RECENT_DAYS = 14  # Older evening reads are not shown as a friend's current picture.
EVENING = (('stocks', stocks, 'Stocks'), ('anime', anime, 'New episodes'), ('games', games, 'Game sales'))


def query(raw):
    """(sections, week offset, friend name) from the gateway's request."""
    values = parse_qs(raw, keep_blank_values=True)
    if set(values) - {'sections', 'week', 'name'} or any(len(value) != 1 for value in values.values()):
        raise ValueError('Invalid shared view')
    chosen = [item for item in values.get('sections', [''])[0].split(',') if item]
    if any(item not in SECTIONS for item in chosen):
        raise ValueError('Invalid shared view')
    name = values.get('name', [''])[0]
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,39}', name):
        raise ValueError('Invalid shared view')
    return chosen, week_offset({'week': values['week']} if 'week' in values else {}), name


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


def week(data, chosen, name):
    days, offset = data['days'], data['offset']
    label = {0: 'This week', -1: 'Last week', 1: 'Next week'}.get(offset, '{count} weeks earlier' if offset < 0 else '{count} weeks ahead')
    base = '/friends/' + name

    def step(link_id, target, text, symbol):
        if not -3 <= target <= 3:
            return '<span class="week-arrow is-disabled" aria-disabled="true" aria-label="' + text + '">' + symbol + '</span>'
        return '<a id="' + link_id + '" class="week-arrow" href="' + base + '?week=' + str(target) + '" aria-label="' + text + '">' + symbol + '</a>'
    controls = ('<div class="schedule-toolbar"><div class="schedule-date"><h2 id="week-heading">' + date_part(days[0]['date'], 'month') + '</h2>'
                '<p class="schedule-range">' + date_part(days[0]['date'], 'short') + '<span class="range-dash">–</span>' + date_part(days[-1]['date'], 'short')
                + '<span class="range-dot"> · </span>' + ui.ui(label, count=abs(offset)) + '</p></div>'
                '<nav class="schedule-navigation" aria-label="Week navigation">' + step('week-previous', offset - 1, 'Previous week', '‹')
                + '<a id="week-current" class="current-week" href="' + base + '">' + ui.ui('This week') + '</a>'
                + step('week-next', offset + 1, 'Next week', '›') + '</nav></div>')
    columns = '<div class="schedule-grid">'
    for day in days:
        today = day['date'] == data['today']
        columns += ('<section class="schedule-day' + (' is-today' if today else '') + '"><header class="schedule-day-heading"><h3>'
                    '<span class="schedule-weekday">' + date_part(day['date'], 'weekday') + '</span><span class="schedule-day-number">'
                    + date_part(day['date'], 'day') + '</span></h3>'
                    + ('<span class="schedule-today">' + ui.ui('Today') + '</span>' if today else '<span class="schedule-today" aria-hidden="true"></span>')
                    + '</header>')
        if 'schedule' in chosen:
            columns += '<div class="schedule-calendar"><h4>' + ui.ui('Events') + '</h4>'
            columns += ''.join('<div class="schedule-event' + (' is-tbc' if event.get('draft') else '') + '"><span class="event-time">'
                               + event_time(event, day['date'], data['timezone']) + '</span><span class="event-title" data-content>'
                               + html.escape(event.get('title') if event.get('draft') else event['subject']) + '</span></div>'
                               for event in day['events'])
            if not day['events']:
                empty = 'Calendar unavailable' if data['calendar_error'] else 'No calendar events saved'
                columns += '<span class="schedule-empty" role="img" aria-label="' + empty + '" title="' + empty + '">—</span>'
            columns += '</div>'
        if 'todos' in chosen:
            columns += '<div class="schedule-work"><h4>' + ui.ui('To-dos') + '</h4>'
            tasks = [{'text': task['text'], 'done': task['done'], 'section': task['section'], 'status': task.get('status', 'done' if task['done'] else 'open')}
                     for task in day['tasks']]
            if tasks:
                columns += '<ul class="schedule-tasks">' + ''.join(task_card(task) for task in sorted(tasks, key=lambda task: bool(task['done']))) + '</ul>'
            elif day['plan_error']:
                columns += '<p class="schedule-empty">' + ui.ui('Task records unavailable') + '</p>'
            else:
                columns += '<span class="schedule-empty" role="img" aria-label="No to-dos saved" title="No to-dos saved">—</span>'
            columns += '</div>'
        columns += '</section>'
    zone = '<p class="shared-zone">' + ui.ui('Times are in {name}’s time zone ({zone}).', name=name, zone=data['timezone']) + '</p>'
    return controls + zone + columns + '</div>'


def latest(module, runtime, today):
    """(date, rows) of the newest recent evening read, or None."""
    for back in range(RECENT_DAYS):
        day = (today - timedelta(days=back)).isoformat()
        if module.saved_path(runtime, day).is_file():
            return day, module.saved_rows(runtime, day)
    return None


def page(app, raw_query):
    chosen, offset, name = query(raw_query)
    zone = app.profile().get('timezone')
    now = app.now() if app.now else datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(zone)).date() if zone else date.today()
    parts = []
    number = 0
    if zone and ('schedule' in chosen or 'todos' in chosen):
        number += 1
        title = 'Schedule' if 'schedule' in chosen else 'To-dos'
        parts.append(section_markup(number, ui.ui(title), week(saved_week(app.runtime, zone, now, offset), chosen, name), 'schedule'))
    for key, module, title in EVENING:
        if key not in chosen:
            continue
        number += 1
        found = latest(module, app.runtime, today)
        if not found:
            body = '<p class="shared-empty">' + ui.ui('No evening briefing in the last two weeks.') + '</p>'
        else:
            day, rows = found
            body = '<p class="shared-date">' + ui.ui('From the evening briefing of {date}', date=ui.day_text(day)) + '</p>'
            if not rows:
                body += '<p class="shared-empty">' + ui.ui('Nothing to show that evening.') + '</p>'
            elif key == 'stocks':
                body += holdings_markup(rows, day)
            else:
                body += render_block(['episodes' if key == 'anime' else 'deals', rows], {}, day)
        parts.append(section_markup(number, ui.ui(title), body, key))
    if not parts:
        parts.append('<p class="shared-none">' + ui.ui('{name} is not sharing anything with you yet.', name=name) + '</p>')
    theme = clock_theme(zone, now)['theme']
    source = ('<!doctype html><html lang="en" data-edition="' + theme + '"><head><meta charset="utf-8">'
              '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>' + html.escape(name) + ' — GoodMorning</title>'
              + favicon_links('secretary') + '<link rel="stylesheet" href="/briefing.css"><link rel="stylesheet" href="/schedule.css"></head>'
              '<body class="schedule-page shared-page"><header class="masthead"><a class="wordmark" href="/gm.html">GoodMorning<span>A personal secretary just for you</span></a>'
              '<nav class="edition-switch" aria-label="Your desk"><a class="edition-link" href="/gm.html">Morning</a><a class="edition-link" href="/gn.html">Evening</a>'
              '<a class="edition-link" href="/schedule">Schedule</a><a class="edition-link" href="/chat">Secretary</a></nav></header>'
              '<main><div class="shared-heading"><p class="shared-eyebrow">' + ui.ui('Shared with you') + '</p><h1 data-content>' + html.escape(name) + '</h1>'
              '<p class="shared-note">' + ui.ui('Only what {name} chose to share with you. Everything else stays private.', name=name) + '</p></div>'
              '<article class="shared-sections">' + ''.join(parts) + '</article></main></body></html>')
    return app.resources.rewrite(ui.page(source, app.csrf, '/friends/' + name)).encode()
