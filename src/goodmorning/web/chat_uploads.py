"""Private, streamed chat attachments; browsers receive IDs, never filesystem paths."""
import hashlib
import json
import os
import re
import threading
from urllib.parse import parse_qs, quote

from goodmorning.runtime_files import atomic_text

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
UPLOAD_ROUTE = re.compile(r'/api/chat-uploads/([a-f0-9]{32})')


def upload_name(query):
    fields = parse_qs(query, keep_blank_values=True, strict_parsing=True)
    if set(fields) != {'name'} or len(fields['name']) != 1:
        raise ValueError('Invalid upload name')
    name = fields['name'][0]
    if (not name or name in ('.', '..') or len(name.encode()) > 240
            or any(ord(char) < 32 or ord(char) == 127 or char in '/\\' for char in name)):
        raise ValueError('Invalid upload name')
    return name


def attachment_ids(body):
    values = body.get('attachments', [])
    if (not isinstance(values, list) or len(values) > 100
            or any(not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value) for value in values)
            or len(set(values)) != len(values)):
        raise ValueError('Invalid attachments')
    return values


class UploadReader:
    """Bound a forwarded binary stream without buffering private files at the gateway."""
    def __init__(self, stream, size):
        self.stream, self.remaining = stream, size

    def read(self, size=-1):
        if not self.remaining:
            return b''
        data = self.stream.read(min(self.remaining, size if size >= 0 else 65536))
        if not data:
            raise ValueError('Incomplete upload')
        self.remaining -= len(data)
        return data


class Uploads:
    def __init__(self, runtime):
        self.directory = runtime / 'browser-uploads'
        if self.directory.is_symlink():
            raise ValueError('Unsafe upload storage')
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.lock = threading.RLock()

    def paths(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{32}', identifier):
            raise ValueError('Invalid attachment ID')
        directory = self.directory / identifier
        if self.directory.is_symlink() or directory.is_symlink():
            raise ValueError('Unsafe upload storage')
        return directory, directory / 'metadata.json'

    def get(self, identifier):
        directory, metadata = self.paths(identifier)
        if metadata.is_symlink() or not metadata.is_file() or metadata.stat().st_size > 2048:
            raise ValueError('Unknown attachment')
        entry = json.loads(metadata.read_text())
        name = upload_name('name=' + quote(entry['name'], safe=''))
        path = directory / 'files' / name
        if (path.parent.is_symlink() or path.is_symlink() or not path.is_file()
                or path.stat().st_size != entry['size'] or not 0 <= entry['size'] <= MAX_UPLOAD_BYTES):
            raise ValueError('Attachment unavailable')
        return {'id': identifier, 'name': name, 'size': entry['size']}

    def files(self, identifiers):
        entries = [self.get(identifier) for identifier in identifiers]
        return [{'uri': (self.directory / entry['id'] / 'files' / entry['name']).as_uri(), 'name': entry['name']}
                for entry in entries]

    def receive(self, identifier, name, stream, size):
        upload_name('name=' + quote(name, safe=''))
        if not 0 <= size <= MAX_UPLOAD_BYTES:
            raise ValueError('File exceeds 50 MB')
        with self.lock:
            directory, metadata = self.paths(identifier)
            if directory.exists():
                old = self.get(identifier)
                digest = hashlib.sha256()
                reader = UploadReader(stream, size)
                while chunk := reader.read(65536):
                    digest.update(chunk)
                saved = json.loads(metadata.read_text())
                if old['name'] != name or old['size'] != size or saved['sha256'] != digest.hexdigest():
                    raise ValueError('Upload ID already belongs to another file')
                return old
            directory.mkdir(mode=0o700)
            files = directory / 'files'
            files.mkdir(mode=0o700)
            path = files / name
            try:
                digest = hashlib.sha256()
                reader = UploadReader(stream, size)
                with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as target:
                    while chunk := reader.read(65536):
                        target.write(chunk)
                        digest.update(chunk)
                entry = {'name': name, 'size': size, 'sha256': digest.hexdigest()}
                atomic_text(metadata, json.dumps(entry) + '\n')
            except Exception:
                path.unlink(missing_ok=True)
                metadata.unlink(missing_ok=True)
                files.rmdir()
                directory.rmdir()
                raise
            return {'id': identifier, 'name': name, 'size': size}
