"""A public content fingerprint, fixed for the lifetime of each release process."""
import hashlib
import json
import re
from goodmorning.paths import ROOT, WEB_ASSETS

PATCH_NOTES = WEB_ASSETS / 'patch-notes.json'
NOTE_TEXT_LIMIT = 2000
NOTE_AUTHOR_LIMIT = 40
_note_cache = None


def fingerprint(root):
    digest = hashlib.sha256()
    for directory in ('src', 'assets', 'scripts', 'docs', 'templates', 'deploy', 'skill-source', 'integrations', 'vendor', 'requirements'):
        for path in sorted((root / directory).rglob('*')):
            if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                digest.update(str(path.relative_to(root)).encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


VERSION = fingerprint(ROOT)


def patch_note():
    """Latest deployer-authored patch note, or None when absent/invalid.

    Each website deployment carries exactly one current note: the newest entry
    of patch-notes.json. An invalid file never breaks the release endpoint;
    it simply yields no note.
    """
    global _note_cache
    try:
        stat = PATCH_NOTES.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None
    if _note_cache is not None and _note_cache[0] == signature:
        return _note_cache[1]
    note = None
    try:
        payload = json.loads(PATCH_NOTES.read_text(encoding='utf-8'))
        entries = payload.get('notes') if isinstance(payload, dict) else None
        first = entries[0] if isinstance(entries, list) and entries else None
        if not isinstance(first, dict):
            raise ValueError('No patch notes')
        if not isinstance(first.get('date'), str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', first['date']):
            raise ValueError('Bad patch note date')
        if not isinstance(first.get('author'), str) or not 1 <= len(first['author']) <= NOTE_AUTHOR_LIMIT:
            raise ValueError('Bad patch note author')
        for text in (first.get('en'), first.get('zh')):
            if not isinstance(text, str) or not 1 <= len(text) <= NOTE_TEXT_LIMIT or '\x00' in text:
                raise ValueError('Bad patch note text')
        note = {'date': first['date'], 'author': first['author'], 'en': first['en'], 'zh': first['zh']}
    except (ValueError, KeyError, TypeError, AttributeError, OSError, UnicodeError):
        note = None
    _note_cache = (signature, note)
    return note
