"""Public beta release history and a separate deployment fingerprint."""
from datetime import date
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
