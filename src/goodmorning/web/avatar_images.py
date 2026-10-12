"""One private, validated custom secretary portrait per account."""
import base64
import hashlib
import io
import json
from pathlib import Path
import warnings

from goodmorning.runtime_files import atomic_text

MAX_AVATAR_BYTES = 5 * 1024 * 1024
AVATAR_UPLOAD_PATH = '/api/avatar/upload'


def image_path(runtime):
    path = Path(runtime) / 'website-avatar-image.json'
    if path.is_symlink():
        raise ValueError('Unsafe avatar storage')
    return path


def read_image(runtime):
    path = image_path(runtime)
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('Invalid avatar image')
        data = base64.b64decode(json.loads(path.read_text())['png'], validate=True)
    except FileNotFoundError:
        return None
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('Invalid avatar image') from error
    return hashlib.sha256(data).hexdigest(), data


def save_image(runtime, data):
    from PIL import Image, ImageOps
    if not 0 < len(data) <= MAX_AVATAR_BYTES:
        raise ValueError('Invalid avatar image size')
    image_path(runtime)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=('PNG', 'JPEG', 'WEBP')) as image:
                if image.width * image.height > 16_000_000:
                    raise ValueError('Avatar image is too large')
                image.load()
                portrait = ImageOps.exif_transpose(image).convert('RGBA')
                portrait.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                portrait.info.clear()
                output = io.BytesIO()
                portrait.save(output, format='PNG')
    except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise ValueError('Use a PNG, JPEG or WebP image') from error
    atomic_text(image_path(runtime), json.dumps({'png': base64.b64encode(output.getvalue()).decode('ascii')}) + '\n')


def image_url(runtime):
    image = read_image(runtime)
    return '/api/avatar/image/' + image[0] + '.png' if image else None
