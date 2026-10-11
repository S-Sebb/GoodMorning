"""A public content fingerprint, fixed for the lifetime of each release process."""
import hashlib
from goodmorning.paths import ROOT


def fingerprint(root):
    digest = hashlib.sha256()
    for directory in ('src', 'assets', 'scripts', 'docs', 'templates', 'deploy', 'skill-source', 'integrations', 'vendor', 'requirements'):
        for path in sorted((root / directory).rglob('*')):
            if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                digest.update(str(path.relative_to(root)).encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


VERSION = fingerprint(ROOT)
