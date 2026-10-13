"""Private inspection previews for avatar work; never replace originals or history."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import warnings

from goodmorning.runtime_files import secretary_path
from .avatar_images import MAX_AVATAR_BYTES

PREVIEW_SIDE = 512
PREVIEW_DIRECTORY = 'avatar-previews'


def create(runtime, source):
    from PIL import Image, ImageOps, __version__ as pillow_version
    source = Path(source).expanduser().absolute()
    if (source.is_symlink() or any(part.startswith('.env') for part in source.parts)
            or source.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp')):
        raise ValueError('Choose a PNG, JPEG or WebP avatar, not a symlink or credential file')
    runtime = Path(runtime).expanduser().resolve()
    if not runtime.is_dir():
        raise ValueError('Select an existing private runtime; previewing never initializes records')
    with source.open('rb') as stream:
        original = stream.read(MAX_AVATAR_BYTES + 1)
    if not 0 < len(original) <= MAX_AVATAR_BYTES:
        raise ValueError('Avatar source exceeds 5 MB or is empty')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(original), formats=('PNG', 'JPEG', 'WEBP')) as image:
                if image.width * image.height > 16_000_000:
                    raise ValueError('Avatar source has too many pixels')
                portrait = ImageOps.exif_transpose(image).convert('RGBA')
                original_size = portrait.size
                portrait.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE), Image.Resampling.LANCZOS)
                portrait.info.clear()
                output = io.BytesIO()
                portrait.save(output, format='WEBP', lossless=True, exact=True, method=6)
    except (OSError, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise ValueError('Use a readable PNG, JPEG or WebP avatar') from error
    data = output.getvalue()
    source_hash = hashlib.sha256(original).hexdigest()
    identity = hashlib.sha256((f'avatar-preview-v1:{PREVIEW_SIDE}:{pillow_version}:' + source_hash).encode()).hexdigest()
    directory = runtime / PREVIEW_DIRECTORY
    if directory.is_symlink():
        raise ValueError('Unsafe preview storage')
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / (identity + '.webp')
    if path.is_symlink():
        raise ValueError('Unsafe preview storage')
    reused = path.exists()
    if reused:
        if path.stat().st_size != len(data) or path.read_bytes() != data:
            raise ValueError('Preview conflict; preserve the existing file and inspect it')
    else:
        fd, temporary = tempfile.mkstemp(prefix='.preview-', dir=directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {'preview': str(path), 'width': portrait.width, 'height': portrait.height,
            'original_width': original_size[0], 'original_height': original_size[1],
            'source_bytes': len(original), 'preview_bytes': len(data), 'source_sha256': source_hash,
            'original_preserved': True, 'reused': reused}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secretary-dir')
    parser.add_argument('--source', type=Path, action='append', required=True)
    args = parser.parse_args(argv)
    try:
        if len(args.source) > 4:
            raise ValueError('Preview at most four explicitly selected avatars per invocation')
        result = [create(secretary_path(args.secretary_dir), source) for source in args.source]
        print(json.dumps({'previews': result, 'next': 'Read the preview files for avatar inspection. Keep original files for publishing or fine-detail work.'}))
        return 0
    except (OSError, ValueError, ImportError) as error:
        print(json.dumps({'error': 'avatar_preview_unavailable', 'next': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
