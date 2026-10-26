"""Authenticated HTTPS gateway behind NGINX; production listens on a Unix socket only."""
import argparse
import gzip
import hashlib
import html
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler
import json
import logging
import os
from pathlib import Path
import re
import secrets
import socketserver
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, parse_qs, unquote, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

from .briefing_accounts import Accounts, COOKIE, Denied, Limited, SESSION_SECONDS, REMEMBER_SECONDS, PASSWORD_MIN, PASSWORD_MAX, PASSWORD_RULE
from goodmorning.web.briefing_resources import accepts_gzip, Resources, ByteCache, ICON_TYPES, favicon_links
from goodmorning.web.release import VERSION, release_info
from goodmorning.paths import WEB_ASSETS
from goodmorning.web import language as ui
from goodmorning.web import models as site_models
from goodmorning.web import color_schemes as site_colors
from goodmorning.web.chat_uploads import MAX_UPLOAD_BYTES, UPLOAD_ROUTE, IMAGE_ROUTE, UploadReader, upload_name, attachment_ids
from goodmorning.web.avatar_images import AVATAR_UPLOAD_ROUTE, MAX_AVATAR_BYTES
from goodmorning.web.activity import ACTIVITY_PATH, panel as activity_panel
from goodmorning.web.generation_clock import REQUESTED_AT
from goodmorning.web.briefing_reminders import line as reminder_line
from goodmorning.briefings.briefing_day import briefing_day
from . import maintenance as deploy_pause
from . import app_link, app_release, web_push

ASSETS = WEB_ASSETS
# Digital Asset Links let the Android app open this origin without browser controls.
ASSET_LINKS = (ASSETS / 'assetlinks.json').read_bytes()
POLICY = "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; manifest-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
GET_ROUTES = re.compile(r'(?:/|/(?:index|gm|gn)\.html|/offline/(?:gm|gn)\.html|/chat|/schedule|/about-me|/api/schedule|/letters(?:/\d{4}-\d{2}-\d{2})?|/api/avatar(?:/image/[a-f0-9]{64}\.png)?|/api/chats(?:/[a-f0-9]{32}(?:/status)?)?|/api/day|/api/reminders|/api/app-schedule|/api/app-briefings|/api/app-weather|/api/app-profile|/api/notes(?:/batch)?|/api/edition/\d{4}-\d{2}-\d{2}/(?:gm|gn)|/api/jobs/[a-f0-9]{32}(?:/preview)?|/d/\d{4}-\d{2}-\d{2}/(?:gm|gn)\.(?:html|json)|/media/(?:thumb-v1/)?[a-f0-9]{64}\.webp|/d/\d{4}-\d{2}-\d{2}/media/[a-f0-9]+\.webp|/(?:assets/[a-f0-9]{64}/)?desk-secretary(?:-f2|-m1|-m2)?(?:-profile|(?:-day)?(?:-animated)?)\.png|/(?:assets/[a-f0-9]{64}/)?(?:briefing\.css|briefing\.js|browser\.js|schedule\.js|schedule\.css|questions\.js|chat\.js|chat\.css|avatar\.js|avatar\.css|fonts/(?:lora-italic\.woff2|OFL\.txt)))')
POST_ROUTES = re.compile(r'(?:/api/notes(?:/sorted)?|/api/about-me|/api/avatar(?:/upload/(?:day|night|profile))?|/api/(?:generate|regenerate)|/api/chat-uploads/[a-f0-9]{32}|/api/chats|/api/chats/[a-f0-9]{32}/(?:messages|seen|(?:form|permission)/[A-Za-z0-9_]+/reply)|/api/jobs/[a-f0-9]{32}/(?:recover|(?:form|permission)/[A-Za-z0-9_]+/reply))')
# Only the gateway's own background work reaches these; browsers never can.
INTERNAL_ROUTES = re.compile(r'/api/briefing-reminders(?:/lines(?:/[a-f0-9]{32})?)?')
QUEUE_KEY = 'generation_queue'
WAITING_KEY = 'generation_waiting'
MAX_QUEUE = 20
QUEUE_FULL = 'The secretary queue is full. Please wait for earlier requests to finish.'
PUMP_INTERVAL = 5
REMINDER_REFRESH = 300  # Seconds between reads of each opted-in account's upcoming events or briefings.
BRIEFING_WINDOW = 3600  # A briefing reminder missed by longer (server down, time just moved earlier) is skipped.
PAGE_ROUTES = re.compile(r'(?:/|/(?:index|gm|gn)\.html|/chat|/schedule|/about-me|/letters(?:/\d{4}-\d{2}-\d{2})?|/d/\d{4}-\d{2}-\d{2}/(?:gm|gn)\.html)')
BACKEND_PENDING = 'Your secretary is not set up yet. Please contact the server administrator to complete account setup.'
BACKEND_UNAVAILABLE = 'Secretary temporarily unavailable; records are unchanged'


class BackendPending(ValueError):
    """An authenticated login has not been connected to its private runtime."""


def pump_forever(gateway, interval=PUMP_INTERVAL):
    """Release finished tickets and advance queued work without waiting for traffic."""
    while True:
        time.sleep(interval)
        try:
            gateway.pump_queue()
        except Exception:
            pass  # Background maintenance must never stop serving.
        try:
            gateway.remind()
        except Exception:
            pass
        try:
            gateway.remind_briefings()
        except Exception:
            pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):
        return None


class Gateway:
    def __init__(self, accounts, hosts, *, testing=False):
        if not (set(hosts.values()) == {'gm'} or {'gm','gn'} <= set(hosts.values()) <= {'gm','gn','sec'}) or any(not re.fullmatch('[a-z0-9.-]+',h) for h in hosts):
            raise ValueError('Configure a morning hostname or explicit morning, evening and optional secretary hostnames')
        self.accounts, self.hosts, self.testing = accounts, hosts, testing
        self.opener = build_opener(NoRedirect())
        self.generation_lock = threading.RLock()
        self.generation_inflight = set()
        # Public assets share the viewer's exact registry and CSS fingerprints.
        # They must not fall through the private account route allowlist.
        self.icons = Resources(ASSETS)
        self.html_cache = ByteCache(8 * 1024 * 1024, 32)
        self.reminders = {}  # account -> (last read, upcoming events)
        self.briefing_checks = {}  # account -> (last read, today's editions and reminder lines)
        self.html_lock = threading.RLock()
        labels=[host.split('.')[::-1] for host in hosts]
        shared=[]
        for parts in zip(*labels):
            if len(set(parts))!=1:break
            shared.append(parts[0])
        self.language_domain='.'.join(shared[::-1]) if len(shared)>=2 else None

    def backend(self, identifier):
        # No username/path/URL from the browser selects another account's backend.
        self.accounts.check()
        path = self.accounts.directory/'backends.json'
        if path.is_symlink() or path.stat().st_size>100_000:
            raise ValueError('Invalid private backend registry')
        registry = json.loads(path.read_text())
        if not isinstance(registry,dict):
            raise ValueError('Invalid private backend registry')
        if identifier not in registry:
            raise BackendPending(BACKEND_PENDING)
        entry = registry.get(identifier)
        if not isinstance(entry,dict) or set(entry) != {'port','key'}:
            raise ValueError('Invalid private backend configuration')
        if type(entry['port']) is not int or not 1024 <= entry['port'] <= 65535 or not re.fullmatch('[A-Za-z0-9_-]{43}',entry['key']):
            raise ValueError('Invalid private backend configuration')
        return entry

    def proxy(self, identifier, host, path, method, body, headers, *, internal=False):
        backend = self.backend(identifier)
        parsed = urlsplit(path)
        if not ((POST_ROUTES if method=='POST' else GET_ROUTES).fullmatch(parsed.path) or
                internal and INTERNAL_ROUTES.fullmatch(parsed.path) or
                (method in ('GET', 'HEAD') and IMAGE_ROUTE.fullmatch(parsed.path)) or
                method == 'GET' and re.fullmatch(ACTIVITY_PATH, parsed.path)):
            raise Denied('Not found')
        if parsed.path in ('/','/index.html'):
            path = '/chat' if self.hosts[host] == 'sec' else '/'+self.hosts[host]+'.html'
        forwarded = {'Authorization':'Bearer '+backend['key'],'X-GoodMorning-Origin':'https://'+host,
                      'X-GoodMorning-Language':self.accounts.website_language(identifier) or ui.current()}
        schemes = site_colors.current()  # This device's choice, from select_language.
        forwarded.update({'X-GoodMorning-Style': schemes['style'], 'X-GoodMorning-Day-Scheme': schemes['day'],
                          'X-GoodMorning-Night-Scheme': schemes['night']})
        if method == 'POST' and parsed.path in ('/api/generate', '/api/regenerate') and REQUESTED_AT.get() is not None:
            forwarded['X-GoodMorning-Requested-At'] = str(REQUESTED_AT.get())
        if body is not None:
            if UPLOAD_ROUTE.fullmatch(parsed.path) or AVATAR_UPLOAD_ROUTE.fullmatch(parsed.path):
                forwarded['Content-Type'] = 'application/octet-stream'
                forwarded['Content-Length'] = headers['Content-Length']
            else:
                forwarded['Content-Type']='application/json'
        # Never forward cookies, user-provided proxy headers or credentials.
        if headers.get('If-None-Match'):
            forwarded['If-None-Match']=headers['If-None-Match'][:256]
        request = Request(f'http://127.0.0.1:{backend["port"]}'+path,data=body,method=method,headers=forwarded)
        try:
            response = self.opener.open(request,timeout=20)
        except HTTPError as error:
            response = error
        with response:
            limit = MAX_UPLOAD_BYTES if IMAGE_ROUTE.fullmatch(parsed.path) else 4_000_000
            data=response.read(limit + 1)
            if len(data)>limit:
                raise ValueError('Secretary response exceeds its limit')
            return response.status,dict(response.headers),data

    def ticket(self):
        with self.accounts.db() as db:
            row=db.execute('SELECT value FROM metadata WHERE key=?',('generation',)).fetchone()
            return json.loads(row[0]) if row else None

    def paused(self):
        """True while the deploy pause flag is enabled. Reads only."""
        return deploy_pause.is_paused(self.accounts)

    def check_paused(self):
        if self.paused():
            raise deploy_pause.MaintenancePaused(deploy_pause.MESSAGE_EN)

    def activity(self, identifier):
        # Read only: never reconcile reservations, prune queues or dispatch work.
        with self.accounts.db() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='generation'").fetchone()
            ticket = json.loads(row[0]) if row else {}
            queue = self._read_queue(db)
            row = db.execute('SELECT value FROM metadata WHERE key=?', (WAITING_KEY,)).fetchone()
            suspended = json.loads(row[0]) if row else []
        result = []
        def destination(entry, mode, date=None):
            if entry.get('chat'):
                return 'https://' + entry['host'] + '/chat?id=' + entry['chat']
            day = entry.get('date') or date
            kind = entry.get('kind') or mode
            path = f'/d/{day}/{kind}.html' if isinstance(day, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', day) and kind in ('gm', 'gn') else '/'
            return 'https://' + entry['host'] + path
        if ticket.get('user') == identifier and ticket.get('host') in self.hosts:
            kind = 'chat' if ticket.get('chat') else 'job'
            target = ticket.get(kind)
            if isinstance(target, str) and re.fullmatch('[a-f0-9]{32}', target):
                try:
                    status, _, raw = self.proxy(identifier, ticket['host'], f'/api/activity/{kind}/{target}', 'GET', None, {})
                    value = json.loads(raw)
                    if status != 200 or value.get('mode') not in ('secretary', 'initialize', 'todo', 'eureka', 'gm', 'gn') or value.get('state') not in ('working', 'waiting', 'idle', 'uncertain', 'unavailable'):
                        raise ValueError('Activity unavailable')
                except Exception:
                    value = {'mode': 'secretary' if kind == 'chat' or self.hosts[ticket['host']] == 'sec' else self.hosts[ticket['host']], 'state': 'unavailable'}
                if value['state'] != 'idle':
                    result.append({'mode': value['mode'], 'state': value['state'], 'url': destination(ticket, value['mode'], value.get('date'))})
        for entry in queue:
            if not self._valid_queue_entry(entry) or entry['user'] != identifier or entry['host'] not in self.hosts or entry['kind'] == 'lines':
                continue
            candidate = entry['candidate']
            if candidate.get('chat'):
                mode = candidate.get('kind') or entry['body'].get('mode', 'secretary')
            else:
                mode = candidate.get('kind', 'secretary')
            url = destination({**candidate, 'host': entry['host']}, mode)
            if not any(item['url'] == url for item in result):
                result.append({'mode': mode, 'state': 'queued', 'url': url})
        for item in suspended:
            if item.get('user') != identifier or item.get('host') not in self.hosts:
                continue
            key = 'chat' if item.get('chat') else 'job'
            try:
                status, _, raw = self.proxy(identifier, item['host'], f'/api/activity/{key}/{item[key]}', 'GET', None, {})
                value = json.loads(raw)
                if status != 200 or value.get('mode') not in ('secretary', 'initialize', 'todo', 'eureka', 'gm', 'gn') or value.get('state') not in ('working', 'waiting', 'idle', 'uncertain', 'unavailable'):
                    raise ValueError('Activity unavailable')
            except Exception:
                value = {'mode':item.get('kind') or 'secretary', 'state':'unavailable'}
            if value['state'] == 'idle':
                continue
            url = destination(item, value['mode'], value.get('date'))
            if not any(entry['url'] == url for entry in result):
                result.append({'mode':value['mode'], 'state':value['state'], 'url':url})
        return {'activity': result}

    def clear_ticket(self,ticket):
        with self.accounts.db() as db:
            db.execute('DELETE FROM metadata WHERE key=? AND value=?',('generation',json.dumps(ticket,separators=(',',':'))))

    def confirm_dispatch(self, ticket):
        if not ticket.get('dispatching'):
            return
        confirmed = {key: value for key, value in ticket.items() if key != 'dispatching'}
        with self.accounts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            updated = db.execute('UPDATE metadata SET value=? WHERE key=? AND value=?',
                       (json.dumps(confirmed, separators=(',', ':')), 'generation', json.dumps(ticket, separators=(',', ':'))))
            if updated.rowcount:
                self.remember_waiting(db, ticket, remove=True)

    def remember_waiting(self, db, ticket, *, remove=False):
        row = db.execute('SELECT value FROM metadata WHERE key=?', (WAITING_KEY,)).fetchone()
        waiting = json.loads(row[0]) if row else []
        key = 'chat' if ticket.get('chat') else 'job'
        waiting = [item for item in waiting if (item.get('user'), item.get(key)) != (ticket['user'], ticket.get(key))]
        if not remove:
            waiting.append(ticket)
        if waiting:
            db.execute('INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (WAITING_KEY, json.dumps(waiting, separators=(',', ':'))))
        else:
            db.execute('DELETE FROM metadata WHERE key=?', (WAITING_KEY,))

    def reconcile_ticket(self):
        current = self.ticket()
        if current and current.get('lines'):
            return self.reconcile_lines(current)
        # A failed preflight or lost HTTP response can leave intent without a
        # job ID. Recover the receipt through a read, never replay the POST.
        if (current and not current.get('job') and not current.get('chat')
                and current.get('kind') in ('gm', 'gn') and current.get('date')):
            encoded = json.dumps(current, separators=(',', ':'))
            try:
                with self.generation_lock:
                    if encoded in self.generation_inflight:
                        return
                status, _, data = self.proxy(current['user'], current['host'],
                    '/api/edition/' + current['date'] + '/' + current['kind'], 'GET', None, {})
                receipt = json.loads(data)
                job = receipt.get('job')
                if (status != 200 or not isinstance(job, str) or not re.fullmatch('[a-f0-9]{32}', job)
                        or current.get('request') and receipt.get('regeneration_request') != current['request']):
                    return
                with self.generation_lock, self.accounts.db() as db:
                    if encoded in self.generation_inflight:
                        return
                    updated = {**current, 'job': job}
                    changed = db.execute('UPDATE metadata SET value=? WHERE key=? AND value=?',
                        (json.dumps(updated, separators=(',', ':')), 'generation', encoded))
                    if not changed.rowcount:
                        return
                    current = updated
            except Exception:
                return  # No matching receipt: retain uncertainty, never assume idle.
        if current and not current.get('dispatching') and (current.get('job') or current.get('chat')):
            try:
                path = '/api/chats/' + current['chat'] + '/status' if current.get('chat') else '/api/jobs/' + current['job']
                status, _, data = self.proxy(current['user'], current['host'], path, 'GET', None, {})
                terminal = ('idle',) if current.get('chat') else ('ready', 'stopped')
                result = json.loads(data)
                waiting = result.get('state') == 'waiting' and result.get('reservation_required') is False
                if status == 200 and waiting:
                    with self.accounts.db() as db:
                        db.execute('BEGIN IMMEDIATE')
                        deleted = db.execute('DELETE FROM metadata WHERE key=? AND value=?',
                                             ('generation', json.dumps(current, separators=(',', ':'))))
                        if deleted.rowcount:
                            self.remember_waiting(db, current)
                    if deleted.rowcount:
                        self.announce(current, result)
                elif status == 200 and result.get('state') in terminal:
                    self.clear_ticket(current)
                    self.announce(current, result)
            except Exception:
                pass  # Uncertain work keeps its reservation. Never launch work blindly.

    def reconcile_lines(self, current):
        """Releases the slot once the secretary's reminder lines are saved or given up on. A request
        the backend never received cannot be running, so its reservation goes too."""
        encoded = json.dumps(current, separators=(',', ':'))
        try:
            with self.generation_lock:
                if encoded in self.generation_inflight:
                    return
            status, _, data = self.proxy(current['user'], current['host'], '/api/briefing-reminders/lines/' + current['lines'],
                                         'GET', None, {}, internal=True)
            if status == 404:
                return self.clear_ticket(current)
            if status != 200:
                return
            if current.get('dispatching'):
                self.confirm_dispatch(current)
                current = {key: value for key, value in current.items() if key != 'dispatching'}
            if json.loads(data)['state'] in ('ready', 'stopped'):
                self.clear_ticket(current)
        except Exception:
            pass  # Uncertain work keeps its reservation.

    def notify(self, user, kind, message, *, ttl=3600, urgency='normal', only=None, phone=None):
        """Sends without blocking the caller; delivery problems never affect the work itself. only names
        one browser and phone one linked phone; without either, every device that chose this kind gets it."""
        def send():
            try:
                if phone or kind != 'events' and not only:  # Linked phones schedule their own event reminders.
                    app_link.record(self.accounts, user, kind, message, only=phone)
                if not phone:
                    web_push.send(self.accounts, user, message, kind=kind, ttl=ttl, urgency=urgency, only=only,
                                  subject='https://' + next(iter(self.hosts)))
            except Exception as error:
                logging.getLogger(__name__).warning('Notification failed (%s)', type(error).__name__)
        threading.Thread(target=send, daemon=True).start()

    def announce(self, ticket, result):
        """A reserved task just finished or needs the account owner."""
        user, chat = ticket['user'], ticket.get('chat')
        lang = self.accounts.website_language(user) or 'en'
        def t(source, **values):
            return ui.text(source, lang=lang, **values)
        day, edition = ticket.get('date'), ticket.get('kind')
        page = '/chat?id=' + chat if chat else (f'/d/{day}/{edition}.html' if edition in ('gm', 'gn') and day else '/')
        if result.get('state') == 'waiting':
            forms, permissions = result.get('forms') or [], result.get('permissions') or []
            detail = ''
            if forms:
                fields = forms[0].get('fields') or [{}]
                detail = fields[0].get('title') or (forms[0].get('title') if forms[0].get('title') != 'Questions' else '')
            elif permissions:
                detail = permissions[0].get('action') or ''
            return self.notify(user, 'waiting', {'title': t('Your secretary needs your answer'),
                'body': str(detail)[:200] or t('Open GoodMorning to answer.'), 'url': page, 'tag': 'waiting-' + (chat or ticket.get('job', ''))},
                urgency='high')
        if chat:
            return self.notify(user, 'chat', {'title': t('Your secretary replied'), 'body': self.reply_excerpt(user, ticket) or t('Open the chat to read it.'),
                                              'url': page, 'tag': 'chat-' + chat})
        name = t('Your morning briefing') if edition == 'gm' else t('Your evening briefing')
        if result.get('state') == 'ready':
            message = {'title': t('{name} is ready', name=name), 'body': t('Tap to read it.')}
        else:
            message = {'title': t('{name} could not finish', name=name), 'body': t(result.get('label') or 'Open it to see what happened.')}
        self.notify(user, 'briefing', {**message, 'url': page, 'tag': 'briefing-' + str(day) + '-' + str(edition)})

    def app_sync(self, user, link, after):
        """Everything the app's widgets and background check need, in one request, with this phone's own
        notification choices; the phone names itself to the website through `device`."""
        host = next(iter(self.hosts))
        def read(path):
            status, _, raw = self.proxy(user, host, path, 'GET', None, {})
            if status != 200:
                raise ValueError('Backend read failed')
            return json.loads(raw)
        entry = next(entry for entry in app_link.links(self.accounts, user) if entry['id'] == link)
        chosen = entry['settings']
        result = {'device': link, 'settings': chosen, 'language': self.accounts.website_language(user) or 'en',
                  'appearance': entry['appearance'] or self.accounts.website_color_schemes(user) or site_colors.DEFAULT,
                  'notifications': app_link.outbox(self.accounts, user, after, chosen, link), 'busy': self.busy(user)}
        for key, read_part in (('schedule', lambda: read('/api/app-schedule')),
                               ('secretary', lambda: read('/api/app-profile')),
                               ('reminders', lambda: read('/api/reminders?hours=24')['events']),
                               ('chat', lambda: self.app_chat_summary(user, read)),
                               ('briefings', lambda: self.app_briefings(user, read)),
                               ('weather', lambda: read('/api/app-weather'))):
            try:
                result[key] = read_part()
            except Exception:
                result[key] = None  # The app keeps showing what it had; other parts still update.
        return result

    def busy(self, user):
        """Whether this account has work running or queued, whose end the app checks for sooner."""
        with self.accounts.db() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='generation'").fetchone()
            return bool(row and json.loads(row[0]).get('user') == user) or any(entry.get('user') == user for entry in self._read_queue(db))

    def app_signin(self, user, host):
        """Signs the app's own WebView in for a phone that moved there from Chrome, whose sign-in stayed in Chrome."""
        token, _ = self.accounts.app_session(user, host)
        return {'cookie': f'{COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={REMEMBER_SECONDS}'}

    def app_briefings(self, user, read):
        result = read('/api/app-briefings')
        # A request still waiting in the shared queue is not yet a job on the account's backend.
        for item in self.queue_status(user)['queue']:
            edition = result['editions'].get(item.get('edition'))
            if item['work'] == 'generate' and item.get('date') == result['date'] and edition and edition['state'] == 'missing':
                edition['state'] = 'working'
        return result

    def app_generate(self, user, body):
        """The briefings widget's Generate button: today's edition, through the usual queue."""
        host = next(iter(self.hosts))
        if set(body) != {'kind'} or body['kind'] not in ('gm', 'gn'):
            raise ValueError('Invalid generation request')
        status, headers, raw = self.proxy(user, host, '/api/day', 'GET', None, {})
        if status != 200:
            return status, headers, raw
        return self.generate(user, host, json.dumps({'date': json.loads(raw)['date'], 'kind': body['kind']}).encode(), {})

    def app_chat_summary(self, user, read):
        chats = [item for item in read('/api/chats')['chats'] if item['mode'] == 'secretary']
        if not chats:
            return {}
        latest = chats[0]
        status = read('/api/chats/' + latest['id'])
        replies = [item['text'] for item in status.get('messages', []) if item.get('role') == 'assistant' and isinstance(item.get('text'), str)]
        text = ' '.join(re.sub(r'[*_`#>\[\]]+', '', replies[-1]).split()) if replies else ''
        return {'id': latest['id'], 'title': latest['title'], 'state': status.get('state'),
                'unread': bool(latest.get('unread')), 'reply': text[:600]}

    def app_chat(self, user, body):
        """A message from the chat widget: continues a conversation or starts one, through the usual queue."""
        from goodmorning.web.briefing_chat import identifier as chat_id
        host = next(iter(self.hosts))
        if set(body) not in ({'text'}, {'text', 'chat'}):
            raise ValueError('Invalid conversation message')
        request = secrets.token_hex(16)
        if 'chat' in body:
            path, payload = '/api/chats/' + chat_id(body['chat']) + '/messages', {'id': request, 'text': body['text']}
        else:
            path, payload = '/api/chats', {'id': request, 'mode': 'secretary', 'text': body['text']}
        return self.chat_message(user, host, path, json.dumps(payload).encode(), {})

    def app_note(self, user, body):
        """Saves one quick note word for word; no model runs."""
        return self.proxy(user, next(iter(self.hosts)), '/api/notes', 'POST', json.dumps(body).encode(), {})

    def app_sort(self, user, body):
        """Sort with the secretary: a new Secretary conversation through the usual queue, with the
        unsorted and edited notes that fit one message. The notes are marked once it is accepted."""
        host = next(iter(self.hosts))
        if body:
            raise ValueError('Invalid sort request')
        status, headers, raw = self.proxy(user, host, '/api/notes/batch', 'GET', None, {})
        if status != 200:
            return status, headers, raw
        batch = json.loads(raw)
        if not batch['notes']:
            return 409, {'Content-Type': 'application/json'}, json.dumps({'error': ui.text('There are no notes to sort.')}).encode()
        chat = secrets.token_hex(16)
        status, headers, raw = self.chat_message(user, host, '/api/chats',
                                                 json.dumps({'id': chat, 'mode': 'secretary', 'text': batch['text']}).encode(), {})
        if status >= 300:
            return status, headers, raw
        self.proxy(user, host, '/api/notes/sorted', 'POST', json.dumps({'chat': chat, 'notes': batch['notes']}).encode(), {})
        return 202, {'Content-Type': 'application/json'}, json.dumps({'chat': chat, 'remaining': batch['remaining']}).encode()

    def reply_excerpt(self, user, ticket):
        try:
            status, _, raw = self.proxy(user, ticket['host'], '/api/chats/' + ticket['chat'], 'GET', None, {})
            replies = [item['text'] for item in json.loads(raw).get('messages', []) if item.get('role') == 'assistant' and isinstance(item.get('text'), str)]
        except Exception:
            return ''
        if status != 200 or not replies:
            return ''
        text = ' '.join(re.sub(r'[*_`#>\[\]]+', '', replies[-1]).split())
        return text if len(text) <= 180 else text[:179] + '…'

    def remind(self):
        """Event reminders for accounts that turned them on: read upcoming events every few minutes, send when due."""
        now = time.time()
        with self.accounts.db() as db:
            users = [key[5:] for (key,) in db.execute("SELECT key FROM metadata WHERE key LIKE 'push:%'")]
        for user in users:
            state = web_push.account(self.accounts, user)
            # Each device keeps its own reminders switch and lead time.
            devices = [(web_push.device(entry['endpoint']), web_push.choices(state, entry)) for entry in state['subscriptions']]
            devices = [(device, chosen) for device, chosen in devices if chosen['events']]
            if not devices:
                self.reminders.pop(user, None)
                continue
            checked, events = self.reminders.get(user, (0, []))
            if now - checked >= REMINDER_REFRESH:
                try:
                    status, _, raw = self.proxy(user, next(iter(self.hosts)), '/api/reminders', 'GET', None, {})
                    events = json.loads(raw)['events'] if status == 200 else events
                except Exception:
                    pass  # Keep the last known events; the next refresh tries again.
                self.reminders[user] = (now, events)
            lang = self.accounts.website_language(user) or 'en'
            for event in events:
                body = ui.text('Starts at {time}', lang=lang, time=event['time'])
                if event.get('location'):
                    body += ' · ' + event['location']
                for device, chosen in devices:
                    if event['starts'] - chosen['lead'] * 60 <= now < event['starts'] and web_push.remembered(self.accounts, user, event['key'] + '@' + device):
                        self.notify(user, 'events', {'title': event['subject'], 'body': body, 'url': '/schedule?view=day', 'tag': 'event-' + event['key']},
                                    ttl=max(60, int(event['starts'] - now)), urgency='high', only=device)

    def briefing_targets(self):
        """Each account's browsers and notifying linked phones with a briefing reminder on, and their choices."""
        with self.accounts.db() as db:
            users = {key.split(':', 1)[1] for (key,) in db.execute("SELECT key FROM metadata WHERE key LIKE 'push:%' OR key LIKE 'app-links:%'")}
        targets = {}
        for user in users:
            state = web_push.account(self.accounts, user)
            found = [({'only': web_push.device(entry['endpoint'])}, web_push.choices(state, entry)) for entry in state['subscriptions']]
            found += [({'phone': entry['id']}, entry['settings']) for entry in app_link.links(self.accounts, user) if entry['notifies']]
            found = [(target, chosen) for target, chosen in found if chosen['gm'] or chosen['gn']]
            if found:
                targets[user] = found
        return targets

    def reminder_state(self, user):
        status, _, raw = self.proxy(user, next(iter(self.hosts)), '/api/briefing-reminders', 'GET', None, {}, internal=True)
        if status != 200:
            raise ValueError('Backend read failed')
        return json.loads(raw)

    def write_lines(self, user):
        """Asks the secretary for reminder lines in the saved tone, through the shared line like any model work."""
        with self.accounts.db() as db:
            row = db.execute('SELECT value FROM metadata WHERE key=?', ('generation',)).fetchone()
            waiting = [json.loads(row[0])] if row else []
            waiting += [entry['candidate'] for entry in self._read_queue(db) if entry.get('kind') == 'lines']
        if any(item.get('lines') and item.get('user') == user for item in waiting):
            return
        host, identifier = next(iter(self.hosts)), secrets.token_hex(16)
        entry = {'kind': 'lines', 'candidate': {'user': user, 'host': host, 'lines': identifier, 'dispatching': True},
                 'user': user, 'host': host, 'path': '/api/briefing-reminders/lines', 'body': {'id': identifier},
                 'language': self.accounts.website_language(user) or 'en', 'enqueued': time.time()}
        action, _, _ = self._reserve_or_queue('lines', entry['candidate'], entry['path'], entry['body'], entry['language'], entry['enqueued'])
        if action == 'active_new':
            self._dispatch_queued(entry)

    def remind_briefings(self, now=None):
        """Morning and evening reminders, at each device's own time, while that edition of today's
        briefing is not prepared, queued or being prepared; once a day per device."""
        now = time.time() if now is None else now
        for user, targets in self.briefing_targets().items():
            try:
                checked, state = self.briefing_checks.get(user, (0, None))
                if now - checked >= REMINDER_REFRESH:
                    self.briefing_checks[user] = (now, state)  # A failed read waits for the next refresh too.
                    state = self.reminder_state(user)
                    self.briefing_checks[user] = (now, state)
                    try:
                        if state['write']:
                            self.write_lines(user)
                    except Exception:
                        pass  # Built-in lines remind meanwhile; the next refresh asks again.
                local = datetime.fromtimestamp(now, ZoneInfo(state['timezone']))
                day = briefing_day(state['timezone'], local)
                due = []
                for target, chosen in targets:
                    for kind in ('gm', 'gn'):
                        hour, minute = map(int, chosen[kind + '_time'].split(':'))
                        # Times before the 04:00 rollover belong to the night after the briefing day.
                        at = datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=local.tzinfo) + timedelta(days=hour < 4)
                        if chosen[kind] and 0 <= (local - at).total_seconds() < BRIEFING_WINDOW:
                            due.append((target, kind))
                due = [(target, kind) for target, kind in due
                       if not web_push.reminded(self.accounts, user, kind + '-' + day + '@' + next(iter(target.values())))]
                if not due:
                    continue
                if now - self.briefing_checks[user][0] >= 30:  # The editions as they are now, not minutes ago.
                    self.briefing_checks[user] = (now, state)
                    state = self.reminder_state(user)
                    self.briefing_checks[user] = (now, state)
                if state['date'] != day:
                    continue
                queued = {item.get('edition') for item in self.queue_status(user)['queue'] if item['work'] == 'generate' and item.get('date') == day}
                active = self.ticket() or {}
                if active.get('user') == user and active.get('date') == day:
                    queued.add(active.get('kind'))
                lang = self.accounts.website_language(user) or 'en'
                for target, kind in due:
                    if not web_push.remembered(self.accounts, user, kind + '-' + day + '@' + next(iter(target.values()))):
                        continue
                    if state['editions'][kind] != 'missing' or kind in queued:
                        continue
                    title = ui.text("Your morning briefing isn't prepared yet" if kind == 'gm' else "Your evening briefing isn't prepared yet", lang=lang)
                    # The ready notification shares this tag, so it replaces the reminder.
                    self.notify(user, kind, {'title': title, 'body': reminder_line(state['lines'], kind, day),
                                             'url': f'/d/{day}/{kind}.html', 'tag': 'briefing-' + day + '-' + kind}, **target)
            except Exception:
                continue  # One account's backend never stops another's reminders.

    @staticmethod
    def _valid_queue_entry(entry):
        if not isinstance(entry, dict) or entry.get('kind') not in ('chat', 'generate', 'regenerate', 'recover', 'reply', 'lines'):
            return False
        candidate = entry.get('candidate')
        if not isinstance(candidate, dict) or not isinstance(entry.get('user'), str) or not isinstance(entry.get('host'), str):
            return False
        if not isinstance(entry.get('path'), str) or not isinstance(entry.get('body'), dict):
            return False
        if entry.get('language') not in ('en', 'zh-CN') or not isinstance(entry.get('enqueued'), (int, float)):
            return False
        try:
            if len(json.dumps(entry['body']).encode()) > 20000:
                return False
        except (TypeError, ValueError):
            return False
        return True

    def _read_queue(self, db):
        row = db.execute('SELECT value FROM metadata WHERE key=?', (QUEUE_KEY,)).fetchone()
        if not row:
            return []
        try:
            queue = json.loads(row[0])
        except (TypeError, ValueError):
            return []
        return queue if isinstance(queue, list) else []

    def _write_queue(self, db, queue):
        if queue:
            db.execute('INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (QUEUE_KEY, json.dumps(queue, separators=(',', ':'))))
        else:
            db.execute('DELETE FROM metadata WHERE key=?', (QUEUE_KEY,))

    def _prune_queue(self, queue, now):
        # Accepted work must not vanish merely because another request is slow.
        return [entry for entry in queue if self._valid_queue_entry(entry)]

    def dispatch_generation(self, candidate, path, raw, headers):
        encoded = json.dumps(candidate, separators=(',', ':'))
        with self.generation_lock:
            self.generation_inflight.add(encoded)
        try:
            status, upstream, data = self.proxy(candidate['user'], candidate['host'], path, 'POST', raw, headers)
            try:
                result = json.loads(data)
            except (TypeError, ValueError):
                result = {}
            job = result.get('job') if isinstance(result, dict) else None
            if status < 300 and isinstance(job, str) and re.fullmatch('[a-f0-9]{32}', job):
                with self.accounts.db() as db:
                    db.execute('UPDATE metadata SET value=? WHERE key=? AND value=?',
                        (json.dumps({**candidate, 'job': job}, separators=(',', ':')), 'generation', encoded))
            elif 400 <= status < 500 or status < 300 and result == {'ready': True}:
                self.clear_ticket(candidate)
            return status, upstream, data
        finally:
            with self.generation_lock:
                self.generation_inflight.discard(encoded)

    def dispatch_lines(self, candidate, path, raw):
        encoded = json.dumps(candidate, separators=(',', ':'))
        with self.generation_lock:
            self.generation_inflight.add(encoded)  # Until the backend answers, a 404 cannot prove it never started.
        try:
            status, _, _ = self.proxy(candidate['user'], candidate['host'], path, 'POST', raw, {}, internal=True)
        finally:
            with self.generation_lock:
                self.generation_inflight.discard(encoded)
        if 400 <= status < 500:
            self.clear_ticket(candidate)
        elif status < 300:
            self.confirm_dispatch(candidate)
        return status

    def _reserve_or_queue(self, kind, candidate, path, body, language, enqueued=None):
        """Atomically take the active slot or join the bounded global waiting line."""
        self.check_paused()
        entry = {'kind': kind, 'candidate': candidate, 'user': candidate['user'], 'host': candidate['host'],
                 'path': path, 'body': body, 'language': language, 'enqueued': time.time() if enqueued is None else enqueued}
        with self.accounts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value FROM metadata WHERE key=?', ('generation',)).fetchone()
            queue = self._prune_queue(self._read_queue(db), entry['enqueued'])
            if row:
                current = json.loads(row[0])
                if {key:value for key,value in current.items() if key != 'dispatching'} == {key:value for key,value in candidate.items() if key != 'dispatching'}:
                    self._write_queue(db, queue)
                    return ('active_duplicate', None, len(queue))
                for index, waiting in enumerate(queue):
                    if waiting.get('kind') == kind and waiting.get('candidate') == candidate:
                        self._write_queue(db, queue)
                        return ('queued_duplicate', index + 1, len(queue))
                if len(queue) >= MAX_QUEUE:
                    self._write_queue(db, queue)
                    return ('full', None, len(queue))
                queue.append(entry)
                self._write_queue(db, queue)
                return ('queued', len(queue), len(queue))
            if queue:
                for index, waiting in enumerate(queue):
                    if waiting.get('kind') == kind and waiting.get('candidate') == candidate:
                        self._write_queue(db, queue)
                        return ('queued_duplicate', index + 1, len(queue))
                if len(queue) >= MAX_QUEUE:
                    self._write_queue(db, queue)
                    return ('full', None, len(queue))
                queue.append(entry)
                self._write_queue(db, queue)
                return ('queued', len(queue), len(queue))
            db.execute('INSERT INTO metadata VALUES (?,?)', ('generation', json.dumps(candidate, separators=(',', ':'))))
            return ('active_new', None, 0)

    def _dispatch_queued(self, entry):
        token = ui.CURRENT.set(entry.get('language') or 'en')
        clock_token = REQUESTED_AT.set(entry['enqueued'])
        try:
            raw = json.dumps(entry['body']).encode()
            candidate = entry['candidate']
            if entry['kind'] in ('generate', 'regenerate'):
                return self.dispatch_generation(candidate, entry['path'], raw, {})[0]
            if entry['kind'] == 'lines':
                return self.dispatch_lines(candidate, entry['path'], raw)
            status, upstream, data = self.proxy(entry['user'], entry['host'], entry['path'], 'POST', raw, {})
            if 400 <= status < 500:
                self.clear_ticket(candidate)
            elif status < 300:
                self.confirm_dispatch(candidate)
            return status
        finally:
            REQUESTED_AT.reset(clock_token)
            ui.CURRENT.reset(token)

    def pump_queue(self):
        """Advance the global waiting line while the active slot is free."""
        self.reconcile_ticket()
        if self.paused():
            return
        for _ in range(MAX_QUEUE + 1):
            with self.accounts.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT value FROM metadata WHERE key=?', ('generation',)).fetchone():
                    return
                queue = self._prune_queue(self._read_queue(db), time.time())
                if not queue:
                    self._write_queue(db, queue)
                    return
                head = queue.pop(0)
                db.execute('INSERT INTO metadata VALUES (?,?)',
                           ('generation', json.dumps(head['candidate'], separators=(',', ':'))))
                self._write_queue(db, queue)
            try:
                self._dispatch_queued(head)
            except Exception:
                return  # Uncertain dispatch keeps its reservation and blocks the line.
            self.reconcile_ticket()
            with self.accounts.db() as db:
                row = db.execute('SELECT value FROM metadata WHERE key=?', ('generation',)).fetchone()
                if row:
                    return
            # An invalid head cleared its own reservation; immediately try the next waiter.

    def queue_status(self, identifier):
        self.pump_queue()
        now = time.time()
        with self.accounts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            queue = self._prune_queue(self._read_queue(db), now)
            self._write_queue(db, queue)
            row = db.execute('SELECT value FROM metadata WHERE key=?', ('generation',)).fetchone()
            waiting = []
            for index, entry in enumerate(queue):
                if entry.get('user') != identifier or entry['kind'] == 'lines':  # Background work the user never asked for.
                    continue
                item = {'work': entry['kind'], 'position': index + 1}
                if entry['kind'] == 'chat':
                    item['chat'] = entry['candidate'].get('chat')
                elif entry['kind'] in ('generate', 'regenerate'):
                    item['date'] = entry['candidate'].get('date')
                    item['edition'] = entry['candidate'].get('kind')
                    if entry['kind'] == 'regenerate':
                        item['previous'] = entry['body'].get('previous')
                else:
                    key = 'chat' if entry['candidate'].get('chat') else 'job'
                    item[key] = entry['candidate'].get(key)
                waiting.append(item)
            return {'queue': waiting, 'depth': len(queue), 'active': row is not None}

    def queued_response(self, kind, candidate, position, depth):
        payload = {'queued': True, 'position': position, 'depth': depth}
        if candidate.get('chat'):
            payload['chat'] = candidate['chat']
        elif kind in ('generate', 'regenerate'):
            payload.update(date=candidate['date'], edition=candidate['kind'])
        else:
            payload['job'] = candidate['job']
        return 202, {'Content-Type': 'application/json'}, json.dumps(payload).encode()

    def chat_message(self, identifier, host, path, raw, headers):
        self.check_paused()
        from goodmorning.web.briefing_chat import identifier as chat_id, message, MODES
        body = json.loads(raw)
        if path == '/api/chats':
            if set(body) not in ({'id', 'mode', 'text'}, {'id', 'mode', 'text', 'attachments'}) or body['mode'] not in MODES:
                raise ValueError('Invalid secretary mode')
            chat = chat_id(body['id'])
        else:
            if set(body) not in ({'id', 'text'}, {'id', 'text', 'attachments'}):
                raise ValueError('Invalid conversation message')
            chat = re.fullmatch(r'/api/chats/([a-f0-9]{32})/messages', path)[1]
        request = chat_id(body['id'])
        message(body['text'])
        attachment_ids(body)
        candidate = {'user': identifier, 'host': host, 'chat': chat, 'request': request, 'dispatching':True}
        language = self.accounts.website_language(identifier) or ui.current()
        self.pump_queue()
        # An interrupt targets the same working conversation and steers its
        # existing session. Reuse its reservation instead of queueing behind
        # other work; a different conversation still joins the waiting line.
        previous = None
        with self.accounts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value FROM metadata WHERE key=?', ('generation',)).fetchone()
            if row:
                try:
                    current = json.loads(row[0])
                except (TypeError, ValueError):
                    current = None
                if (isinstance(current, dict) and not current.get('dispatching')
                        and current.get('user') == identifier and current.get('host') == host
                        and current.get('chat') == chat and current.get('request') != request):
                    previous = current
                    db.execute('UPDATE metadata SET value=? WHERE key=? AND value=?',
                               (json.dumps(candidate, separators=(',', ':')), 'generation', json.dumps(current, separators=(',', ':'))))
        if previous is not None:
            try:
                status, upstream, data = self.proxy(identifier, host, path, 'POST', raw, headers)
            except Exception:
                raise
            if 400 <= status < 500:
                with self.accounts.db() as db:
                    db.execute('UPDATE metadata SET value=? WHERE key=? AND value=?',
                               (json.dumps(previous, separators=(',', ':')), 'generation', json.dumps(candidate, separators=(',', ':'))))
            elif status < 300:
                self.confirm_dispatch(candidate)
            return status, upstream, data
        action, position, depth = self._reserve_or_queue('chat', candidate, path, body, language)
        if action in ('queued', 'queued_duplicate'):
            return self.queued_response('chat', candidate, position, depth)
        if action == 'full':
            return 429, {'Content-Type': 'application/json'}, json.dumps({'error': QUEUE_FULL}).encode()
        if action == 'active_duplicate':
            if (self.ticket() or {}).get('dispatching'):
                return 409, {'Content-Type': 'application/json'}, b'{"error":"Delivery is uncertain. Ask the administrator to inspect this conversation before sending again."}'
            return 202, {'Content-Type': 'application/json'}, json.dumps({'chat': chat}).encode()
        created = action == 'active_new'
        status, upstream, data = self.proxy(identifier, host, path, 'POST', raw, headers)
        if created and 400 <= status < 500:
            self.clear_ticket(candidate)
        elif created and status < 300:
            self.confirm_dispatch(candidate)
        return status, upstream, data

    def generate(self,identifier,host,raw,headers, *, regenerate=False):
        self.check_paused()
        requested_at = time.time()
        body=json.loads(raw)
        expected = {'date', 'kind', 'id', 'previous'} if regenerate else {'date', 'kind'}
        if set(body)!=expected or not isinstance(body['date'],str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',body['date']) or body['kind'] not in ('gm','gn'):
            raise ValueError('Invalid generation request')
        if regenerate and (not isinstance(body['id'], str) or not re.fullmatch('[a-f0-9]{32}', body['id'])
                           or body['previous'] is not None and (not isinstance(body['previous'], str) or not re.fullmatch('[a-f0-9]{32}', body['previous']))):
            raise ValueError('Invalid regeneration request')
        work = 'regenerate' if regenerate else 'generate'
        path = '/api/' + work
        candidate={'user':identifier,'host':host,'date':body.get('date'),'kind':body.get('kind')}
        if regenerate:
            candidate['request'] = body['id']
        # Reopening an existing edition is a read, not another generation request.
        status, _, existing = self.proxy(identifier, host, '/api/edition/'+body['date']+'/'+body['kind'], 'GET', None, {})
        if status == 200:
            edition = json.loads(existing)
            existing_job = edition.get('job')
            if isinstance(existing_job, str) and re.fullmatch('[a-f0-9]{32}', existing_job) and (not regenerate or edition.get('regeneration_request') == body['id']):
                return 202, {'Content-Type':'application/json'}, json.dumps({'job':existing_job}).encode()
        language = self.accounts.website_language(identifier) or ui.current()
        self.pump_queue()
        action, position, depth = self._reserve_or_queue(work, candidate, path, body, language, enqueued=requested_at)
        if action in ('queued', 'queued_duplicate'):
            return self.queued_response(work, candidate, position, depth)
        if action == 'full':
            return 429,{'Content-Type':'application/json'},json.dumps({'error':QUEUE_FULL}).encode()
        if action == 'active_duplicate':
            current = self.ticket()
            if current and {k:current.get(k) for k in candidate}==candidate:
                if not current.get('job'):
                    return 409,{'Content-Type':'application/json'},b'{"error":"A generation request needs administrator reconciliation before retrying."}'
                return 202,{'Content-Type':'application/json'},json.dumps({'job':current['job']}).encode()
            return self.queued_response(work, candidate, position or 1, depth)
        clock_token = REQUESTED_AT.set(requested_at)
        try:
            status,upstream,data=self.dispatch_generation(candidate,path,raw,headers)
        finally:
            REQUESTED_AT.reset(clock_token)
        if status < 300:
            self.reconcile_ticket()
        return status,upstream,data

    def input_reply(self, identifier, host, path, raw, headers):
        self.check_paused()
        match = re.fullmatch(r'/api/(jobs|chats)/([a-f0-9]{32})/(form|permission)/([A-Za-z0-9_]+)/reply', path)
        collection, target, category, request = match.groups()
        key = 'job' if collection == 'jobs' else 'chat'
        status, _, data = self.proxy(identifier, host, '/api/'+collection+'/'+target+('/status' if key == 'chat' else ''), 'GET', None, {})
        value = json.loads(data)
        # A reply can wake a suspended model. Reacquire its slot before forwarding.
        if status != 200 or value.get('state') != 'waiting' or value.get('reservation_required') is not False:
            return 409, {'Content-Type':'application/json'}, b'{"error":"Refresh status before sending this answer again."}'
        body = json.loads(raw)
        if category == 'form' and (set(body) != {'answer'} or not isinstance(body['answer'], dict)):
            raise ValueError('Invalid briefing answer')
        if category == 'permission' and (set(body) != {'decision'} or body['decision'] not in ('once', 'reject')):
            raise ValueError('Invalid permission answer')
        if not any(form.get('id') == request for form in value.get('forms' if category == 'form' else 'permissions', [])):
            raise ValueError('This feedback form changed; review the current task list')
        candidate = {'user':identifier, 'host':host, key:target, 'request':request, 'dispatching':True,
                     'date':value.get('date'), 'kind':value.get('kind') or value.get('mode')}
        self.pump_queue()
        action, position, depth = self._reserve_or_queue('reply', candidate, path, body, self.accounts.website_language(identifier) or ui.current())
        if action in ('queued', 'queued_duplicate'):
            return self.queued_response('reply', candidate, position, depth)
        if action == 'full':
            return 429, {'Content-Type':'application/json'}, json.dumps({'error':QUEUE_FULL}).encode()
        if action == 'active_duplicate':
            return 202, {'Content-Type':'application/json'}, json.dumps({key:target}).encode()
        status, upstream, data = self.proxy(identifier, host, path, 'POST', raw, headers)
        if 400 <= status < 500:
            self.clear_ticket(candidate)
        elif status < 300:
            self.confirm_dispatch(candidate)
        return status, upstream, data

    def recover(self, identifier, host, path, raw, headers):
        self.check_paused()
        body = json.loads(raw)
        if set(body) != {'id'} or not isinstance(body['id'], str) or not re.fullmatch('[a-f0-9]{32}', body['id']):
            raise ValueError('Invalid recovery request')
        job = re.fullmatch(r'/api/jobs/([a-f0-9]{32})/recover', path)[1]
        candidate = {'user':identifier, 'host':host, 'job':job, 'request':body['id'], 'dispatching':True}
        language = self.accounts.website_language(identifier) or ui.current()
        self.pump_queue()
        observed = self.ticket()
        refreshable = False
        if observed and all(observed.get(k) == candidate[k] for k in ('user','host','job')) and observed.get('request') != body['id']:
            status, _, data = self.proxy(identifier, host, '/api/jobs/'+job, 'GET', None, {})
            refreshable = status == 200 and json.loads(data).get('recovery_action') == 'refresh'
        with self.accounts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT value FROM metadata WHERE key='generation'").fetchone()
            previous = json.loads(row[0]) if row else None
            queue = self._prune_queue(self._read_queue(db), time.time())
            if row:
                current = json.loads(row[0])
                if any(current.get(k) != candidate[k] for k in ('user', 'host', 'job')):
                    for index, waiting in enumerate(queue):
                        if waiting.get('kind') == 'recover' and waiting.get('candidate') == candidate:
                            self._write_queue(db, queue)
                            return self.queued_response('recover', candidate, index + 1, len(queue))
                    if len(queue) >= MAX_QUEUE:
                        self._write_queue(db, queue)
                        return 429, {'Content-Type':'application/json'}, json.dumps({'error':QUEUE_FULL}).encode()
                    queue.append({'kind':'recover','candidate':candidate,'user':identifier,'host':host,
                                  'path':path,'body':body,'language':language,'enqueued':time.time()})
                    self._write_queue(db, queue)
                    return self.queued_response('recover', candidate, len(queue), len(queue))
                if current.get('request') == body['id']:
                    self._write_queue(db, queue)
                    return 202, {'Content-Type':'application/json'}, json.dumps({'job':job}).encode()
                # Only an undispatched preflight can replace its own reservation.
                if current != observed or not refreshable:
                    self._write_queue(db, queue)
                    return 409, {'Content-Type':'application/json'}, b'{"error":"Refresh status before trying recovery again."}'
            elif queue:
                for index, waiting in enumerate(queue):
                    if waiting.get('kind') == 'recover' and waiting.get('candidate') == candidate:
                        self._write_queue(db, queue)
                        return self.queued_response('recover', candidate, index + 1, len(queue))
                if len(queue) >= MAX_QUEUE:
                    self._write_queue(db, queue)
                    return 429, {'Content-Type':'application/json'}, json.dumps({'error':QUEUE_FULL}).encode()
                queue.append({'kind':'recover','candidate':candidate,'user':identifier,'host':host,
                              'path':path,'body':body,'language':language,'enqueued':time.time()})
                self._write_queue(db, queue)
                return self.queued_response('recover', candidate, len(queue), len(queue))
            self._write_queue(db, queue)
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('generation', json.dumps(candidate, separators=(',',':'))))
        status, upstream, data = self.proxy(identifier, host, path, 'POST', raw, headers)
        if 400 <= status < 500:
            if previous:
                with self.accounts.db() as db:
                    db.execute('UPDATE metadata SET value=? WHERE key=? AND value=?',
                               (json.dumps(previous,separators=(',',':')),'generation',json.dumps(candidate,separators=(',',':'))))
            else:
                self.clear_ticket(candidate)
        elif status < 300:
            self.confirm_dispatch(candidate)
        return status, upstream, data


def account_page(session, title, kind='gm'):
    temporary = bool(session.get('temporary'))
    login = not session.get('user_id')
    def password_field(name,label,autocomplete):
        # HTML length limits count UTF-16 units; JS/server validate actual characters.
        limit = PASSWORD_MAX * 2 if autocomplete == 'new-password' else 256
        described = ' aria-describedby="password-rules"' if autocomplete == 'new-password' else ''
        return ('<div class="account-field"><label for="password-'+name+'">'+label+'</label><div class="password-field">'
                '<input id="password-'+name+'" name="'+name+'" type="password" autocomplete="'+autocomplete+'" required maxlength="'+str(limit)+'"'+described+'>'
                '<button type="button" class="password-toggle" data-password-target="password-'+name+'" '
                'data-password-label="'+label.lower()+'" aria-controls="password-'+name+'" aria-pressed="false" '
                'aria-label="Show '+label.lower()+'">Show</button></div></div>')
    fields = ('<label>Username<input name="username" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" required maxlength="40"></label>'
              +password_field('password','Password','current-password')+
              '<label class="remember-login"><input type="checkbox" name="remember">Remember me for 60 days on this device</label>') if login else (
              password_field('current','Current password','current-password')+
              password_field('replacement','New password','new-password')+
              password_field('repeat','Repeat new password','new-password'))
    note = 'Accounts are created by the server administrator. Forgotten passwords require administrator help.' if login else (
        'Replace your temporary password before opening private briefings.' if temporary else 'Changing your password signs out other devices. Your encrypted records stay unchanged.')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + favicon_links(kind) +
            '<title>'+html.escape(title)+'</title><link rel="stylesheet" href="/auth.css"></head><body'+(' class="sign-in"' if login else '')+'><main class="account-card">'
            '<p class="wordmark">GoodMorning</p><p class="eyebrow">Your personal secretary</p><h1>'+html.escape(title)+'</h1><p>'+note+'</p>'+
            ('' if login else '<p id="password-rules">'+PASSWORD_RULE+'</p>')+
            '<form id="account-form" method="post" action="/api/auth/'+('login' if login else 'password')+'" data-action="'+('login' if login else 'password')+'" data-csrf="'+session['csrf']+'" '
            'data-password-min="'+str(PASSWORD_MIN)+'" data-password-max="'+str(PASSWORD_MAX)+'">'+fields+
            '<button type="submit" disabled>'+('Sign in' if login else 'Change password')+'</button></form><p id="account-error" role="alert"></p>'+
            '<noscript>Enable JavaScript to sign in or change your password.</noscript>'+
            ('' if login or temporary else '<a href="/">Back to briefing</a>')+
            '<script src="/auth.js" defer></script></main></body></html>').encode()


def handler_for(gateway):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'GoodMorning'

        def log_message(self,*_):
            pass  # Never log paths, passwords, answers, cookies or rendered briefings.

        def setup(self):
            super().setup()
            self.connection.settimeout(25)

        def respond(self,data,status=200,mime='application/json',*,token=None,cookie_age=SESSION_SECONDS,location=None,cache='no-store',etag=None,language_cookie=None,color_cookie=None,app_cookie=None,link_cookie=None,resource=None,retry_after=None,owner=None):
            if not isinstance(data,bytes):
                if isinstance(data,dict) and isinstance(data.get('error'),str):data={**data,'error':ui.text(data['error'])}
                data=json.dumps(data,separators=(',',':')).encode()
            encoded=bool(data) and accepts_gzip(self.headers.get('Accept-Encoding','')) and mime.startswith(('text/','application/json')) and not mime.startswith('text/html')
            if encoded:
                data=resource.compressed if resource else gzip.compress(data,mtime=0)
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control',cache)
            self.send_header('Content-Language',ui.current())
            self.send_header('Vary','Accept-Encoding')
            policy = POLICY.replace("img-src 'self'", "img-src 'self' blob:") if mime.startswith('text/html') and (b'id="chat-config"' in data or b'id="quick-chat"' in data) else POLICY
            self.send_header('Content-Security-Policy',policy)
            self.send_header('X-Content-Type-Options','nosniff')
            # Native same-origin forms need a non-null Origin for strict CSRF checks.
            # This policy still sends no referrer to external sites.
            self.send_header('Referrer-Policy','same-origin' if mime.startswith('text/html') else 'no-referrer')
            self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
            self.send_header('Strict-Transport-Security','max-age=31536000')
            if retry_after is not None:
                self.send_header('Retry-After',str(int(retry_after)))
            if encoded:
                self.send_header('Content-Encoding','gzip')
            if location:
                self.send_header('Location',location)
            if etag:
                self.send_header('ETag',etag)
            if owner:
                self.send_header('X-GoodMorning-Owner',owner)
            if token is not None:
                self.send_header('Set-Cookie',f'{COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={cookie_age if token else 0}')
            if language_cookie is not None:
                value=ui.language(language_cookie)
                domain='; Domain='+gateway.language_domain if gateway.language_domain else ''
                self.send_header('Set-Cookie','GoodMorningLanguage='+value+'; Path=/; Secure; SameSite=Lax; Max-Age=31536000'+domain)
            if color_cookie is not None:
                value = site_colors.cookie(color_cookie)
                domain = '; Domain='+gateway.language_domain if gateway.language_domain else ''
                self.send_header('Set-Cookie', 'GoodMorningAppearance='+value+'; Path=/; Secure; SameSite=Lax; Max-Age=31536000'+domain)
            if app_cookie is not None:
                # Which app build shows this site, so the page can offer the app's own updates.
                self.send_header('Set-Cookie','GoodMorningApp='+str(int(app_cookie))+'; Path=/; Secure; SameSite=Lax; Max-Age=31536000')
            if link_cookie is not None:
                # Which linked phone shows this site, so a color scheme chosen here also reaches its widgets.
                domain = '; Domain='+gateway.language_domain if gateway.language_domain else ''
                self.send_header('Set-Cookie','GoodMorningLink='+link_cookie+'; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=31536000'+domain)
            self.end_headers()
            if self.command!='HEAD' and status!=304:
                self.wfile.write(data)

        def host(self):
            if len(self.headers.get_all('Host',[])) != 1:
                raise Denied('Forbidden')
            host=self.headers['Host']
            if host not in gateway.hosts or self.headers.get('X-Forwarded-Proto')!='https':
                raise Denied('Forbidden')
            return host

        def session(self,host):
            raw=self.headers.get('Cookie','')
            if len(raw)>4096 or raw.count(COOKIE+'=')!=1:
                raise Denied('Login required')
            cookie=SimpleCookie()
            try:
                cookie.load(raw)
                return gateway.accounts.session(cookie[COOKIE].value,host)
            except (KeyError,ValueError,CookieError):
                raise Denied('Login required')

        def address(self):
            value=self.headers.get('X-Real-IP','')
            import ipaddress
            return str(ipaddress.ip_address(value))  # NGINX overwrites it, never trusts clients.

        def browser_language(self):
            try:
                cookie=SimpleCookie();cookie.load(self.headers.get('Cookie','')[:4096])
                return ui.language(cookie['GoodMorningLanguage'].value)
            except (KeyError,ValueError,CookieError):return 'en'

        def app_user(self):
            """The account behind the app's token; repeated failures from one address are limited.
            The link stays on the request; the app says whether it posts notifications itself."""
            notifies={'app':True,'push':False}.get(self.headers.get('X-GoodMorning-Notify'))
            found=app_link.verify(gateway.accounts,self.headers.get('X-GoodMorning-App'),notifies)
            if not found:
                gateway.accounts.limit([('app-token-ip:'+self.address(),30)])
                raise Denied('Link this phone again in GoodMorning under Account → Linked phones.')
            user,self.app_link=found
            return user

        def app_post(self,host,path):
            """App requests carry no browser Origin or cookies; the pairing secret or app token authorizes them."""
            if gateway.paused():
                return self.maintenance_json()
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1:
                raise ValueError('Invalid request body')
            size=int(self.headers['Content-Length'])
            if not 0<size<=20000 or self.headers.get('Content-Type')!='application/json':
                raise ValueError('Invalid request body')
            body=json.loads(self.rfile.read(size))
            if not isinstance(body,dict):raise ValueError('A JSON object is required')
            if path=='/api/app/pair':
                gateway.accounts.limit([('app-pair-ip:'+self.address(),20)])
                if set(body)!={'label'}:raise ValueError('Invalid phone name')
                return self.respond(app_link.pair(gateway.accounts,body['label']))
            user=self.app_user()
            if path=='/api/app/signin':
                gateway.accounts.limit([('app-signin:'+user,10)])
                if body:raise ValueError('Invalid sign-in request')
                return self.respond(gateway.app_signin(user,host))
            self.select_language({'user_id':user})
            gateway.backend(user)
            handler={'/api/app/generate':gateway.app_generate,'/api/app/chat':gateway.app_chat,
                     '/api/app/note':gateway.app_note,'/api/app/notes/sort':gateway.app_sort}[path]
            status,headers,data=handler(user,body)
            return self.respond(data,status,headers.get('Content-Type','application/json'))

        def app_build(self):
            """The app's version code from its launch address (/app?app=N), or None."""
            build=parse_qs(urlsplit(self.path).query).get('app',[''])[0]
            return int(build) if re.fullmatch(r'[1-9][0-9]{0,5}',build) else None

        def app_page(self):
            """A page the app asked for (widgets, notifications), else the last page; the first launch opens chat."""
            target=parse_qs(urlsplit(self.path).query).get('next',[''])[0]
            page,_,query=target.partition('?')
            if PAGE_ROUTES.fullmatch(page) and re.fullmatch(r'[A-Za-z0-9=&_.%-]*',query):return target
            try:
                cookie=SimpleCookie();cookie.load(self.headers.get('Cookie','')[:4096])
                page=unquote(cookie['GoodMorningAppPage'].value)
            except (KeyError,ValueError,CookieError):return '/chat'
            return page if PAGE_ROUTES.fullmatch(page) else '/chat'

        def select_language(self,session=None):
            selected=(gateway.accounts.website_language(session['user_id']) or 'en') if session and session.get('user_id') else self.browser_language()
            ui.CURRENT.set(selected)
            # Colors belong to the device; one that has not chosen yet keeps its account's earlier choice.
            try:
                colors = site_colors.from_cookie(self.cookie('GoodMorningAppearance'))
            except (KeyError, ValueError, CookieError):
                if session and session.get('user_id'):
                    colors = gateway.accounts.website_color_schemes(session['user_id']) or site_colors.DEFAULT
                else:
                    try:  # Before devices, a signed-out page knew only the account's day scheme.
                        colors = site_colors.validate({'day': self.cookie('GoodMorningDayScheme'), 'night': site_colors.DEFAULT['night']})
                    except (KeyError, ValueError, CookieError):
                        colors = site_colors.DEFAULT
            site_colors.CURRENT.set(dict(colors))

        def cookie(self,name):
            cookie = SimpleCookie(); cookie.load(self.headers.get('Cookie', '')[:4096])
            return cookie[name].value

        def this_link(self,user):
            """The linked phone showing this page (GoodMorningLink), if it is still one of the account's."""
            try:
                link = self.cookie('GoodMorningLink')
            except (KeyError, CookieError):
                return None
            return link if any(entry['id'] == link for entry in app_link.links(gateway.accounts, user)) else None

        def account_html(self,session,title,host):
            source=account_page(session,title,gateway.hosts[host]).decode()
            return gateway.icons.rewrite(ui.page(source,session['csrf'],urlsplit(self.path).path)).encode()

        def unavailable(self,session=None,host=None,*,pending=False):
            message = BACKEND_PENDING if pending else BACKEND_UNAVAILABLE
            path = urlsplit(self.path).path
            if not session or not session.get('user_id') or not PAGE_ROUTES.fullmatch(path):
                return self.respond({'error':message},503)
            title = 'Secretary setup pending' if pending else 'Secretary temporarily unavailable'
            source = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                      '<meta name="viewport" content="width=device-width,initial-scale=1">'+favicon_links(gateway.hosts[host])+
                      '<title>'+title+'</title><link rel="stylesheet" href="/auth.css"></head><body>'
                      '<main class="account-card"><p class="eyebrow">Your personal secretary</p><h1>'+title+'</h1>'
                      '<p role="status">'+message+'</p><p><a href="'+html.escape(self.path,quote=True)+'">Try again</a></p></main>'
                      '<nav class="account-tools" aria-label="Account"><a href="/password">Change password</a>'
                      '<button id="sign-out" data-csrf="'+session['csrf']+'">Sign out</button></nav>'
                      '<script src="/auth.js" defer></script></body></html>')
            data = gateway.icons.rewrite(ui.page(source,session['csrf'],path)).encode()
            return self.respond(data,503,'text/html; charset=utf-8')

        def maintenance_html(self):
            return self.respond(deploy_pause.html_page(),503,'text/html; charset=utf-8',
                                cache='no-store',retry_after=deploy_pause.RETRY_AFTER_SECONDS)

        def maintenance_json(self):
            return self.respond(deploy_pause.json_error(),503,
                                cache='no-store',retry_after=deploy_pause.RETRY_AFTER_SECONDS)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            session = None
            host = None
            try:
                host=self.host()
                self.select_language()
                path=urlsplit(self.path).path
                if path == '/api/app/release':
                    return self.respond(app_release.latest(),cache='public, max-age=300')
                if path == '/api/release':
                    tag='W/"'+VERSION+'"'
                    cached=self.headers.get('If-None-Match')==tag
                    return self.respond(b'' if cached else release_info(),304 if cached else 200,cache='public, no-cache',etag=tag)
                resource=gateway.icons.paths.get(path) or gateway.icons.alias(path)
                if resource:
                    tag=resource.etag
                    if resource.mime.startswith('text/') and accepts_gzip(self.headers.get('Accept-Encoding','')):tag=tag[:-1]+'-gzip"'
                    cached=any(value.strip().removeprefix('W/') in (tag,'*') for value in self.headers.get('If-None-Match','').split(','))
                    return self.respond(b'' if cached else resource.data,304 if cached else 200,resource.mime,
                                        cache='public, max-age=31536000, immutable' if path in gateway.icons.paths else 'public, no-cache',etag=tag,resource=resource)
                if path=='/.well-known/assetlinks.json':
                    return self.respond(ASSET_LINKS,cache='public, max-age=3600')
                if gateway.paused():
                    if path.startswith('/api/'):
                        return self.maintenance_json()
                    return self.maintenance_html()
                if path=='/api/app/pair':
                    gateway.accounts.limit([('app-claim-ip:'+self.address(),240)])
                    try:
                        claimed=app_link.claim(gateway.accounts,self.headers.get('X-GoodMorning-Pairing'))
                    except ValueError:
                        return self.respond({'error':'This code expired. Show a new code in the app.'},404)
                    return self.respond(claimed or {'pending':True})
                if path=='/api/app/avatar':
                    user=self.app_user()
                    image=parse_qs(urlsplit(self.path).query).get('path',[''])[0]
                    if not re.fullmatch(r'/api/avatar/image/[a-f0-9]{64}\.png',image):raise ValueError('Invalid portrait')
                    status,headers,data=gateway.proxy(user,next(iter(gateway.hosts)),image,'GET',None,{})
                    return self.respond(data,status,headers.get('Content-Type','image/png') if status==200 else 'application/json')
                if path=='/api/app/notes':
                    user=self.app_user()
                    self.select_language({'user_id':user})
                    gateway.backend(user)
                    status,headers,data=gateway.proxy(user,next(iter(gateway.hosts)),'/api/notes','GET',None,{})
                    return self.respond(data,status,'application/json')
                if path=='/api/app/sync':
                    user=self.app_user()
                    after=parse_qs(urlsplit(self.path).query).get('after',['0'])[0]
                    if not after.isdigit():raise ValueError('Invalid cursor')
                    self.select_language({'user_id':user})
                    return self.respond(gateway.app_sync(user,self.app_link,int(after)))
                try:
                    session=self.session(host)
                except Denied:
                    if path=='/api/release/seen':return self.respond({'version':None,'enabled':False})
                    if path=='/api/language':return self.respond({'language':ui.current()})
                    if path=='/api/model':return self.respond({'model':site_models.for_language(ui.current())})
                    if path=='/api/color-schemes':return self.respond(site_colors.current())
                    query=parse_qs(urlsplit(self.path).query)
                    if path=='/app' and 'b' not in query:
                        # The app opens /app from outside the site, so the browser holds back the SameSite=Strict
                        # login cookie. One same-site step through this page sends it, without loosening the cookie.
                        target='/app?'+urlencode({**{key:value[0] for key,value in query.items()},'b':'1'})
                        return self.respond(('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url='
                                             +html.escape(target,quote=True)+'"><title>GoodMorning</title>').encode(),mime='text/html; charset=utf-8',
                                            app_cookie=self.app_build())
                    if path!='/login':
                        return self.respond({'error':'Login required'},401) if path.startswith('/api/') else self.respond(b'',302,location='/login')
                    gateway.accounts.limit([('prelogin-ip:'+self.address(),60)])
                    token,csrf=gateway.accounts.anonymous(host)
                    return self.respond(self.account_html({'csrf':csrf},'Sign in',host),mime='text/html; charset=utf-8',token=token,cookie_age=600)
                self.select_language(session)
                if path=='/api/release/seen':
                    user=session.get('user_id')
                    return self.respond({'version':gateway.accounts.release_seen(user) if user else None,'enabled':bool(user)})
                if path=='/api/language':return self.respond({'language':ui.current()})
                if path=='/api/model':return self.respond({'model':site_models.for_language(ui.current())})
                if path=='/api/color-schemes':return self.respond(site_colors.current())
                if path=='/login' and not session['user_id']:
                    return self.respond(self.account_html(session,'Sign in',host),mime='text/html; charset=utf-8')
                if not session['user_id']:
                    return self.respond({'error':'Login required'},401) if path.startswith('/api/') else self.respond(b'',302,location='/login')
                if path=='/password' or session['temporary']:
                    if path!='/password':
                        return self.respond({'error':'Password change required'},403) if path.startswith('/api/') else self.respond(b'',302,location='/password')
                    return self.respond(self.account_html(session,'Change password',host),mime='text/html; charset=utf-8')
                if path=='/login':
                    return self.respond(b'',302,location='/')
                if path=='/app':
                    link=parse_qs(urlsplit(self.path).query).get('link',[''])[0]
                    entry=next((entry for entry in app_link.links(gateway.accounts,session['user_id']) if entry['id']==link),None)
                    try:
                        self.cookie('GoodMorningAppearance');chosen=True
                    except (KeyError,CookieError):chosen=False
                    colors=None
                    if entry and not chosen and entry['appearance']:
                        colors=entry['appearance']  # A new view on this phone, such as the app leaving Chrome, keeps its colors.
                    elif entry and entry['appearance']!=site_colors.current():
                        # Colors chosen on this phone before the app named its link reach the widgets too.
                        app_link.appearance(gateway.accounts,session['user_id'],link,site_colors.current())
                    if not entry:link=None
                    return self.respond(b'',302,location=self.app_page(),app_cookie=self.app_build(),link_cookie=link,color_cookie=colors)
                if path=='/api/queue':
                    return self.respond(gateway.queue_status(session['user_id']))
                if path=='/api/activity':
                    return self.respond(gateway.activity(session['user_id']))
                if path=='/api/app/links':
                    return self.respond({'links':app_link.links(gateway.accounts,session['user_id'])})
                if path=='/api/push':
                    return self.respond({'publicKey':web_push.public_key(gateway.accounts),
                                         'devices':web_push.devices(gateway.accounts,session['user_id']),
                                         'links':app_link.links(gateway.accounts,session['user_id'])})
                if re.fullmatch(r'/offline/(?:gm|gn)\.html',path):
                    # The read-only copy sw.js keeps for reading offline gets no session token or account controls.
                    # Its owner tag lets the device drop it when another account signs in here.
                    status,headers,data=gateway.proxy(session['user_id'],host,self.path,'GET',None,{})
                    owner=hashlib.sha256(('offline-owner:'+session['user_id']).encode()).hexdigest()[:32]
                    if status!=200:return self.respond(data,status,owner=owner)
                    data=gateway.icons.rewrite(data.decode()).encode()
                    tag='"'+hashlib.sha256(owner.encode()+data).hexdigest()+'"'
                    unchanged=self.headers.get('If-None-Match')==tag
                    return self.respond(b'' if unchanged else data,304 if unchanged else 200,headers['Content-Type'],etag=tag,owner=owner)
                status,headers,data=gateway.proxy(session['user_id'],host,self.path,'GET',None,self.headers)
                if status >= 500 and PAGE_ROUTES.fullmatch(path):
                    return self.unavailable(session,host)
                mime=headers.get('Content-Type','application/json')
                if mime.startswith('text/html'):
                    cache_key=(session['user_id'],host,self.path,ui.current(),tuple(site_colors.current().items()),session['csrf'],VERSION,hashlib.sha256(data).digest())
                    with gateway.html_lock:cached=gateway.html_cache.get(cache_key)
                    if cached is not None:return self.respond(cached,status,mime)
                    # Replace backend-wide CSRF with the authenticated session's CSRF.
                    text=data.decode()
                    text=re.sub(r'(&quot;csrf&quot;:\s*&quot;)[A-Za-z0-9_-]{43}(&quot;)',r'\g<1>'+session['csrf']+r'\g<2>',text)
                    # A public, non-authorizing namespace changes with every login.
                    scope=hashlib.sha256(('chat-workspace:'+session['csrf']).encode()).hexdigest()
                    text=re.sub(r'(&quot;workspaceScope&quot;:\s*&quot;)[a-f0-9]{64}(&quot;)',r'\g<1>'+scope+r'\g<2>',text)
                    controls='<nav class="account-tools" aria-label="Account"><a href="/password">Change password</a><button id="sign-out" data-csrf="'+session['csrf']+'">Sign out</button></nav><script src="/auth.js" defer></script><script src="/app.js" defer></script>'
                    text=text.replace('</head>','<link rel="manifest" href="/manifest.webmanifest"></head>',1)
                    data=text.replace('</body>',controls+'</body>').encode()
                    data=gateway.icons.rewrite(ui.page(activity_panel(data.decode(),gateway.hosts),session['csrf'],self.path)).encode()
                    if status == 200:
                        with gateway.html_lock:gateway.html_cache.put(cache_key,data,len(data))
                # Personal pages/media never enter durable browser or shared proxy caches.
                static=path.startswith('/assets/')
                return self.respond(data,status,mime,cache=headers.get('Cache-Control','no-store') if static else 'no-store',etag=headers.get('ETag') if static else None)
            except Limited as error:
                return self.respond({'error':str(error)},429)
            except Denied:
                return self.respond({'error':'Forbidden'},403)
            except BackendPending:
                return self.unavailable(session,host,pending=True)
            except deploy_pause.MaintenancePaused:
                path=urlsplit(self.path).path
                if path.startswith('/api/'):
                    return self.maintenance_json()
                return self.maintenance_html()
            except Exception as error:
                # Exception text can contain credentials, private paths or response bodies.
                logging.getLogger(__name__).warning('Secretary read failed (%s)',type(error).__name__)
                return self.unavailable(session,host)

        def do_POST(self):
            try:
                host=self.host()
                self.select_language()
                if urlsplit(self.path).path in ('/api/app/pair','/api/app/signin','/api/app/chat','/api/app/generate','/api/app/note','/api/app/notes/sort'):
                    return self.app_post(host,urlsplit(self.path).path)
                if self.headers.get('Origin')!='https://'+host or self.headers.get('Sec-Fetch-Site','same-origin')!='same-origin':
                    raise Denied('Forbidden')
                path=urlsplit(self.path).path
                if gateway.paused() and path != '/api/auth/logout':
                    return self.maintenance_json()
                session=self.session(host)
                self.select_language(session)
                path=urlsplit(self.path).path
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1:
                    raise ValueError('Invalid request body')
                size=int(self.headers['Content-Length'])
                if UPLOAD_ROUTE.fullmatch(path) or AVATAR_UPLOAD_ROUTE.fullmatch(path):
                    if not session['user_id'] or session['temporary']:
                        raise Denied('Sign in with a permanent password before uploading')
                    if not secrets.compare_digest(self.headers.get('X-Briefing-CSRF', ''), session['csrf']):
                        raise Denied('Forbidden')
                    avatar_upload = bool(AVATAR_UPLOAD_ROUTE.fullmatch(path))
                    if size > (MAX_AVATAR_BYTES if avatar_upload else MAX_UPLOAD_BYTES):
                        return self.respond({'error': 'Avatar images must be 5 MB or smaller.' if avatar_upload else 'Files must be 50 MB or smaller.'}, 413)
                    if size < 0 or self.headers.get('Content-Type') != 'application/octet-stream':
                        raise ValueError('Invalid upload')
                    if not avatar_upload:
                        upload_name(urlsplit(self.path).query)
                    status, headers, data = gateway.proxy(session['user_id'], host, self.path, 'POST',
                        UploadReader(self.rfile, size), self.headers)
                    return self.respond(data, status, headers.get('Content-Type', 'application/json'))
                form=path in ('/api/language','/api/model','/api/color-schemes') and self.headers.get('Content-Type','').split(';')[0]=='application/x-www-form-urlencoded'
                if not 0<size<=20000 or (not form and self.headers.get('Content-Type')!='application/json'):
                    raise ValueError('Invalid request body')
                raw=self.rfile.read(size)
                if len(raw)!=size:
                    raise ValueError('Incomplete request')
                if form:
                    fields=parse_qs(raw.decode(),keep_blank_values=True,strict_parsing=True)
                    expected={'csrf','language','return_to'} if path=='/api/language' else {'csrf','model','return_to'}
                    if path=='/api/color-schemes':expected={'csrf','day','night','return_to'}|({'style'} if 'style' in fields else set())
                    if set(fields)!=expected or any(len(values)!=1 for values in fields.values()):raise ValueError('Invalid settings form')
                    body={key:values[0] for key,values in fields.items()}
                else:body=json.loads(raw)
                if not isinstance(body,dict):
                    raise ValueError('A JSON object is required')
                if not secrets.compare_digest(body.get('csrf','') if form else self.headers.get('X-Briefing-CSRF',''),session['csrf']):raise Denied('Forbidden')
                if path=='/api/language':
                    if not form and set(body)!={'language'}:raise ValueError('Invalid language choice')
                    selected=ui.language(body['language'])
                    if session['user_id']:gateway.accounts.website_language(session['user_id'],selected)
                    ui.CURRENT.set(selected)
                    target=body.get('return_to','/')
                    if form and (len(target)>2048 or any(ord(c)<32 for c in target) or '\\' in target or urlsplit(target).netloc or urlsplit(target).scheme or not (GET_ROUTES.fullmatch(urlsplit(target).path) or target in ('/login','/password'))):target='/'
                    return self.respond({'language':selected},303 if form else 200,location=target if form else None,language_cookie=selected)
                if path=='/api/model':
                    return self.respond({'error':'Model selection is automatic from the website language.'},405)
                if path=='/api/color-schemes':
                    selected = site_colors.validate({key: body[key] for key in site_colors.OPTIONS if key in body} if form else body)
                    link=session['user_id'] and self.this_link(session['user_id'])
                    if link:app_link.appearance(gateway.accounts,session['user_id'],link,selected)
                    site_colors.CURRENT.set(selected)
                    target=body.get('return_to','/')
                    if form and (len(target)>2048 or any(ord(c)<32 for c in target) or '\\' in target or urlsplit(target).netloc or urlsplit(target).scheme or not (GET_ROUTES.fullmatch(urlsplit(target).path) or target in ('/login','/password'))):target='/'
                    return self.respond(selected,303 if form else 200,location=target if form else None,color_cookie=selected)
                if path=='/api/auth/login' and not session['user_id']:
                    if set(body) not in ({'username','password'},{'username','password','remember'}) or type(body.get('remember',False)) is not bool:
                        raise ValueError('Invalid login')
                    remember=body.get('remember',False)
                    token,csrf,temporary=gateway.accounts.login(body['username'],body['password'],host,self.address(),session,remember=remember)
                    logged=gateway.accounts.session(token,host)
                    selected=gateway.accounts.website_language(logged['user_id'])
                    if selected is None:selected=gateway.accounts.website_language(logged['user_id'],ui.current())
                    ui.CURRENT.set(selected)
                    return self.respond({'next':'/password' if temporary else '/'},token=token,cookie_age=REMEMBER_SECONDS if remember else SESSION_SECONDS,language_cookie=selected)
                if not session['user_id']:
                    raise Denied('Login required')
                if path=='/api/release/seen':
                    if set(body)!={'version'} or body['version'] is None:raise ValueError('Invalid release version')
                    return self.respond({'version':gateway.accounts.release_seen(session['user_id'],body['version']),'enabled':True})
                if path=='/api/auth/password':
                    if set(body)!={'current','replacement'}:
                        raise ValueError('Invalid password change')
                    token,csrf=gateway.accounts.change_password(session,body['current'],body['replacement'],self.address())
                    return self.respond({'next':'/'},token=token,cookie_age=REMEMBER_SECONDS if session['remembered'] else SESSION_SECONDS)
                if path=='/api/auth/logout':
                    gateway.accounts.logout(session)
                    return self.respond({'next':'/login'},token='')
                if session['temporary']:
                    raise Denied('Change your temporary password first')
                if path=='/api/app/link':
                    if set(body)!={'code'}:raise ValueError(app_link.INVALID_CODE)
                    gateway.accounts.limit([('app-link-user:'+session['user_id'],10)])
                    return self.respond({'label':app_link.confirm(gateway.accounts,session['user_id'],body['code']),
                                         'links':app_link.links(gateway.accounts,session['user_id'])})
                if path=='/api/app/unlink':
                    if set(body)!={'id'} or not isinstance(body['id'],str):raise ValueError('Invalid phone')
                    app_link.unlink(gateway.accounts,session['user_id'],body['id'])
                    return self.respond({'links':app_link.links(gateway.accounts,session['user_id'])})
                if path=='/api/push/subscribe':
                    if set(body)!={'subscription','label'}:raise ValueError('Invalid push subscription')
                    return self.respond(web_push.subscribe(gateway.accounts,session['user_id'],body['subscription'],body['label'],self.this_link(session['user_id'])))
                if path=='/api/push/unsubscribe':
                    # The browser itself names its endpoint; Account turns another device off by its name.
                    if len(body)!=1 or not isinstance(next(iter(body.values()),None),str) or set(body)-{'endpoint','device'}:raise ValueError('Invalid push subscription')
                    web_push.unsubscribe(gateway.accounts,session['user_id'],body.get('endpoint'),identifier=body.get('device'))
                    return self.respond({'devices':web_push.devices(gateway.accounts,session['user_id'])})
                if path=='/api/push/settings':
                    if set(body) not in ({'device','settings'},{'link','settings'}) or not isinstance(body.get('device',body.get('link')),str):
                        raise ValueError('Invalid notification settings')
                    if 'device' in body:
                        return self.respond({'settings':web_push.settings(gateway.accounts,session['user_id'],body['device'],body['settings'])})
                    return self.respond({'settings':app_link.settings(gateway.accounts,session['user_id'],body['link'],body['settings'])})
                # Reject incomplete setup before taking a global reservation or queue slot.
                gateway.backend(session['user_id'])
                if path=='/api/generate':
                    status,headers,data=gateway.generate(session['user_id'],host,raw,self.headers)
                elif path=='/api/regenerate':
                    status,headers,data=gateway.generate(session['user_id'],host,raw,self.headers,regenerate=True)
                elif re.fullmatch(r'/api/jobs/[a-f0-9]{32}/recover', path):
                    status,headers,data=gateway.recover(session['user_id'],host,path,raw,self.headers)
                elif re.fullmatch(r'/api/(?:jobs|chats)/[a-f0-9]{32}/(?:form|permission)/[A-Za-z0-9_]+/reply', path):
                    status,headers,data=gateway.input_reply(session['user_id'],host,path,raw,self.headers)
                elif path == '/api/chats' or re.fullmatch(r'/api/chats/[a-f0-9]{32}/messages', path):
                    status,headers,data=gateway.chat_message(session['user_id'],host,path,raw,self.headers)
                else:
                    status,headers,data=gateway.proxy(session['user_id'],host,self.path,'POST',raw,self.headers)
                return self.respond(data,status,headers.get('Content-Type','application/json'))
            except Limited as error:
                return self.respond({'error':str(error)},429)
            except Denied as error:
                return self.respond({'error':str(error)},403)
            except BackendPending:
                return self.respond({'error':BACKEND_PENDING},503)
            except deploy_pause.MaintenancePaused:
                return self.maintenance_json()
            except (ValueError,KeyError,TypeError):
                route=urlsplit(self.path).path
                error='Invalid upload' if UPLOAD_ROUTE.fullmatch(route) else app_link.INVALID_CODE if route=='/api/app/link' else 'Phone request could not be read. Update the app or try again.' if route.startswith('/api/app/') else 'Notification settings could not be saved. Try again.' if route.startswith('/api/push/') else 'Invalid release version' if route=='/api/release/seen' else 'Choose English or Simplified Chinese' if route=='/api/language' else 'Choose one of the offered website models' if route=='/api/model' else 'Choose one of the offered color schemes' if route=='/api/color-schemes' else 'Invalid request. '+PASSWORD_RULE
                return self.respond({'error':error},400)
            except Exception:
                return self.respond({'error':'Request could not be confirmed. Refresh before retrying.'},503)
    return Handler


class Server(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):
    daemon_threads=True
    # NGINX opens one upstream connection per concurrent browser asset request.
    # Keep a bounded backlog without creating more account-processing workers.
    request_queue_size=64
    request_wait_seconds=20
    def __init__(self,*args):
        self.slots=threading.BoundedSemaphore(16)
        super().__init__(*args)

    def process_request(self,request,address):
        if not self.slots.acquire(timeout=self.request_wait_seconds):
            data=json.dumps({'error':BACKEND_UNAVAILABLE},separators=(',',':')).encode()
            try:
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\n'
                    b'Cache-Control: no-store\r\nRetry-After: 1\r\nConnection: close\r\nContent-Length: '+
                    str(len(data)).encode()+b'\r\n\r\n'+data)
            except OSError:
                pass  # A disconnected peer must not stop the listener.
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request,address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self,request,address):
        try:
            super().process_request_thread(request,address)
        finally:
            self.slots.release()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account-mount',type=Path,required=True)
    parser.add_argument('--socket',type=Path,required=True)
    parser.add_argument('--gm-host',required=True)
    parser.add_argument('--gn-host')
    parser.add_argument('--sec-host')
    args=parser.parse_args()
    os.umask(0o077)
    hosts = {args.gm_host:'gm'}
    if args.gn_host:
        hosts[args.gn_host] = 'gn'
    if args.sec_host:
        hosts[args.sec_host] = 'sec'
    gateway=Gateway(Accounts(args.account_mount),hosts)
    maintenance=threading.Thread(target=pump_forever,args=(gateway,),daemon=True)
    maintenance.start()
    # systemd owns RuntimeDirectory and removes the Unix socket on service stop.
    with Server(str(args.socket),handler_for(gateway)) as server:
        os.chmod(args.socket,0o660)
        server.serve_forever()


if __name__=='__main__':
    main()
