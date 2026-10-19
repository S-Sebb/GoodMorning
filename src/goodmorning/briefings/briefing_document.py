"""Versioned browser-native briefing data: validate first, render without Markdown."""
from datetime import date as Date, timedelta
import html
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .briefing_layout import icon, category_icon, news_visual, episode_visual, deal_visual
from goodmorning.web import language as ui

MAX_BYTES = 150_000
TITLES = {'weather': 'Weather', 'news': 'News', 'schedule': 'Schedule',
          'must-do': 'Project steps', 'nice-to-do': 'Optional project steps', 'reminders': 'Reminders',
          'today': 'Today', 'still-open': 'Still open', 'tomorrow': 'Tomorrow', 'notes': 'Notes',
          'tasks': 'Tasks', 'attention': 'Reminders', 'anime': 'New episodes', 'games': 'Game sales', 'stocks': 'Stocks'}
WEATHER = {'temperature': ('Temperature', 'thermometer', 'temperature cool'),
           'precipitation': ('Precipitation', 'rain', 'precipitation'),
           'warning': ('Extreme warning', 'warning', 'other'), 'air': ('AQI', 'leaf', 'air')}
AGENDA_LABELS = ['Date', 'Time', 'Event', 'Place', 'Preparation']
DATED_TITLE_RE = re.compile(r'^(.*)\s+—\s+(\d{4}-\d{2}-\d{2})$')


def split_dated_title(title):
    """Split a section title like 'News — 2026-10-12' into (base, iso_date|None)."""
    if not isinstance(title, str):
        return title, None
    match = DATED_TITLE_RE.match(title.strip())
    if not match:
        return title.strip(), None
    try:
        Date.fromisoformat(match.group(2))
    except ValueError:
        return title.strip(), None
    return match.group(1).strip(), match.group(2)


def humanize_iso_date(iso_date):
    """Short human date for display badges, e.g. '2026-10-12' -> 'Oct 12'."""
    try:
        value = Date.fromisoformat(iso_date)
    except (ValueError, TypeError):
        return iso_date
    return f'{value.strftime("%b")} {value.day}'


def heading_html(title):
    """Display heading with a subtle date badge; keeps full date for screen readers."""
    from .briefing_web import visible_text
    base, iso = split_dated_title(visible_text(title))
    if not iso:
        return html.escape(visible_text(title))
    human = humanize_iso_date(iso)
    return (html.escape(base) + ' <span class="section-date" data-date="' +
            html.escape(iso, quote=True) + '"><span aria-hidden="true">· ' +
            html.escape(human) + '</span><span class="visually-hidden"> (' +
            html.escape(iso) + ')</span></span>')


def weather_display(card, metric):
    """Normalize LLM-composed weather values for display; saved data is unchanged."""
    if metric is None:
        return None
    text = str(metric).strip()
    if not text:
        return text
    if card == 'temperature':
        # 16C -> 16°C, 14.5-20.4C -> 14.5–20.4°C; leave existing °C alone.
        text = re.sub(r'(?<!°)(?<=\d)C\b', '°C', text)
        text = re.sub(r'(?<!°)(?<=\d)c\b', '°C', text)
        text = re.sub(r'(?<=\d)-(?=\d)', '–', text)
        text = re.sub(r'\s+-\s+', ' – ', text)
    elif card == 'precipitation':
        text = re.sub(r'\brain\s+yes\b', 'Rain likely', text, flags=re.IGNORECASE)
        text = re.sub(r'\brain\s+no\b', 'No rain', text, flags=re.IGNORECASE)
        text = re.sub(r'\brain\s+unknown\b', 'Rain unknown', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+-\s+', ' – ', text)
        text = re.sub(r'(?<=\d)-(?=\d)', '–', text)
    elif card == 'air':
        text = re.sub(r'^(?:US\s*AQI|EU\s*AQI|AQI)\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+-\s+', ' – ', text)
        head, sep, tail = text.partition('–')
        if sep and tail.strip():
            tail = tail.strip()
            tail = tail[:1].upper() + tail[1:] if tail[:1].isalpha() else tail
            text = head.strip() + ' – ' + tail
    return text.strip() or text


def weather_parts(card, metric):
    """Split a normalized weather value into (main, sub|None) for card display.

    Main stays prominent on its own line; sub moves to a smaller second line
    with no connecting dash, e.g. '15°C (14.5–20.4°C)' -> ('15°C', '(14.5–20.4°C)'),
    '65% – Rain likely' -> ('65%', 'Rain likely'), '27 – Good' -> ('27', 'Good').
    """
    display = weather_display(card, metric)
    if display is None:
        return None, None
    if card == 'temperature' and '(' in display:
        main, _, rest = display.partition('(')
        main = main.strip()
        sub = ('(' + rest).strip()
        if main:
            return main, (sub or None)
        return display.strip(), None
    if '–' in display:
        main, _, sub = display.partition('–')
        main, sub = main.strip(), sub.strip()
        if main and sub:
            if sub[:1].isalpha():
                sub = sub[:1].upper() + sub[1:]
            return main, sub
    return display.strip(), None


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
    if tag in ('actions', 'events', 'decisions'):
        sequence(value, path, 2, 2)
        sequence(value[1], path + '.items', 1, 200)
        width = {'actions': 7, 'events': 7, 'decisions': 4}[tag]
        for row in value[1]:
            sequence(row, path + '.row', width, width)
            pattern = {'actions': r'(?:task|cu)_[0-9a-f]{16}', 'events': r'(?:[0-9a-f]{16}|draft_[0-9a-f]{16}(?:@\d{4}-\d{2}-\d{2})?)', 'decisions': r'(?:[0-9a-f]{16}|(?:ib|draft)_[0-9a-f]{16})'}[tag]
            if not isinstance(row[0], str) or not re.fullmatch(pattern, row[0]) or type(row[1]) is not int or row[1] < 1:
                fail(path, 'source-linked rows need a durable ID and positive revision')
            for cell in row[2:]:
                text(cell, path + '.cell', empty=True)
            if tag == 'actions':
                if row[2] and not re.fullmatch(r'oc_[0-9a-f]{16}|cuoc_[0-9a-f]{16}_[0-9]{8}', row[2]):
                    fail(path, 'invalid occurrence ID')
                if row[3]:
                    try:
                        valid = Date.fromisoformat(row[3]).isoformat() == row[3]
                    except ValueError:
                        valid = False
                    if not valid:
                        fail(path, 'invalid agreed action date')
                if row[4] not in ('open', 'partial', 'blocked', 'done'):
                    fail(path, 'invalid action status')
                text(row[5], path + '.title', 600)
            else:
                text(row[4] if tag == 'events' else row[2], path + '.title', 600)
    elif tag == 'errands':
        # [id, revision, title, finding, sources, note]: one saved errand done this morning.
        # finding is what the user sees ("" keeps the row hidden); note is the dated result the next morning reads.
        sequence(value, path, 2, 2)
        sequence(value[1], path + '.items', 1, 50)
        for row in value[1]:
            sequence(row, path + '.row', 6, 6)
            if not isinstance(row[0], str) or not re.fullmatch(r'task_[0-9a-f]{16}', row[0]) or type(row[1]) is not int or row[1] < 1:
                fail(path, 'source-linked rows need a durable ID and positive revision')
            text(row[2], path + '.title', 600)
            text(row[3], path + '.finding', 1000, empty=True)
            if row[4] != []:
                sources(row[4], path + '.sources')
            text(row[5], path + '.note', 1000)
    elif tag == 'episodes':
        # [id, title, local_title, episode, episode_title, episode_local_title, aired, cover_url], copied from the anime read.
        sequence(value, path, 2, 2)
        sequence(value[1], path + '.items', 1, 50)
        for row in value[1]:
            sequence(row, path + '.row', 8, 8)
            if not isinstance(row[0], str) or not re.fullmatch(r'(?:anilist|bangumi):\d{1,9}', row[0]):
                fail(path, 'episode rows need a source title ID')
            text(row[1], path + '.title', 300)
            for cell in row[2:6]:
                text(cell, path + '.cell', 300, empty=True)
            if not row[3].strip() or not isinstance(row[6], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?', row[6]):
                fail(path, 'episode rows need an episode number and broadcast date')
            if row[7] and (not isinstance(row[7], str) or not row[7].startswith('https://')):
                fail(path, 'cover images require an HTTPS URL')
            text(row[7], path + '.cover', 2000, empty=True)
    elif tag == 'deals':
        # [id, name, discount_percent, final_price, original_price, sale_ends, cover_url], copied from the games read.
        sequence(value, path, 2, 2)
        sequence(value[1], path + '.items', 1, 50)
        for row in value[1]:
            sequence(row, path + '.row', 7, 7)
            if not isinstance(row[0], str) or not re.fullmatch(r'steam:\d{1,9}', row[0]):
                fail(path, 'deal rows need a Steam app ID')
            if type(row[2]) is not int or not 1 <= row[2] <= 100:
                fail(path, 'deal rows need a discount percent')
            text(row[1], path + '.name', 300)
            text(row[3], path + '.price', 40)
            text(row[4], path + '.original', 40, empty=True)
            if not isinstance(row[5], str) or row[5] and not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', row[5]):
                fail(path, 'sale end must be a local date and time or empty')
            if row[6] and (not isinstance(row[6], str) or not row[6].startswith('https://')):
                fail(path, 'cover images require an HTTPS URL')
            text(row[6], path + '.cover', 2000, empty=True)
    elif tag == 'holdings':
        # [symbol, name, session_date, shares, close, previous_close, cost_or_null, currency,
        #  dividends_counted, dividend_today, shares_may_have_changed], copied from the stocks read.
        # Briefings saved before dividends were counted end at currency.
        sequence(value, path, 2, 2)
        sequence(value[1], path + '.items', 1, 50)
        for row in value[1]:
            sequence(row, path + '.row', 8, 11)
            if len(row) not in (8, 11) or len(row) == 11 and (
                    any(type(cell) not in (int, float) or not 0 <= cell < 1e9 for cell in row[8:10]) or type(row[10]) is not bool):
                fail(path, 'holding rows need dividend amounts and a share-change flag')
            if not isinstance(row[0], str) or not re.fullmatch(r'(?:sh|sz|bj)\d{6}|us[A-Z][A-Z0-9.-]{0,9}', row[0]):
                fail(path, 'holding rows need an A-share or US symbol')
            text(row[1], path + '.name', 100)
            if not isinstance(row[2], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', row[2]):
                fail(path, 'holding rows need a session date')
            if any(type(cell) not in (int, float) or not 0 < cell < 1e9 for cell in row[3:6]) or (
                    row[6] is not None and (type(row[6]) not in (int, float) or not 0 < row[6] < 1e9)):
                fail(path, 'holding rows need positive shares, prices and an optional cost')
            if row[7] not in ('CNY', 'USD'):
                fail(path, 'holding rows need CNY or USD')
    elif tag in ('p', 'list'):
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
        fail(path, 'unknown block type; use p/list/table/agenda/tasks/weather/news/flexible/episodes/deals/holdings')


def validate(data, partial=False):
    required = {'v', 'greeting', 'opening', 'sections'}
    if not isinstance(data, dict) or not required <= data.keys() or data.keys() - required - {'closing', 'lang'}:
        fail('document', 'required keys v/greeting/opening/sections; optional closing/lang only')
    if type(data['v']) is not int or data['v'] not in (1, 2):
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
            if data['v'] == 1 and value[0] in ('actions', 'events', 'decisions', 'errands'):
                fail(path, 'source-linked blocks require native v2')
            if data['v'] == 2:
                if section[0] in ('must-do', 'nice-to-do', 'reminders', 'still-open', 'tomorrow', 'notes'):
                    fail(path, 'v2 uses Schedule, Tasks, Reminders and Today review')
                owner = {'actions': ('tasks', 'today'), 'events': ('schedule',), 'decisions': ('attention',), 'errands': ('tasks',)}
                if value[0] in ('tasks', 'flexible', 'agenda'):
                    fail(path, 'v2 actions/events require source-linked blocks')
                if value[0] in owner and section[0] not in owner[value[0]]:
                    fail(path, 'source-linked block has the wrong section owner')
            if (value[0] == 'episodes') != (section[0] == 'anime') and value[0] != 'p':
                fail(path, 'episodes blocks belong in the anime section, which holds only episodes and paragraphs')
            if (value[0] == 'deals') != (section[0] == 'games') and value[0] != 'p':
                fail(path, 'deals blocks belong in the games section, which holds only deals and paragraphs')
            if (value[0] == 'holdings') != (section[0] == 'stocks') and value[0] != 'p':
                fail(path, 'holdings blocks belong in the stocks section, which holds only holdings and paragraphs')
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
    if data['v'] == 2:
        identities = set()
        for section in data['sections']:
            for value in section[1]:
                if value[0] not in ('actions', 'events', 'decisions', 'errands'):
                    continue
                for row in value[1]:
                    identity = (value[0], 'outcome' if section[0] == 'today' else 'action', row[0], row[2] if value[0] == 'actions' else '')
                    if identity in identities:
                        fail('sections', 'duplicate source card; keep one owner per occurrence')
                    identities.add(identity)
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


def _project_of(detail):
    import re as _re
    if not detail or not isinstance(detail, str):
        return ''
    match = _re.search(r'(?:Project|项目)\s*[:：]\s*([^·|\n]+)', detail)
    return match.group(1).strip() if match else ''


def _detail_for_project_group(detail, project, title=''):
    import re as _re
    if not detail or not isinstance(detail, str):
        return ''
    text = detail.strip()
    if title:
        title_norm = ' '.join(title.split())
        collapsed = ' '.join(text.split())
        if collapsed == title_norm:
            text = ''
        elif collapsed.startswith(title_norm):
            remainder = collapsed[len(title_norm):].lstrip()
            remainder = _re.sub(r'^[|·—\-–:;,.]+\s*', '', remainder)
            text = remainder
    if not text.strip():
        # Title-only duplication: nothing extra to show; structured badges follow.
        return ''
    text = _re.sub(r'\|\s*deadline\s+\d{4}-\d{2}-\d{2}(\s*\(soft\))?', '', text, flags=_re.IGNORECASE)
    text = _re.sub(r'(?:^|[·|])\s*deadline\s+\d{4}-\d{2}-\d{2}(\s*\(soft\))?', '', text, flags=_re.IGNORECASE)
    if project:
        text = _re.sub(r'(?:Project|项目)\s*[:：]\s*' + _re.escape(project), '', text)
    else:
        # Still drop any embedded project badge; the subgroup heading owns it.
        text = _re.sub(r'(?:Project|项目)\s*[:：]\s*[^·|\n]+', '', text)
    # Group heading already explains the date; drop the inline suffix.
    text = _re.sub(r'To be scheduled|No workday assigned|待安排|还没定在哪天做', '', text)
    parts = [p.strip(' \t|·—-–:;,') for p in _re.split(r'[·\n]+', text.replace('|', '·'))]
    parts = [p for p in parts if p and p not in ('.',)]
    return ' · '.join(parts).strip(' \t·|')


def _humanize_iso_in_text(text, reference=None):
    return ui.human_dates(text, reference)


def _human_due(text, reference=None):
    # Labelled deadlines read like the page's other dates; free prose keeps its own wording.
    return re.sub(r'((?:Due|Soft target|截止|弹性目标日期)\s*[:：]\s*)(\d{4}-\d{2}-\d{2})\b',
                  lambda match: match[1] + ui.day_text(match[2], reference=reference), text or '')


def _decision_display(title, detail, reference=None):
    import re as _re
    clean_title = _re.sub(r'^(?:Review calendar change|Calendar (?:change|update)|有日历变更等你确认)\s*[:：]\s*', '', (title or '').strip(), flags=_re.IGNORECASE).strip() or title
    text = _humanize_iso_in_text(detail, reference)
    parts = [p.strip() for p in _re.split(r'[·\n]+', text.replace('|', '·')) if p.strip()]
    # Bare default status adds noise; the card title already carries cancellations.
    parts = [p for p in parts if p.lower() not in ('confirmed', 'cancelled', '已确认', '已取消')]
    # Combine same-day pairs like "Fri 23 Oct 11:00 · Fri 23 Oct 12:00" into a range.
    if len(parts) >= 2:
        combined = []
        skip_next = False
        for index, part in enumerate(parts):
            if skip_next:
                skip_next = False
                continue
            nxt = parts[index + 1] if index + 1 < len(parts) else ''
            first = _re.match(r'^(.+) (\d{2}:\d{2})$', part)
            second = _re.match(r'^(.+) (\d{2}:\d{2})$', nxt)
            if first and second and first.group(1) == second.group(1):
                combined.append(f"{first.group(1)} {first.group(2)}–{second.group(2)}")
                skip_next = True
            else:
                combined.append(part)
        parts = combined
    return clean_title, ' · '.join(parts)


def _render_project_subgroups(rows, images, briefing_date, collapse=True):
    import re as _re
    # rows: [[status, title, detail]] in code-owned relevance order; keep it inside groups.
    subgroups = {}
    for status, title, detail in rows:
        project = _project_of(detail)
        subgroups.setdefault(project, []).append([status, title, _detail_for_project_group(detail, project, title)])

    def _urgency(items):
        hard_dates, soft_dates = [], []
        for _, _, detail in items:
            for match in _re.finditer(r'(Soft target|Due|弹性目标日期|截止)\s*[:：]\s*(\d{4}-\d{2}-\d{2})', detail):
                (hard_dates if match.group(1) in ('Due', '截止') else soft_dates).append(match.group(2))
        if hard_dates:
            return (False, min(hard_dates), True)
        if soft_dates:
            return (True, min(soft_dates), False)
        return (True, '9999', False)

    ordered = sorted(subgroups.items(),
                     key=lambda kv: (*_urgency(kv[1])[:2], kv[0] == '', -len(kv[1]), kv[0].lower()))
    urgencies = {id(items): _urgency(items) for _, items in ordered}
    collapsible = collapse and sum(len(items) for _, items in ordered) > 4
    body = []
    for index, (project, items) in enumerate(ordered):
        # Lift a shared due date to the heading so it is not repeated per card.
        # Compare date tokens so mixed hard/soft labels on the same date still lift (hard wins).
        dates = set()
        for _, _, detail in items:
            found = _re.findall(r'(?:Soft target|Due|弹性目标日期|截止)\s*[:：]\s*(\d{4}-\d{2}-\d{2})', detail)
            dates.add(found[0] if len(found) == 1 else '')
        shared_date = next(iter(dates)) if len(dates) == 1 and next(iter(dates)) else ''
        shared_due = ''
        if shared_date:
            hards = sum('Due' in d or '截止' in d for _, _, d in items)
            at = next((_re.search(r'(?:Due|截止)\s*[:：]\s*\S+', d) for _, _, d in items if _re.search(r'(?:Due|截止)\s*[:：]', d)), None)
            soft = next((_re.search(r'(?:Soft target|弹性目标日期)\s*[:：]\s*\S+', d) for _, _, d in items if _re.search(r'(?:Soft target|弹性目标日期)\s*[:：]', d)), None)
            picked = (at.group(0) if at else None) if hards else (soft.group(0) if soft else None)
            shared_due = picked.strip() if picked else ''
        display_items = []
        for status, title, detail in items:
            if shared_due:
                detail = detail.replace(shared_due, '')
                parts = [p.strip(' \t|·—-–:;,') for p in _re.split(r'[·\n]+', detail.replace('|', '·'))]
                detail = ' · '.join(p for p in parts if p).strip(' \t·|')
            display_items.append([status, title, detail])
        label = project if project else ui.ui('General')
        count = f'<span class="project-count">{len(display_items)}</span>'
        due_badge = f' <span class="project-due">{escaped(_human_due(shared_due, briefing_date))}</span>' if shared_due else ''
        heading = f'<span class="project-name" data-content>{escaped(project) if project else label}</span>{due_badge} {count}'
        task_list = render_block(['tasks', display_items], images, briefing_date)
        if len(ordered) == 1 and not project:
            body.append(task_list)
        elif collapsible:
            has_hard = urgencies[id(items)][2]
            open_attr = ' open' if (index < 2 or has_hard) else ''
            body.append(f'<details class="task-project"{open_attr}><summary class="task-project-heading">{heading}</summary>{task_list}</details>')
        else:
            body.append(f'<div class="task-project"><h4 class="task-project-heading">{heading}</h4>{task_list}</div>')
    return ''.join(body)


HEADS_UP = ('Heads-up only; nothing to tick off', 'Heads-up: this can only be done on its day')


def later(day, briefing_date):
    """A day after tomorrow: shown early because the user asked for advance notice."""
    try:
        return bool(briefing_date and day and (Date.fromisoformat(day) - Date.fromisoformat(briefing_date)).days > 1)
    except ValueError:
        return False


def action_day(day, briefing_date):
    if not day:
        return ui.ui('To be scheduled')
    if briefing_date and day < briefing_date:
        return ui.ui('Still open') + ' — ' + ui.agenda_day(day)
    if later(day, briefing_date):
        return ui.ui('Coming up') + ' — ' + ui.agenda_day(day)
    return ui.agenda_day(day, briefing_date)


def holdings_markup(rows, briefing_date):
    """Each market's latest closed session: totals first, then every holding's day and total gain/loss."""
    def signed(amount, symbol='', suffix=''):
        sign = '+' if amount > 0.005 else '−' if amount < -0.005 else ''
        return f'{sign}{symbol}{abs(amount):,.2f}{suffix}'

    def trend(amount):
        return 'is-up' if amount > 0.005 else 'is-down' if amount < -0.005 else 'is-flat'

    def price(amount):
        # At least two decimals; dividends may need four (¥2.5797).
        text = f'{amount:,.4f}'.rstrip('0')
        return text + '0' * (2 - len(text.partition('.')[2]))

    def count(amount):
        return f'{amount:,}' if type(amount) is int else f'{amount:,.4f}'.rstrip('0').rstrip('.')

    markets = []
    for currency, market in (('CNY', 'A-shares'), ('USD', 'US stocks')):
        group = [row + [0, 0, False][len(row) - 8:] for row in rows if row[7] == currency]
        if not group:
            continue
        money = '¥' if currency == 'CNY' else '$'
        session = max(row[2] for row in group)
        change = sum((row[4] - row[5]) * row[3] for row in group)
        before = sum(row[5] * row[3] for row in group)
        costed = [row for row in group if row[6]]
        meta = ui.ui('Market value') + f' {money}{sum(row[4] * row[3] for row in group):,.2f}'
        if costed:
            total = sum((row[4] - row[6] + row[8]) * row[3] for row in costed)
            label = ui.ui('Total gain/loss') if len(costed) == len(group) else ui.ui('Total gain/loss ({count} with a cost)', count=len(costed))
            meta += f' · {label} <span class="{trend(total)}">{signed(total, money)}</span>'
        items = []
        for symbol, name, day, shares, close, previous, cost, _, counted, today, changed in group:
            move = (close - previous) * shares
            detail = (f'<span>{escaped(symbol[2:])}</span> · {ui.ui("{shares} shares", shares=count(shares))} · '
                      f'{ui.ui("Close {price}", price=money + price(close))}')
            if day < session:
                detail += f' · <span class="holding-paused">{ui.ui("No trading")}</span>'
            since = ''
            if cost:
                gain = close - cost + counted
                since = (f'<p class="holding-since">{ui.ui("Total")} <span class="{trend(gain)}">'
                         f'{signed(gain * shares, money)} ({signed(gain / cost * 100, suffix="%")})</span></p>')
            notes = []
            if today:
                notes.append(ui.ui('Ex-dividend {amount}/share, counted in Total' if cost and counted >= today else 'Ex-dividend {amount}/share',
                                   amount=money + price(today)))
            if changed:
                notes.append(ui.ui('Bonus or transfer shares may have changed your share count; tell your secretary your current shares'))
            since += ''.join(f'<p class="holding-note">{note}</p>' for note in notes)
            items.append(f'<li class="holding-row"><div class="holding-copy"><h4 class="holding-name" data-content>{escaped(name)}</h4>'
                         f'<p class="holding-detail">{detail}</p>{since}</div><div class="holding-change {trend(move)}">'
                         f'<span class="holding-amount">{signed(move, money)}</span>'
                         f'<span class="holding-percent">{signed((close - previous) / previous * 100, suffix="%")}</span></div></li>')
        markets.append(f'<div class="holding-market"><div class="holding-summary"><h3>{ui.ui(market)} · {ui.day_label(session, reference=briefing_date)}</h3>'
                       f'<p class="holding-total {trend(change)}"><span class="holding-amount">{signed(change, money)}</span>'
                       f'<span class="holding-percent">{signed(change / before * 100, suffix="%")}</span></p>'
                       f'<p class="holding-meta">{meta}</p></div><ul class="holding-list">{"".join(items)}</ul></div>')
    return '<div class="holdings">' + ''.join(markets) + '</div>'


def render_block(value, images, briefing_date=None):
    tag = value[0]
    if tag == 'actions':
        groups = {}
        for row in value[1]:
            groups.setdefault(row[3], []).append([row[4], row[5], row[6]])
        # Only the undated backlog folds away; everything on a dated day stays visible.
        return ''.join('<div class="action-group"><h3 class="agenda-day">' + action_day(day, briefing_date) + '</h3>' +
                       _render_project_subgroups(rows, images, briefing_date, collapse=not day) + '</div>' for day, rows in groups.items())
    if tag == 'errands':
        items = []
        for _, _, title, finding, links, _ in value[1]:
            if not finding:
                continue  # Checked, but nothing the user asked to hear.
            cited = ' ' + citations(links) if links else ''
            items.append(f'<li class="task-card task"><div class="task-title"><span class="check is-note" aria-hidden="true"></span>{escaped(title)}</div>'
                         f'<div class="task-detail">{escaped(finding)}{cited}</div></li>')
        return ('<div class="action-group"><h3 class="agenda-day">' + ui.ui('Checked for you this morning') + '</h3>'
                '<ul class="task-list">' + ''.join(items) + '</ul></div>') if items else ''
    if tag == 'events':
        return render_block(['agenda', [r[2:] for r in value[1]]], images, briefing_date)
    if tag == 'decisions':
        items = []
        for row in value[1]:
            disp_title, disp_detail = _decision_display(row[2], row[3], briefing_date)
            # Short facts (source, time, place) share a line; each longer explanation gets its own.
            parts = disp_detail.split(' · ') if disp_detail else []
            short, long = [p for p in parts if len(p) <= 32], [p for p in parts if len(p) > 32]
            detail = (f'<div class="decision-meta">{escaped(" · ".join(short))}</div>' if short else '') + ''.join(f'<div class="decision-detail">{escaped(p)}</div>' for p in long)
            ask = (f'<a class="decision-ask" href="/chat" data-quick-ask="Let’s look at “{{title}}” together." data-quick-ask-title="{escaped(disp_title)}">'
                   + ui.ui('Review with your secretary') + '</a>')
            items.append('<li class="decision-card"><div class="decision-title">' + escaped(disp_title) + '</div>' + detail + ask + '</li>')
        return '<ul class="decision-list">' + ''.join(items) + '</ul>'
    if tag == 'p':
        return '<p>' + escaped(value[1]) + (' ' + citations(value[2]) if len(value) == 3 else '') + '</p>'
    if tag == 'list':
        return '<ul>' + ''.join('<li>' + escaped(item) + '</li>' for item in value[1]) + '</ul>'
    if tag == 'tasks':
        items = []
        for status, title, detail in value[1]:
            status_label='Completed' if status=='done' else 'Not completed'
            tick = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="m5 12.5 4.5 4.5L19 7"/></svg>' if status=='done' else ''
            # A read-only status dot; nothing here looks like a checkbox to tick.
            mark = '<span class="check'+(' is-'+status if status in ('done', 'partial', 'blocked') else '')+'" role="img" data-ui-aria-label="'+status_label+'" aria-label="'+ui.text(status_label)+'">'+tick+'</span>'
            if status == 'open' and any(detail.startswith(ui.text(note, lang=lang)) for note in HEADS_UP for lang in ('en', 'zh-CN')):
                mark = '<span class="check is-note" aria-hidden="true"></span>'  # Same circle, but no "Not completed" status to announce.
            label = '<span class="task-status">' + ui.ui(status.capitalize()) + '</span> ' if status in ('partial', 'blocked') else ''
            detail_html = f'<div class="task-detail">{label}{escaped(_human_due(detail, briefing_date))}</div>' if (detail or label) else ''
            items.append(f'<li class="task-card task"><div class="task-title">{mark}{escaped(title)}</div>{detail_html}</li>')
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
                heading='<h3 class="agenda-day">'+icon('calendar')+(ui.ui('Coming up')+' — ' if later(date,briefing_date) else '')+ui.agenda_day(date,briefing_date)+'</h3>' if date else ''
                groups.append('<div class="agenda-group">'+heading+'<ol class="agenda-events">')
                previous=date
            # The day heading already names the date, so cards don't repeat it.
            fields = [(labels[3], place, 'pin'), (labels[4], prep, 'list')] if date else [(labels[0], date, 'calendar'), (labels[3], place, 'pin'), (labels[4], prep, 'list')]
            detail = ''.join(f'<div class="event-detail">{icon(symbol)}<div><span class="detail-label">{escaped(label) if len(value)==3 else ui.ui(label)}</span><div>{escaped(content)}</div></div></div>' for label, content, symbol in fields if content)
            groups.append(f'<li class="agenda-event"><div class="event-time">{icon("clock")}<span>{escaped(time)}</span></div><div class="event-copy"><h4>{escaped(event)}</h4>{detail}</div></li>')
        return '<div class="agenda">' + ''.join(groups) + '</ol></div></div>'
    if tag == 'weather':
        cards = []
        for row in value[1]:
            card, metric, detail, *custom = row
            label, symbol, style = WEATHER[card]
            main, sub = weather_parts(card, metric) if metric is not None else (None, None)
            if main is None:
                metric = ''
            elif sub:
                metric = ('<p class="weather-value"><span class="weather-main">' + escaped(main) +
                          '</span><span class="weather-sub">' + escaped(sub) + '</span></p>')
            else:
                metric = '<p class="weather-value"><span class="weather-main">' + escaped(main) + '</span></p>'
            cards.append(f'<div class="weather-tile {style}"><div class="weather-label">{icon(symbol)}<h3>{escaped(custom[0]) if custom else ui.ui(label)}</h3></div>{metric}<div class="weather-detail"><p>{escaped(detail)}</p></div></div>')
        return '<div class="weather-tiles">' + ''.join(cards) + '</div>'
    if tag == 'episodes':
        cards = []
        for _, title, local, episode, episode_title, episode_local, aired, cover in value[1]:
            # The original name leads; the website-language name follows as a small notation.
            names = f'<h4 class="episode-show" data-content>{escaped(title)}</h4>'
            if local:
                names += f'<p class="episode-show-local" data-content>{escaped(local)}</p>'
            line = f'<span class="episode-number">{ui.ui("Episode {number}", number=episode)}</span>'
            if episode_title:
                line += f'<span class="episode-name" data-content>{escaped(episode_title)}</span>'
            if episode_local:
                line += f'<span class="episode-name-local" data-content>{escaped(episode_local)}</span>'
            day, _, clock = aired.partition('T')
            when = ui.day_label(day, reference=briefing_date) + (' ' + clock if clock else '')
            cards.append(f'<li class="episode-card">{episode_visual(cover, title, images)}<div class="episode-copy">{names}'
                         f'<p class="episode-line">{line}</p><p class="episode-aired">{icon("clock")}<span>{when}</span></p></div></li>')
        return '<ul class="episode-list">' + ''.join(cards) + '</ul>'
    if tag == 'deals':
        cards = []
        for _, name, discount, price, original, ends, cover in value[1]:
            prices = f'<span class="deal-discount">−{discount}%</span><span class="deal-price">{escaped(price)}</span>'
            if original:
                prices += f'<s class="deal-original">{escaped(original)}</s>'
            when = ''
            if ends:
                day, _, clock = ends.partition('T')
                when = (f'<p class="deal-ends">{icon("clock")}<span>{ui.ui("Sale ends")} '
                        f'{ui.day_label(day, reference=briefing_date)} {clock}</span></p>')
            cards.append(f'<li class="deal-card">{deal_visual(cover, name, images)}<div class="deal-copy">'
                         f'<h4 class="deal-name" data-content>{escaped(name)}</h4><p class="deal-line">{prices}</p>{when}</div></li>')
        return '<ul class="deal-list">' + ''.join(cards) + '</ul>'
    if tag == 'holdings':
        return holdings_markup(value[1], briefing_date)
    if tag == 'news':
        from .briefing_layout import country_flag
        category = value[1]
        symbol = country_flag(value[3]) if len(value) == 4 else category_icon(category)
        cards = []
        for headline, summary, refs in value[2]:
            picture = news_visual(refs[0][1], escaped(refs[0][0]), images)
            cards.append(f'<li class="news-card{"" if picture else " text-only"}">{picture}<div class="news-copy"><h4>{escaped(headline)}</h4><div class="news-summary"><p>{escaped(summary)}</p></div><div class="news-source">{citations(refs)}</div></div></li>')
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


def cover_urls(data):
    """Anime and game covers, which are images themselves rather than pages to preview."""
    cell = {'episodes': 7, 'deals': 6}
    return list(dict.fromkeys(row[cell[value[0]]] for section in data['sections'] for value in section[1]
                             if value[0] in cell for row in value[1] if row[cell[value[0]]]))[:32]


def image_urls(data):
    """Every image a rendered edition may show: publisher previews and anime and game covers."""
    return news_urls(data) + cover_urls(data)
