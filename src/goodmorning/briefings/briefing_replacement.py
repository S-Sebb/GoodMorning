"""Explicit browser replacement, guarded by the original snapshot and run marker."""
import hashlib
from pathlib import Path

from . import briefing_document as native
from goodmorning.records.state import parse_daily


def snapshot(runtime, date, kind):
    source = native.source_path(Path(runtime), date, kind)
    if source.is_symlink() or source.parent.is_symlink():
        raise ValueError('Unsafe saved edition')
    raw = None
    if source.exists():
        with source.open('rb') as stream:
            raw = stream.read(native.MAX_BYTES + 1)
        if len(raw) > native.MAX_BYTES:
            raise ValueError('Saved edition exceeds its size limit; preserve it for inspection')
    daily = Path(runtime) / 'daily' / (date + '.md')
    if daily.is_symlink():
        raise ValueError('Unsafe daily record')
    run = parse_daily(str(daily))[kind]
    return {'sha256': hashlib.sha256(raw).hexdigest() if raw is not None else None,
            'run': {key: run[key] for key in ('ran', 'session', 'answer_file')}}, raw


def check(runtime, job, document=None):
    """Allow only the authorized baseline or this job's interrupted exact save."""
    baseline = job.get('replacement')
    if baseline is None:
        return False
    current, raw = snapshot(runtime, job['date'], job['kind'])
    if current == baseline:
        return True
    own_run = {'ran': True, 'session': job.get('session'),
               'answer_file': 'daily/' + native.source_path(Path(runtime), job['date'], job['kind']).name}
    if document is not None and current['run'] in (baseline['run'], own_run) and raw is not None:
        try:
            if native.parse(raw.decode('utf-8')) == document:
                return True
        except (ValueError, UnicodeError):
            pass
    raise ValueError('The saved edition changed after regeneration was requested; preserve it and inspect the session')
