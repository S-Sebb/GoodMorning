"""Rebuild the bundled public-holiday data from the python-holidays library.

Maintainers and the weekly Holiday data workflow only; the website reads the JSON it
writes with the standard library:

    uv run --no-project --with holidays==0.107 python src/goodmorning/calendar/public_holidays_build.py

It prints in plain words what changed against the previous file. China's days off and
make-up workdays exist only once the State Council publishes them, usually in November
for the next year; the library lists a year's make-up workdays only then, so China lists
only those years. Chinese names stay in the file's `names`; a new name without Chinese
wording is written without it and reported, so the name test fails until it is worded.
"""
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import sys

import holidays

OUTPUT = Path(__file__).with_name('public_holidays.json')
# This year and next; earlier years stay listed.
YEARS = tuple(range(2026, date.today().year + 2))
COUNTRIES = {'CN': 'China', 'US': 'United States', 'GB': 'United Kingdom', 'AU': 'Australia', 'CA': 'Canada'}
REGIONS = {'GB': ('ENG', 'WLS', 'SCT', 'NIR'), 'AU': ('ACT', 'NSW', 'NT', 'QLD', 'SA', 'TAS', 'VIC', 'WA'),
           'CA': ('AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT')}
# A run of days off in China is named after its festival; the make-up workdays too.
CHINA_RUNS = {"New Year's Day": 'New Year', 'Chinese New Year (Spring Festival)': 'Spring Festival',
              "Chinese New Year's Eve": 'Spring Festival', 'Tomb-Sweeping Day': 'Qingming Festival',
              'Labor Day': 'Labor Day', 'Dragon Boat Festival': 'Dragon Boat Festival',
              'Mid-Autumn Festival': 'Mid-Autumn Festival', 'National Day': 'National Day'}


def china_years():
    workdays = holidays.country_holidays('CN', years=YEARS).weekend_workdays
    return [year for year in YEARS if any(day.year == year for day in workdays)]


def china(years):
    days, workdays = {}, {}
    for year in years:
        listed = holidays.country_holidays('CN', years=year, language='en_US')
        festival = {day: CHINA_RUNS[name] for day, name in listed.items() if name in CHINA_RUNS}
        for day, name in listed.items():
            moved = re.fullmatch(r'Day off \(substituted from (\d\d/\d\d/\d{4})\)', name)
            if moved:
                source = datetime.strptime(moved[1], '%m/%d/%Y').date()
                nearest = min(festival, key=lambda other: abs((other - day).days))
                workdays[source] = festival[nearest]
            days[day] = name if name in CHINA_RUNS else None
        for day in days:
            if days[day] is None:
                days[day] = festival[min(festival, key=lambda other: abs((other - day).days))] + ' holiday'
        missing = {day for day in listed.weekend_workdays if day.year == year} - set(workdays)
        if missing:
            raise SystemExit(f'make-up workdays without a festival: {sorted(missing)}')
    # The announced runs include the weekend days that join or border them.
    for day in sorted(days):
        for step in (1, -1):
            other = day + timedelta(days=step)
            while other.weekday() >= 5 and other not in days and other not in workdays:
                days[other] = run_name(days[day])
                other += timedelta(days=step)
    return ({day.isoformat(): days[day] for day in sorted(days)},
            {day.isoformat(): workdays[day] + ' make-up workday' for day in sorted(workdays)})


def run_name(name):
    return name if name.endswith(' holiday') else CHINA_RUNS[name] + ' holiday'


def listed(country, region=None):
    days = {}
    for year in YEARS:
        language = 'en_GB' if country == 'GB' else 'en_US'
        for day, name in holidays.country_holidays(country, subdiv=region, years=year, language=language).items():
            days[day.isoformat()] = name
    return dict(sorted(days.items()))


def changes(previous, data):
    """Plain-words lines on the regions and years a rebuild adds, changes or drops."""
    places = {}
    for code, region in data['regions'].items():
        old = previous.get('regions', {}).get(code, {'years': [], 'days': {}, 'workdays': {}})
        place = region['label'] if region['label'] == region['country'] else f"{region['label']} ({region['country']})"
        dated = lambda listing, year: {day: name for day, name in listing.items() if day.startswith(str(year))}
        for year in sorted({*old['years'], *region['years']}):
            if year not in old['years']:
                workdays = len(dated(region['workdays'], year))
                what = f'Adds {year} for {{}}' + (f', with its {workdays} make-up workdays (调休上班)' if workdays else '')
            elif year not in region['years']:
                what = f'Drops {year} for {{}}'
            elif any(dated(old[key], year) != dated(region[key], year) for key in ('days', 'workdays')):
                what = f'Changes dates in {year} for {{}}'
            else:
                continue
            places.setdefault(what, []).append(place)
    return ['- ' + what.format(', '.join(names)) + '.' for what, names in places.items()]


def main():
    previous = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {'names': {}}
    regions = {}
    cn_years = china_years()
    days, workdays = china(cn_years)
    regions['CN'] = {'country': 'China', 'label': 'China', 'years': cn_years, 'days': days, 'workdays': workdays}
    regions['US'] = {'country': 'United States', 'label': 'United States', 'years': list(YEARS), 'days': listed('US'), 'workdays': {}}
    for country, codes in REGIONS.items():
        aliases = {}
        for name, code in holidays.country_holidays(country).subdivisions_aliases.items():
            aliases.setdefault(code, name)  # English first; Canada also lists French names.
        for code in codes:
            regions[f'{country}-{code}'] = {'country': COUNTRIES[country], 'label': aliases[code], 'years': list(YEARS),
                                            'days': listed(country, code), 'workdays': {}}
    used = {value for region in regions.values() for value in (region['country'], region['label'],
            *region['days'].values(), *region['workdays'].values())}
    chinese = dict(holidays.country_holidays('CN', language='zh_CN', years=YEARS[0]).items())
    english = dict(holidays.country_holidays('CN', language='en_US', years=YEARS[0]).items())
    names = {**{english[day]: chinese[day] for day in english if english[day] in CHINA_RUNS}, **previous['names']}
    names = {name: names[name] for name in sorted(used) if name in names}
    if (regions, names) == (previous.get('regions'), previous['names']):
        print('No changes.')  # A new library release alone does not rewrite the file.
        return
    data = {'source': f'python-holidays {holidays.__version__}', 'regions': regions, 'names': names}
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n')
    lines = changes(previous, data)
    missing = sorted(used - set(names))
    if missing:
        lines.append('- Needs Chinese wording before merging: ' + ', '.join(f'"{name}"' for name in missing) + '.')
    was = '' if data['source'] == previous.get('source') else f" (was {previous.get('source', 'nothing')})"
    print('\n'.join([f"Built from {data['source']}{was}.", *lines]))


if __name__ == '__main__':
    sys.exit(main())
