"""Versioned browser-native briefing data: validate first, render without Markdown."""
from datetime import date as Date, timedelta
import html
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .briefing_layout import icon, category_icon, news_visual
from goodmorning.web import language as ui

MAX_BYTES = 150_000
TITLES = {'weather': 'Weather', 'news': 'News', 'schedule': 'Schedule',
          'must-do': 'Project steps', 'nice-to-do': 'Optional project steps', 'reminders': 'Reminders',
          'today': 'Today', 'still-open': 'Still open', 'tomorrow': 'Tomorrow', 'notes': 'Notes'}
WEATHER = {'temperature': ('Temperature', 'thermometer', 'temperature cool'),
           'precipitation': ('Precipitation', 'rain', 'precipitation'),
           'warning': ('Extreme warning', 'warning', 'other'), 'air': ('AQI', 'leaf', 'air')}
AGENDA_LABELS = ['Date', 'Time', 'Event', 'Place', 'Preparation']


def source_path(runtime, date, kind):
    if Date.fromisoformat(date).isoformat() != date or kind not in ('gm', 'gn'):
        raise ValueError('Use an ISO briefing date and gm/gn edition')
    selected = Path(runtime) / 'daily' / f'{date}.{kind}.json'
    if selected.is_symlink() or selected.resolve() != selected:
        raise ValueError('Refusing symlinked briefing source')
    if selected.is_file() and selected.stat().st_size > MAX_BYTES:
        raise ValueError('Saved briefing too large')
    return selected


def fail(path, message):
    raise ValueError(f'{path}: {message}')


def text(value, path, limit=5000, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        fail(path, f'expected {"possibly empty " if empty else "nonempty "}text, at most {limit} characters')
    try:
        value.encode('utf-8')
    except UnicodeError:
        fail(path, 'invalid Unicode')
    if any(ord(c) < 32 and c not in '\n\t' for c in value):
        fail(path, 'control characters are not allowed')


def sequence(value, path, low, high):
    if not isinstance(value, list) or not low <= len(value) <= high:
        fail(path, f'expected array of {low}..{high} entries')


def sources(value, path):
    sequence(value, path, 1, 16)
    for index, pair in enumerate(value):
        here = f'{path}[{index}]'
        sequence(pair, here, 2, 2)
        text(pair[0], here + '.label', 200)
        text(pair[1], here + '.url', 2000)
        try:
            url = urlsplit(pair[1])
            valid = url.scheme in ('https', 'http') and url.hostname and not url.username and not url.password
            url.port
        except ValueError:
            valid = False
        if not valid or any(c.isspace() for c in pair[1]) or '\\' in pair[1]:
            fail(here, 'source requires an absolute HTTP(S) URL without credentials')


def block(value, path):
    sequence(value, path, 2, 4)
    tag = value[0]
    if tag in ('p', 'list'):
        sequence(value, path, 2, 3 if tag == 'p' else 2)
        if tag == 'p':
            text(value[1], path + '.text')
            if len(value) == 3:
                sources(value[2], path + '.sources')
        else:
            sequence(value[1], path + '.items', 1, 200)
            for item in value[1]:
                text(item, path + '.item')
    elif tag in ('tasks', 'flexible'):
        sequence(value, path, 2, 2)
        sequence(value[1], path + '.items', 1, 200)
        for index, row in enumerate(value[1]):
            here = f'{path}.items[{index}]'
            sequence(row, here, 4 if tag == 'flexible' else 3, 4 if tag == 'flexible' else 3)
            if tag == 'flexible':
                text(row[0], here + '.date', 10, empty=True)
                if row[0]:
                    try:
                        valid = Date.fromisoformat(row[0]).isoformat() == row[0]
                    except ValueError:
                        valid = False
                    if not valid:
                        fail(here + '.date', 'use YYYY-MM-DD or an empty string for no assigned date')
                row = row[1:]
            if row[0] not in ('open', 'done', 'partial', 'blocked'):
                fail(here, 'status must be open/done/partial/blocked')
            text(row[1], here + '.title', 600)
            text(row[2], here + '.detail', empty=True)
    elif tag in ('table', 'agenda'):
        sequence(value, path, 3 if tag == 'table' else 2, 3)
        columns = value[1] if tag == 'table' else (value[2] if len(value) == 3 else AGENDA_LABELS)
        rows = value[2] if tag == 'table' else value[1]
        sequence(columns, path + '.columns', 1 if tag == 'table' else 5, 16 if tag == 'table' else 5)
        for label in columns:
            text(label, path + '.label', 200)
        sequence(rows, path + '.rows', 1, 200)
        for index, row in enumerate(rows):
            sequence(row, f'{path}.rows[{index}]', len(columns), len(columns))
            for cell in row:
                text(cell, path + '.cell', empty=True)
            if tag == 'agenda':
                text(row[1], path + '.time', 200)
                text(row[2], path + '.event', 600)
    elif tag == 'weather':
        sequence(value, path, 2, 2)
        sequence(value[1], path + '.cards', 1, 4)
        order = []
        for index, row in enumerate(value[1]):
            here = f'{path}.cards[{index}]'
            sequence(row, here, 3, 4)
            if not isinstance(row[0], str) or row[0] not in WEATHER:
                fail(here, 'unknown weather card type')
            order.append(list(WEATHER).index(row[0]))
            if row[1] is not None:
                text(row[1], here + '.value', 100)
            text(row[2], here + '.detail')
            if len(row) == 4:
                text(row[3], here + '.label', 200)
        if order != sorted(set(order)):
            fail(path, 'weather order is temperature, precipitation, applicable warning, air; no duplicates')
    elif tag == 'news':
        sequence(value, path, 3, 4)
        text(value[1], path + '.category', 200)
        sequence(value[2], path + '.stories', 1, 200)
        for index, row in enumerate(value[2]):
            here = f'{path}.stories[{index}]'
            sequence(row, here, 3, 3)
            text(row[0], here + '.headline', 600)
            text(row[1], here + '.summary')
            sources(row[2], here + '.sources')
        if len(value) == 4 and (not isinstance(value[3], str) or not re.fullmatch('[A-Z]{2}', value[3])):
            fail(path, 'country flag requires a two-letter country code')
    else:
        fail(path, 'unknown block type; use p/list/table/agenda/tasks/weather/news/flexible')


def validate(data, partial=False):
    required = {'v', 'greeting', 'opening', 'sections'}
    if not isinstance(data, dict) or not required <= data.keys() or data.keys() - required - {'closing', 'lang'}:
        fail('document', 'required keys v/greeting/opening/sections; optional closing/lang only')
    if type(data['v']) is not int or data['v'] != 1:
        fail('v', 'unsupported version; preserve the original')
    for key in ('greeting', 'opening'):
        text(data[key], key, 350)
    if 'closing' in data:
        text(data['closing'], 'closing', 600)
    if 'lang' in data and (not isinstance(data['lang'], str) or not re.fullmatch('[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*', data['lang'])):
        fail('lang', 'expected a language tag such as en or zh-CN')
    sequence(data['sections'], 'sections', 0 if partial else 1, 80)
    for index, section in enumerate(data['sections']):
        path = f'sections[{index}]'
        sequence(section, path, 2, 4)
        if not isinstance(section[0], str) or section[0] not in TITLES:
            fail(path, 'unknown section type; use notes plus an explicit title for custom content')
        sequence(section[1], path + '.blocks', 1, 100)
        flexible_seen = False
        for number, value in enumerate(section[1]):
            block(value, f'{path}.blocks[{number}]')
            if value[0] == 'flexible':
                if section[0] not in ('schedule', 'tomorrow'):
                    fail(path, 'flexible schedules belong in schedule or tomorrow, not reminders/notes')
                flexible_seen = True
            elif value[0] == 'agenda' and flexible_seen:
                fail(path, 'put timed agenda blocks before flexible schedules')
        if len(section) >= 3:
            text(section[2], path + '.note', 600, empty=True)
        if len(section) == 4:
            text(section[3], path + '.title', 200)
    return data


def parse(source, partial=False):
    try:
        if len(source.encode('utf-8')) > MAX_BYTES:
            fail('document', 'exceeds 150000 bytes')
    except (AttributeError, UnicodeError) as error:
        raise ValueError('document: expected valid UTF-8 text') from error

    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                fail('document', 'duplicate object key')
            result[key] = value
        return result

    try:
        data = json.loads(source, object_pairs_hook=pairs,
                          parse_constant=lambda _: fail('document', 'non-finite numbers are not allowed'))
        return validate(data, partial=partial)
    except (TypeError, RecursionError, UnicodeError) as error:
        raise ValueError('document: invalid structure or encoding') from error


def encode(data):
    source = json.dumps(validate(data), ensure_ascii=False, separators=(',', ':')) + '\n'
    if len(source.encode('utf-8')) > MAX_BYTES:
        fail('document', 'canonical form exceeds 150000 bytes')
    return source


def validate_task_ownership(data):
    """Reject repeated task cards on write; historical documents remain readable."""
    seen = {}
    for index, section in enumerate(data['sections']):
        for number, value in enumerate(section[1]):
            if value[0] not in ('tasks', 'flexible'):
                continue
            for row_number, row in enumerate(value[1]):
                day = row[0] if value[0] == 'flexible' else None
                title = ' '.join(row[-2].split())
                path = f'sections[{index}].blocks[{number}].items[{row_number}]'
                previous = seen.setdefault(title, {})
                # Distinct dated occurrences of recurring work are not duplicates.
                if previous and (day is None or None in previous or day in previous):
                    fail(path, 'duplicate task card; keep one section owner, already listed at ' + next(iter(previous.values())))
                previous[day] = path
    return data


def strings(value):
    """Decoded text for reply lint; JSON escapes must not hide routine boilerplate."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def escaped(value):
    from .briefing_web import visible_text
    return html.escape(visible_text(value))


def citations(value):
    return ' '.join(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{escaped(label)}</a>' for label, url in value)


def render_block(value, images, briefing_date=None):
    tag = value[0]
    if tag == 'p':
        return '<p>' + escaped(value[1]) + (' ' + citations(value[2]) if len(value) == 3 else '') + '</p>'
    if tag == 'list':
        return '<ul>' + ''.join('<li>' + escaped(item) + '</li>' for item in value[1]) + '</ul>'
    if tag == 'tasks':
        items = []
        for status, title, detail in value[1]:
            status_label='Completed' if status=='done' else 'Not completed'
            tick = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="m5 12.5 4.5 4.5L19 7"/></svg>' if status=='done' else ''
            mark = '<span class="check'+(' is-done' if status=='done' else '')+'" data-ui-aria-label="'+status_label+'" aria-label="'+ui.text(status_label)+'">'+tick+'</span>'
            label = '<span class="task-status">' + ui.ui(status.capitalize()) + '</span> ' if status in ('partial', 'blocked') else ''
            items.append(f'<li class="task-card task"><div class="task-title">{mark}{escaped(title)}</div><div class="task-detail">{label}{escaped(detail)}</div></li>')
        return '<ul class="task-list">' + ''.join(items) + '</ul>'
    if tag == 'flexible':
        groups = {}
        for date, status, title, detail in value[1]:
            groups.setdefault(date, []).append([status, title, detail])
        body = ''.join('<div class="flexible-group"><h4 class="agenda-day">' +
                       (ui.agenda_day(date, briefing_date) if date else ui.ui('No date assigned')) +
                       '</h4>' + render_block(['tasks', rows], images, briefing_date) + '</div>'
                       for date, rows in groups.items())
        return '<div class="flexible-schedule"><h3 class="flexible-title">' + ui.ui('Flexible schedule') + '</h3>' + body + '</div>'
    if tag == 'table':
        columns, rows = value[1:]
        headers = ''.join('<th>' + escaped(label) + '</th>' for label in columns)
        body = ''.join('<tr>' + ''.join('<td>' + escaped(cell) + '</td>' for cell in row) + '</tr>' for row in rows)
        return f'<div class="table-scroll" tabindex="0" role="region" data-ui-aria-label="Briefing table; scroll horizontally if needed" aria-label="{ui.text("Briefing table; scroll horizontally if needed")}"><table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>'
    if tag == 'agenda':
        labels = value[2] if len(value) == 3 else AGENDA_LABELS
        groups, previous = [], None
        for date, time, event, place, prep in value[1]:
            if date != previous:
                if groups:groups.append('</ol></div>')
                heading='<h3 class="agenda-day">'+icon('calendar')+ui.agenda_day(date,briefing_date)+'</h3>' if date else ''
                groups.append('<div class="agenda-group">'+heading+'<ol class="agenda-events">')
                previous=date
            fields = [(labels[0], date, 'calendar'), (labels[3], place, 'pin'), (labels[4], prep, 'list')]
            detail = ''.join(f'<div class="event-detail">{icon(symbol)}<div><span class="detail-label">{escaped(label) if len(value)==3 else ui.ui(label)}</span><div>{escaped(content)}</div></div></div>' for label, content, symbol in fields if content)
            groups.append(f'<li class="agenda-event"><div class="event-time">{icon("clock")}<span>{escaped(time)}</span></div><div class="event-copy"><h4>{escaped(event)}</h4>{detail}</div></li>')
        return '<div class="agenda">' + ''.join(groups) + '</ol></div></div>'
    if tag == 'weather':
        cards = []
        for row in value[1]:
            card, metric, detail, *custom = row
            label, symbol, style = WEATHER[card]
            metric = '<p class="weather-value">' + escaped(metric) + '</p>' if metric is not None else ''
            cards.append(f'<div class="weather-tile {style}"><div class="weather-label">{icon(symbol)}<h3>{escaped(custom[0]) if custom else ui.ui(label)}</h3></div>{metric}<div class="weather-detail"><p>{escaped(detail)}</p></div></div>')
        return '<div class="weather-tiles">' + ''.join(cards) + '</div>'
    if tag == 'news':
        from .briefing_layout import country_flag
        category = value[1]
        symbol = country_flag(value[3]) if len(value) == 4 else category_icon(category)
        cards = []
        for headline, summary, refs in value[2]:
            picture = news_visual(refs[0][1], escaped(refs[0][0]), category, images)
            cards.append(f'<li class="news-card">{picture}<div class="news-copy"><h4>{escaped(headline)}</h4><div class="news-summary"><p>{escaped(summary)}</p></div><div class="news-source">{citations(refs)}</div></div></li>')
        return f'<h3 class="news-category">{symbol}{escaped(category)}</h3><ul class="news-grid">' + ''.join(cards) + '</ul>'
    raise ValueError('Validate blocks before rendering')


def section_title(section, date, language='en'):
    if len(section) == 4:
        return section[3]
    return ui.text(TITLES[section[0]],lang=language if language in ui.LANGUAGES else 'en') + (' — ' + (Date.fromisoformat(date) - timedelta(days=1)).isoformat() if section[0] == 'news' else '')


def news_urls(data):
    return list(dict.fromkeys(url for section in data['sections'] for value in section[1]
                             if value[0] == 'news' for row in value[2] for _, url in row[2]
                             if url.startswith('https://')))[:32]
