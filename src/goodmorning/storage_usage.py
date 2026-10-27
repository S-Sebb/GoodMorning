"""Bounded filesystem size inventory. No file contents, writes, engine or model calls."""
import os
from pathlib import Path
import re

MAX_ENTRIES = 100_000


def measure(directory, *, exclude=(), limit=MAX_ENTRIES):
    result = {'present': False, 'files': 0, 'logical_bytes': 0, 'allocated_bytes': 0,
              'library_bytes': 0, 'skipped_symlinks': 0, 'complete': True}
    if directory.is_symlink():
        result.update(skipped_symlinks=1, complete=False)
        return result
    if not directory.is_dir():
        return result
    result['present'] = True
    visited = 0
    for root, dirs, files in os.walk(directory, followlinks=False, onerror=lambda error: result.update(complete=False)):
        for name in list(dirs):
            visited += 1
            if visited > limit:
                result['complete'] = False
                return result
            path = Path(root) / name
            if path in exclude or path.is_symlink():
                dirs.remove(name)
                result['skipped_symlinks'] += int(path.is_symlink())
        for name in files:
            visited += 1
            if visited > limit:
                result['complete'] = False
                return result
            path = Path(root) / name
            if path.is_symlink():
                result['skipped_symlinks'] += 1
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                result['complete'] = False
                continue  # Live caches can change while a read-only inventory runs.
            result['files'] += 1
            result['logical_bytes'] += stat.st_size
            result['allocated_bytes'] += getattr(stat, 'st_blocks', 0) * 512
            if path.suffix in ('.so', '.node'):
                result['library_bytes'] += stat.st_size
    return result


def inventory(runtime, cache=None):
    runtime = Path(runtime).expanduser().resolve()
    hosted = runtime.name == 'secretary' and re.fullmatch('[a-f0-9]{32}', runtime.parent.name)
    roots = {'records': runtime, 'previews': runtime / 'avatar-previews', 'uploads': runtime / 'browser-uploads'}
    if hosted:
        volume = runtime.parent
        roots.update(engine=volume / 'home/.local/share/opencode', temporary=volume / 'tmp')
        cache = Path(cache) if cache is not None else volume / 'cache'
    elif (runtime / 'tmp').exists():
        roots['temporary'] = runtime / 'tmp'
    if cache is not None:
        roots['cache'] = Path(cache).expanduser().absolute()
    groups = {}
    seen = set()
    for name, path in roots.items():
        if path in seen:
            continue
        seen.add(path)
        exclude = tuple(other for other in roots.values() if other != path and other.is_relative_to(path))
        groups[name] = measure(path, exclude=exclude)
    return {'groups': groups, 'logical_bytes': sum(group['logical_bytes'] for group in groups.values()),
            'allocated_bytes': sum(group['allocated_bytes'] for group in groups.values()),
            'complete': all(group['complete'] for group in groups.values()), 'read_only': True,
            'note': 'Reported filesystem allocation is not a storage bill. Library files can be a fixed startup cost. No history or original files were removed.'}
