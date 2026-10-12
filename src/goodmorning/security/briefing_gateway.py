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
from urllib.parse import urlsplit, parse_qs
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
from goodmorning.web.avatar_images import AVATAR_UPLOAD_PATH, MAX_AVATAR_BYTES
from goodmorning.web.activity import ACTIVITY_PATH, panel as activity_panel

ASSETS = WEB_ASSETS
POLICY = "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
GET_ROUTES = re.compile(r'(?:/|/(?:index|gm|gn)\.html|/chat|/api/avatar(?:/image/[a-f0-9]{64}\.png)?|/api/chats(?:/[a-f0-9]{32})?|/api/day|/api/edition/\d{4}-\d{2}-\d{2}/(?:gm|gn)|/api/jobs/[a-f0-9]{32}(?:/preview)?|/d/\d{4}-\d{2}-\d{2}/(?:gm|gn)\.(?:html|json)|/media/(?:thumb-v1/)?[a-f0-9]{64}\.webp|/d/\d{4}-\d{2}-\d{2}/media/[a-f0-9]+\.webp|/(?:assets/[a-f0-9]{64}/)?desk-secretary(?:-f2|-m1|-m2)?\.png|/(?:assets/[a-f0-9]{64}/)?(?:briefing\.css|briefing\.js|browser\.js|questions\.js|chat\.js|chat\.css|avatar\.js|avatar\.css|fonts/(?:lora-italic\.woff2|OFL\.txt)))')
POST_ROUTES = re.compile(r'(?:/api/avatar(?:/upload)?|/api/(?:generate|regenerate)|/api/chat-uploads/[a-f0-9]{32}|/api/chats|/api/chats/[a-f0-9]{32}/(?:messages|(?:form|permission)/[A-Za-z0-9_]+/reply)|/api/jobs/[a-f0-9]{32}/(?:recover|(?:form|permission)/[A-Za-z0-9_]+/reply))')
QUEUE_KEY = 'generation_queue'
WAITING_KEY = 'generation_waiting'
MAX_QUEUE = 20
QUEUE_TTL = 900
QUEUE_FULL = 'The secretary queue is full. Please wait for earlier requests to finish.'
PUMP_INTERVAL = 5
PAGE_ROUTES = re.compile(r'(?:/|/(?:index|gm|gn)\.html|/chat|/d/\d{4}-\d{2}-\d{2}/(?:gm|gn)\.html)')
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


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):
        return None


class Gateway:
    def __init__(self, accounts, hosts, *, testing=False):
        if not (set(hosts.values()) == {'gm'} or {'gm','gn'} <= set(hosts.values()) <= {'gm','gn','sec'}) or any(not re.fullmatch('[a-z0-9.-]+',h) for h in hosts):
            raise ValueError('Configure a morning hostname or explicit morning, evening and optional secretary hostnames')
        self.accounts, self.hosts, self.testing = accounts, hosts, testing
        self.opener = build_opener(NoRedirect())
        self.icons = Resources(ASSETS, types={**ICON_TYPES,'language.js':'text/javascript','model.js':'text/javascript',
            'auth.js':'text/javascript','auth.css':'text/css','update.js':'text/javascript','update.css':'text/css',
            'activity.js':'text/javascript','activity.css':'text/css',
            'marked.js':'text/javascript','markdown.js':'text/javascript',
            'color-schemes.js':'text/javascript','color-schemes.css':'text/css'})
        self.html_cache = ByteCache(8 * 1024 * 1024, 32)
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

    def proxy(self, identifier, host, path, method, body, headers):
        backend = self.backend(identifier)
        parsed = urlsplit(path)
        if not ((POST_ROUTES if method=='POST' else GET_ROUTES).fullmatch(parsed.path) or
                (method in ('GET', 'HEAD') and IMAGE_ROUTE.fullmatch(parsed.path)) or
                method == 'GET' and re.fullmatch(ACTIVITY_PATH, parsed.path)):
            raise Denied('Not found')
        if parsed.path in ('/','/index.html'):
            path = '/chat' if self.hosts[host] == 'sec' else '/'+self.hosts[host]+'.html'
        forwarded = {'Authorization':'Bearer '+backend['key'],'X-GoodMorning-Origin':'https://'+host,
                     'X-GoodMorning-Language':self.accounts.website_language(identifier) or ui.current(),
                      'X-GoodMorning-Model':self.accounts.website_model(identifier) or site_models.DEFAULT}
        schemes = self.accounts.website_color_schemes(identifier) or site_colors.DEFAULT
        forwarded.update({'X-GoodMorning-Day-Scheme': schemes['day'], 'X-GoodMorning-Night-Scheme': schemes['night']})
        if body is not None:
            if UPLOAD_ROUTE.fullmatch(parsed.path) or parsed.path == AVATAR_UPLOAD_PATH:
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
            if not self._valid_queue_entry(entry) or entry['user'] != identifier or entry['host'] not in self.hosts:
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
        if current and not current.get('dispatching') and (current.get('job') or current.get('chat')):
            try:
                path = '/api/chats/' + current['chat'] if current.get('chat') else '/api/jobs/' + current['job']
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
                elif status == 200 and result.get('state') in terminal:
                    self.clear_ticket(current)
            except Exception:
                pass  # Uncertain work keeps its reservation. Never launch work blindly.

    @staticmethod
    def _valid_queue_entry(entry):
        if not isinstance(entry, dict) or entry.get('kind') not in ('chat', 'generate', 'regenerate', 'recover', 'reply'):
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
        return [entry for entry in queue
                if self._valid_queue_entry(entry) and (entry['kind'] == 'reply' or now - entry['enqueued'] < QUEUE_TTL)]

    def _reserve_or_queue(self, kind, candidate, path, body, language):
        """Atomically take the active slot or join the bounded global waiting line."""
        entry = {'kind': kind, 'candidate': candidate, 'user': candidate['user'], 'host': candidate['host'],
                 'path': path, 'body': body, 'language': language, 'enqueued': time.time()}
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
        try:
            raw = json.dumps(entry['body']).encode()
            status, upstream, data = self.proxy(entry['user'], entry['host'], entry['path'], 'POST', raw, {})
            candidate = entry['candidate']
            if entry['kind'] in ('generate', 'regenerate'):
                try:
                    result = json.loads(data)
                except (TypeError, ValueError):
                    result = {}
                if status < 300 and re.fullmatch('[a-f0-9]{32}', result.get('job', '')):
                    updated = {**candidate, 'job': result['job']}
                    with self.accounts.db() as db:
                        db.execute('UPDATE metadata SET value=? WHERE key=? AND value=?',
                                   (json.dumps(updated, separators=(',', ':')), 'generation', json.dumps(candidate, separators=(',', ':'))))
                elif status < 500:
                    self.clear_ticket(candidate)
            elif 400 <= status < 500:
                self.clear_ticket(candidate)
            elif status < 300:
                self.confirm_dispatch(candidate)
            return status
        finally:
            ui.CURRENT.reset(token)

    def pump_queue(self):
        """Advance the global waiting line while the active slot is free."""
        self.reconcile_ticket()
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
                if entry.get('user') != identifier:
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
                        and current.get('chat') == chat):
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
        created = action == 'active_new'
        status, upstream, data = self.proxy(identifier, host, path, 'POST', raw, headers)
        if created and 400 <= status < 500:
            self.clear_ticket(candidate)
        elif created and status < 300:
            self.confirm_dispatch(candidate)
        return status, upstream, data

    def generate(self,identifier,host,raw,headers, *, regenerate=False):
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
        action, position, depth = self._reserve_or_queue(work, candidate, path, body, language)
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
        status,upstream,data=self.proxy(identifier,host,path,'POST',raw,headers)
        result=json.loads(data)
        if status<300 and re.fullmatch('[a-f0-9]{32}',result.get('job','')):
            updated={**candidate,'job':result['job']}
            with self.accounts.db() as db:
                db.execute('UPDATE metadata SET value=? WHERE key=? AND value=?',
                           (json.dumps(updated,separators=(',',':')),'generation',json.dumps(candidate,separators=(',',':'))))
        elif status<500:
            self.clear_ticket(candidate)
        if status < 300:
            self.reconcile_ticket()
        return status,upstream,data

    def input_reply(self, identifier, host, path, raw, headers):
        match = re.fullmatch(r'/api/(jobs|chats)/([a-f0-9]{32})/(form|permission)/([A-Za-z0-9_]+)/reply', path)
        collection, target, category, request = match.groups()
        key = 'job' if collection == 'jobs' else 'chat'
        status, _, data = self.proxy(identifier, host, '/api/'+collection+'/'+target, 'GET', None, {})
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
            '<title>'+html.escape(title)+'</title><link rel="stylesheet" href="/auth.css"></head><body><main class="account-card">'
            '<p class="eyebrow">Your personal secretary</p><h1>'+html.escape(title)+'</h1><p>'+note+'</p>'+
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

        def respond(self,data,status=200,mime='application/json',*,token=None,cookie_age=SESSION_SECONDS,location=None,cache='no-store',etag=None,language_cookie=None,color_cookie=None,resource=None):
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
            policy = POLICY.replace("img-src 'self'", "img-src 'self' blob:") if mime.startswith('text/html') and b'id="chat-config"' in data else POLICY
            self.send_header('Content-Security-Policy',policy)
            self.send_header('X-Content-Type-Options','nosniff')
            # Native same-origin forms need a non-null Origin for strict CSRF checks.
            # This policy still sends no referrer to external sites.
            self.send_header('Referrer-Policy','same-origin' if mime.startswith('text/html') else 'no-referrer')
            self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
            self.send_header('Strict-Transport-Security','max-age=31536000')
            if encoded:
                self.send_header('Content-Encoding','gzip')
            if location:
                self.send_header('Location',location)
            if etag:
                self.send_header('ETag',etag)
            if token is not None:
                self.send_header('Set-Cookie',f'{COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={cookie_age if token else 0}')
            if language_cookie is not None:
                value=ui.language(language_cookie)
                domain='; Domain='+gateway.language_domain if gateway.language_domain else ''
                self.send_header('Set-Cookie','GoodMorningLanguage='+value+'; Path=/; Secure; SameSite=Lax; Max-Age=31536000'+domain)
            if color_cookie is not None:
                value = site_colors.validate(color_cookie)['day']
                domain = '; Domain='+gateway.language_domain if gateway.language_domain else ''
                self.send_header('Set-Cookie', 'GoodMorningDayScheme='+value+'; Path=/; Secure; SameSite=Lax; Max-Age=31536000'+domain)
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

        def select_language(self,session=None):
            selected=(gateway.accounts.website_language(session['user_id']) or 'en') if session and session.get('user_id') else self.browser_language()
            ui.CURRENT.set(selected)
            if session and session.get('user_id'):
                colors = gateway.accounts.website_color_schemes(session['user_id']) or site_colors.DEFAULT
            else:
                try:
                    cookie = SimpleCookie(); cookie.load(self.headers.get('Cookie', '')[:4096])
                    colors = site_colors.validate({'day': cookie['GoodMorningDayScheme'].value, 'night': 'classic'})
                except (KeyError, ValueError, CookieError):
                    colors = site_colors.DEFAULT
            site_colors.CURRENT.set(dict(colors))

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

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            session = None
            host = None
            try:
                host=self.host()
                self.select_language()
                path=urlsplit(self.path).path
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
                try:
                    session=self.session(host)
                except Denied:
                    if path=='/api/release/seen':return self.respond({'version':None,'enabled':False})
                    if path=='/api/language':return self.respond({'language':ui.current()})
                    if path=='/api/model':return self.respond({'model':site_models.DEFAULT})
                    if path=='/api/color-schemes':return self.respond(site_colors.current())
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
                if path=='/api/model':return self.respond({'model':gateway.accounts.website_model(session['user_id']) or site_models.DEFAULT})
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
                if path=='/api/queue':
                    return self.respond(gateway.queue_status(session['user_id']))
                if path=='/api/activity':
                    return self.respond(gateway.activity(session['user_id']))
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
                    controls='<nav class="account-tools" aria-label="Account"><a href="/password">Change password</a><button id="sign-out" data-csrf="'+session['csrf']+'">Sign out</button></nav><script src="/auth.js" defer></script>'
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
            except Exception as error:
                # Exception text can contain credentials, private paths or response bodies.
                logging.getLogger(__name__).warning('Secretary read failed (%s)',type(error).__name__)
                return self.unavailable(session,host)

        def do_POST(self):
            try:
                host=self.host()
                self.select_language()
                if self.headers.get('Origin')!='https://'+host or self.headers.get('Sec-Fetch-Site','same-origin')!='same-origin':
                    raise Denied('Forbidden')
                session=self.session(host)
                self.select_language(session)
                path=urlsplit(self.path).path
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1:
                    raise ValueError('Invalid request body')
                size=int(self.headers['Content-Length'])
                if UPLOAD_ROUTE.fullmatch(path) or path == AVATAR_UPLOAD_PATH:
                    if not session['user_id'] or session['temporary']:
                        raise Denied('Sign in with a permanent password before uploading')
                    if not secrets.compare_digest(self.headers.get('X-Briefing-CSRF', ''), session['csrf']):
                        raise Denied('Forbidden')
                    avatar_upload = path == AVATAR_UPLOAD_PATH
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
                    if path=='/api/color-schemes':expected={'csrf','day','night','return_to'}
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
                    if not form and set(body)!={'model'}:raise ValueError('Invalid model choice')
                    selected=site_models.model(body['model'])
                    if session['user_id']:gateway.accounts.website_model(session['user_id'],selected)
                    site_models.CURRENT.set(selected)
                    target=body.get('return_to','/')
                    if form and (len(target)>2048 or any(ord(c)<32 for c in target) or '\\' in target or urlsplit(target).netloc or urlsplit(target).scheme or not (GET_ROUTES.fullmatch(urlsplit(target).path) or target in ('/login','/password'))):target='/'
                    return self.respond({'model':selected},303 if form else 200,location=target if form else None)
                if path=='/api/color-schemes':
                    selected = site_colors.validate({key: body[key] for key in ('day', 'night')} if form else body)
                    if session['user_id']:gateway.accounts.website_color_schemes(session['user_id'], selected)
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
            except (ValueError,KeyError,TypeError):
                route=urlsplit(self.path).path
                error='Invalid upload' if UPLOAD_ROUTE.fullmatch(route) else 'Invalid release version' if route=='/api/release/seen' else 'Choose English or Simplified Chinese' if route=='/api/language' else 'Choose one of the offered website models' if route=='/api/model' else 'Choose one of the offered color schemes' if route=='/api/color-schemes' else 'Invalid request. '+PASSWORD_RULE
                return self.respond({'error':error},400)
            except Exception:
                return self.respond({'error':'Request could not be confirmed. Refresh before retrying.'},503)
    return Handler


class Server(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):
    daemon_threads=True
    def __init__(self,*args):
        self.slots=threading.BoundedSemaphore(16)
        super().__init__(*args)

    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            request.close()
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
