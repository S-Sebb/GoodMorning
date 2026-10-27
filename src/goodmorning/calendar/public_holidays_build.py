"""Rebuild the bundled public-holiday data from the python-holidays library.

Maintainers only; the website reads the JSON it writes with the standard library:

    uv run --no-project --with holidays==0.107 python src/goodmorning/calendar/public_holidays_build.py

China's days off and make-up workdays exist only once the State Council publishes
them, usually in November for the next year; list a year in CHINA_YEARS only after
checking the library against that announcement. Chinese names stay in the file's
`names`; the script reports any it lacks and keeps the old file unchanged.
"""
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import sys

import holidays

OUTPUT = Path(__file__).with_name('public_holidays.json')
YEARS = (2026, 2027)
CHINA_YEARS = (2026,)
COUNTRIES = {'CN': 'China', 'US': 'United States', 'GB': 'United Kingdom', 'AU': 'Australia', 'CA': 'Canada'}
REGIONS = {'GB': ('ENG', 'WLS', 'SCT', 'NIR'), 'AU': ('ACT', 'NSW', 'NT', 'QLD', 'SA', 'TAS', 'VIC', 'WA'),
           'CA': ('AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT')}
# A run of days off in China is named after its festival; the make-up workdays too.
CHINA_RUNS = {"New Year's Day": 'New Year', 'Chinese New Year (Spring Festival)': 'Spring Festival',
              "Chinese New Year's Eve": 'Spring Festival', 'Tomb-Sweeping Day': 'Qingming Festival',
              'Labor Day': 'Labor Day', 'Dragon Boat Festival': 'Dragon Boat Festival',
              'Mid-Autumn Festival': 'Mid-Autumn Festival', 'National Day': 'National Day'}


def china():
    days, workdays = {}, {}
    for year in CHINA_YEARS:
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


def main():
    previous = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {'names': {}}
    regions = {}
    days, workdays = china()
    regions['CN'] = {'country': 'China', 'label': 'China', 'years': list(CHINA_YEARS), 'days': days, 'workdays': workdays}
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
    chinese = dict(holidays.country_holidays('CN', language='zh_CN', years=CHINA_YEARS[0]).items())
    english = dict(holidays.country_holidays('CN', language='en_US', years=CHINA_YEARS[0]).items())
    names = {**{english[day]: chinese[day] for day in english if english[day] in CHINA_RUNS}, **previous['names']}
    names = {name: names[name] for name in sorted(used) if name in names}
    missing = sorted(used - set(names))
    if missing:
        print(json.dumps(missing, ensure_ascii=False, indent=2))
        raise SystemExit(f'{len(missing)} names need Chinese wording in {OUTPUT.name}; nothing was written')
    data = {'source': f'python-holidays {holidays.__version__}', 'regions': regions, 'names': names}
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n')
    print(f'{OUTPUT.name}: {len(regions)} regions, {len(names)} names')


if __name__ == '__main__':
    sys.exit(main())
