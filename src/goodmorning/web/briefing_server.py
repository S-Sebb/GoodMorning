"""Private live seven-day viewer and narrowly scoped OpenChamber generation bridge."""
import argparse
from contextlib import ExitStack
import gzip
import hashlib
from datetime import date as Date, datetime, timedelta
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import secrets
import threading
import time
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, quote, parse_qs, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from goodmorning.briefings.briefing_day import briefing_day
from goodmorning.briefings.briefing_web import ASSETS, KINDS, build, celestial, edition, preview_shell, section_markup, navigation
from .briefing_resources import ByteCache, Resources, accepts_gzip, favicon_links
from goodmorning.briefings.briefing_images import checked_image, small_preview, cached_previews
from goodmorning.briefings.briefing_document import source_path
from goodmorning.briefings import briefing_document as native
from goodmorning.briefings.briefing_stream import DEFAULT_PLANS, load as load_preview, require_final
from goodmorning.runtime_files import atomic_text, profile_fields, runtime_lock
from .briefing_chat import (AVATAR_FILES, Chats, avatar_id, avatar_widget, close_question, model_answer, page as chat_page,
                            parked_forms, read_avatar, valid_answer, write_avatar)
from goodmorning.paths import ROOT
from . import language as ui
from . import models as site_models
from . import color_schemes as site_colors
from .release import VERSION, release_info, acknowledge_version
from .session_inventory import job_session_title
from .chat_theme import clock_theme
from .chat_uploads import MAX_UPLOAD_BYTES, UPLOAD_ROUTE, IMAGE_ROUTE, upload_name, expire_forever
from .avatar_images import MAX_AVATAR_BYTES, AVATAR_UPLOAD_ROUTE, find_image, image_urls, save_image
from .bridge_json import read_json
from .activity import ACTIVITY_PATH, snapshot as activity_snapshot
from . import app_briefings
from .briefing_reminders import ReminderLines, Unknown
from . import schedule
from . import letters
from . import about_me
from . import quick_chat
from .quick_notes import Notes

DESK_ART = '<svg viewBox="0 0 64 64" width="64" height="64" fill="none" aria-hidden="true"><rect x="15" y="8" width="36" height="48" rx="7" fill="var(--surface)" stroke="currentColor" stroke-width="1.5"/><path d="M24 19h18M24 25h12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" opacity=".4"/><circle cx="27" cy="36" r="1.5" fill="currentColor"/><circle cx="39" cy="36" r="1.5" fill="currentColor"/><path d="M28 43q5 5 10 0" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>'

# Waiting-page labels for the step the job helper recorded: collecting a section's
# sources, then writing it with (one, many, none-or-unknown) item counts.
COLLECTING = {'weather': 'Checking the weather forecast', 'news': 'Collecting the news',
              'schedule': 'Looking through your calendar', 'tasks': 'Gathering your tasks',
              'attention': 'Checking your reminders', 'today': 'Looking over today’s updates',
              'anime': 'Checking for new episodes', 'games': 'Checking game sales', 'stocks': 'Checking your stocks',
              'letter': 'Looking back on your week'}
WRITING = {'weather': ('Writing up the weather',) * 3,
           'news': ('Choosing from 1 story', 'Choosing from {count} stories', 'Writing up the news'),
           'schedule': ('Arranging 1 appointment', 'Arranging {count} appointments', 'Writing up your schedule'),
           'tasks': ('Sorting 1 task', 'Sorting {count} tasks', 'Writing up your tasks'),
           'attention': ('Writing up 1 reminder', 'Writing up {count} reminders', 'Writing up your reminders'),
           'today': ('Reviewing 1 update from today', 'Reviewing {count} updates from today', 'Reviewing your day'),
           'anime': ('Writing up 1 new episode', 'Writing up {count} new episodes', 'Writing up new episodes'),
           'games': ('Writing up 1 game deal', 'Writing up {count} game deals', 'Writing up game sales'),
           'stocks': ('Summing up 1 holding', 'Summing up {count} holdings', 'Summing up your stocks'),
           'letter': ('Writing your weekly letter',) * 3}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


class Chamber:
    def __init__(self, url, directory):
        parsed = urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path not in ('', '/') or parsed.username or parsed.query or parsed.fragment:
            raise ValueError('OpenChamber must be an explicit loopback HTTP origin')
        self.url, self.directory = url.rstrip('/'), str(directory)

    def request(self, path, body=None, method=None):
        headers = {'x-opencode-directory': quote(self.directory, safe='')}
        token = os.environ.get('GM_OPENCHAMBER_TOKEN')
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(self.url + path, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        with build_opener(NoRedirect).open(request, timeout=20) as response:
            return read_json(response, attachment_data=urlsplit(path).path.endswith(('/prompt', '/message')),
                             message_data=urlsplit(path).path.endswith('/message'))

    def control(self, action, **parameters):
        if action == 'session.messages':
            # OpenChamber 2.2 multiplies this limit by four, exceeding V2's 200.
            # Read bounded native pages instead; keep the requested visible-message window.
            session = parameters['sessionId']
            limit = parameters.get('limit', 100)
            messages, cursor = [], None
            for _ in range(max(10, limit // 10)):
                query = {'limit': 200, **({'cursor': cursor} if cursor else {'order': 'desc'})}
                page = self.request(f'/api/session/{session}/message?' + urlencode(query))
                for entry in page['data']:
                    role = entry.get('type')
                    if role not in ('user', 'assistant'):continue
                    text = entry.get('text', '') if role == 'user' else ''.join(
                        part['text'] for part in entry.get('content', []) if part.get('type') == 'text')
                    # The engine interrupts a run after an hour without activity, closing a question
                    # nobody answered. Its input is private tool state, so only the tool IDs remain.
                    questions = [part['id'] for part in entry.get('content', []) if role == 'assistant'
                                 and part.get('type') == 'tool' and part.get('name') == 'question']
                    if questions and (entry.get('error') or {}).get('type') == 'aborted':
                        messages.append({'id': entry['id'] + ':expired', 'role': 'assistant', 'text': '',
                                         'kind': 'expired', 'tools': questions})
                    if text.strip():messages.append({'id': entry['id'], 'role': role, 'text': text.strip()})
                next_cursor = page['cursor'].get('next')
                if len(messages) >= limit or not next_cursor:break
                if next_cursor == cursor:raise ValueError('Repeated message cursor')
                cursor = next_cursor
            status = self.request('/api/openchamber/control', {'action': 'session.status',
                'input': {'directory': self.directory, 'sessionId': session}})
            return {**status, 'messages': list(reversed(messages[:limit])), 'more': len(messages) > limit or bool(next_cursor)}
        return self.request('/api/openchamber/control', {'action': action, 'input': {'directory': self.directory, **parameters}})

    def relocate(self, session):
        """A session keeps its original release location across server updates. Moves only this
        resumed session to the running release, without replacing its history; True when it moved."""
        if self.request(f'/api/session/{session}')['data']['location']['directory'] == self.directory:
            return False
        self.request(f'/api/session/{session}/move', {'directory': self.directory})
        if self.request(f'/api/session/{session}')['data']['location']['directory'] != self.directory:
            raise ValueError('Conversation release update was not confirmed')
        return True

    def pending(self, session):
        return (self.request(f'/api/session/{session}/form').get('data', []),
                self.request(f'/api/session/{session}/permission').get('data', []))


class BrowserApp:
    def __init__(self, runtime, chamber=None, now=None, *, preflight=False):
        self.runtime = runtime.resolve()
        self.zone = profile_fields(runtime).get('timezone')
        self.chamber, self.now = chamber, now
        self.preflight = preflight
        self.csrf = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.cache = ByteCache(16 * 1024 * 1024, 14)
        self.pages = ByteCache(8 * 1024 * 1024, 14)
        self.profile_cache = None
        self.media = ByteCache(4 * 1024 * 1024, 128)
        self.thumbnails = ByteCache(2 * 1024 * 1024, 128)
        self.resources = Resources(ASSETS)
        self.chats = Chats(self.runtime, chamber)
        self.reminders = ReminderLines(self.runtime, chamber)
        self.notes = Notes(self.runtime)
        self.job_dir = self.runtime / 'browser-jobs'
        if self.job_dir.is_symlink():
            raise ValueError('Unsafe job directory')
        self.job_dir.mkdir(mode=0o700, exist_ok=True)
        self.job_file = self.job_dir / 'jobs.json'
        if self.job_file.is_symlink():
            raise ValueError('Unsafe job registry')
        self.jobs = json.loads(self.job_file.read_text()) if self.job_file.exists() else {}
        # A restart cannot prove that an interrupted create/send failed.
        for job in self.jobs.values():
            if job['state'] == 'starting':
                job['state'] = 'uncertain'
        if self.jobs:
            self.save_jobs()

    def profile(self):
        path = self.runtime / 'profile.md'
        signature = self.file_signature(path)
        with self.lock:
            if self.profile_cache is None or self.profile_cache[0] != signature:
                self.profile_cache = signature, profile_fields(self.runtime)
            return self.profile_cache[1]

    @staticmethod
    def file_signature(path):
        if path.is_symlink():raise ValueError('Unsafe cached source')
        try:
            stat = path.stat()
            return stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size
        except FileNotFoundError:return None

    def today(self):
        self.zone = self.profile().get('timezone')
        if not self.zone:
            raise ValueError('Initialize your profile timezone first')
        return briefing_day(self.zone, self.now() if self.now else None)

    def avatar(self):
        return read_avatar(self.runtime)

    def release_seen(self, replacement=None):
        with self.lock:
            path = self.runtime / 'release-seen.json'
            self.file_signature(path)
            seen = json.loads(path.read_text())['version'] if path.exists() else None
            if replacement is not None:
                seen = acknowledge_version(replacement, seen)
                atomic_text(path, json.dumps({'version': seen}) + '\n')
            return seen

    def set_avatar(self, value):
        with self.lock:
            return write_avatar(self.runtime, avatar_id(value))

    def avatar_sources(self):
        sources = {entry: {variant: self.resources.urls.get(name, '/' + name) for variant, name in files.items()}
                   for entry, files in AVATAR_FILES.items()}
        custom = image_urls(self.runtime)
        if custom:
            sources['custom'] = custom
        return sources

    def app_profile(self):
        """The secretary's name and portrait for the Android widgets."""
        from goodmorning.runtime_files import normalize_secretary_name
        name = normalize_secretary_name(profile_fields(self.runtime).get('secretary_name', '')) or None
        avatar = self.avatar()
        urls = image_urls(self.runtime) if avatar == 'custom' else None
        return {'name': name, 'avatar': avatar, 'image': urls and (urls['profile'] or urls['day'])}

    def reminder_state(self):
        """Today's editions as reminders see them, and the lines to remind with in the website language."""
        date = self.today()
        editions = {}
        for kind in KINDS:
            job = self.jobs.get(date + '.' + kind)
            state = self.status(job['id'])['state'] if job else 'missing'
            saved = self.source(date, kind).is_file() and (state in ('ready', 'missing') or not self.preflight)
            editions[kind] = 'ready' if saved else 'missing' if state in ('ready', 'missing') else state
        return {'date': date, 'timezone': self.zone, 'editions': editions, **self.reminders.current(ui.current())}

    def chat_state(self, chat):
        """A sort conversation's state; one still waiting in the gateway's line is not here yet."""
        try:
            return self.chats.status(chat, include_messages=False)['state']
        except ValueError:
            return 'starting'

    def avatar_settings(self):
        with self.lock:
            return {'avatar': self.avatar(), 'avatars': [{'id': entry, **source}
                    for entry, source in self.avatar_sources().items()]}

    def upload_avatar(self, data, variant='night'):
        with self.lock:
            self.file_signature(self.runtime / 'website-avatar.json')
            save_image(self.runtime, data, variant)
            self.set_avatar('custom')
            return self.avatar_settings()

    def briefing_avatar(self, avatar=None, kind='gm'):
        return avatar_widget(avatar or self.avatar(), self.avatar_sources(), 'briefing-avatar', kind)

    def briefing_layout(self, text, avatar=None, kind='gm'):
        text = text.replace('</head>', '<link rel="stylesheet" href="/scroll-rails.css"><script src="/scroll-rails.js" defer></script></head>')
        portrait = self.briefing_avatar(avatar, kind)
        text = re.sub(r'<body([^>]*)>', lambda match: '<body' + match[1] + ' class="briefing-letter">', text, count=1)
        text, count = re.subn(r'<div class="hero-copy">(.*?)</div>',
                             lambda match: '<div class="hero-copy">' + portrait + '<div class="letter-copy">' + match[1] + '</div></div>',
                             text, count=1, flags=re.S)
        if not count:
            text = text.replace('<p class="eyebrow">', portrait + '<p class="eyebrow">', 1)
        text = re.sub(r'<div class="briefing-tools">.*?</div>', '', text, count=1, flags=re.S)
        questions = '<div id="agent-questions"></div>'
        if questions in text and '<article' in text:
            text = text.replace(questions, '', 1)
            text = re.sub(r'<article\b', questions + '<article', text, count=1)
        links = []
        layouts = {}
        for section_match in re.finditer(r'<section id="section-(\d+)" class="briefing-section ([^"]+)"', text):
            layouts[section_match.group(1)] = section_match.group(2).split()[0] if section_match.group(2).strip() else 'notes'
        symbols = {'weather': 'sun', 'news': 'news', 'schedule': 'calendar',
                   'must-do': 'check', 'nice-to-do': 'list', 'reminders': 'bell', 'tomorrow': 'calendar',
                   'today': 'sun', 'still-open': 'list', 'tasks': 'check', 'attention': 'bell'}
        from goodmorning.briefings.briefing_layout import icon as section_icon
        for match in re.finditer(r'<a class="scroll-chunk" href="(#section-(\d+))"([^>]*)>', text):
            label = re.search(r'aria-label="\d+: ([^"]+)"', match.group(3))
            if not label:
                continue
            full = html.unescape(label.group(1))
            base, iso = native.split_dated_title(full)
            number = match.group(2)
            layout = layouts.get(number, 'notes')
            symbol = symbols.get(layout, 'list')
            if iso:
                human = native.humanize_iso_date(iso)
                visible = (section_icon(symbol) + '<span class="nav-label" data-content>' + html.escape(base) + '</span>' +
                           ' <span class="nav-date" data-date="' + html.escape(iso, quote=True) + '" data-content>· ' + html.escape(human) + '</span>')
                links.append(f'<a href="{match.group(1)}" data-layout="{html.escape(layout, quote=True)}" aria-label="{html.escape(full, quote=True)}" data-content>{visible}</a>')
            else:
                visible = section_icon(symbol) + '<span class="nav-label" data-content>' + html.escape(base) + '</span>'
                links.append(f'<a href="{match.group(1)}" data-layout="{html.escape(layout, quote=True)}" data-content>{visible}</a>')
        navigation = '<nav class="briefing-section-nav" aria-label="Briefing sections">' + ''.join(links) + '</nav>'
        text = re.sub(r'<article\b', navigation + '<article', text, count=1)
        text = text.replace('</head>', '<link rel="stylesheet" href="/avatar.css"></head>')
        text = text.replace('</body>', '<script src="/avatar.js" defer></script></body>')
        picker = ('<button id="mobile-sections" type="button" hidden aria-controls="mobile-section-dialog" aria-expanded="false" aria-label="Browse sections">'
                  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true"><path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><span>Sections</span></button>'
                  '<dialog id="mobile-section-dialog" aria-labelledby="mobile-section-heading"><header><h2 id="mobile-section-heading">Briefing sections</h2>'
                  '<button id="close-sections" type="button" aria-label="Close sections"><svg viewBox="0 0 20 20" width="20" height="20" fill="none" aria-hidden="true"><path d="m6 6 8 8m0-8-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></button></header>'
                  '<nav id="mobile-section-list" aria-label="Briefing sections"></nav></dialog>')
        text = text.replace('</body>', picker + '</body>')
        return text

    def chat_settings(self):
        from goodmorning.setup_check import profile_status
        try:
            status = profile_status(self.runtime, self.profile(),ui.current())
            ready = status['profile_ready']
            secretary_name = status.get('secretary_name')
        except (ValueError, KeyError):
            ready = False
            secretary_name = None
        current = self.avatar()
        return {'defaultMode': 'secretary' if ready else 'initialize', 'connected': bool(self.chamber),
                **clock_theme(self.profile().get('timezone'), self.now() if self.now else None),
                'secretary_name': secretary_name, 'avatar': current,
                'avatars': self.avatar_settings()['avatars']}

    def chat_page(self):
        settings = self.chat_settings()
        return self.resources.rewrite(ui.page(chat_page(self.csrf, settings['defaultMode'] == 'secretary', settings['connected'], settings.get('secretary_name'), settings['avatar'], {item['id']: {key: value for key, value in item.items() if key != 'id'} for item in settings['avatars']}, settings['timezone'], settings['theme']),self.csrf,'/chat')).encode()

    def initialization_page(self, kind):
        switches = ''.join(f'<a class="edition-link{" selected" if other == kind else ""}" href="/{other}.html">{label}</a>' for other, label in KINDS.items()) + '<a class="edition-link" href="/schedule">Schedule</a><a class="edition-link" href="/letters">Letters</a>'
        text = f'<!doctype html><html lang="en" data-edition="{kind}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>Initialize your secretary — GoodMorning</title><link rel="stylesheet" href="/briefing.css"></head><body><header class="masthead"><a class="wordmark" href="/{kind}.html">GoodMorning<span>A personal secretary just for you</span></a><nav class="edition-switch" aria-label="Edition">{switches}<a class="edition-link" href="/chat">Secretary</a></nav></header><main><section class="waiting-room"><div class="waiting-art">{celestial(kind)}</div><p class="eyebrow">{KINDS[kind]} edition</p><h1>Let’s make this yours.</h1><p class="subtitle">Complete your secretary’s setup before preparing a briefing. Your saved records stay unchanged.</p><a id="initialize" class="initialize-button" href="/chat?mode=initialize">Initialize my secretary</a></section></main></body></html>'
        text = self.briefing_layout(text, kind=kind)
        return self.resources.rewrite(ui.page(text.replace('</head>', favicon_links(kind) + '</head>'),self.csrf,'/'+kind+'.html')).encode()

    def dates(self):
        today = Date.fromisoformat(self.today())
        return [(today - timedelta(days=i)).isoformat() for i in range(7)]

    def source(self, date, kind):
        if date not in self.dates() or kind not in KINDS:
            raise ValueError('Edition outside the seven-day window')
        return source_path(self.runtime, date, kind)

    def save_jobs(self):
        atomic_text(self.job_file, json.dumps(self.jobs) + '\n')

    def week(self, date, kind):
        days = []
        today = self.today()
        for day in reversed(self.dates()):
            label = ui.day_label(day)
            ready = self.source(day, kind).is_file()
            selected = ' aria-current="date"' if day == date else ''
            link = f'/{kind}.html' if day == today else f'/d/{day}/{kind}.html'
            marker = '<span class="today-marker">Today</span>' if day == today else ''
            missing = '' if ready else ' class="is-missing"'
            days.append(f'<a href="{link}"{missing}{selected}>{marker}{label}<small>{"Saved" if ready else "Not generated"}</small></a>')
        return '<nav class="week-picker" aria-label="Past seven briefing days">' + ''.join(days) + '</nav>'

    def files(self, date, kind):
        signature = []
        source = self.source(date, kind)
        if source.is_symlink():
            raise ValueError('Unsafe source')
        signature.append(self.file_signature(source))
        signature = (str(source), *signature)
        manifest = self.runtime / 'browser-images' / date / 'manifest.json'
        if manifest.is_symlink() or manifest.parent.is_symlink():
            raise ValueError('Unsafe image manifest')
        signature += (self.file_signature(manifest),)
        with self.lock:
            key = date, kind, ui.current()
            cached = self.cache.get(key)
            if not cached or cached[0] != signature:
                files = build(self.runtime, date, include_assets=False, kind=kind) if signature[1] else {}
                for name, data in files.items():
                    if name.startswith('media/'):
                        shared = self.media.get(name)
                        if shared is None:
                            self.media.put(name, data, len(data))
                        else:
                            files[name] = shared
                # Each immutable byte string is counted once, including index aliases.
                size = sum(len(data) for data in {id(data): data for data in files.values()}.values())
                self.cache.put(key, (signature, files), size)
                return files
            return cached[1]

    def image(self, name):
        # The caller's route permits only a SHA-256-named WebP, never a path.
        with self.lock:
            cached = self.media.get('media/' + name)
            if cached is not None:
                return cached
            root = self.runtime / 'browser-images'
            if root.is_symlink():
                return None
            for directory in [root / 'objects'] + [root / day for day in self.dates()]:
                data = checked_image(directory / name, name[:64])
                if data is not None:
                    self.media.put('media/' + name, data, len(data))
                    return data
        return None

    def thumbnail(self, name):
        with self.lock:
            cached = self.thumbnails.get(name)
            if cached is not None:
                return cached
            data = self.image(name)
            if data is None:
                return None
            try:
                preview = small_preview(data)
            except (ImportError, ValueError, OSError):
                return None
            self.thumbnails.put(name, preview, len(preview))
            return preview

    def page(self, date, kind, pinned):
        if not pinned and self.chat_settings()['defaultMode'] == 'initialize' and not native.source_path(self.runtime,date,kind).is_file():
            return self.initialization_page(kind)
        path = self.source(date, kind)
        week = self.week(date, kind)
        confirmed = path.is_file()
        avatar = self.avatar()
        current_job = self.jobs.get(date+'.'+kind)
        if confirmed and self.preflight and current_job and self.status(current_job['id'])['state'] != 'ready':
            confirmed = False
        page_key = date, kind, pinned, ui.current(), tuple(site_colors.current().items()), VERSION
        page_signature = None
        if confirmed:
            manifest = self.runtime / 'browser-images' / date / 'manifest.json'
            if manifest.parent.is_symlink():raise ValueError('Unsafe image manifest')
            page_signature = self.file_signature(path), self.file_signature(manifest), week, VERSION, avatar, json.dumps(self.avatar_sources(), sort_keys=True), current_job and (current_job['id'], current_job['state'])
            with self.lock:
                cached = self.pages.get(page_key)
                if cached and cached[0] == page_signature:return cached[1]
        if confirmed:
            text = self.files(date, kind)[f'{kind}.html'].decode()
            switches = ''.join(f'<a class="edition-link{" selected" if other == kind else ""}" href="{f"/d/{date}/{other}.html" if pinned else f"/{other}.html"}">{label}</a>' for other, label in KINDS.items())
            text = re.sub(r'<nav class="edition-switch"[^>]*>.*?</nav>', '<nav class="edition-switch" aria-label="Edition">' + switches + '</nav>', text)
            text = text.replace('<main id="content">', '<main id="content">' + week)
            text = text.replace(f'{date} / {KINDS[kind]} edition', f'{KINDS[kind]} edition')
            text = text.replace('href="briefing.css"', 'href="/briefing.css"').replace('src="briefing.js"', 'src="/briefing.js"')
            text = text.replace('href="fonts/lora-italic.woff2"', 'href="/fonts/lora-italic.woff2"')
            text = text.replace('href="index.html"', f'href="/{kind}.html"')
            text = text.replace(f'href="{kind}{path.suffix}"', f'href="/d/{date}/{kind}{path.suffix}"').replace('src="media/', 'src="/media/')
        else:
            current = date == self.today()
            button = '<button id="generate" type="button">Prepare my ' + KINDS[kind].lower() + ' briefing</button>' if current and self.chamber else ''
            heading = 'Your briefing awaits.' if current else 'No briefing was prepared for this day.'
            detail = 'Would you like your secretary to put it together?' if current else 'Past briefings can’t be created afterwards. Your saved plans for this day are still in Schedule.'
            if not current:
                offset = (Date.fromisoformat(date) - Date.fromisoformat(self.today())).days
                button = f'<a class="initialize-button" href="/schedule?view=day&amp;day={offset}">Open this day in Schedule</a>'
            if current and not self.chamber:
                detail = 'Generation is not connected. Start this viewer with an OpenChamber connection.'
            switches = ''.join(f'<a class="edition-link{" selected" if other == kind else ""}" href="{f"/d/{date}/{other}.html" if pinned else f"/{other}.html"}">{label}</a>' for other, label in KINDS.items())
            text = f'<!doctype html><html lang="en" data-edition="{kind}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>{KINDS[kind]} briefing — GoodMorning</title><link rel="stylesheet" href="/briefing.css"></head><body><header class="masthead"><a class="wordmark" href="/{kind}.html">GoodMorning<span>A personal secretary just for you</span></a><nav class="edition-switch" aria-label="Edition">{switches}</nav></header><main>{week}<section class="waiting-room"><div class="waiting-art">{celestial(kind)}</div><p class="eyebrow">{KINDS[kind]} edition</p><h1>{heading}</h1><p class="subtitle">{detail}</p>{button}<div id="generation" hidden><div class="desk-animation" aria-hidden="true">✦<span>▱</span>✦</div><progress id="generation-progress" max="100" value="5" aria-label="Briefing preparation stages"></progress><p id="generation-status" role="status"></p><div id="agent-questions"></div></div><p id="generation-error" role="alert"></p><noscript>Enable JavaScript to prepare a briefing. Saved editions can still be read.</noscript></section></main></body></html>'
            if (current and self.chamber) or date + '.' + kind in self.jobs:
                controls = re.search(r'<div id="generation".*?</noscript>', text)[0]
                document = {'v': 1, 'greeting': heading, 'opening': detail, 'sections': []}
                text = edition(document, date, kind, KINDS, preview_plan=DEFAULT_PLANS[kind],ui_intro=True)
                text = text.replace('<main id="content">', '<main id="content">' + week)
                text = re.sub(r'<nav class="edition-switch"[^>]*>.*?</nav>', '<nav class="edition-switch" aria-label="Edition">' + switches + '</nav>', text)
                text = re.sub(r'<div class="briefing-tools">.*?</div>', '<section class="generation-desk">' + button + controls + '<p class="preview-notice">Unfinished preview · sections appear here as they are prepared. Nothing is saved yet.</p></section>', text)
                text = text.replace('href="briefing.css"', 'href="/briefing.css"').replace('src="briefing.js"', 'src="/briefing.js"').replace('href="fonts/', 'href="/fonts/').replace('href="index.html"', f'href="/{kind}.html"')
                text = text.replace(f'{date} / {KINDS[kind]} edition', f'{KINDS[kind]} edition')
        text = self.briefing_layout(text, avatar, kind)
        can_restart = date == self.today() and bool(self.chamber) and self.preflight
        if can_restart:
            hidden = '' if confirmed or current_job else ' hidden'
            disabled = '' if confirmed else ' disabled'
            tools = ('<div class="briefing-actions"><button id="regenerate" type="button" aria-haspopup="dialog"' + hidden + disabled + '>'
                     '<svg viewBox="0 0 20 20" width="16" height="16" fill="none" aria-hidden="true"><path d="M16 8a6 6 0 1 0 .2 3M16 3v5h-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
                     '<span>Regenerate today’s briefing</span></button><p id="regeneration-status" role="status"></p><p id="regeneration-error" role="alert"></p></div>')
            text = re.sub(r'(<nav class="briefing-section-nav")', tools + r'\1', text, count=1)
            dialog = ('<dialog id="regenerate-dialog" aria-labelledby="regenerate-title" aria-describedby="regenerate-description">'
                      '<form method="dialog"><p class="eyebrow">A fresh start</p><h2 id="regenerate-title">Regenerate today’s briefing?</h2>'
                      '<p id="regenerate-description">Your last saved briefing stays safe until the new one is saved. Tasks, completions and saved feedback are kept. A new secretary session will prepare the replacement.</p>'
                      '<div class="dialog-actions"><button value="cancel">Keep this briefing</button><button value="regenerate" id="confirm-regenerate">Regenerate briefing</button></div></form></dialog>')
            text = text.replace('</body>', dialog + '</body>')
        text = text.replace('<span>▱</span>', '<span>' + DESK_ART + '</span>')
        text=text.replace('<p id="generation-status" role="status"></p>','<p id="generation-status" role="status"></p><p id="generation-elapsed"></p><p id="request-language-note" role="status"></p>')
        missing = not confirmed
        config = json.dumps({'date': date, 'kind': kind, 'pinned': pinned, 'csrf': self.csrf if missing or can_restart else None, 'missing': missing,
                             'job': current_job['id'] if current_job else None,
                             # Namespaces the evening check-in answers this device keeps; the gateway changes it with every sign-in.
                             'workspaceScope': hashlib.sha256(('chat-workspace:' + self.csrf).encode()).hexdigest()}).replace('<', '\\u003c')
        # Inert JSON in a data attribute; no inline scripts or unsafe HTML.
        marker = '<div id="browser-config" hidden data-config="' + html.escape(config, quote=True) + '"></div><script src="/questions.js" defer></script><script src="/browser.js" defer></script>'
        text = re.sub(r'(<nav class="edition-switch"[^>]*>.*?)(</nav>)', r'\1<a class="edition-link" href="/schedule">Schedule</a><a class="edition-link" href="/letters">Letters</a><a class="edition-link" href="/chat">Secretary</a>\2', text, count=1)
        text = text.replace('href="icons/', 'href="/icons/')
        if '<link rel="icon"' not in text:
            text = text.replace('</head>', favicon_links(kind) + '</head>')
        return_to=f'/d/{date}/{kind}.html' if pinned else f'/{kind}.html'
        output = self.resources.rewrite(ui.page(quick_chat.widget(text.replace('</body>', marker + '</body>'), self.csrf),self.csrf,return_to)).encode()
        if confirmed:
            with self.lock:self.pages.put(page_key, (page_signature, output), len(output))
        return output

    def offline_page(self, kind):
        """The latest saved edition as the read-only copy a device keeps for reading offline (sw.js).

        It has no request token, form or account control, so keeping it on a device keeps no secret.
        None while the newest saved edition awaits its check, so devices keep the copy they have."""
        date = next((day for day in self.dates() if self.source(day, kind).is_file()), None)
        if date is None:
            raise ValueError('No saved edition')
        job = self.jobs.get(date + '.' + kind)
        if self.preflight and job and self.status(job['id'])['state'] != 'ready':
            return None
        saved = datetime.fromtimestamp(self.source(date, kind).stat().st_mtime, ZoneInfo(self.zone))
        time_text = f'{saved:%H:%M}'
        text = self.files(date, kind)[f'{kind}.html'].decode()
        switches = ''.join(f'<a class="edition-link{" selected" if other == kind else ""}" href="/{other}.html">{label}</a>' for other, label in KINDS.items())
        text = re.sub(r'<nav class="edition-switch"[^>]*>.*?</nav>', '<nav class="edition-switch" aria-label="Edition">' + switches + '</nav>', text)
        text = re.sub(r'<div class="briefing-tools">.*?</div>', '', text, count=1, flags=re.S)
        text = text.replace('href="briefing.css"', 'href="/briefing.css"').replace('src="briefing.js"', 'src="/briefing.js"')
        text = text.replace('href="fonts/', 'href="/fonts/').replace('href="icons/', 'href="/icons/').replace('href="index.html"', f'href="/{kind}.html"')
        # The device keeps only each image's plain source, so no other size is asked for offline.
        text = re.sub(r'\s(?:srcset|sizes)="[^"]*"', '', text.replace('src="media/', 'src="/media/'))
        # briefing.js drops the date only while the edition is the account's current day in its timezone, and
        # sw.js marks a copy shown because the server failed rather than the connection (unreachable).
        date_text = ui.day_text(saved.date().isoformat())
        notice = (f'<p class="offline-notice" role="status" data-day="{date}" data-zone="{html.escape(self.zone, quote=True)}">'
                  '<span class="offline-earlier">' + ui.ui('You’re offline · showing the version from {date}, {time}.', date=date_text, time=time_text) + '</span>'
                  '<span class="offline-today" hidden>' + ui.ui('You’re offline · showing the version from {time}.', time=time_text) + '</span>'
                  '<span class="unreachable-earlier" hidden>' + ui.ui('GoodMorning can’t be reached right now · showing the version from {date}, {time}.', date=date_text, time=time_text) + '</span>'
                  '<span class="unreachable-today" hidden>' + ui.ui('GoodMorning can’t be reached right now · showing the version from {time}.', time=time_text) + '</span> '
                  '<a href="">' + ui.ui('Try again') + '</a></p>')
        text = text.replace('<main id="content">', '<main id="content">' + notice, 1)
        text = text.replace('</head>', '<link rel="stylesheet" href="/color-schemes.css"><link rel="stylesheet" href="/pixel.css"></head>', 1)
        return self.resources.rewrite(ui.translate(site_colors.mark(text))).encode()

    def start(self, date, kind, requested_at=None):
        if self.chat_settings()['defaultMode'] == 'initialize':
            raise ValueError('Initialize your secretary before preparing a briefing')
        self.source(date, kind)
        if date != self.today() or not self.chamber:
            raise ValueError('Only today can be generated with a connected secretary')
        with self.lock:
            if self.source(date, kind).exists():
                existing = self.jobs.get(date+'.'+kind)
                if existing and self.preflight and self.status(existing['id'])['state'] != 'ready':
                    return {'job':existing['id']}  # A snapshot without its owning final marker is not ready.
                return {'ready': True}
            key = date + '.' + kind
            if key in self.jobs:
                return {'job': self.jobs[key]['id']}
            job = {'id': secrets.token_hex(16), 'date': date, 'kind': kind, 'state': 'starting','language':ui.current(),
                    'model':site_models.current(),'created': time.time()}
            from .generation_clock import timestamp
            started = requested_at if requested_at is not None else (self.now().timestamp() if self.now else time.time())
            job['generation_started_at'] = timestamp(started)
            if self.preflight:
                job.update(state='preflight')
            self.jobs[key] = job
            self.save_jobs()  # Record intent before any upstream side effect.
            if self.preflight:
                from goodmorning.briefings.briefing_preflight import initialize
                try:
                    context = initialize(self.runtime, job)
                except Exception as error:
                    job['state'] = 'stopped'
                    self.save_jobs()
                    logging.getLogger(__name__).warning('briefing_preflight_failed (%s)', type(error).__name__)
                    # Preflight failed before dispatch. Return its durable receipt
                    # so the gateway can release the slot and the user can recover.
                    return {'job': job['id']}
                if context['awaiting']:
                    return {'job':job['id']}
                job['state'] = 'starting'
                self.save_jobs()
            threading.Thread(target=self.dispatch, args=(job,), daemon=True).start()
            return {'job': job['id']}

    def generation_prompt(self, job):
        selected = job.get('language','en')
        job_label, runtime_label = ('浏览器任务','运行目录') if selected == 'zh-CN' else ('Browser job','Runtime')
        edition = f"请准备我的{'早间' if job['kind'] == 'gm' else '晚间'}简报（/{job['kind']}）。" if selected == 'zh-CN' else f"/{job['kind']}"
        return (f"{edition}\n{job_label}: {job['id']}\n"
                f"{runtime_label}: {self.runtime}\nWebsite language: {selected}")

    def dispatch(self, job):
        try:
            result = self.chamber.control('session.create', title=job_session_title(
                ui.text(KINDS[job['kind']]+' briefing',lang=job.get('language','en')), job['date']))
            session = result['sessionId']
            if not re.fullmatch(r'ses[A-Za-z0-9_]+', session):
                raise ValueError('Invalid session')
            with self.lock:
                job['session'] = session
                self.save_jobs()
            site_models.apply_to_session(self.chamber, session, job.get('model', site_models.DEFAULT))
            prompt = self.generation_prompt(job)
            dispatched = self.chamber.control('session.send', sessionId=session, prompt=prompt)
            if dispatched.get('promptDispatched') is not True:
                raise ValueError('Prompt dispatch was not confirmed')
            with self.lock:
                job.update(state='running', running_at=time.time())
                self.save_jobs()
        except Exception:
            with self.lock:
                job['state'] = 'uncertain'
                self.save_jobs()  # Never blindly replay a possibly dispatched request.

    def regenerate(self, body):
        """Replace only an explicitly confirmed, quiescent edition; never erase its records."""
        if (not isinstance(body, dict) or set(body) != {'date', 'kind', 'id', 'previous'}
                or not isinstance(body['id'], str) or not re.fullmatch('[a-f0-9]{32}', body['id'])):
            raise ValueError('Invalid regeneration request')
        date, kind = body['date'], body['kind']
        self.source(date, kind)
        if not self.preflight or not self.chamber or date != self.today():
            raise ValueError('Only today’s connected workflow can be regenerated')
        if self.chat_settings()['defaultMode'] == 'initialize':
            raise ValueError('Initialize your secretary before preparing a briefing')
        from goodmorning.briefings.briefing_replacement import snapshot
        from goodmorning.briefings.briefing_job import context_path
        from goodmorning.briefings.briefing_preflight import answer, initialize
        from goodmorning.briefings.briefing_stream import bounded_json
        with self.lock, ExitStack() as locks:
            key = date + '.' + kind
            previous = self.jobs.get(key)
            if previous and previous.get('regeneration_request') == body['id']:
                return {'job': previous['id']}
            if body['previous'] != (previous['id'] if previous else None):
                raise ValueError('This briefing changed; refresh before regenerating')
            baseline, raw = snapshot(self.runtime, date, kind)
            if not previous and raw is None and not baseline['run']['ran']:
                raise ValueError('Prepare a briefing before regenerating it')
            if previous:
                if previous['state'] in ('starting', 'uncertain'):
                    raise ValueError('Inspect uncertain dispatches in OpenChamber before regenerating')
                locks.enter_context(runtime_lock(self.job_dir, previous['id'] + '.workflow.lock'))
                locks.enter_context(runtime_lock(self.job_dir, previous['id'] + '.preview.lock'))
            session = previous.get('session') if previous else baseline['run']['session']
            if session:
                forms, permissions = self.chamber.pending(session)
                if forms or permissions or self.chamber.control('session.status', sessionId=session)['sessionStatus']['type'] != 'idle':
                    raise ValueError('Finish or stop the existing session and resolve pending inputs before regenerating')
            context = None
            if previous:
                target = context_path(self.runtime, previous['id'])
                context = bounded_json(target, 300_000) if target.exists() else None
                if context and context.get('awaiting') and context.get('browser_answer') is not None:
                    context = answer(self.runtime, previous, context['browser_answer'])
            locks.enter_context(runtime_lock(self.runtime, '.state.lock'))
            baseline, raw = snapshot(self.runtime, date, kind)
            job = {'id': secrets.token_hex(16), 'date': date, 'kind': kind, 'state': 'preflight',
                   'language': ui.current(), 'model': site_models.current(), 'created': time.time(),
                    'replacement': baseline, 'regeneration_request': body['id']}
            # Replacing presentation must not change a reminder's original trigger.
            job['generation_started_at'] = previous.get('generation_started_at') if previous else None
            try:
                context = initialize(self.runtime, job, previous=context)
            except Exception as error:
                logging.getLogger(__name__).warning('briefing_regeneration_preflight_failed (%s)', type(error).__name__)
                # No replacement owner or model dispatch has been committed.
                raise ValueError('Regeneration stopped before the new briefing was saved. Your previous briefing is preserved.') from None
            if raw is not None:
                atomic_text(self.job_dir / (job['id'] + '.previous.json'), raw.decode('utf-8'))
            if previous:
                self.jobs[key + '.' + previous['id']] = {**previous, 'state': 'superseded'}
            job['state'] = 'preflight' if context['awaiting'] else 'starting'
            self.jobs[key] = job
            self.save_jobs()  # Commit the new owner before any dispatch; old helpers now refuse writes.
            if job['state'] == 'starting':
                threading.Thread(target=self.dispatch, args=(job,), daemon=True).start()
            return {'job': job['id']}

    def recover(self, identifier, body):
        """Explicit recovery only: refresh undispatched feedback or resume a known idle session."""
        if not isinstance(body, dict) or set(body) != {'id'} or not isinstance(body['id'], str) or not re.fullmatch('[a-f0-9]{32}', body['id']):
            raise ValueError('Invalid recovery request')
        with self.lock:
            job = self.job(identifier)
            if job['state'] == 'superseded':
                raise ValueError('This browser job was replaced; refresh the briefing')
            if job.get('recovery_request') == body['id']:
                return {'job':identifier}
            if not self.preflight or not self.chamber or job['date'] != self.today():
                raise ValueError('Only today’s connected workflow can be recovered')
            status = self.status(identifier)
            live = self.jobs[job['date']+'.'+job['kind']]
            if job['state'] in ('starting', 'uncertain', 'complete'):
                raise ValueError('Inspect uncertain dispatches in OpenChamber; never replay them')
            if not job.get('session') and job['state'] in ('preflight', 'stopped'):
                from goodmorning.briefings.briefing_job import context_path
                from goodmorning.briefings.briefing_preflight import answer, initialize
                from goodmorning.briefings.briefing_stream import bounded_json
                target = context_path(self.runtime, identifier)
                context = bounded_json(target, 300_000) if target.exists() else None
                if context and context.get('awaiting') and context.get('browser_answer') is not None:
                    # A saved input may already have amended the daily record. Verify it, never discard it.
                    context = answer(self.runtime, live, context['browser_answer'])
                else:
                    revision = live.get('preflight_revision', 0) + 1
                    if context:
                        atomic_text(self.job_dir/(identifier+f'.context-r{revision}.json'), json.dumps(context)+'\n')
                    live.update(preflight_revision=revision, state='preflight')
                    self.save_jobs()
                    try:
                        context = initialize(self.runtime, live)
                    except Exception as error:
                        live.update(state='stopped', recovery_request=body['id'])
                        self.save_jobs()
                        logging.getLogger(__name__).warning('briefing_recovery_preflight_failed (%s)', type(error).__name__)
                        return {'job': identifier}
                live.update(recovery_request=body['id'], state='preflight' if context['awaiting'] else 'starting')
                self.save_jobs()
                if live['state'] == 'starting':
                    threading.Thread(target=self.dispatch, args=(live,), daemon=True).start()
            elif job.get('session') and status['state'] == 'stopped':
                forms, permissions = self.chamber.pending(job['session'])
                if forms or permissions or self.chamber.control('session.status', sessionId=job['session'])['sessionStatus']['type'] != 'idle':
                    raise ValueError('The existing session must be idle with no pending inputs')
                live.update(state='starting', recovery_request=body['id'])
                self.save_jobs()  # Record intent before sending to the existing session.
                threading.Thread(target=self.continue_session, args=(live,), daemon=True).start()
            else:
                raise ValueError('This job does not need recovery')
            return {'job':identifier}

    def park(self, identifier, session, forms):
        """Saves a briefing session's open questions, then closes them in the engine, as Chats.park
        does for conversations. The answer later continues the job from its checkpoint."""
        if not forms:
            return
        with self.lock:
            live = next(job for job in self.jobs.values() if job['id'] == identifier)
            questions = live.setdefault('questions', [])
            known = {entry['id'] for entry in questions}
            questions.extend({'id': form['id'], 'form': form, 'parked': True} for form in forms if form['id'] not in known)
            self.save_jobs()  # Saved before closing, so a crash in between loses nothing.
        for form in forms:
            if close_question(self.chamber, session, form['id']) is False:
                with self.lock:
                    questions[:] = [entry for entry in questions if entry['id'] != form['id']]
                    self.save_jobs()

    def continue_session(self, job, answer=None):
        try:
            # Closing an answered question ends the engine's run a moment later.
            for _ in range(50 if answer else 1):
                forms, permissions = self.chamber.pending(job['session'])
                idle = not forms and not permissions and self.chamber.control('session.status', sessionId=job['session'])['sessionStatus']['type'] == 'idle'
                if idle:
                    break
                time.sleep(0.2)
            if not idle:
                raise ValueError('Session changed before continuation')
            self.chamber.relocate(job['session'])
            site_models.apply_to_session(self.chamber, job['session'], job.get('model', site_models.DEFAULT))
            prompt = self.generation_prompt(job) + ('\n\n' + answer if answer else '')
            result = self.chamber.control('session.send', sessionId=job['session'], prompt=prompt)
            if result.get('promptDispatched') is not True:
                raise ValueError('Continuation was not confirmed')
            state = 'running'
        except Exception:
            state = 'uncertain'
        with self.lock:
            job['state'] = state
            if state == 'running':
                job['running_at'] = time.time()
            self.save_jobs()

    def job(self, identifier):
        with self.lock:
            job = next((dict(j) for j in self.jobs.values() if j['id'] == identifier), None)
        if not job:
            raise ValueError('Unknown briefing job')
        return job

    def preview(self, identifier, after=-1):
        job = self.job(identifier)
        target = self.job_dir / (identifier + '.preview.json')
        checkpoint = load_preview(target)
        if not checkpoint:
            return {'revision': None}
        plan, outcomes, document = (checkpoint[key] for key in ('plan', 'outcomes', 'document'))
        if not -1 <= after <= len(outcomes):
            raise ValueError('Invalid preview offset')
        images, _ = cached_previews(self.runtime / 'browser-images' / job['date'], native.image_urls(document), responsive=True)
        images = {url: {**entry, 'src': '/' + entry['src'].lstrip('/')} for url, entry in images.items()}
        changes, sections = [], iter(document['sections'])
        for index, outcome in enumerate(outcomes):
            section = next(sections) if outcome == 'ready' else None
            if index < after:
                continue
            change = {'index': index, 'state': outcome}
            if section:
                title = native.section_title(section, job['date'],document.get('lang','en'))
                content = ''.join(native.render_block(value, images, job['date']) for value in section[1])
                if len(section) >= 3 and section[2]:
                    content += '<p class="section-takeaway">' + native.escaped(section[2]) + '</p>'
                change.update(html=section_markup(index + 1, native.escaped(title), content, section[0]),
                              navigation=navigation(index + 1, title, content, job['kind']))
            changes.append(change)
        result = {'revision': self.preview_revision(checkpoint, job), 'image_revision': self.image_revision(job), 'resolved': len(outcomes), 'planned': len(plan),
                  'greeting': document['greeting'], 'opening': document['opening'], 'lang': document.get('lang', 'en'),
                  'changes': changes, 'closing': native.escaped(document.get('closing', ''))}
        if after == -1:
            result['sections'], result['navigation'] = preview_shell(plan, job['kind'])
        return result

    def image_revision(self, job):
        path = self.runtime / 'browser-images' / job['date'] / 'manifest.json'
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError('Unsafe image manifest')
        return f'{path.stat().st_mtime_ns}:{path.stat().st_size}' if path.is_file() else None

    def preview_revision(self, checkpoint, job):
        return hashlib.sha256(json.dumps([checkpoint, self.image_revision(job)], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:24]

    def activity(self, identifier, checkpoint):
        """Label and bar position for the step the job helper last recorded.
        A marker for another section than the preview's next one is stale and ignored."""
        path = self.job_dir / (identifier + '.activity.json')
        try:
            from goodmorning.briefings.briefing_stream import bounded_json
            step = bounded_json(path, 4_000) if path.exists() else None
        except (ValueError, OSError, UnicodeError):
            return None
        if not isinstance(step, dict):
            return None
        if not checkpoint:
            return {'progress': 12, 'progress_cap': 19, 'label': ui.text('Writing your greeting')} if step.get('step') == 'opening' else None
        resolved, planned = len(checkpoint['outcomes']), len(checkpoint['plan'])
        if step.get('step') in ('closing', 'save') and resolved == planned:
            return {'progress': 95, 'progress_cap': 97, 'label': ui.text('Writing a closing note')} if step['step'] == 'closing' else \
                   {'progress': 97, 'progress_cap': 99, 'label': ui.text('Saving your briefing')}
        if step.get('position') != resolved:
            return None
        share, base = 75 / planned, 20 + 75 * resolved / planned
        if step['step'] == 'images':
            label = ui.text('Fetching {total} cover pictures' if step.get('pictures') == 'covers' else 'Fetching {total} story pictures', total=step['total'])
            return {'progress': base, 'progress_cap': base + share * .05, 'label': label, 'step_label': label}
        if resolved == planned:
            return None
        tag = checkpoint['plan'][resolved][0]
        if step['step'] == 'collect' and step.get('section') == tag:
            done, total = step['done'], max(step['total'], 1)
            label = ui.text(COLLECTING.get(tag, 'Gathering this section’s sources'))
            if total > 1:
                label += ' · ' + ui.text('{done} of {total}', done=done + 1, total=total)
            return {'progress': base + share * (.05 + .35 * done / total), 'progress_cap': base + share * (.05 + .35 * (done + 1) / total),
                    'label': label, 'step_label': label}
        if step['step'] == 'write' and step.get('section') == tag:
            count = step.get('count')
            one, many, none = WRITING.get(tag, ('Writing this section',) * 3)
            label = ui.text(none) if not isinstance(count, int) or count == 0 else ui.text(one) if count == 1 else ui.text(many, count=count)
            return {'progress': base + share * .45, 'progress_cap': base + share * .95, 'label': label, 'step_label': label}
        return None

    def status(self, identifier):
        job = self.job(identifier)
        if job['state'] == 'superseded':
            return {'state': 'stopped', 'progress': 0, 'label': 'This briefing was replaced. Refresh to open the new edition.', 'forms': [], 'permissions': []}
        saved = self.source(job['date'], job['kind']).is_file()

        def verified():
            """'ready' when the saved edition is verified, 'foreign' when a valid
            edition was saved outside this job, else 'invalid'. Records stay unchanged."""
            try:
                self.files(job['date'], job['kind'])
                if self.preflight:
                    from goodmorning.records.state import parse_daily, load_state, stat_answer
                    run = parse_daily(str(self.runtime/'daily'/(job['date']+'.md')))[job['kind']]
                    if not run['ran'] or run['answer_file'] != 'daily/'+self.source(job['date'],job['kind']).name:
                        return 'invalid'
                    indexed = load_state(str(self.runtime)).get('days', {}).get(job['date'], {}).get(job['kind'], {})
                    if any(indexed.get(key) != run[key] for key in ('ran', 'session', 'answer_file')) or indexed.get('sha1') != stat_answer(str(self.source(job['date'], job['kind'])))['sha1']:
                        return 'invalid'
                    if run['session'] != job.get('session'):
                        return 'foreign'
                if preview_path.exists():
                    document = native.parse(self.source(job['date'], job['kind']).read_text())
                    require_final(self.runtime, identifier, job['date'], job['kind'], job.get('session'), document)
            except (ValueError, OSError, UnicodeError):
                return 'invalid'
            return 'ready'

        invalid = 'The saved edition is not readable. Inspect its format in OpenChamber; your records are unchanged.'
        mismatch = 'This edition was updated outside its briefing job and cannot be verified. Regenerate to replace it; your records are unchanged.'
        preview_path = self.job_dir / (identifier + '.preview.json')
        if saved and job['state'] == 'complete':
            reason = verified()
            if reason != 'ready':
                return {'state': 'stopped', 'progress': 95, 'label': mismatch if reason == 'foreign' else invalid, 'forms': [], 'permissions': [],
                        'regeneratable': self.preflight and job['date'] == self.today()}
            return {'state': 'ready', 'progress': 100, 'label': 'Your briefing is ready', 'forms': [], 'permissions': []}
        result = {'state': job['state'], 'progress': 5, 'label': 'Opening your secretary’s desk', 'forms': [], 'permissions': [],
                  'language':job.get('language'), 'date':job['date'], 'kind':job['kind']}
        if job['state'] == 'preflight':
            from goodmorning.briefings.briefing_job import context_path
            from goodmorning.briefings.briefing_stream import bounded_json
            context = bounded_json(context_path(self.runtime,identifier),300_000)
            return {**result,'state':'waiting','label':ui.text('Before your briefing'),'forms':[context['form']] if context['awaiting'] else [],
                    'reservation_required': False,
                    'recovery':'Refresh task list' if job['kind'] == 'gn' else None,'recovery_action':'refresh' if job['kind']=='gn' else None}
        checkpoint = None
        if preview_path.exists():
            try:
                checkpoint = load_preview(preview_path)
                resolved, planned = len(checkpoint['outcomes']), len(checkpoint['plan'])
                result.update(preview_revision=self.preview_revision(checkpoint, job), image_revision=self.image_revision(job), progress=20 + 75 * resolved / planned,
                              label=f'{resolved} of {planned} sections resolved' if resolved == planned else f'Preparing {checkpoint["plan"][resolved][1]}')
            except (ValueError, OSError, UnicodeError, TypeError, KeyError):
                result.update(preview_error='The preview is unreadable. Preserve it and inspect the briefing session.')
        result.update(self.activity(identifier, checkpoint) or {})
        if job.get('running_at'):
            result['elapsed'] = max(0, int(time.time() - job['running_at']))
        if job.get('session') and self.chamber:
            try:
                forms, permissions = self.chamber.pending(job['session'])
                self.park(identifier, job['session'], forms)
                forms = parked_forms(self.job(identifier).get('questions', []))
                receipts = job.get('replied_inputs', [])
                permissions = [permission for permission in permissions if 'permission:'+permission['id'] not in receipts]
                state = None if forms or permissions else self.chamber.control('session.status', sessionId=job['session'])['sessionStatus']['type']
            except Exception:
                result.update(state='uncertain', label='The secretary connection is unavailable. Completed preview sections remain readable; check the session in OpenChamber.')
                return result
            result.update(forms=forms, permissions=permissions)
            if forms or permissions:
                result.update(state='waiting', label='Your secretary needs your answer')
                if job['state'] not in ('starting', 'uncertain'):
                    result['reservation_required'] = False
            else:
                if state == 'idle' and job['state'] == 'running':
                    reason = verified() if saved else 'invalid'
                    if reason == 'ready':
                        with self.lock:
                            if self.jobs[job['date'] + '.' + job['kind']]['id'] != identifier:
                                return self.status(identifier)  # An older poll must never complete its replacement.
                            self.jobs[job['date'] + '.' + job['kind']]['state'] = 'complete'
                            self.save_jobs()
                            # Only this job's verified transient preview; never delete unrelated records.
                            if preview_path.exists() and not preview_path.is_symlink():
                                preview_path.unlink()
                            for name in ('.activity.json', '.news.json'):
                                transient = self.job_dir / (identifier + name)
                                if transient.exists() and not transient.is_symlink():
                                    transient.unlink()
                        result.update(state='ready', progress=100, label='Your briefing is ready')
                    else:
                        replacement = 'replacement' in job
                        result.update(state='stopped', label='Regeneration stopped before the new briefing was saved. Your previous briefing is preserved.' if replacement
                                      else mismatch if reason == 'foreign' else invalid if saved else 'Preparation stopped before an edition was saved. Open the session in OpenChamber to continue.')
        elif job.get('session'):
            result.update(state='uncertain', label='The secretary is not connected. Completed preview sections remain readable; check the session in OpenChamber.')
        if result['state'] == 'uncertain':
            result['label'] = 'The connection was interrupted. Check OpenChamber before retrying; a session may already be running.'
        if self.preflight and job['date'] == self.today() and result['state'] == 'stopped' and job['state'] not in ('starting', 'uncertain', 'complete'):
            result['recovery'] = 'Continue existing session' if job.get('session') else 'Prepare again'
            result['recovery_action']='resume' if job.get('session') else 'restart'
        result['regeneratable'] = (self.preflight and job['date'] == self.today() and result['state'] == 'stopped'
                                   and job['state'] not in ('starting', 'uncertain'))
        result['label']=ui.text(result['label'])
        return result

    def reply(self, identifier, category, request_id, body):
        job = self.job(identifier)
        if job['state'] == 'superseded':
            raise ValueError('This browser job was replaced; refresh the briefing')
        if job['state'] == 'preflight' and category == 'form':
            from goodmorning.briefings.briefing_preflight import answer
            from goodmorning.briefings.briefing_job import context_path
            from goodmorning.briefings.briefing_stream import bounded_json
            with self.lock:
                live = self.jobs[job['date']+'.'+job['kind']]
                if live['id'] != identifier:
                    raise ValueError('This browser job was replaced; refresh the briefing')
                if live['state'] != 'preflight':
                    return {'answered':True}
                context = bounded_json(context_path(self.runtime, identifier), 300_000)
                if not context.get('form') or request_id != context['form']['id']:
                    raise ValueError('This feedback form changed; review the current task list')
                context = answer(self.runtime,live,body['answer'])
                live['state'] = 'stopped' if context.get('cancelled') else 'starting'
                self.save_jobs()
                if live['state'] == 'starting':
                    threading.Thread(target=self.dispatch,args=(live,),daemon=True).start()
            return {'answered':True}
        if not job.get('session') or category not in ('form', 'permission'):
            raise ValueError('Invalid reply target')
        if category+':'+request_id in job.get('replied_inputs', []):
            return {'answered': True}
        forms, permissions = self.chamber.pending(job['session'])
        if category == 'form':
            self.park(identifier, job['session'], forms)
            with self.lock:
                live = self.jobs[job['date']+'.'+job['kind']]
                if live['id'] != identifier:
                    raise ValueError('This browser job was replaced; refresh the briefing')
                question = next((entry for entry in live.get('questions', []) if entry['id'] == request_id and entry.get('parked')), None)
                if not question:
                    raise ValueError('This request is no longer pending in this briefing session')
                if 'answer' in question:
                    return {'answered': True}
                if live['state'] in ('starting', 'uncertain'):
                    raise ValueError('Wait for the briefing to settle before answering')
                question['answer'] = valid_answer(question['form'], body.get('answer'))
                live['state'] = 'starting'
                self.save_jobs()
            # An answer after the day has passed still finishes this edition under its own date.
            threading.Thread(target=self.continue_session, args=(live, model_answer(question['form'], question['answer'])), daemon=True).start()
            return {'answered': True}
        pending = forms if category == 'form' else permissions
        if not any(item['id'] == request_id for item in pending):
            raise ValueError('This request is no longer pending in this briefing session')
        if category == 'form':
            body = {'answer': body['answer']}
        else:
            if body.get('decision') not in ('once', 'reject'):
                raise ValueError('Only explicit one-time approval or rejection is allowed')
            body = {'decision': body['decision']}
        self.chamber.request(f'/api/session/{job["session"]}/{category}/{request_id}/reply', body)
        with self.lock:
            live = self.jobs[job['date']+'.'+job['kind']]
            if live['id'] != identifier:
                return {'answered': True}  # The old reply must never alter the replacement's input receipts.
            live.setdefault('replied_inputs', []).append(category+':'+request_id)
            self.save_jobs()
        return {'answered': True}


def serve_live(app, port, *, gateway_key=None, public_origins=()):
    if bool(gateway_key) != bool(public_origins):
        raise ValueError('A public backend requires both a gateway key and explicit HTTPS origins')
    class Handler(BaseHTTPRequestHandler):
        def select_language(self):
            if gateway_key:
                selected=ui.language(self.headers.get('X-GoodMorning-Language','en'))
            else:
                path=app.runtime/'website-language.json'
                if path.is_symlink():raise ValueError('Unsafe website language file')
                selected=ui.language(json.loads(path.read_text())['language']) if path.is_file() else 'en'
            ui.CURRENT.set(selected)

        def select_color_schemes(self):
            if gateway_key:
                selected = site_colors.validate({'style': self.headers.get('X-GoodMorning-Style', site_colors.DEFAULT['style']),
                                                 'day': self.headers.get('X-GoodMorning-Day-Scheme', site_colors.DEFAULT['day']),
                                                 'night': self.headers.get('X-GoodMorning-Night-Scheme', site_colors.DEFAULT['night'])})
            else:
                selected = site_colors.read(app.runtime)
            site_colors.CURRENT.set(selected)

        def authorized(self, mutation=False):
            if gateway_key:
                # The public gateway authenticates sessions and checks per-session CSRF.
                # Direct loopback access is still denied, even for another agent account.
                return (secrets.compare_digest(self.headers.get('Authorization',''), 'Bearer '+gateway_key)
                        and self.headers.get('X-GoodMorning-Origin') in public_origins)
            origin = f'http://127.0.0.1:{self.server.server_port}'
            return (self.headers.get('Host') == origin.removeprefix('http://')
                    and self.headers.get('Origin', origin) == origin
                    and (self.headers.get('Sec-Fetch-Site') != 'cross-site'
                         or (not mutation and self.headers.get('Sec-Fetch-Mode') == 'navigate'))
                    and (not mutation or (self.headers.get('Origin') == origin
                         and secrets.compare_digest(self.headers.get('X-Briefing-CSRF', ''), app.csrf))))

        def respond(self, data, status=200, content_type='application/json', resource=None, compress=False, cache='no-store',location=None):
            if not isinstance(data, bytes):
                if isinstance(data,dict):
                    data={key:ui.text(value) if key in ('error','label','recovery') and isinstance(value,str) else value for key,value in data.items()}
                data = json.dumps(data).encode()
            if content_type.startswith('text/html'):compress=False
            # Unsent attachment previews are local blob: images on /chat and in the desk pages' quick chat.
            previews = content_type.startswith('text/html') and (urlsplit(self.path).path == '/chat' or b'id="quick-chat"' in data)
            compressed = resource.compressed if resource else gzip.compress(data, compresslevel=6, mtime=0) if compress else data
            encoded = len(compressed) < len(data) and accepts_gzip(self.headers.get('Accept-Encoding', ''))
            tag = (resource.etag if resource else '"' + hashlib.sha256(data).hexdigest() + '"') if cache != 'no-store' else None
            if tag and encoded:
                tag = tag[:-1] + '-gzip"'
            if tag and any(value.strip().removeprefix('W/') in (tag, '*') for value in self.headers.get('If-None-Match', '').split(',')):
                status = 304
            data = compressed if encoded else data
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            if status != 304:
                self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', cache)
            self.send_header('Content-Language',ui.current())
            if location:self.send_header('Location',location)
            if resource or compress:
                self.send_header('Vary', 'Accept-Encoding')
            if encoded and status != 304:
                self.send_header('Content-Encoding', 'gzip')
            if tag:
                self.send_header('ETag', tag)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'same-origin' if content_type.startswith('text/html') else 'no-referrer')
            image_sources = "'self' blob:" if previews else "'self'"
            self.send_header('Content-Security-Policy', f"default-src 'none'; style-src 'self'; script-src 'self'; img-src {image_sources}; font-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.end_headers()
            if self.command != 'HEAD' and status != 304:
                self.wfile.write(data)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not self.authorized():
                return self.respond({'error': 'Forbidden'}, 403)
            parsed = urlsplit(self.path)
            path = parsed.path
            try:
                self.select_language()
                self.select_color_schemes()
                if path=='/api/language':return self.respond({'language':ui.current()})
                if path=='/api/model':return self.respond({'model':site_models.current()})
                if path=='/api/color-schemes':return self.respond(site_colors.current())
                if path=='/api/avatar':return self.respond(app.avatar_settings())
                avatar_image = re.fullmatch(r'/api/avatar/image/([a-f0-9]{64})\.png', path)
                if avatar_image:
                    image = find_image(app.runtime, avatar_image[1])
                    if image:
                        return self.respond(image, content_type='image/png')
                    return self.respond({'error': 'Not found'}, 404)
                if path=='/api/release':return self.respond(release_info())
                if path=='/api/release/seen':return self.respond({'version':app.release_seen(),'enabled':True})
                activity = re.fullmatch(ACTIVITY_PATH, path)
                if activity:
                    return self.respond(activity_snapshot(app, activity[1], activity[2]))
                if path == '/api/day':
                    return self.respond({'date': app.today(), 'timezone': app.zone})
                if path == '/api/reminders':
                    hours = parse_qs(parsed.query).get('hours', ['3'])
                    if hours not in (['3'], ['24']):
                        return self.respond({'error': 'Invalid reminder window'}, 400)
                    return self.respond(schedule.upcoming(app, int(hours[0])))
                if path == '/api/briefing-reminders':
                    return self.respond(app.reminder_state())
                lines = re.fullmatch(r'/api/briefing-reminders/lines/([a-f0-9]{32})', path)
                if lines:
                    try:
                        return self.respond(app.reminders.status(lines[1]))
                    except Unknown:
                        return self.respond({'error': 'Not found'}, 404)
                if path == '/api/app-profile':
                    return self.respond(app.app_profile())
                if path == '/api/app-schedule':
                    return self.respond(schedule.compact(app), compress=True)
                if path == '/api/app-briefings':
                    return self.respond(app_briefings.summary(app), compress=True)
                if path == '/api/app-weather':
                    from goodmorning.weather import widget
                    return self.respond(widget(app.runtime))
                if path == '/api/notes':
                    return self.respond(app.notes.listing(app.chat_state), compress=True)
                if path == '/api/notes/batch':
                    return self.respond(app.notes.batch(app.profile().get('timezone')))
                if path in ('/schedule', '/api/schedule'):
                    mode, offset = schedule.schedule_query(parse_qs(parsed.query, keep_blank_values=True))
                    if path == '/api/schedule':
                        return self.respond(schedule.snapshot(app, offset, mode), compress=True)
                    return self.respond(schedule.page(app, offset, mode), content_type='text/html; charset=utf-8')
                if path == '/about-me':
                    return self.respond(about_me.page(app), content_type='text/html; charset=utf-8')
                letter = re.fullmatch(r'/letters(?:/(\d{4}-\d{2}-\d{2}))?', path)
                if letter:
                    return self.respond(letters.page(app, letter[1]), content_type='text/html; charset=utf-8')
                if path == '/api/queue':
                    # Standalone viewers have no shared gateway waiting line.
                    return self.respond({'queue':[], 'depth':0})
                if path == '/chat':
                    return self.respond(app.chat_page(), content_type='text/html; charset=utf-8', compress=True)
                if path == '/api/chats':
                    return self.respond({**app.chat_settings(), 'chats': app.chats.listing()}, compress=True)
                attachment_image = IMAGE_ROUTE.fullmatch(path)
                if attachment_image:
                    data, mime = app.chats.uploads.image(attachment_image[1])
                    return self.respond(data, content_type=mime)
                chat_status = re.fullmatch(r'/api/chats/([a-f0-9]{32})/status', path)
                if chat_status:
                    return self.respond(app.chats.status(chat_status[1], include_messages=False), compress=True)
                chat = re.fullmatch(r'/api/chats/([a-f0-9]{32})', path)
                if chat:
                    limit = int(parse_qs(parsed.query).get('limit', ['100'])[0])
                    return self.respond(app.chats.status(chat[1], limit=limit), compress=True)
                job = re.fullmatch(r'/api/jobs/([0-9a-f]{32})', path)
                if job:
                    return self.respond(app.status(job[1]), compress=True)
                preview = re.fullmatch(r'/api/jobs/([0-9a-f]{32})/preview', path)
                if preview:
                    after = int(parse_qs(parsed.query).get('after', ['-1'])[0])
                    return self.respond(app.preview(preview[1], after), compress=True)
                existing = re.fullmatch(r'/api/edition/(\d{4}-\d{2}-\d{2})/(gm|gn)', path)
                if existing:
                    app.source(existing[1], existing[2])
                    item = app.jobs.get(existing[1] + '.' + existing[2])
                    return self.respond({'job': item['id'] if item else None,
                                         'regeneration_request': item.get('regeneration_request') if item else None})
                if path in ('/', '/index.html', '/gm.html', '/gn.html'):
                    kind = 'gn' if path == '/gn.html' else 'gm'
                    if not app.profile().get('timezone'):
                        return self.respond(app.initialization_page(kind), content_type='text/html; charset=utf-8', compress=True)
                    day = app.today()
                    page = app.page(day, kind, False)
                    return self.respond(page, content_type='text/html; charset=utf-8', compress=b'&quot;csrf&quot;: null' in page)
                offline = re.fullmatch(r'/offline/(gm|gn)\.html', path)
                if offline:
                    page = app.offline_page(offline[1])
                    if page is None:
                        return self.respond({'error': 'This briefing is being checked; try again shortly.'}, 503)
                    return self.respond(page, content_type='text/html; charset=utf-8')
                edition = re.fullmatch(r'/d/(\d{4}-\d{2}-\d{2})/(gm|gn)\.(html|json)', path)
                if edition:
                    date, kind, suffix = edition.groups()
                    source = app.source(date, kind)
                    if suffix == 'html':
                        page = app.page(date, kind, True)
                        return self.respond(page, content_type='text/html; charset=utf-8', compress=b'&quot;csrf&quot;: null' in page)
                    if source.exists() and source.suffix == '.' + suffix:
                        mime = 'application/json'
                        return self.respond(app.files(date, kind)[f'{kind}.{suffix}'], content_type=mime + '; charset=utf-8', compress=True)
                shared_media = re.fullmatch(r'/media/([a-f0-9]{64}\.webp)', path)
                if shared_media:
                    data = app.image(shared_media[1])
                    if data is not None:
                        return self.respond(data, content_type='image/webp', cache='private, max-age=31536000, immutable')
                thumbnail = re.fullmatch(r'/media/thumb-v1/([a-f0-9]{64}\.webp)', path)
                if thumbnail:
                    data = app.thumbnail(thumbnail[1])
                    if data is not None:
                        return self.respond(data, content_type='image/webp', cache='private, max-age=31536000, immutable')
                media = re.fullmatch(r'/d/(\d{4}-\d{2}-\d{2})/(media/[a-f0-9]+\.webp)', path)
                if media:
                    app.source(media[1], 'gm')
                    data = app.image(media[2].removeprefix('media/')) if re.fullmatch(r'media/[a-f0-9]{64}\.webp', media[2]) else None
                    if data:
                        return self.respond(data, content_type='image/webp', cache='private, max-age=31536000, immutable')
                resource = app.resources.paths.get(path)
                if resource:
                    return self.respond(resource.data, content_type=resource.mime, resource=resource, cache='public, max-age=31536000, immutable')
                resource = app.resources.alias(path)
                if resource:
                    return self.respond(resource.data, content_type=resource.mime, resource=resource, cache='no-cache')
                return self.respond({'error': 'Not found'}, 404)
            except ValueError:
                return self.respond({'error': 'Edition or request unavailable'}, 404)
            except Exception:
                return self.respond({'error': 'Secretary connection unavailable; your saved records are unchanged'}, 503)

        def do_POST(self):
            path=urlsplit(self.path).path
            form=path in ('/api/language','/api/model','/api/color-schemes') and self.headers.get('Content-Type','').split(';')[0]=='application/x-www-form-urlencoded'
            if not self.authorized(not form):
                return self.respond({'error': 'Forbidden'}, 403)
            try:
                self.select_language()
                self.select_color_schemes()
                avatar_upload = AVATAR_UPLOAD_ROUTE.fullmatch(path)
                if avatar_upload:
                    if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                        raise ValueError('Invalid upload')
                    length = int(self.headers['Content-Length'])
                    if length > MAX_AVATAR_BYTES:
                        return self.respond({'error': 'Avatar images must be 5 MB or smaller.'}, 413)
                    if length <= 0 or self.headers.get('Content-Type') != 'application/octet-stream':
                        raise ValueError('Invalid upload')
                    data = self.rfile.read(length)
                    if len(data) != length:
                        raise ValueError('Incomplete upload')
                    return self.respond(app.upload_avatar(data, avatar_upload[1]), 201)
                upload = UPLOAD_ROUTE.fullmatch(path)
                if upload:
                    if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                        raise ValueError('Invalid upload')
                    length = int(self.headers['Content-Length'])
                    if length > MAX_UPLOAD_BYTES:
                        return self.respond({'error': 'Files must be 50 MB or smaller.'}, 413)
                    if length < 0 or self.headers.get('Content-Type') != 'application/octet-stream':
                        raise ValueError('Invalid upload')
                    if not app.chamber:
                        raise ValueError('The secretary is not connected')
                    name = upload_name(urlsplit(self.path).query)
                    return self.respond(app.chats.uploads.receive(upload[1], name, self.rfile, length), 201)
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 20000 or (not form and self.headers.get('Content-Type') != 'application/json'):
                    raise ValueError('Invalid input')
                raw=self.rfile.read(length)
                if form:
                    fields=parse_qs(raw.decode(),keep_blank_values=True,strict_parsing=True)
                    expected={'csrf','language','return_to'} if path=='/api/language' else {'csrf','model','return_to'}
                    if path=='/api/color-schemes':expected={'csrf','day','night','return_to'}|({'style'} if 'style' in fields else set())
                    if set(fields)!=expected or any(len(values)!=1 for values in fields.values()):raise ValueError('Invalid settings form')
                    body={key:values[0] for key,values in fields.items()}
                    origin=f'http://127.0.0.1:{self.server.server_port}'
                    if self.headers.get('Origin')!=origin or not secrets.compare_digest(body['csrf'],app.csrf):return self.respond({'error':'Forbidden'},403)
                else:body=json.loads(raw)
                if path=='/api/release/seen':
                    if not isinstance(body,dict) or set(body)!={'version'} or body['version'] is None:raise ValueError('Invalid release version')
                    return self.respond({'version':app.release_seen(body['version']),'enabled':True})
                if path=='/api/language':
                    if not form and set(body)!={'language'}:raise ValueError('Invalid language choice')
                    selected=ui.language(body['language'])
                    atomic_text(app.runtime/'website-language.json',json.dumps({'language':selected})+'\n')
                    ui.CURRENT.set(selected)
                    target=body.get('return_to','/')
                    if not re.fullmatch(r'/(?:|chat|schedule|about-me|(?:gm|gn)\.html|d/\d{4}-\d{2}-\d{2}/(?:gm|gn)\.html)',target):target='/'
                    return self.respond({'language':selected},303 if form else 200,location=target if form else None)
                if path=='/api/model':
                    return self.respond({'error':'Model selection is automatic from the website language.'},405)
                if path=='/api/color-schemes':
                    selected = site_colors.validate({key: body[key] for key in site_colors.OPTIONS if key in body} if form else body)
                    site_colors.write(app.runtime, selected)
                    site_colors.CURRENT.set(selected)
                    target=body.get('return_to','/')
                    if not re.fullmatch(r'/(?:|chat|schedule|about-me|(?:gm|gn)\.html|d/\d{4}-\d{2}-\d{2}/(?:gm|gn)\.html)',target):target='/'
                    return self.respond(selected,303 if form else 200,location=target if form else None)
                if path == '/api/generate':
                    requested_at = self.headers.get('X-GoodMorning-Requested-At') if gateway_key else None
                    return self.respond(app.start(body['date'], body['kind'], float(requested_at) if requested_at is not None else None), 202)
                if path == '/api/regenerate':
                    try:
                        return self.respond(app.regenerate(body), 202)
                    except ValueError as error:
                        return self.respond({'error': str(error)}, 409)
                recovery = re.fullmatch(r'/api/jobs/([a-f0-9]{32})/recover', path)
                if recovery:
                    return self.respond(app.recover(recovery[1], body), 202)
                if path == '/api/schedule/tick':
                    try:
                        return self.respond(schedule.tick(app, body))
                    except ValueError as error:
                        if str(error).startswith(('write_conflict', 'unknown_occurrence', 'not_found')):
                            return self.respond({'error': 'Couldn’t save — this task changed since the page loaded. Refresh and try again.'}, 409)
                        raise
                if path == '/api/chats':
                    return self.respond(app.chats.start(body), 202)
                if path == '/api/briefing-reminders/lines':
                    return self.respond(app.reminders.start(body), 202)
                if path == '/api/notes':
                    return self.respond(app.notes.save(body))
                if path == '/api/notes/sorted':
                    return self.respond(app.notes.mark(body))
                if path == '/api/about-me':
                    try:
                        return self.respond(about_me.save(app, body))
                    except about_me.Invalid as error:
                        return self.respond({'error': str(error)}, 400)
                if path == '/api/avatar':
                    if set(body) != {'avatar'}:
                        raise ValueError('Choose a secretary avatar')
                    return self.respond({'avatar': app.set_avatar(body['avatar'])})
                chat = re.fullmatch(r'/api/chats/([a-f0-9]{32})/messages', path)
                if chat:
                    return self.respond(app.chats.send(chat[1], body), 202)
                chat_seen = re.fullmatch(r'/api/chats/([a-f0-9]{32})/seen', path)
                if chat_seen:
                    return self.respond(app.chats.seen(chat_seen[1]))
                if path == '/api/admin/outreach':
                    # Root-only: the public gateway never forwards /api/admin routes.
                    return self.respond(app.chats.outreach(body), 201)
                chat_reply = re.fullmatch(r'/api/chats/([a-f0-9]{32})/(form|permission)/([A-Za-z0-9_]+)/reply', path)
                if chat_reply:
                    return self.respond(app.chats.reply(*chat_reply.groups(), body))
                reply = re.fullmatch(r'/api/jobs/([0-9a-f]{32})/(form|permission)/([A-Za-z0-9_]+)/reply', path)
                if reply:
                    return self.respond(app.reply(*reply.groups(), body))
                return self.respond({'error': 'Not found'}, 404)
            except (ValueError, KeyError, TypeError):
                return self.respond({'error': 'Invalid or stale request'}, 400)
            except Exception:
                return self.respond({'error': 'Reply could not be confirmed. Refresh its status before trying again.'}, 503)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    threading.Thread(target=expire_forever, args=(app.chats.uploads,), daemon=True).start()
    print(f'Private live viewer: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secretary-dir', type=Path, required=True)
    parser.add_argument('--openchamber-url', help='Explicit loopback OpenChamber origin; omitted means browsing only')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--gateway-key-file', type=Path)
    parser.add_argument('--public-origin', action='append', default=[])
    args = parser.parse_args()
    runtime = args.secretary_dir.expanduser().resolve()
    directory = ROOT
    chamber = Chamber(args.openchamber_url, directory) if args.openchamber_url else None
    # One bridge per runtime, including across processes: double clicks/restarts
    # must not create independent sessions for the same edition.
    import fcntl
    job_dir = runtime / 'browser-jobs'
    if job_dir.is_symlink():
        raise ValueError('Unsafe job directory')
    job_dir.mkdir(mode=0o700, exist_ok=True)
    lock_path = job_dir / 'server.lock'
    if lock_path.is_symlink():
        raise ValueError('Unsafe lock path')
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('A live briefing server already owns this runtime')
        key = args.gateway_key_file.read_text().strip() if args.gateway_key_file else None
        if key and not re.fullmatch('[A-Za-z0-9_-]{43}',key):
            raise ValueError('Invalid gateway key')
        if any(not re.fullmatch(r'https://[a-z0-9.-]+',origin) for origin in args.public_origin):
            raise ValueError('Public origins must be explicit HTTPS hostnames')
        serve_live(BrowserApp(runtime, chamber, preflight=True), args.port,
                   gateway_key=key, public_origins=tuple(args.public_origin))


if __name__ == '__main__':
    main()
