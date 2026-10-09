"""Bounded expansion of common Thunderbird recurrence properties (stdlib only).

Unknown rule parts fail closed. This is not a general ICS file parser.
"""

import calendar
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

WEEKDAYS = {name: n for n, name in enumerate(('MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'))}
MAX_DAYS = 200000
MAX_OCCURRENCES = 10000


def recurrence_zone(name, fallback):
    if not name or name == 'floating':
        return fallback
    if name in ('UTC', 'Etc/UTC', 'Z'):
        return timezone.utc
    # Thunderbird can store a VTIMEZONE component instead of a bare TZID.
    match = re.search(r'(?:^|\n)TZID:([^\r\n]+)', name)
    if match:
        name = match[1]
    # Older Mozilla TZIDs prefix the IANA identifier with a version.
    if name.startswith('/mozilla.org/'):
        name = '/'.join(name.split('/')[3:])
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError) as exc:
        raise ValueError('unsupported Betterbird recurrence timezone; nothing imported') from exc


def occurrence_id(stamp, floating=False):
    if floating:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return str(int(stamp.astimezone(timezone.utc).timestamp() * 1000000))


def _date(value, zone, date_only=False):
    if re.fullmatch(r'\d{8}', value):
        return datetime.strptime(value, '%Y%m%d').replace(tzinfo=zone)
    if date_only:
        raise ValueError('all-day recurrence requires DATE values')
    if re.fullmatch(r'\d{8}T\d{6}Z?', value):
        utc = value.endswith('Z')
        return datetime.strptime(value.rstrip('Z'), '%Y%m%dT%H%M%S').replace(
            tzinfo=timezone.utc if utc else zone).astimezone(zone)
    raise ValueError('unsupported recurrence date')


def _rule(value, seed, stop, all_day):
    pairs = [part.split('=', 1) for part in value.split(';')]
    if any(len(pair) != 2 for pair in pairs) or len({p[0] for p in pairs}) != len(pairs):
        raise ValueError('malformed recurrence rule')
    rule = dict(pairs)
    allowed = {'FREQ', 'INTERVAL', 'COUNT', 'UNTIL', 'BYDAY', 'BYMONTHDAY', 'BYMONTH', 'BYSETPOS', 'WKST'}
    if set(rule) - allowed or rule.get('FREQ') not in ('DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'):
        raise ValueError('unsupported recurrence rule frequency or component')
    freq = rule['FREQ']
    interval = int(rule.get('INTERVAL', '1'))
    count = int(rule['COUNT']) if 'COUNT' in rule else None
    if interval < 1 or (count is not None and count < 1) or ('COUNT' in rule and 'UNTIL' in rule):
        raise ValueError('invalid recurrence interval/count/until')
    until = _date(rule['UNTIL'], seed.tzinfo, all_day) if 'UNTIL' in rule else None
    wkst = WEEKDAYS.get(rule.get('WKST', 'MO'))
    if wkst is None:
        raise ValueError('invalid recurrence week start')

    def integers(key, low, high, nonzero=False):
        values = [int(v) for v in rule[key].split(',')] if key in rule else []
        if any(v < low or v > high or (nonzero and v == 0) for v in values):
            raise ValueError('invalid recurrence ' + key)
        return values

    months = integers('BYMONTH', 1, 12)
    monthdays = integers('BYMONTHDAY', -31, 31, True)
    positions = integers('BYSETPOS', -366, 366, True)
    weekdays = []
    for value in rule.get('BYDAY', '').split(',') if 'BYDAY' in rule else []:
        match = re.fullmatch(r'([+-]?\d+)?(MO|TU|WE|TH|FR|SA|SU)', value)
        if not match:
            raise ValueError('invalid recurrence BYDAY')
        ordinal = int(match[1]) if match[1] else None
        if ordinal is not None and (ordinal == 0 or abs(ordinal) > 53 or freq in ('DAILY', 'WEEKLY')):
            raise ValueError('unsupported recurrence BYDAY ordinal')
        weekdays.append((ordinal, WEEKDAYS[match[2]]))
    if freq == 'WEEKLY' and monthdays:
        raise ValueError('BYMONTHDAY is invalid for weekly recurrence')
    if positions and not (months or monthdays or weekdays):
        raise ValueError('BYSETPOS requires another BY component')
    first = seed.date()
    if (stop.date() - first).days > MAX_DAYS:
        raise ValueError('recurrence expansion exceeds history limit')
    week_anchor = first - timedelta(days=(first.weekday() - wkst) % 7)
    candidates = []
    period = None
    emitted = 0

    def selected(items):
        if positions:
            items = sorted({items[p - 1 if p > 0 else p] for p in positions if abs(p) <= len(items)})
        return [stamp for stamp in items if stamp >= seed]

    day = first
    if freq == 'WEEKLY':
        day = week_anchor
    elif freq == 'MONTHLY':
        day = first.replace(day=1)
    elif freq == 'YEARLY':
        day = first.replace(month=1, day=1)
    # Finish the last period so BYSETPOS is evaluated against its whole set.
    last = stop.date()
    if freq == 'WEEKLY':
        last += timedelta(days=6 - (last.weekday() - wkst) % 7)
    elif freq == 'MONTHLY':
        last = last.replace(day=calendar.monthrange(last.year, last.month)[1])
    elif freq == 'YEARLY':
        last = last.replace(month=12, day=31)
    while day <= last:
        distance = (day - first).days
        month_distance = (day.year - first.year) * 12 + day.month - first.month
        key = (distance if freq == 'DAILY' else (day - week_anchor).days // 7 if freq == 'WEEKLY'
               else month_distance if freq == 'MONTHLY' else day.year - first.year)
        if period is not None and key != period:
            for stamp in selected(candidates):
                if until is not None and stamp > until:
                    return
                emitted += 1
                if stamp < stop:
                    yield stamp
                if count is not None and emitted >= count:
                    return
            candidates = []
        period = key
        length = calendar.monthrange(day.year, day.month)[1]
        match_day = key % interval == 0 and (not months or day.month in months)
        if monthdays:
            match_day = match_day and (day.day in monthdays or day.day - length - 1 in monthdays)
        if weekdays:
            def weekday_match(ordinal, weekday):
                if day.weekday() != weekday:
                    return False
                if ordinal is None:
                    return True
                if freq == 'YEARLY' and not months:
                    index = (day - day.replace(month=1, day=1)).days
                    remaining = (day.replace(month=12, day=31) - day).days
                else:
                    index, remaining = day.day - 1, length - day.day
                return ordinal == index // 7 + 1 or ordinal == -(remaining // 7 + 1)
            match_day = match_day and any(weekday_match(*entry) for entry in weekdays)
        elif freq == 'WEEKLY':
            match_day = match_day and day.weekday() == first.weekday()
        if freq in ('MONTHLY', 'YEARLY') and not monthdays and not weekdays:
            match_day = match_day and day.day == first.day
        if freq == 'YEARLY' and not months and not monthdays and not weekdays:
            match_day = match_day and day.month == first.month
        if match_day:
            stamp = datetime.combine(day, seed.timetz())
            # RFC 5545: nonexistent local times are ignored and not counted.
            if stamp.astimezone(timezone.utc).astimezone(seed.tzinfo).replace(tzinfo=None) == stamp.replace(tzinfo=None):
                candidates.append(stamp)
        day += timedelta(days=1)
    for stamp in selected(candidates):
        if until is not None and stamp > until:
            return
        emitted += 1
        if stamp < stop:
            yield stamp
        if count is not None and emitted >= count:
            return


def expand(properties, seed, stop, all_day=False, floating=False):
    """Return (start, excluded) pairs. Exclusions stage explicit cancellations."""
    included = {occurrence_id(seed, floating): seed} if seed < stop else {}
    excluded = {}
    positive = False
    for raw in properties:
        line = re.sub(r'\r?\n[ \t]', '', raw).strip()
        head, sep, value = line.partition(':')
        if not sep or '\n' in line or '\r' in line:
            raise ValueError('malformed recurrence property')
        parts = head.split(';')
        kind = parts[0].upper()
        params = {}
        for part in parts[1:]:
            key, sep, val = part.partition('=')
            if not sep or key.upper() in params:
                raise ValueError('malformed recurrence parameters')
            params[key.upper()] = val.strip('"')
        if kind == 'RRULE':
            if params:
                raise ValueError('unsupported RRULE parameters')
            positive = True
            stamps = _rule(value.upper(), seed, stop, all_day)
        elif kind in ('RDATE', 'EXDATE'):
            if set(params) - {'TZID', 'VALUE'} or params.get('VALUE', 'DATE-TIME') not in ('DATE', 'DATE-TIME'):
                raise ValueError('unsupported recurrence date parameters')
            zone = recurrence_zone(params.get('TZID'), seed.tzinfo)
            stamps = [_date(v, zone, all_day or params.get('VALUE') == 'DATE') for v in value.split(',')]
            positive = positive or kind == 'RDATE'
        else:
            raise ValueError('unsupported recurrence property ' + kind)
        target = excluded if kind == 'EXDATE' else included
        for stamp in stamps:
            if stamp < stop:
                target[occurrence_id(stamp, floating)] = stamp
            if len(included) + len(excluded) > MAX_OCCURRENCES:
                raise ValueError('recurrence expansion exceeds occurrence limit')
    if not positive:
        raise ValueError('recurrence master has no supported inclusion rule')
    included.update(excluded)
    return [(stamp, key in excluded) for key, stamp in sorted(included.items(), key=lambda item: item[1])]
