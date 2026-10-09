#!/usr/bin/env python3
"""Build an owner-deployment bundle using a public-file allowlist, never git state."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    'README.md', 'config.example.md', '.gitignore',
    '.opencode/commands/*.md', '.opencode/skills/*/SKILL.md',
    'docs/*.md', 'templates/*.md', 'templates/*.json',
    'scripts/*.py', 'scripts/*.mjs', 'scripts/news_sources.json',
    'scripts/vendor/openchamber-relay/*.ts',
    'scripts/vendor/openchamber-relay/LICENSE',
    'scripts/vendor/openchamber-relay/manifest.json',
    'tests/*.py', 'tests/*.mjs',
)


def public_files(root):
    root = Path(root).resolve()
    files = sorted({path for pattern in PATTERNS for path in root.glob(pattern) if path.is_file()})
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('release files must not be symlinks or escape the checkout')
    return files


def build(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists() or Path(str(output) + '.sha256').exists():
        raise ValueError('release output exists; choose a new output instead of overwriting it')
    files = public_files(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {}
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative, content = path.relative_to(root).as_posix(), path.read_bytes()
            manifest[relative] = hashlib.sha256(content).hexdigest()
            item = zipfile.ZipInfo('GoodMorning/' + relative, date_time=(1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            archive.writestr(item, content)
        item = zipfile.ZipInfo('GoodMorning/RELEASE-MANIFEST.json', date_time=(1980, 1, 1, 0, 0, 0))
        item.compress_type = zipfile.ZIP_DEFLATED
        item.external_attr = 0o100644 << 16
        archive.writestr(item, json.dumps(manifest, sort_keys=True, indent=2))
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    Path(str(output) + '.sha256').write_text(checksum + '  ' + output.name + '\n', encoding='utf-8')
    return {'archive': str(output), 'sha256': checksum, 'files': len(manifest)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='dist/GoodMorning-deploy.zip')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(ROOT, args.output)))
        return 0
    except (OSError, ValueError) as error:
        parser.exit(1, 'release build failed: ' + str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
