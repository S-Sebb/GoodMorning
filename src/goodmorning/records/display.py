"""How a saved item reads on each page, decided once by the secretary when it records the item.

`display` holds time-neutral wording in English and Chinese for the morning briefing,
the evening briefing and the Schedule tab. Code adds dates, times and status. The
`source` fingerprint covers the fields the wording describes, so an outside change
to them (a calendar sync, a rename) makes the wording stale and pages fall back to
the saved fields. Briefings and the Schedule tab only read it.
"""
import hashlib
import json
import re

LANGUAGES = ('en', 'zh')
LIMITS = {'title': 120, 'detail': 240, 'schedule': 40}
# Relative time goes stale: morning wording also shows on later days while an item stays open, and evening
# wording can show several nights ahead. Only "tonight" always holds, and only in evening wording.
RELATIVE = re.compile(r'\b(?:today|tonight|tomorrow|yesterday|overdue)\b|今天|今晚|今早|明天|明早|明晚|后天|昨天|逾期', re.IGNORECASE)
EVENING = re.compile(r'\b(?:today|tomorrow|yesterday|overdue)\b|今天|今早|明天|明早|明晚|后天|昨天|逾期', re.IGNORECASE)
DESCRIBED = {'task': ('title', 'detail', 'kind', 'project'), 'draft': ('title', 'detail', 'location'),
             'event': ('subject', 'location', 'notes', 'online')}


def fingerprint(kind, item):
    """The fields this item's wording describes; dates and status are not among them."""
    values = [item.get(key) or '' for key in DESCRIBED[kind]]
    if kind == 'event' and values[2]:
        from goodmorning.calendar.calendar_safety import clean_preparation
        values[2] = clean_preparation(values[2])  # Reads show cleaned notes; saved and read copies must agree.
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()[:16]


def _text(value, path, limit, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()) or '\n' in value:
        raise ValueError(f'invalid_input: display {path} is {"possibly empty " if empty else ""}one-line text of at most {limit} characters')
    if (EVENING if '.evening.' in path else RELATIVE).search(value):
        raise ValueError(f'invalid_input: display {path} must not use relative time words such as today/tomorrow; pages add the date')


def check(value, kind, item):
    """Validate the secretary's wording and stamp the code-owned fingerprint when it is new."""
    if not isinstance(value, dict) or set(value) - {*LANGUAGES, 'source'} or not set(LANGUAGES) <= set(value):
        raise ValueError('invalid_input: display needs en and zh wording')
    for language in LANGUAGES:
        wording = value[language]
        if not isinstance(wording, dict) or set(wording) - {'morning', 'evening', 'schedule'} or not {'morning', 'schedule'} <= set(wording):
            raise ValueError(f'invalid_input: display.{language} needs morning and schedule, and optionally evening')
        for edition in ('morning', 'evening'):
            if edition in wording:
                card = wording[edition]
                if not isinstance(card, dict) or set(card) != {'title', 'detail'}:
                    raise ValueError(f'invalid_input: display.{language}.{edition} is {{title, detail}}')
                _text(card['title'], f'{language}.{edition}.title', LIMITS['title'])
                _text(card['detail'], f'{language}.{edition}.detail', LIMITS['detail'], empty=True)
        _text(wording['schedule'], f'{language}.schedule', LIMITS['schedule'])
    out = dict(value)
    out.setdefault('source', fingerprint(kind, item))
    if not isinstance(out['source'], str) or not re.fullmatch('[0-9a-f]{16}', out['source']):
        raise ValueError('invalid_input: display source is code-owned')
    return out


def wording(item, kind, place, language):
    """The stored wording for one place ('morning', 'evening' or 'schedule'), or None when missing or stale."""
    value = item.get('display')
    if not value or value.get('source') != fingerprint(kind, item):
        return None
    words = value.get('zh' if str(language).startswith('zh') else 'en') or {}
    if place == 'schedule':
        return words.get('schedule')
    return words.get(place) or (words.get('morning') if place == 'evening' else None)
