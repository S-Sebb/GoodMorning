"""Today's briefings as plain rows for the Android widgets: no markup, no hidden record IDs.

Each row is {'style': 'heading'|'story'|'item'|'text', 'side', 'title', 'text'}: a news category heading,
a news story whose 'source' names its publishers, a card with an optional short leading label (time,
status, value), or a paragraph.
"""
from goodmorning.briefings import briefing_document as native
from goodmorning.briefings.briefing_web import KINDS
from . import language as ui

MARKS = {'open': '○', 'partial': '◐', 'blocked': '!', 'done': '✓'}
TEXT_LIMIT = 1500


def _row(style, title='', text='', side=''):
    return {'style': style, 'side': side, 'title': title[:TEXT_LIMIT], 'text': text[:TEXT_LIMIT]}


def _joined(*parts):
    return ' · '.join(part for part in parts if part)


def _rows(block, date):
    tag, items = block[0], block[1]
    if tag == 'p':
        return [_row('text', text=items)]
    if tag == 'list':
        return [_row('item', item, side='•') for item in items]
    if tag == 'table':
        return [_row('item', row[0], _joined(*row[1:])) for row in block[2]]
    if tag == 'agenda':  # [date, time, event, place, preparation]
        return [_row('item', row[2], _joined(row[3], row[4]), row[1]) for row in items]
    if tag in ('tasks', 'flexible'):
        return [_row('item', row[-2], row[-1], MARKS[row[-3]]) for row in items]
    if tag == 'weather':
        rows = []
        for row in items:
            # A saved forecast frame gives the same headlines as the page; older briefings keep their values.
            summary = native.weather_summary(row[0], block[2], ui.text) if len(block) == 3 else None
            label = row[3] if len(row) == 4 else ui.text(native.WEATHER[row[0]][0])
            rows.append(_row('item', label, _joined(summary[1], row[2]), summary[0]) if summary else _row('item', label, row[2], row[1] or '—'))
        return rows
    if tag == 'news':
        return [_row('heading', items)] + [{**_row('story', story[0], story[1]), 'source': _joined(*(ref[0] for ref in story[2]))}
                                           for story in block[2]]
    if tag == 'actions':
        return [_row('item', row[5], row[6], MARKS[row[4]]) for row in items]
    if tag == 'events':
        return [_row('item', row[4], _joined(row[5], row[6]), row[3]) for row in items]
    if tag == 'decisions':
        return [_row('item', *native._decision_display(row[2], row[3], date)) for row in items]
    if tag == 'errands':
        return [_row('item', row[2], row[3]) for row in items if row[3]]
    if tag == 'episodes':
        return [_row('item', row[2] or row[1], row[5] or row[4], '#' + row[3]) for row in items]
    if tag == 'deals':
        return [_row('item', row[1], _joined(row[3], row[4]), f'-{row[2]}%') for row in items]
    if tag == 'celebration':
        from goodmorning.records.celebrations import words
        return [_row('item', *words(item, ui.text, ui.current())) for item in items] + [_row('text', text=block[2])]
    if tag == 'holdings':
        return [_row('item', row[1], f'{row[4]:g} {row[7]}', f'{(row[4] - row[5]) / row[5] * 100:+.1f}%') for row in items]
    return []


def document(data, date, kinds=None):
    """The edition's text in reading order; kinds keeps only those section types."""
    language = data.get('lang') or ui.current()
    sections = []
    for section in data['sections']:
        if kinds and section[0] not in kinds:
            continue
        rows = [row for block in section[1] for row in _rows(block, date)]
        sections.append({'type': section[0], 'title': native.section_title(section, date, language),
                         'note': section[2] if len(section) > 2 else '', 'rows': rows})
    return {'greeting': data['greeting'], 'opening': data['opening'], 'closing': data.get('closing', ''), 'sections': sections}


def summary(app):
    """Both of today's editions: their text once saved, otherwise how far generation has come."""
    date = app.today()
    editions = {}
    for kind in KINDS:
        source = app.source(date, kind)
        job = app.jobs.get(date + '.' + kind)
        state = app.status(job['id'])['state'] if job else 'missing'
        if source.is_file() and (state in ('ready', 'missing') or not app.preflight):
            editions[kind] = {'state': 'ready', **document(native.parse(source.read_text()), date)}
        elif state in ('ready', 'missing'):
            editions[kind] = {'state': 'missing'}
        else:
            # waiting: a question before the briefing; stopped: open the page to check.
            editions[kind] = {'state': 'waiting' if state == 'waiting' else 'stopped' if state in ('stopped', 'uncertain') else 'working'}
    return {'date': date, 'editions': editions}
