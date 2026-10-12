"""Shared immutable assets, negotiated text compression and bounded byte caches."""
from collections import OrderedDict
from dataclasses import dataclass
import gzip
import hashlib

ICON_TYPES = {f'icons/{kind}.{extension}': mime
              for kind in ('gm', 'gn', 'secretary')
              for extension, mime in (('svg', 'image/svg+xml'), ('png', 'image/png'))}


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
        types = types if types is not None else {'fonts/lora-italic.woff2': 'font/woff2', 'briefing.css': 'text/css',
                 'briefing.js': 'text/javascript', 'browser.js': 'text/javascript',
                   'questions.js': 'text/javascript', 'chat.js': 'text/javascript', 'chat.css': 'text/css', 'language.js':'text/javascript',
                    'model.js':'text/javascript',
                    'marked.js': 'text/javascript', 'markdown.js': 'text/javascript',
                    'color-schemes.js': 'text/javascript', 'color-schemes.css': 'text/css',
                   'update.js': 'text/javascript', 'update.css': 'text/css',
                   'avatar.js': 'text/javascript', 'avatar.css': 'text/css',
                 'fonts/OFL.txt': 'text/plain', 'desk-secretary.png': 'image/png',
                 'desk-secretary-f2.png': 'image/png', 'desk-secretary-m1.png': 'image/png',
                 'desk-secretary-m2.png': 'image/png', **ICON_TYPES}
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
