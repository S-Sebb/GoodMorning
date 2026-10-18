"""Published ICS feeds (Outlook, Google, iCloud): fetch, expand and stage for review.

A feed is the whole calendar, so an event that disappears from the window is
staged as a cancellation. Unsupported content stops the batch; nothing is imported.
"""

import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, build_opener
from zoneinfo import ZoneInfo

from .calendar_recurrence import expand, occurrence_id
from .calendar_store import endpoints

MAX_BYTES = 10_000_000
FEED_DAYS = 30
WINDOWS = json.loads((Path(__file__).parent / 'windows_zones.json').read_text())
ESCAPES = {'n': '\n', 'N': '\n', ',': ',', ';': ';', '\\': '\\'}


@dataclass
class Item:
    external_id: str
    occurrence_id: str
    subject: str
    start: datetime
    end: datetime
    all_day: bool
    location: str
    notes: str
    status: str


def fetch(url):
    if not re.match(r'https?://', url):
        raise ValueError('calendar feed needs an http(s) link')
    request = Request(url, headers={'User-Agent': 'GoodMorning calendar sync'})
    with build_opener().open(request, timeout=8) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('calendar feed is too large; nothing imported')
    return data.decode('utf-8', 'replace')


def zone(name, fallback):
    if not name:
        return fallback
    name = WINDOWS.get(name, name)
    try:
        return timezone.utc if name in ('UTC', 'Etc/UTC') else ZoneInfo(name)
    except (KeyError, ValueError) as exc:
        raise ValueError(f'unsupported calendar feed timezone {name!r}; nothing imported') from exc


def lines(text):
    """Unfolded content lines as (NAME, params, value)."""
    for line in re.sub(r'\r?\n[ \t]', '', text).splitlines():
        match = re.match(r'((?:[^:"]|"[^"]*")*):(.*)', line)
        if not match:
            continue
        name, *parts = re.findall(r'(?:[^;"]|"[^"]*")+', match[1]) or ['']
        params = {key.upper(): value.strip('"') for key, _, value in (p.partition('=') for p in parts)}
        yield name.upper(), params, match[2]


def unescape(value):
    return re.sub(r'\\(.)', lambda m: ESCAPES.get(m[1], m[1]), value)


def text(value):
    return unescape(value).strip()


def stamp(value, params, fallback):
    if params.get('VALUE') == 'DATE' or re.fullmatch(r'\d{8}', value):
        return datetime.strptime(value, '%Y%m%d').replace(tzinfo=fallback), True
    if value.endswith('Z'):
        return datetime.strptime(value, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc), False
    return datetime.strptime(value, '%Y%m%dT%H%M%S').replace(tzinfo=zone(params.get('TZID'), fallback)), False


def duration(value):
    match = re.fullmatch(r'([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?', value)
    if not match:
        raise ValueError('unsupported calendar feed duration; nothing imported')
    weeks, days, hours, minutes, seconds = (int(v or 0) for v in match.groups()[1:])
    return timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds)


def events(feed, start, end, tz):
    """Every occurrence overlapping [start, end), with stable source identities."""
    components, current = [], None
    for name, params, value in lines(feed):
        if name == 'BEGIN' and value.upper() == 'VEVENT':
            current = []
        elif name == 'END' and value.upper() == 'VEVENT' and current is not None:
            components.append(current)
            current = None
        elif current is not None:
            current.append((name, params, value))
    masters, overrides, items = {}, {}, []
    for props in components:
        first = {}
        for name, params, value in props:
            first.setdefault(name, (params, value))
        if 'UID' not in first or 'DTSTART' not in first:
            raise ValueError('calendar feed event without UID or start; nothing imported')
        begin, all_day = stamp(first['DTSTART'][1], first['DTSTART'][0], tz)
        if 'DTEND' in first:
            finish = stamp(first['DTEND'][1], first['DTEND'][0], tz)[0]
        else:
            finish = begin + (duration(first['DURATION'][1]) if 'DURATION' in first else timedelta(days=all_day))
        if finish <= begin:
            raise ValueError('calendar feed event without a positive duration; nothing imported')
        item = Item(text(first['UID'][1]), '', text(first.get('SUMMARY', ({}, ''))[1]) or '(no title)', begin, finish,
                    all_day, text(first.get('LOCATION', ({}, ''))[1]), unescape(first.get('DESCRIPTION', ({}, ''))[1]),
                    'cancelled' if first.get('STATUS', ({}, ''))[1].upper() == 'CANCELLED' else 'confirmed')
        if 'RECURRENCE-ID' in first:
            original = stamp(first['RECURRENCE-ID'][1], first['RECURRENCE-ID'][0], tz)[0]
            overrides.setdefault(item.external_id, {})[occurrence_id(original)] = replace(item, occurrence_id=occurrence_id(original))
            continue
        rules = []
        for name, params, value in props:
            if name in ('RRULE', 'RDATE', 'EXDATE'):
                # The expander only knows IANA zones; feeds may name Windows zones.
                head = name + ''.join(f';{k}={getattr(zone(v, tz), "key", "UTC") if k == "TZID" else v}'
                                      for k, v in params.items())
                rules.append(head + ':' + value)
        if rules:
            masters[item.external_id] = (item, rules)
        elif item.end > start and item.start < end:
            items.append(item)
    for key, (master, rules) in masters.items():
        length = master.end - master.start
        moved = overrides.pop(key, {})
        for begin, excluded in expand(rules, master.start, end, master.all_day):
            identity = occurrence_id(begin)
            finish = (begin + length if master.all_day else
                      (begin.astimezone(timezone.utc) + length).astimezone(begin.tzinfo))
            override = moved.pop(identity, None)
            in_window = finish > start and begin < end
            if override is not None:
                if in_window or (override.end > start and override.start < end):
                    items.append(replace(override, status='cancelled') if excluded else override)
            elif in_window:
                items.append(replace(master, start=begin, end=finish, occurrence_id=identity,
                                     status='cancelled' if excluded else master.status))
        items.extend(o for o in moved.values() if o.end > start and o.start < end)
    for moved in overrides.values():
        items.extend(o for o in moved.values() if o.end > start and o.start < end)
    if len(items) > 10000:
        raise ValueError('calendar feed exceeds occurrence limit; nothing imported')
    return sorted(items, key=lambda i: (i.start, i.external_id, i.occurrence_id))


def batch(items, tzname):
    out = []
    for item in items:
        data = {'external_id': item.external_id, 'occurrence_id': item.occurrence_id, 'subject': item.subject,
                'start': item.start.isoformat(), 'end': item.end.isoformat(), 'location': item.location,
                'notes': item.notes, 'status': item.status}
        if item.all_day:
            if not tzname:
                raise ValueError('all-day feed events need the calendar timezone; nothing imported')
            data.update(all_day=True, timezone=tzname, start=item.start.date().isoformat(), end=item.end.date().isoformat())
        out.append(data)
    return out


def sync(store, source, feed, start, end, tz, tzname, actor):
    """Stage the feed's window; previously imported events missing from it become cancellations."""
    staged = batch(events(feed, start, end, tz), tzname)
    present = {(e['external_id'], e['occurrence_id']) for e in staged}
    for row in store.con.execute("SELECT external_id,occurrence_id,raw_json FROM events "
                                 "WHERE source=? AND review!='rejected' AND raw_json IS NOT NULL", (source,)):
        raw = json.loads(row['raw_json'])
        if raw.get('status') == 'cancelled' or (row['external_id'], row['occurrence_id']) in present:
            continue
        begin, finish = endpoints(raw)
        if finish > start and begin < end:
            staged.append({'external_id': row['external_id'], 'occurrence_id': row['occurrence_id'], 'status': 'cancelled'})
    result = store.stage(source, staged, actor)
    result['removed'] = len(staged) - len(present)
    return result


def refresh(runtime, day):
    """Briefing start: sync a saved feed so the edition reviews current changes. Never blocks the briefing."""
    from goodmorning.runtime_files import calendar_config, calendar_path, profile_fields
    from .calendar_store import CalendarStore
    config = calendar_config(runtime)
    path = calendar_path(runtime, config=config)
    if not config.get('ics_url') or not path.is_file():
        return None
    try:
        tzname = config.get('timezone') or profile_fields(runtime).get('timezone')
        tz = ZoneInfo(tzname)
        start = datetime.fromisoformat(day).replace(tzinfo=tz)
        feed = fetch(config['ics_url'])
        store = CalendarStore(str(path))
        try:
            return sync(store, config.get('ics_source') or 'ics', feed, start, start + timedelta(days=FEED_DAYS),
                        tz, tzname, 'calendar-feed')
        finally:
            store.close()
    except Exception as error:  # The edition still runs on the saved schedule.
        return {'unavailable': type(error).__name__}
