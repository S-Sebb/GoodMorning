"""Opt-in public article preview caching. Never use browser cookies or hotlink."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
from html.parser import HTMLParser
import http.client
import io
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import sqlite3
import time
from urllib.parse import urljoin, urlsplit
from goodmorning.runtime_files import atomic_text, runtime_lock


def object_name(entry):
    if not isinstance(entry, dict) or entry.get('status') != 'cached':
        return None
    digest = entry.get('sha256')
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        return None
    return digest + '.webp' if entry.get('file') == digest + '.webp' else None


def checked_image(asset, digest):
    if (not asset.is_file() or asset.is_symlink() or asset.parent.is_symlink()
            or asset.stat().st_size > 1_000_000):
        return None
    data = asset.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest or not data.startswith(b'RIFF') or data[8:12] != b'WEBP':
        return None
    return data


def store_image(directory, name, data):
    target = directory / name
    if target.is_symlink():
        raise ValueError('Refusing symlinked preview file')
    if not target.exists():
        target.write_bytes(data)
        target.chmod(0o600)
    elif checked_image(target, name[:64]) is None:
        raise ValueError('Existing image object is corrupt; preserved without replacement')


def thumbnail_dimensions(width, height):
    scale = min(320 / width, 240 / height, 1)
    return max(1, round(width * scale)), max(1, round(height * scale))


def small_preview(data):
    """A bounded, in-memory derivative; keep the original image on disk once."""
    from PIL import Image
    try:
        image = Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as error:
        raise ValueError('Preview dimensions exceed the normalized bound') from error
    with image:
        if image.format != 'WEBP' or not 0 < image.width <= 640 or not 0 < image.height <= 480:
            raise ValueError('Not a normalized publisher preview')
        size = thumbnail_dimensions(image.width, image.height)
        if size == image.size:
            return data
        image = image.convert('RGB').resize(size, Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format='WEBP', quality=84)
        return output.getvalue()


def shared_catalog(directory):
    if directory.is_symlink() or directory.resolve() != directory:
        raise ValueError('Refusing symlinked shared image store')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / 'catalog.sqlite'
    if path.is_symlink():
        raise ValueError('Refusing symlinked image catalog')
    connection = sqlite3.connect(str(path))
    connection.execute('CREATE TABLE IF NOT EXISTS previews (url TEXT PRIMARY KEY, entry TEXT NOT NULL)')
    path.chmod(0o600)
    return connection


class PreviewMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.image = None
        self.alt = "Publisher article preview"

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag != "meta":
            return
        key = values.get("property", values.get("name", "")).lower()
        if key == "og:image" or (key == "twitter:image" and not self.image):
            self.image = values.get("content")
        if key == "og:image:alt":
            self.alt = values.get("content", self.alt)[:300]


def public_target(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("Preview fetch requires public HTTPS")
    addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Private or non-global preview destination refused")
    return parts, addresses[0][4][0]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        connection = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(connection, server_hostname=self.host)
        except Exception:
            connection.close()
            raise


def fetch_public(url, limit, deadline):
    for _ in range(4):
        if deadline <= time.monotonic():
            raise TimeoutError('Article preview budget exhausted')
        parts, address = public_target(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Article preview budget exhausted")
        connection = PinnedHTTPS(parts.hostname, address, min(remaining, 8))
        try:
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            connection.request("GET", path, headers={"User-Agent": "GoodMorningPrivatePreview/1.0", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Missing redirect destination")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(f"Publisher returned HTTP {response.status}")
            length = response.getheader("Content-Length")
            if length and int(length) > limit:
                raise ValueError("Publisher asset too large")
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Article preview budget exhausted")
                connection.sock.settimeout(min(remaining, 8)) if connection.sock else None
                chunk = response.read(min(65536, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > limit:
                    raise ValueError("Publisher asset too large")
            return b"".join(chunks), response.getheader("Content-Type", ""), url
        finally:
            connection.close()
    raise ValueError("Too many publisher redirects")


def cache_previews(urls, directory, shared_directory=None):
    """Serialize date manifests; successes persist, failures retry after one hour."""
    if directory.is_symlink() or directory.resolve() != directory:
        raise ValueError('Refusing symlinked preview cache')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (directory / '.images.lock').is_symlink():
        raise ValueError('Refusing symlinked preview lock')
    with runtime_lock(directory, '.images.lock'):
        return collect_previews(urls, directory, shared_directory)


def collect_previews(urls, directory, shared_directory):
    """At most 32 articles, four workers, 18s/item within a shared 24s network budget."""
    from PIL import Image, ImageOps
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest_path = directory / "manifest.json"
    if directory.is_symlink() or manifest_path.is_symlink():
        raise ValueError("Refusing symlinked preview cache")
    if manifest_path.exists() and manifest_path.stat().st_size > 100_000:
        raise ValueError('Preview manifest exceeds its limit; preserve it')
    old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if not isinstance(old, dict):
        raise ValueError('Invalid preview manifest; preserve it before repairing the cache')
    urls = list(dict.fromkeys(urls))[:32]
    budget = time.monotonic() + 24
    reusable = {}
    if shared_directory:
        with closing(shared_catalog(shared_directory)) as catalog, catalog:
            for url in urls:
                row = catalog.execute('SELECT entry FROM previews WHERE url=?', (url,)).fetchone()
                if row:
                    entry = json.loads(row[0])
                    name = object_name(entry)
                    if name:
                        if checked_image(shared_directory / name, entry['sha256']) is not None:
                            reusable[url] = entry

    def collect(url):
        if url in reusable:
            return url, reusable[url]
        entry = old.get(url)
        if (isinstance(entry, dict) and entry.get('status') == 'unavailable'
                and type(entry.get('retry_after')) in (int, float) and time.time() < entry['retry_after'] <= time.time() + 3600):
            return url, entry
        name = object_name(entry)
        if name:
            data = checked_image(directory / name, name[:64])
            if data is not None:
                if shared_directory:
                    store_image(shared_directory, name, data)
                return url, entry
        try:
            deadline = min(time.monotonic() + 18, budget)
            if deadline <= time.monotonic():
                raise TimeoutError('Article preview budget exhausted')
            page, content_type, final_url = fetch_public(url, 3_000_000, deadline)
            if "text/html" not in content_type:
                raise ValueError("Article response is not HTML")
            metadata = PreviewMetadata()
            metadata.feed(page.decode("utf-8", errors="replace"))
            if not metadata.image:
                raise ValueError("No publisher preview image")
            image_url = urljoin(final_url, metadata.image)
            payload, image_type, image_url = fetch_public(image_url, 6_000_000, deadline)
            if not image_type.startswith("image/"):
                raise ValueError("Preview response is not an image")
            with Image.open(io.BytesIO(payload)) as image:
                if image.width * image.height > 20_000_000:
                    raise ValueError("Preview dimensions too large")
                image.seek(0)
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((640, 480))
                output = io.BytesIO()
                image.save(output, format="WEBP", quality=84)
            data = output.getvalue()
            name = hashlib.sha256(data).hexdigest() + ".webp"
            store_image(shared_directory or directory, name, data)
            return url, {"status": "cached", "file": name, "sha256": hashlib.sha256(data).hexdigest(),
                         "image_url": image_url, "article_url": url, "alt": metadata.alt}
        except Exception as error:
            return url, {"status": "unavailable", "reason": str(error)[:180], 'retry_after':time.time() + 3600}

    with ThreadPoolExecutor(max_workers=4) as pool:
        entries = dict(pool.map(collect, urls))
    if shared_directory:
        with closing(shared_catalog(shared_directory)) as catalog, catalog:
            for url, entry in entries.items():
                if entry.get('status') == 'cached':
                    catalog.execute('INSERT OR REPLACE INTO previews VALUES (?,?)', (url, json.dumps(entry, ensure_ascii=False, separators=(',', ':'))))
    manifest = json.dumps({**old, **entries}, ensure_ascii=False, separators=(',', ':')) + '\n'
    if len(manifest.encode()) > 100_000:
        raise ValueError('Preview manifest exceeds its limit; preserve it')
    atomic_text(manifest_path, manifest)
    return entries


def cached_previews(directory, urls, responsive=False):
    """Read only checked raster assets for the selected briefing's citations."""
    path = directory / "manifest.json"
    if not path.is_file() or path.is_symlink() or directory.is_symlink() or path.stat().st_size > 100_000:
        return {}, {}
    try:
        entries = json.loads(path.read_text())
    except (ValueError, UnicodeError):
        return {}, {}
    if not isinstance(entries, dict):
        return {}, {}
    selected, files = {}, {}
    for url in urls:
        entry = entries.get(url, {})
        name = object_name(entry)
        if not name:
            continue
        asset = directory / name
        if not asset.exists():
            asset = directory.parent / 'objects' / name
        data = checked_image(asset, entry.get('sha256'))
        if data is None:
            continue
        alt = entry.get('alt')
        selected[url] = {**entry, "src": "media/" + name, 'alt': alt if isinstance(alt, str) else 'Publisher article preview'}
        if responsive:
            try:
                from PIL import Image
                with Image.open(io.BytesIO(data)) as image:
                    if image.format != 'WEBP' or not 0 < image.width <= 640 or not 0 < image.height <= 480:
                        selected.pop(url)
                        continue
                    selected[url].update(width=image.width, height=image.height,
                        small_width=thumbnail_dimensions(image.width, image.height)[0],
                        small_src='/media/thumb-v1/' + name)
            except ImportError:
                pass  # Optional Pillow absent: keep the existing full-size preview.
            except (ValueError, OSError, Image.DecompressionBombError):
                selected.pop(url)
                continue
        files["media/" + name] = data
    return selected, files
