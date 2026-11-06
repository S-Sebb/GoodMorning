#!/usr/bin/env python3
"""Move one account's legacy projects into secretary memory, then remove the legacy copies (#290).

Run as the account's own service user with VAULT, the account's mounted vault (`/srv/goodmorning/live/<id>`), whose
`secretary/` is the runtime. Output is counts, paths and hashes only, never names or record text.

migrate --dry-run     The planned counts and a fingerprint of the plan and every file it reads.
migrate [--expect F]  With F, refuse unless the fingerprint still matches. While memory is on: back up profile.md,
                      memory.json, projects/ and projects.json to VAULT/backups/project-memory-290-<UTC>/, test-restore
                      it, add one memory entry per project with a note from its record, then delete the `## Project roots`
                      section and the backed-up projects/ and projects.json. A rerun resumes an interrupted migration.
restore BACKUP        Put every backed-up file back byte for byte, with its mode, owner and mtime, unless memory.json,
                      profile.md or the legacy files changed after the migration.
verify-backup BACKUP  Check the backup against its manifest; --restore-test also restores it into a scratch directory
                      inside the backup, compares that with the manifest and deletes it.

A project is a legacy root or a to-do label with an open, partial or blocked to-do, matched ignoring case and spacing,
with the label's spelling. Its note is its record's Goal outline and Current progress, when it passes `memory.change`'s
checks. While memory is off nothing changes. Anything unexpected (an unclear profile, foreign owners, xattrs, files
changed since the backup or memory written since) is refused, so a person can look.
    python deploy/migrate_project_memory.py --vault VAULT migrate [--dry-run | --expect F]
    python deploy/migrate_project_memory.py --vault VAULT restore|verify-backup BACKUP [--restore-test]
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.briefings.briefing_day import briefing_day  # noqa: E402
from goodmorning.records import memory  # noqa: E402
from goodmorning.records.inbox_store import InboxStore, encode  # noqa: E402
from goodmorning.runtime_files import profile_fields, runtime_lock  # noqa: E402

PREFIX = 'project-memory-290-'
HEADING = re.compile(r'## Project roots[ \t]*')
VARIANT = re.compile(r'[ \t]*#+[ \t]*project[\s_-]*roots?\b', re.I)
MENTION = re.compile(r'project[\s_-]*roots?\b', re.I)
TOP = re.compile(r'#{1,2}[ \t]')  # A `#` or `##` heading ends the section.
FENCE = re.compile(r'[ \t]{0,3}(```|~~~)')
ROOT = re.compile(r'- ([^|]*[^|\s])[ \t]*(\|.*)?')
COMMENT = re.compile(r'<!--.*?(?:-->|\Z)', re.S)
# Every version of the old project template (affa5f5 to 74596a8) fills these sections with HTML comments only.
NOTE_SECTIONS = ('Goal outline', 'Current progress')


def sha256(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def lines(text):
    """Each line as (offset, text without its line ending, whether it starts outside HTML comments and code fences)."""
    rows, offset, comment, fence = [], 0, False, False
    for line in text.splitlines(keepends=True):
        body = line.rstrip('\r\n')
        rows.append((offset, body, not comment and not fence))
        if not comment and FENCE.match(body):
            fence = not fence
        elif not fence:
            for token in re.findall(r'<!--|-->', body):
                comment = token == '<!--'
        offset += len(line)
    return rows


def section(text, has_records):
    """(start, end) of the profile's one `## Project roots` section, or None when it clearly has none."""
    rows = lines(text)
    found = [row for row in rows if VARIANT.match(row[1])]
    if len(found) > 1 or found and not (found[0][2] and HEADING.fullmatch(found[0][1])) or (
            not found and has_records and MENTION.search(text)):
        raise ValueError('profile_unclear: the Project roots heading is missing, repeated, varied, commented or fenced; '
                         'nothing was changed, inspect profile.md by hand')
    if not found:
        return None
    start = found[0][0]
    return start, next((offset for offset, body, outside in rows if offset > start and outside and TOP.match(body)), len(text))


def roots(text, span):
    """Each root name in the section, outside HTML comments and code fences."""
    return [match[1].strip() for offset, body, outside in lines(text)
            if span and span[0] < offset < span[1] and outside and (match := ROOT.fullmatch(body))]


def without_roots(text, span):
    """The profile without its Project roots section; every other byte stays."""
    return text[:span[0]] + text[span[1]:] if span else text


def legacy(runtime):
    """The legacy record paths, each directory before its contents."""
    folder, registry = runtime / 'projects', runtime / 'projects.json'
    found = ([folder, *sorted(folder.rglob('*'))] if folder.is_dir() or folder.is_symlink() else []) + (
        [registry] if registry.exists() or registry.is_symlink() else [])
    if any(path.is_symlink() for path in found):
        raise ValueError('unsafe_path: a legacy project record is a symlink; inspect it')
    return found


def records(root):
    """Each projects/*.md record by its `name:` field and by its file stem, as (text, last_update)."""
    by_name, by_stem = {}, {}
    for path in sorted((root / 'projects').glob('*.md')):
        text = path.read_bytes().decode('utf-8')
        head = text.split('\n## ', 1)[0]
        fields = {m[1].lower(): m[2].strip('"\' ') for m in re.finditer(r'^([a-z_]+)[ \t]*:[ \t]*([^\r\n]*?)[ \t]*\r?$', head, re.M | re.I)}
        try:
            updated = date.fromisoformat(fields.get('last_update', '')).isoformat()
        except ValueError:
            updated = None
        by_name.setdefault(memory.key(fields.get('name') or path.stem), (text, updated))
        by_stem.setdefault(memory.key(path.stem), (text, updated))
    return lambda name: by_name.get(memory.key(name)) or by_stem.get(memory.key(name))


def record_section(text, title):
    match = re.search(rf'^## {title}[ \t]*\r?$(.*?)(?=^## |\Z)', text, re.M | re.S | re.I)
    return '\n'.join(line.strip() for line in COMMENT.sub('', match[1]).splitlines() if line.strip()) if match else ''


def open_labels(runtime):
    """Each project label with an open, partial or blocked to-do, oldest first."""
    if not (runtime / 'inbox.sqlite').exists():
        return []
    inbox = InboxStore(runtime)
    try:
        if inbox.version != 2:
            return []  # A store from before tasks.
        rows = inbox.db.execute("SELECT json_extract(data,'$.project') FROM tasks WHERE json_extract(data,'$.status') "
                                "IN ('open','partial','blocked') ORDER BY created_at,rowid")
        return [label for (label,) in rows if label and label.strip()]
    finally:
        inbox.close()


def website_language(runtime):
    """The language of the newest chat turn, the one `memory.change` holds a chat's writes to."""
    turns = [(turn.get('created', item.get('created', 0)), turn['language'])
             for item in memory.conversations(runtime) for turn in item['turns'] if turn.get('language')]
    return max(turns)[1] if turns else 'en'


def plan(runtime, source, span, data, labels, language):
    """The memory after seeding and its counts. `source` holds the original profile.md and projects/."""
    names = {}
    for name in roots((source / 'profile.md').read_bytes().decode('utf-8'), span) + labels:
        names[memory.key(name)] = name  # A later to-do label replaces a root's spelling but keeps its place.
    find = records(source)
    today = briefing_day(profile_fields(runtime).get('timezone', ''))
    entries = [dict(entry) for entry in data['projects']]
    size = sum(len(text) for text in data['note'].values()) + sum(len(entry['note']) for entry in entries)
    counts = {'projects': len(names), 'added': 0, 'notes': 0, 'shortened': 0, 'no_note': 0, 'wrong_language': 0, 'kept': 0}
    for name in names.values():
        try:
            name = memory.project_name(name)
        except ValueError:
            counts['no_note'] += 1  # Too long for a to-do label, so add_projects would skip it too.
            continue
        entry = memory.find(entries, name)
        if not entry:
            entry = {'name': name, 'note': ''}
            entries.append(entry)
            counts['added'] += 1
        record = find(name)
        if entry['note']:
            counts['kept'] += 1  # Written in chat or on About me since #294: the user's words win.
            continue
        parts = [record_section(record[0], title) for title in NOTE_SECTIONS] if record else []
        candidates = ['\n'.join(part for part in parts if part), parts[0]] if parts else []
        note = ''
        for candidate in dict.fromkeys(candidates):
            try:
                candidate = memory.plain(name, candidate)
            except ValueError:
                continue
            if language == 'zh-CN' and candidate and not memory.chinese(candidate):
                counts['wrong_language'] += 1  # Seeding English would break the note's language; leave it to chat.
                break
            if candidate and len(candidate) <= memory.PROJECT and size + len(candidate) <= memory.LENGTH:
                note = candidate
                break
        if note:
            size += len(note)
            counts['notes'] += 1
            counts['shortened'] += note != candidates[0]
            entry['note'] = note
        else:
            counts['no_note'] += 1
        if 'updated' not in entry or note:
            entry['updated'] = record[1] if record and record[1] else today
    if len(entries) > memory.PROJECTS:
        raise ValueError(f'too_many_projects: {len(entries)} entries exceed {memory.PROJECTS}; nothing was saved')
    seeded = dict(data)
    if entries != data['projects']:
        seeded.update(projects=entries, updated=today, revision=data['revision'] + 1)
    return seeded, counts


def memory_bytes(runtime):
    target = memory.path(runtime)
    return target.read_bytes() if target.exists() else None


def fingerprint(runtime, seeded, labels, language):
    """The memory revision, profile.md's hash, and a hash of the planned memory, the labels, the language and the records."""
    digest = hashlib.sha256(json.dumps([seeded and encode(seeded), sorted(labels), language, sha256(memory_bytes(runtime))]).encode())
    for path in legacy(runtime):
        digest.update(str(path.relative_to(runtime)).encode() + b'\0' + (b'' if path.is_dir() else path.read_bytes()) + b'\0')
    profile = sha256((runtime / 'profile.md').read_bytes())
    return f'{memory.load(runtime)["revision"]}-{profile[:12]}-{digest.hexdigest()[:12]}'


def atomic_bytes(path, data, mode):
    fd, temporary = tempfile.mkstemp(prefix='.gm-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sync(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json(path, value):
    atomic_bytes(path, (json.dumps(value, indent=1, ensure_ascii=False) + '\n').encode(), 0o600)
    sync(path.parent)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def release():
    from goodmorning.web import release as notes
    return {'version': json.loads(notes.PATCH_NOTES.read_text())['notes'][0]['version'], 'fingerprint': notes.VERSION}


def xattrs(path):
    try:
        return sorted(os.listxattr(path, follow_symlinks=False))  # POSIX ACLs are system.posix_acl_* xattrs.
    except OSError:
        return []  # The filesystem has no xattrs.


def check_metadata(paths):
    """Refuse paths a restore could not recreate exactly: another owner or group, ACLs or other xattrs."""
    for path in paths:
        info = path.lstat()
        if (info.st_uid, info.st_gid) != (os.geteuid(), os.getegid()):
            raise ValueError("foreign_owner: a file to migrate is not owned by the account's service user and group; inspect it")
        if xattrs(path):
            raise ValueError('unsupported_metadata: a file to migrate has an ACL or other xattr; inspect it')


def backup(vault, runtime, sources):
    """Copy the files the migration changes into a new private backup and write its manifest last."""
    folder = vault / 'backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    target = folder / (PREFIX + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    (target / 'files').mkdir(mode=0o700, parents=True)
    files = []
    for path in sources:
        relative, info = path.relative_to(runtime), path.lstat()
        entry = {'path': str(relative), 'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid,
                 'mtime_ns': info.st_mtime_ns, 'xattrs': xattrs(path)}
        copy = target / 'files' / relative
        if stat.S_ISDIR(info.st_mode):
            copy.mkdir(mode=0o700)
            entry['type'] = 'dir'
        else:
            data = path.read_bytes()
            atomic_bytes(copy, data, 0o600)
            entry.update(type='file', size=len(data), sha256=sha256(data))
        files.append(entry)
    for directory in sorted({target / 'files' / Path(entry['path']).parent for entry in files}):
        sync(directory)
    write_json(target / 'manifest.json', {'migration': 290, 'created': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                          'release': release(), 'revision': memory.load(runtime)['revision'], 'files': files,
                                          'complete': True})
    return target


def manifest(target):
    """The manifest of a complete backup whose copies all match it."""
    data = read_json(target / 'manifest.json')
    if not data or data.get('complete') is not True:
        raise ValueError('backup_incomplete: the backup has no complete manifest; inspect it')
    for entry in data['files']:
        copy = target / 'files' / entry['path']
        if copy.is_symlink() or (not copy.is_dir() if entry['type'] == 'dir' else not copy.is_file()
                                 or sha256(copy.read_bytes()) != entry['sha256']):
            raise ValueError('backup_mismatch: a backed-up file differs from the manifest; inspect the backup')
    return data


def backed_up(data, path):
    return next((entry for entry in data['files'] if entry['path'] == path), None)


def check_memory(runtime, data, intent):
    """Memory must be as backed up, or exactly as this run seeded it: anything else is a later write to keep."""
    original = backed_up(data, 'memory.json')
    allowed = {original and original['sha256'], *([intent['memory_sha256']] if intent else [])}
    if sha256(memory_bytes(runtime)) not in allowed:
        raise ValueError(f'memory_changed: memory.json changed after the backup (now revision {memory.load(runtime)["revision"]}); '
                         'continuing would lose that write; inspect it')


def check_runtime(runtime, target, data):
    """profile.md is as backed up or without its section, and each legacy path left is a backed-up one, unchanged."""
    original = (target / 'files' / 'profile.md').read_bytes()
    text = original.decode('utf-8')
    if (runtime / 'profile.md').read_bytes() not in (original, without_roots(text, section(text, True)).encode('utf-8')):
        raise ValueError('changed_since_backup: profile.md changed after the backup; inspect it')
    for path in legacy(runtime):
        entry = backed_up(data, str(path.relative_to(runtime)))
        if not entry or entry['type'] != ('dir' if path.is_dir() else 'file') or (
                entry['type'] == 'file' and sha256(path.read_bytes()) != entry['sha256']):
            raise ValueError('changed_since_backup: a legacy project file was added or changed after the backup; inspect it')


def put_back(target, data, runtime):
    """Restore every backed-up file into runtime, replacing the legacy records and any memory.json the backup lacks."""
    groups = {os.getegid(), *os.getgroups()}
    if any(entry['uid'] != os.geteuid() or entry['gid'] not in groups for entry in data['files']):
        raise ValueError('restore_owner: the backup records an owner this user cannot restore; nothing was written')
    for path in reversed(legacy(runtime)):
        path.rmdir() if path.is_dir() else path.unlink()
    if not backed_up(data, 'memory.json') and memory.path(runtime).exists():
        memory.path(runtime).unlink()
    for entry in data['files']:
        path = runtime / entry['path']
        if entry['type'] == 'dir':
            path.mkdir(mode=0o700, exist_ok=True)
        else:
            atomic_bytes(path, (target / 'files' / entry['path']).read_bytes(), entry['mode'])
            os.chown(path, entry['uid'], entry['gid'])
            os.utime(path, ns=(entry['mtime_ns'], entry['mtime_ns']))
    for entry in reversed(data['files']):  # Directories last, so adding their files does not change their mtime.
        if entry['type'] == 'dir':
            path = runtime / entry['path']
            os.chmod(path, entry['mode'])
            os.chown(path, entry['uid'], entry['gid'])
            os.utime(path, ns=(entry['mtime_ns'], entry['mtime_ns']))
    sync(runtime)


def pending(vault):
    """The newest backup whose migration has not finished and was not restored."""
    backups = sorted((vault / 'backups').glob(PREFIX + '*')) if (vault / 'backups').is_dir() else []
    return next((target for target in reversed(backups) if (target / 'manifest.json').exists()
                 and not (target / 'done.json').exists() and not (target / 'restored.json').exists()), None)


def migrate(vault, runtime, dry_run=False, expect=None):
    target = pending(vault)
    source = target / 'files' if target else runtime
    original = (source / 'profile.md').read_bytes().decode('utf-8')
    span = section(original, bool(legacy(source)))
    result = {'mode': 'migrate', 'legacy': {'section': bool(span), 'record_files': len(list((runtime / 'projects').glob('*.md'))),
                                            'projects_dir': (runtime / 'projects').is_dir(),
                                            'projects_json': (runtime / 'projects.json').exists()},
              **({'resume': target.name} if target else {})}
    data = memory.load(runtime)
    if not target and (not span and not legacy(runtime) or not data['enabled']):
        status = 'memory_off' if span or legacy(runtime) else 'nothing_to_migrate'  # Memory off: nothing added or removed.
        return {**result, 'status': status, 'fingerprint': fingerprint(runtime, None, [], '')}
    labels, language = open_labels(runtime), website_language(runtime)
    if target:
        backup_data = manifest(target)
        intent = read_json(target / 'intent.json')
        check_memory(runtime, backup_data, intent)
        check_runtime(runtime, target, backup_data)
    else:
        sources = [runtime / 'profile.md', *[path for path in [memory.path(runtime)] if path.exists()], *legacy(runtime)]
        check_metadata(sources)
        intent = None
    seeded, counts = (json.loads(intent['memory']), {}) if intent and intent['memory'] else (
        (data, {}) if intent else plan(runtime, source, span, data, labels, language))
    found = fingerprint(runtime, seeded, labels, language)
    if expect is not None and expect != found:
        raise ValueError(f'fingerprint_changed: the account changed since the dry run (now {found}); dry-run again')
    result.update(fingerprint=found, counts=counts, revision=data['revision'])
    if dry_run:
        return {**result, 'status': 'dry_run'}
    if not target:
        target = backup(vault, runtime, sources)
        backup_data = manifest(target)
    verify_backup(target, True)  # Prove the rollback before changing anything.
    check_runtime(runtime, target, backup_data)
    if not intent:
        after = encode(seeded).encode() if seeded != data else None
        intent = {'revision': seeded['revision'], 'memory': after and after.decode(),
                  'memory_sha256': sha256(after) if after else sha256(memory_bytes(runtime))}
        write_json(target / 'intent.json', intent)  # Before the write, so a restore or resume knows the seeded bytes.
    if intent['memory'] and sha256(memory_bytes(runtime)) != intent['memory_sha256']:
        atomic_bytes(memory.path(runtime), intent['memory'].encode(), 0o600)
        sync(runtime)
    profile, text = runtime / 'profile.md', (runtime / 'profile.md').read_bytes().decode('utf-8')
    if span and text == original:
        atomic_bytes(profile, without_roots(original, span).encode('utf-8'), stat.S_IMODE(profile.stat().st_mode))
    check_runtime(runtime, target, backup_data)
    for entry in reversed(backup_data['files']):
        path = runtime / entry['path']
        if entry['path'] not in ('profile.md', 'memory.json') and path.exists():
            path.rmdir() if entry['type'] == 'dir' else path.unlink()
    sync(runtime)
    write_json(target / 'done.json', {'revision': intent['revision'], 'memory_sha256': intent['memory_sha256']})
    return {**result, 'status': 'migrated', 'backup': str(target), 'revision': intent['revision']}


def restore(vault, runtime, target):
    data = manifest(target)
    if (target / 'restored.json').exists():
        return {'mode': 'restore', 'status': 'already_restored', 'backup': str(target)}
    check_memory(runtime, data, read_json(target / 'intent.json'))
    check_runtime(runtime, target, data)
    put_back(target, data, runtime)
    write_json(target / 'restored.json', {'at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'revision': data['revision']})
    return {'mode': 'restore', 'status': 'restored', 'files': len(data['files']), 'revision': data['revision']}


def verify_backup(target, restore_test=False):
    data = manifest(target)
    result = {'mode': 'verify-backup', 'status': 'verified', 'files': len(data['files']), 'revision': data['revision']}
    if not restore_test:
        return result
    scratch = Path(tempfile.mkdtemp(prefix='restore-test-', dir=target))
    try:
        put_back(target, data, scratch)
        for entry in data['files']:
            path, info = scratch / entry['path'], (scratch / entry['path']).lstat()
            same = ((stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid, info.st_mtime_ns)
                    == (entry['mode'], entry['uid'], entry['gid'], entry['mtime_ns']))
            if not same or entry['type'] == 'file' and sha256(path.read_bytes()) != entry['sha256']:
                raise ValueError('restore_mismatch: a test restore differs from the manifest; inspect the backup')
    finally:
        shutil.rmtree(scratch)
    return {**result, 'restore_test': 'passed'}


def owned_directory(path, missing):
    """Refuse a missing, symlinked or foreign directory; True when it is the caller's own."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise ValueError(f'{missing}: {path} does not exist; check --vault') from None
    except PermissionError:
        return False
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f'unsafe_path: {path} is not a directory')
    return info.st_uid == os.geteuid() and info.st_uid != 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--vault', required=True)
    parser.add_argument('mode', choices=('migrate', 'restore', 'verify-backup'))
    parser.add_argument('backup', nargs='?')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--expect')
    parser.add_argument('--restore-test', action='store_true')
    args = parser.parse_args(argv)
    if (args.backup is None) != (args.mode == 'migrate'):
        parser.error('restore and verify-backup take BACKUP; migrate does not')
    os.umask(0o077)
    vault = Path(os.path.abspath(args.vault))
    runtime = vault / 'secretary'
    try:
        if not owned_directory(vault, 'no_vault') or not owned_directory(runtime, 'no_runtime_dir'):
            print(json.dumps({'error': 'wrong_user', 'next': "run as the account's own service user"}))
            return 1
        if not os.access(runtime, os.R_OK | os.W_OK | os.X_OK):
            raise ValueError('runtime_unreadable: the runtime directory is not usable by this user; inspect its mode')
        target = Path(os.path.abspath(args.backup)) if args.backup else None
        if target and (target.parent != vault / 'backups' or not target.name.startswith(PREFIX) or target.is_symlink()):
            raise ValueError(f'invalid_input: BACKUP is a {PREFIX}* directory in {vault / "backups"}')
        if args.mode == 'verify-backup':
            result = verify_backup(target, args.restore_test)
        elif not (runtime / 'profile.md').exists():
            result = {'mode': args.mode, 'status': 'no_runtime'}  # Never provisioned: the runtime is readable and owned.
        elif args.dry_run:
            result = migrate(vault, runtime, True, args.expect)  # A dry run takes no lock: it creates no files.
        else:
            with runtime_lock(runtime, '.profile.lock', memory.WAIT), runtime_lock(runtime, 'memory.lock', memory.WAIT):
                result = migrate(vault, runtime, expect=args.expect) if args.mode == 'migrate' else restore(vault, runtime, target)
    except (ValueError, OSError, sqlite3.Error) as error:
        message = str(error) if isinstance(error, ValueError) else f'storage_error: {type(error).__name__}; preserve the files and inspect'
        print(json.dumps({'error': message.split(':', 1)[0], 'next': message}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
