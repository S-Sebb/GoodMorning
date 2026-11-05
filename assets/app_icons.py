"""Regenerate every app icon from the default secretary portrait (issue #221).

Run from the repository root: uv run --no-project --with Pillow python assets/app_icons.py
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'assets/web'
ANDROID = ROOT / 'android/app/src/main/res/drawable-nodpi'
BACKGROUND = (0xF8, 0xEE, 0xE0, 255)  # manifest background_color and @color/icon_background

# The pixel-style art is antialiased at 256 px, so a 4x nearest-neighbour copy
# keeps its pixels crisp and Lanczos then resamples to each size.
source = Image.open(WEB / 'desk-secretary-profile.png').convert('RGBA')
large = source.resize((1024, 1024), Image.NEAREST)


def portrait(size):
    return large.resize((size, size), Image.LANCZOS)


def placed(canvas, size, background):
    """Portrait centred, bottom at the canvas edge, as wide as `size` (a fraction of the canvas)."""
    image = Image.new('RGBA', (canvas, canvas), background)
    width = round(canvas * size)
    image.alpha_composite(portrait(width), ((canvas - width) // 2, canvas - width))
    return image


def save(image, path):
    image.save(path, optimize=True)


for size in (192, 512):
    save(placed(size, 1, BACKGROUND), WEB / f'icons/app-{size}.png')
# Maskable: the head stays inside the central 80% circle; masks may crop the shoulders.
save(placed(512, 0.75, BACKGROUND), WEB / 'icons/app-maskable-512.png')

# Tab icon: the head only, so the face stays readable at 16-32 px.
face = large.crop((128, 80, 896, 848))
tab = Image.new('RGBA', (128, 128), (0, 0, 0, 0))
ImageDraw.Draw(tab).rounded_rectangle((0, 0, 127, 127), 28, BACKGROUND)
tab.alpha_composite(face.resize((128, 128), Image.LANCZOS))
save(tab.resize((32, 32), Image.LANCZOS), WEB / 'icons/app-32.png')

# Android adaptive icon at 108dp xxxhdpi: the head sits inside the 66dp safe circle
# and the shoulders run to the bottom edge, which every launcher mask crops.
foreground = Image.new('RGBA', (432, 432), (0, 0, 0, 0))
foreground.alpha_composite(portrait(300), (66, 132))
save(foreground, ANDROID / 'ic_launcher_foreground.png')
# Themed icons tint only the alpha, usually dark ink on a light tile: eyes and
# outlines are solid, hair and jacket strong, skin and shirt faint.
ink = foreground.convert('L').point(lambda v: 255 if v < 45 else 210 if v < 100 else max(55, 210 - (v - 100) * 155 // 70))
mono = Image.new('RGBA', foreground.size, (255, 255, 255, 255))
mono.putalpha(ImageChops.multiply(ink, foreground.getchannel('A')))
save(mono, ANDROID / 'ic_launcher_monochrome.png')
