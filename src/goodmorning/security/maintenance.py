"""Deployment pause flag. Stored in the encrypted accounts DB, read by the gateway.

When enabled, the gateway serves a cute 503 maintenance page for all browser
navigations (including pre-login) and 503 JSON with Retry-After for APIs.
The background queue pump still reconciles finished work but never dispatches
new queued work while paused.
"""
import html
import json
import time

MAINTENANCE_KEY = 'maintenance'
RETRY_AFTER_SECONDS = 60

MESSAGE_EN = ('The website is being maintained for a quick update. '
              'Please come back later. Your saved work is safe.')
MESSAGE_ZH = ('网站正在进行一次快速更新维护，请稍后再回来看看。你保存的内容都不会丢。')


class MaintenancePaused(ValueError):
    """Raised when new work is attempted while the pause flag is enabled."""


def _parse(raw):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict) or value.get('enabled') is not True:
        return None
    return value


def get_state(accounts):
    """Return the maintenance dict when paused, else None. Never raises for bad rows."""
    try:
        with accounts.db() as db:
            row = db.execute('SELECT value FROM metadata WHERE key=?', (MAINTENANCE_KEY,)).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return _parse(row[0])


def is_paused(accounts):
    return get_state(accounts) is not None


def set_state(accounts, enabled, *, reason=None, by=None):
    """Enable or disable the pause flag. Returns the stored dict or None."""
    if enabled:
        if reason is not None and (not isinstance(reason, str) or not 1 <= len(reason) <= 200):
            raise ValueError('Maintenance reason must be 1-200 characters')
        if by is not None and (not isinstance(by, str) or not 1 <= len(by) <= 40):
            raise ValueError('Maintenance owner must be 1-40 characters')
        value = {'enabled': True, 'started': time.time()}
        if reason:
            value['reason'] = reason
        if by:
            value['by'] = by
        with accounts.db() as db:
            db.execute('INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (MAINTENANCE_KEY, json.dumps(value, separators=(',', ':'))))
        return value
    with accounts.db() as db:
        db.execute('DELETE FROM metadata WHERE key=?', (MAINTENANCE_KEY,))
    return None


def json_error():
    return {'error': MESSAGE_EN}


def html_page():
    """Bilingual 503 page. Prefers the styled static file; falls back inline.

    The gateway serves this directly (Cache-Control: no-store, Retry-After).
    The NGINX static fallback (assets/web/maintenance.html) uses the same copy.
    """
    try:
        from goodmorning.paths import WEB_ASSETS
        data = (WEB_ASSETS / 'maintenance.html').read_bytes()
        if b'maintenance-status' in data and b'GoodMorning' in data:
            return data
    except (OSError, UnicodeError):
        pass
    # Keep wording identical to assets/web/maintenance.html. Clear info first,
    # then comfortable/cute. Decorative emoticons are aria-hidden.
    return (b'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            b'<meta name="viewport" content="width=device-width,initial-scale=1">'
            b'<title>GoodMorning is being maintained</title>'
            b'<style>:root{color-scheme:light;font-family:system-ui,sans-serif;color:#253d45;background:#f2f6f5}'
            b'*{box-sizing:border-box}body{margin:0;min-height:100vh;min-height:100svh;display:grid;place-items:center;padding:1rem;'
            b'background:radial-gradient(ellipse at top left,#e0ede5,transparent 60%)}'
            b'.card{width:min(100%,28rem);padding:clamp(1.4rem,5vw,2.5rem);border:1px solid #d5e0db;border-radius:1.5rem;'
            b'background:#fffefa;box-shadow:0 1rem 4rem #253d4512;text-align:center}'
            b'.eyebrow{font-size:.75rem;letter-spacing:.13em;text-transform:uppercase;color:#56746a}'
            b'h1{font-family:Georgia,serif;font-weight:500;font-size:1.8rem;margin:.4rem 0}'
            b'p{line-height:1.6;margin:.6rem 0}.emoji{font-size:2.2rem;line-height:1}'
            b'.zh{border-top:1px dashed #d5e0db;margin-top:1rem;padding-top:1rem}'
            b'a{color:#315e50}.tiny{font-size:.85rem;color:#56746a}</style></head><body><main class="card">'
            b'<div class="emoji" aria-hidden="true">\xf0\x9f\x8c\xb7 \xf0\x9f\x8d\xb5</div>'
            b'<p class="eyebrow">GoodMorning maintenance</p>'
            b'<h1>I\'m tidying up, back soon</h1>'
            b'<p role="status">The website is being maintained for a quick update. '
            b'Please come back later. Your saved work is safe. Thank you for waiting!</p>'
            b'<p class="tiny">Tip: give it a few minutes, then <a href="/">try again</a>.</p>'
            b'<div class="zh" lang="zh-CN"><div class="emoji" aria-hidden="true">\xf0\x9f\x8d\xb5 \xe2\x9c\xa8</div>'
            b'<p class="eyebrow">GoodMorning \xe7\xbb\xb4\xe6\x8a\xa4\xe4\xb8\xad</p>'
            b'<h1>\xe6\xad\xa3\xe5\x9c\xa8\xe6\x94\xb6\xe6\x8b\xbe\xe6\xa1\x8c\xe9\x9d\xa2\xef\xbc\x8c\xe9\xa9\xac\xe4\xb8\x8a\xe5\x9b\x9e\xe6\x9d\xa5</h1>'
            b'<p role="status">'
            + MESSAGE_ZH.encode()
            + b'\xe8\xb0\xa2\xe8\xb0\xa2\xe4\xbd\xa0\xe7\x9a\x84\xe7\xad\x89\xe5\xbe\x85\xef\xbc\x81</p>'
            b'<p class="tiny">\xe5\xb0\x8f\xe6\x8f\x90\xe7\xa4\xba\xef\xbc\x9a\xe8\xbf\x87\xe5\x87\xa0\xe5\x88\x86\xe9\x92\x9f\xe5\x86\x8d<a href="/">\xe9\x87\x8d\xe8\xaf\x95\xe4\xb8\x80\xe4\xb8\x8b</a>\xe3\x80\x82</p></div>'
            b'</main></body></html>')


def page_text():
    return html_page()
