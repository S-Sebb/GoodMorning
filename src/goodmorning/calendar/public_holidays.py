"""Public holidays and China's make-up workdays from bundled data.

They are worked out whenever a day is shown and never saved to the calendar. The
profile's `holiday_countries` chooses them: comma-separated region codes such as
`CN, GB-SCT`; empty (never asked) and `none` (declined) show nothing.
"""
import argparse
import json
from pathlib import Path

DATA = json.loads((Path(__file__).parent / 'public_holidays.json').read_text(encoding='utf-8'))
REGIONS = DATA['regions']


def regions(value):
    text = (value or '').strip()
    if text.lower() in ('', 'none'):
        return []
    codes = list(dict.fromkeys(code.strip().upper() for code in text.replace(';', ',').split(',') if code.strip()))
    unknown = [code for code in codes if code not in REGIONS]
    if unknown:
        raise ValueError('unknown holiday region: ' + ', '.join(unknown))
    return codes


def named(value, lang):
    return DATA['names'][value] if lang == 'zh-CN' else value


def choice(code, lang):
    """A region as the user picks it: its country, then the region when the country has several."""
    region = REGIONS[code]
    country = named(region['country'], lang)
    return country if region['label'] == region['country'] else country + ' — ' + named(region['label'], lang)


def days(codes, start, end, lang):
    """{date: [entry]} for start <= date < end (ISO dates); each entry names its day and region."""
    result = {}
    for code in codes:
        region = REGIONS[code]
        for kind, listed in (('holiday', region['days']), ('workday', region['workdays'])):
            for day, name in listed.items():
                if start <= day < end:
                    result.setdefault(day, []).append({'kind': kind, 'key': name, 'name': named(name, lang), 'region': code,
                                                       'label': named(region['label'], lang)})
    return {day: result[day] for day in sorted(result)}


def shown(entries, codes, lang):
    """One day's entries as shown: a holiday shared by several followed regions appears once, and names
    its regions only when some followed region does not have it."""
    groups = {}
    for entry in entries:
        groups.setdefault((entry['kind'], entry['key']), []).append(entry)
    result = []
    for (kind, _), group in groups.items():
        labels = ('、' if lang == 'zh-CN' else ', ').join(dict.fromkeys(entry['label'] for entry in group))
        result.append({'kind': kind, 'regions': [entry['region'] for entry in group],
                       'title': group[0]['name'] + (' · ' + labels if len(group) < len(codes) else '')})
    return result


def unlisted(codes, start, end):
    """[(region code, year)] the range touches but the data does not list yet, such as China before its announcement."""
    years = range(int(start[:4]), int(end[:4]) + 1)
    return [(code, year) for code in codes for year in years if year not in REGIONS[code]['years']]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Public-holiday regions for the profile line holiday_countries')
    parser.add_argument('--website-language', choices=('en', 'zh-CN'), default='en')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--list', action='store_true', help='Every region that can be followed')
    action.add_argument('--check', help='Validate comma-separated region codes and return the line to save')
    args = parser.parse_args(argv)
    if args.list:
        result = {'regions': [{'code': code, 'name': choice(code, args.website_language)} for code in REGIONS]}
    else:
        try:
            codes = regions(args.check)
        except ValueError as error:
            print(json.dumps({'error': 'unknown_region', 'next': f'{error}; use codes from --list'}, ensure_ascii=False))
            return 1
        result = {'save': ', '.join(codes) or 'none',
                  'regions': [{'code': code, 'name': choice(code, args.website_language)} for code in codes]}
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
