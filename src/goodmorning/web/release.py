"""Public beta release history and a separate deployment fingerprint."""
import argparse
from datetime import date, timedelta
import hashlib
import json
import re
from goodmorning.paths import ROOT, WEB_ASSETS

PATCH_NOTES = WEB_ASSETS / 'patch-notes.json'
NOTE_TEXT_LIMIT = 2000
NOTE_AUTHOR_LIMIT = 40
NOTE_CATEGORIES = ('Added', 'Changed', 'Fixed', 'Removed', 'Security', 'Documentation', 'Tests', 'Notes')
_note_cache = None
VERSION_PATTERN = r'0\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'


def fingerprint(root):
    digest = hashlib.sha256()
    for directory in ('src', 'assets', 'scripts', 'docs', 'templates', 'deploy', 'skill-source', 'integrations', 'vendor', 'requirements'):
        for path in sorted((root / directory).rglob('*')):
            if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                digest.update(str(path.relative_to(root)).encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


VERSION = fingerprint(ROOT)


def version_number(value):
    if not isinstance(value, str) or not re.fullmatch(VERSION_PATTERN, value):
        raise ValueError('Use a beta version: 0.minor.patch')
    return tuple(map(int, value.split('.')))


def note_text(value):
    if not isinstance(value, str) or not value.strip() or not 1 <= len(value) <= NOTE_TEXT_LIMIT or '\x00' in value:
        raise ValueError('Bad patch note text')
    return value


def patch_notes():
    """Validated newest-first history; malformed files never break the site."""
    global _note_cache
    try:
        stat = PATCH_NOTES.stat()
        signature = (str(PATCH_NOTES), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return []
    if _note_cache is not None and _note_cache[0] == signature:
        return _note_cache[1]
    notes = []
    try:
        payload = json.loads(PATCH_NOTES.read_text(encoding='utf-8'))
        entries = payload.get('notes') if isinstance(payload, dict) else None
        if not isinstance(entries, list) or not entries:
            raise ValueError('No patch notes')
        previous = None
        for entry in entries:
            number = version_number(entry['version'])
            if previous is not None and number >= previous:
                raise ValueError('Patch notes must have unique descending versions')
            previous = number
            if not isinstance(entry.get('date'), str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', entry['date']):
                raise ValueError('Bad patch note date')
            date.fromisoformat(entry['date'])
            if not isinstance(entry.get('author'), str) or not entry['author'].strip() or not 1 <= len(entry['author']) <= NOTE_AUTHOR_LIMIT:
                raise ValueError('Bad patch note author')
            for key in ('title_en', 'title_zh'):
                note_text(entry.get(key))
            changes = entry.get('changes')
            if not isinstance(changes, list) or not changes:
                raise ValueError('Categorized patch notes are required')
            categories = set()
            for group in changes:
                category = group['category']
                if category not in NOTE_CATEGORIES or category in categories:
                    raise ValueError('Unknown or repeated patch note category')
                categories.add(category)
                for lang in ('en', 'zh'):
                    if not isinstance(group.get(lang), list) or not group[lang]:
                        raise ValueError('Patch note categories require bullet points')
                    for item in group[lang]:
                        note_text(item)
                if len(group['en']) != len(group['zh']):
                    raise ValueError('Patch note translations must have matching bullets')
            commits = entry.get('commits', [])
            if not isinstance(commits, list) or any(not isinstance(commit, str) or not re.fullmatch(r'[a-f0-9]{7,40}', commit) for commit in commits):
                raise ValueError('Bad patch note commits')
            from .language import text
            # Each language's whole note, as the panel lists it, must fit the text limit.
            for lang in ('en', 'zh'):
                note_text('\n\n'.join(text(group['category'], lang='zh-CN' if lang == 'zh' else 'en')
                          + ':\n' + '\n'.join('- ' + item for item in group[lang]) for group in changes))
            notes.append({key: entry[key] for key in ('version', 'date', 'author', 'title_en', 'title_zh')}
                         | {'commits': commits, 'changes': changes})
    except (ValueError, KeyError, TypeError, AttributeError, OSError, UnicodeError):
        notes = []
    _note_cache = (signature, notes)
    return notes


def release_info():
    notes = patch_notes()
    return {'version': VERSION, 'release': notes[0]['version'] if notes else None,
            'note': notes[0] if notes else None, 'notes': notes}


def acknowledge_version(value, seen=None):
    """Accept only published versions; an older tab cannot undo a newer dismissal."""
    number = version_number(value)
    if value not in {note['version'] for note in patch_notes()}:
        raise ValueError('Unknown release version')
    return seen if seen is not None and version_number(seen) > number else value


# Panel-only categories from early releases; the secretary summarizes what users see.
HIDDEN_CATEGORIES = ('Documentation', 'Tests')
WHATS_NEW_DAYS = 7
WHATS_NEW_BULLETS = 120
SEARCH_LIMIT = 20


def _bound(value, upper=False):
    """`0.75.1` is one version; `0.75` is the whole 0.75 series."""
    if not isinstance(value, str) or not re.fullmatch(r'0\.(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))?', value):
        raise ValueError('invalid_version: use 0.minor or 0.minor.patch, such as 0.75 or 0.75.0')
    numbers = tuple(map(int, value.split('.')))
    if not any(note['version'] == value or note['version'].startswith(value + '.') for note in patch_notes()):
        raise ValueError(f'version_not_found: no release {value}')
    return numbers if len(numbers) == 3 else (0, numbers[1], float('inf') if upper else 0)


def _summary(note, lang):
    entry = {'version': note['version'], 'date': note['date'], 'title': note['title_' + lang]}
    for group in note['changes']:
        if group['category'] not in HIDDEN_CATEGORIES:
            entry[group['category'].lower()] = group[lang]
    return entry


def whats_new(language='en', today=None, *, version=None, after=None, start=None, end=None, last=None, since=None, search=None):
    """Bounded, newest-first release notes in one website language; no other source of release facts."""
    notes = patch_notes()
    if not notes:
        raise ValueError('notes_unavailable: the release notes could not be read')
    lang = 'zh' if language == 'zh-CN' else 'en'
    result = {'latest': {'version': notes[0]['version'], 'date': notes[0]['date']}}
    if search is not None:
        words = search.casefold().split()
        if not words:
            raise ValueError('invalid_search: give one or two distinctive words')
        found = [(sum(word in (english + '\n' + chinese).casefold() for word in words),
                  {'version': note['version'], 'date': note['date'], 'category': group['category'].lower(),
                   'text': chinese if lang == 'zh' else english})
                 for note in notes for group in note['changes'] if group['category'] not in HIDDEN_CATEGORIES
                 for english, chinese in zip(group['en'], group['zh'])]
        # Notes word things freely ("a letter about your week"), so rank by words matched, then newest first.
        matches = [match for score, match in sorted(found, key=lambda pair: -pair[0]) if score]
        return result | {'search': search, 'matched_total': len(matches), 'matches': matches[:SEARCH_LIMIT]}
    numbered = [(version_number(note['version']), note) for note in notes]
    if version is not None or after is not None or start is not None or end is not None:
        result['scope'] = {key: value for key, value in (('version', version), ('after', after), ('from', start), ('to', end)) if value is not None}
        if version is not None:
            start = end = version
        low = _bound(after, upper=True) if after is not None else _bound(start) if start is not None else (0, 0, 0)
        high = _bound(end, upper=True) if end is not None else (0, float('inf'), 0)
        chosen = [n for k, n in numbered if (low < k if after is not None else low <= k) and k <= high]
    elif last is not None:
        if not 1 <= last <= 20:
            raise ValueError('invalid_last: ask for 1 to 20 releases')
        chosen, result['scope'] = notes[:last], {'last': last}
    else:
        window = since is None
        if window:
            since = (date.fromisoformat(today) - timedelta(days=WHATS_NEW_DAYS - 1)).isoformat()
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', since):
            raise ValueError('invalid_date: use YYYY-MM-DD')
        chosen, result['scope'] = [note for note in notes if note['date'] >= since], {'since': since}
        if window and not chosen:
            # A quiet week still answers "what's new" with the latest release, marked as older.
            chosen, result['fallback'] = notes[:1], 'latest_release'
    releases, bullets = [], 0
    for note in chosen:
        entry = _summary(note, lang)
        size = sum(len(value) for key, value in entry.items() if isinstance(value, list))
        if releases and bullets + size > WHATS_NEW_BULLETS:
            break
        releases.append(entry)
        bullets += size
    if len(releases) < len(chosen):
        result['older_not_shown'] = len(chosen) - len(releases)
    return result | {'releases': releases}


def main(argv=None):
    parser = argparse.ArgumentParser(description="What's new: bounded release notes in the website language; read-only.")
    parser.add_argument('--secretary-dir')
    parser.add_argument('--website-language', choices=('en', 'zh-CN'), default='en')
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--version', help='One release (0.75.0) or a series (0.75)')
    scope.add_argument('--after', help='Releases newer than this version or series')
    scope.add_argument('--from', dest='start', help='Releases from this version or series on')
    parser.add_argument('--to', dest='end', help='With --after or --from, or alone: up to this version or series')
    scope.add_argument('--last', type=int, help='The newest N releases, 1-20')
    scope.add_argument('--since', help='Releases dated on or after YYYY-MM-DD')
    scope.add_argument('--search', help='Changes mentioning these words in English or Chinese, best matches first')
    args = parser.parse_args(argv)
    try:
        if args.end is not None and (args.version or args.last is not None or args.since or args.search is not None):
            raise ValueError('invalid_scope: --to combines only with --after or --from')
        from goodmorning.runtime_files import profile_fields, secretary_path
        from goodmorning.briefings.briefing_day import briefing_day
        # "Recent" counts in the user's day, which ends at 04:00 like everything else.
        today = briefing_day(profile_fields(secretary_path(args.secretary_dir)).get('timezone', ''))
        result = whats_new(args.website_language, today, version=args.version, after=args.after, start=args.start,
                           end=args.end, last=args.last, since=args.since, search=args.search)
    except ValueError as error:
        message = str(error)
        print(json.dumps({'error': message.split(':', 1)[0], 'next': message}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return 0
