"""Private, validated custom secretary images per account: day and night scenes and a round profile."""
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import warnings

from goodmorning.runtime_files import atomic_text

MAX_AVATAR_BYTES = 5 * 1024 * 1024
# The night scene keeps the original single-image file so earlier uploads stay valid.
VARIANTS = {'night': 'website-avatar-image.json', 'day': 'website-avatar-image-day.json',
            'profile': 'website-avatar-image-profile.json'}
AVATAR_UPLOAD_ROUTE = re.compile(r'/api/avatar/upload/(day|night|profile)')


def image_path(runtime, variant='night'):
    path = Path(runtime) / VARIANTS[variant]
    if path.is_symlink():
        raise ValueError('Unsafe avatar storage')
    return path


def read_image(runtime, variant='night'):
    path = image_path(runtime, variant)
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('Invalid avatar image')
        data = base64.b64decode(json.loads(path.read_text())['png'], validate=True)
    except FileNotFoundError:
        return None
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('Invalid avatar image') from error
    return hashlib.sha256(data).hexdigest(), data


def find_image(runtime, digest):
    for variant in VARIANTS:
        image = read_image(runtime, variant)
        if image and image[0] == digest:
            return image[1]
    return None


def save_image(runtime, data, variant='night'):
    from PIL import Image, ImageOps
    if not 0 < len(data) <= MAX_AVATAR_BYTES:
        raise ValueError('Invalid avatar image size')
    image_path(runtime, variant)
    for other in VARIANTS:
        image_path(runtime, other)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=('PNG', 'JPEG', 'WEBP')) as image:
                if image.width * image.height > 16_000_000:
                    raise ValueError('Avatar image is too large')
                image.load()
                portrait = ImageOps.exif_transpose(image).convert('RGBA')
                if variant == 'profile':
                    portrait = ImageOps.fit(portrait, (512, 512), Image.Resampling.LANCZOS)
                portrait.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                portrait.info.clear()
                output = io.BytesIO()
                portrait.save(output, format='PNG')
    except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise ValueError('Use a PNG, JPEG or WebP image') from error
    atomic_text(image_path(runtime, variant), json.dumps({'png': base64.b64encode(output.getvalue()).decode('ascii')}) + '\n')


def image_urls(runtime):
    """Uploaded images with fallbacks, or None before any upload. A missing profile stays None."""
    urls = {}
    for variant in VARIANTS:
        image = read_image(runtime, variant)
        urls[variant] = '/api/avatar/image/' + image[0] + '.png' if image else None
    if not any(urls.values()):
        return None
    return {'day': urls['day'] or urls['night'] or urls['profile'],
            'night': urls['night'] or urls['day'] or urls['profile'], 'profile': urls['profile']}
