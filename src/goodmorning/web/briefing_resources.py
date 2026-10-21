"""Shared immutable assets, negotiated text compression and bounded byte caches."""
from collections import OrderedDict
from dataclasses import dataclass
import gzip
import hashlib

ICON_TYPES = {f'icons/{kind}.{extension}': mime
              for kind in ('gm', 'gn', 'secretary')
              for extension, mime in (('svg', 'image/svg+xml'), ('png', 'image/png'))}
DESK_ICON_TYPES = {f'icons/desk-{name}.svg': 'image/svg+xml'
                  for name in ('morning', 'evening', 'schedule', 'secretary', 'idea', 'appearance', 'language', 'notifications', 'phone')}
PIXEL_FONTS = {f'fonts/{name}.woff2': 'font/woff2' for name in ('pixelify-sans', 'silkscreen', 'jersey-10', 'fusion-pixel-zh')}
PIXEL_SCENES = {f'{name}.svg': 'image/svg+xml'
                for name in ('grass-block-day', 'grass-block-night', 'grass-block-stone-day', 'grass-block-stone-night',
                             'grass-block-sun', 'pixel-sun', 'pixel-moon', 'picnic-day', 'picnic-night')}


def favicon_links(kind, prefix='/'):
    kind = 'secretary' if kind == 'sec' else kind
    if kind not in ('gm', 'gn', 'secretary'):
        raise ValueError('Unknown page icon')
    return (f'<link rel="icon" type="image/png" sizes="32x32" href="{prefix}icons/{kind}.png">'
            f'<link rel="icon" type="image/svg+xml" sizes="any" href="{prefix}icons/{kind}.svg">')


class ByteCache:
    def __init__(self, max_bytes, max_entries):
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.items = OrderedDict()
        self.size = 0

    def get(self, key):
        entry = self.items.get(key)
        if entry:
            self.items.move_to_end(key)
            return entry[0]
        return None

    def put(self, key, value, size):
        old = self.items.pop(key, None)
        if old:
            self.size -= old[1]
        if size > self.max_bytes:
            return
        self.items[key] = value, size
        self.size += size
        while self.size > self.max_bytes or len(self.items) > self.max_entries:
            _, (_, removed) = self.items.popitem(last=False)
            self.size -= removed


def accepts_gzip(header):
    encodings = {}
    for part in header.lower().split(','):
        name, *parameters = part.strip().split(';')
        quality = 1.0
        try:
            for parameter in parameters:
                if parameter.strip().startswith('q='):
                    quality = float(parameter.strip()[2:])
            encodings[name] = quality if 0 <= quality <= 1 else 0
        except ValueError:
            encodings[name] = 0
    return encodings.get('gzip', encodings.get('*', 0)) > 0


@dataclass(frozen=True)
class Resource:
    data: bytes
    mime: str
    etag: str
    compressed: bytes


class Resources:
    def __init__(self, assets, *, types=None):
        self.paths, self.urls = {}, {}
        types = types if types is not None else {**DESK_ICON_TYPES, **PIXEL_FONTS, **PIXEL_SCENES,
                 'fonts/lora-italic.woff2': 'font/woff2', 'briefing.css': 'text/css', 'pixel.css': 'text/css',
                  'briefing.js': 'text/javascript', 'browser.js': 'text/javascript',
                  'scroll-rails.js': 'text/javascript', 'scroll-rails.css': 'text/css',
                   'questions.js': 'text/javascript', 'chat.js': 'text/javascript', 'chat.css': 'text/css', 'language.js':'text/javascript',
                   'network.js':'text/javascript', 'auth.js':'text/javascript','auth.css':'text/css',
                   'activity.js':'text/javascript','activity.css':'text/css',
                   'quick-chat.js':'text/javascript','quick-chat.css':'text/css',
                     'schedule.js':'text/javascript', 'schedule-mode.js':'text/javascript', 'schedule.css':'text/css',
                    'marked.js': 'text/javascript', 'markdown.js': 'text/javascript',
                      'starry-sky.svg': 'image/svg+xml',
                      'morning-sky.svg': 'image/svg+xml',
                      'city-lights.svg': 'image/svg+xml',
                      'morning-clouds.webp': 'image/webp',
                      'first-light.svg': 'image/svg+xml',
                      'morning-clouds-continuation.webp': 'image/webp',
                     'color-schemes.js': 'text/javascript', 'color-schemes.css': 'text/css',
                   'update.js': 'text/javascript', 'update.css': 'text/css',
                   'avatar.js': 'text/javascript', 'avatar.css': 'text/css',
                   'maintenance.css': 'text/css',
                   'app.js': 'text/javascript', 'sw.js': 'text/javascript', 'manifest.webmanifest': 'application/manifest+json',
                   **{f'icons/app-{size}.png': 'image/png' for size in ('192', '512', 'maskable-512')},
                 'fonts/OFL.txt': 'text/plain', 'fonts/pixel-fonts-OFL.txt': 'text/plain',
                 **{f'desk-secretary{person}{variant}.png': 'image/png' for person in ('', '-f2', '-m1', '-m2')
                    for variant in ('', '-day', '-animated', '-day-animated', '-profile')}, **ICON_TYPES}
        # Register the font first: CSS embeds its immutable, shared URL.
        for name, mime in types.items():
            try:
                data = (assets / name).read_bytes()
            except FileNotFoundError:
                if name.startswith('desk-secretary') and name.endswith('.png'):
                    continue
                raise
            if name == 'language.js':
                import json
                from .language import CATALOG
                data = ('const goodmorningCatalog = '+json.dumps(CATALOG,ensure_ascii=False,separators=(',',':'))+';\n').encode()+data
            if name == 'briefing.css':
                data = data.replace(b'fonts/lora-italic.woff2', self.urls['fonts/lora-italic.woff2'].encode())
            if mime == 'text/css':
                for icon in DESK_ICON_TYPES:
                    if icon in self.urls:
                        data = data.replace(icon.encode(), self.urls[icon].encode())
            if name in ('color-schemes.css', 'pixel.css'):
                for asset in (*PIXEL_FONTS, *PIXEL_SCENES):
                    if asset in self.urls:
                        data = data.replace((asset if asset.startswith('fonts/') else '/' + asset).encode(), self.urls[asset].encode())
            if name == 'color-schemes.css':
                for sky in ('starry-sky.svg', 'city-lights.svg', 'morning-sky.svg', 'morning-clouds.webp', 'first-light.svg',
                            'morning-clouds-continuation.webp'):
                    if sky in self.urls:
                        data = data.replace(('/' + sky).encode(), self.urls[sky].encode())
            digest = hashlib.sha256(data).hexdigest()
            path = f'/assets/{digest}/{name}'
            compressed = gzip.compress(data, compresslevel=6, mtime=0) if mime.startswith('text/') else data
            self.paths[path] = Resource(data, mime, '"' + digest + '"', compressed)
            self.urls[name] = path

    def rewrite(self, text):
        for name, url in self.urls.items():
            for prefix in ('href', 'src'):
                text = text.replace(f'{prefix}="/{name}"', f'{prefix}="{url}"')
        return text

    def alias(self, path):
        url = self.urls.get(path.lstrip('/'))
        return self.paths.get(url)
