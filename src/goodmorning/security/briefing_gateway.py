"""Authenticated HTTPS gateway behind NGINX; production listens on a Unix socket only."""
import argparse
import gzip
import hashlib
import html
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import re
import secrets
import socketserver
import threading
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

from .briefing_accounts import Accounts, COOKIE, Denied, Limited, SESSION_SECONDS, REMEMBER_SECONDS, PASSWORD_MIN, PASSWORD_MAX, PASSWORD_RULE
from goodmorning.web.briefing_resources import accepts_gzip, Resources, ICON_TYPES, favicon_links
from goodmorning.paths import WEB_ASSETS

ASSETS = WEB_ASSETS
AUTH_VERSION = hashlib.sha256((ASSETS/'auth.js').read_bytes()+(ASSETS/'auth.css').read_bytes()).hexdigest()[:16]
POLICY = "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
GET_ROUTES = re.compile(r'(?:/|/(?:index|gm|gn)\.html|/chat|/api/chats(?:/[a-f0-9]{32})?|/api/day|/api/edition/\d{4}-\d{2}-\d{2}/(?:gm|gn)|/api/jobs/[a-f0-9]{32}(?:/preview)?|/d/\d{4}-\d{2}-\d{2}/(?:gm|gn)\.(?:html|json)|/media/(?:thumb-v1/)?[a-f0-9]{64}\.webp|/d/\d{4}-\d{2}-\d{2}/media/[a-f0-9]+\.webp|/(?:assets/[a-f0-9]{64}/)?(?:briefing\.css|briefing\.js|browser\.js|questions\.js|chat\.js|chat\.css|fonts/(?:lora-italic\.woff2|OFL\.txt)))')
POST_ROUTES = re.compile(r'(?:/api/generate|/api/chats|/api/chats/[a-f0-9]{32}/(?:messages|(?:form|permission)/[A-Za-z0-9_]+/reply)|/api/jobs/[a-f0-9]{32}/(?:recover|(?:form|permission)/[A-Za-z0-9_]+/reply))')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):
        return None


class Gateway:
    def __init__(self, accounts, hosts, *, testing=False):
        if not {'gm','gn'} <= set(hosts.values()) <= {'gm','gn','sec'} or any(not re.fullmatch('[a-z0-9.-]+',h) for h in hosts):
            raise ValueError('Configure explicit morning, evening and optional secretary hostnames')
        self.accounts, self.hosts, self.testing = accounts, hosts, testing
        self.opener = build_opener(NoRedirect())
        self.icons = Resources(ASSETS, types=ICON_TYPES)

    def backend(self, identifier):
        # No username/path/URL from the browser selects another account's backend.
        self.accounts.check()
        path = self.accounts.directory/'backends.json'
        if path.is_symlink() or path.stat().st_size>100_000:
            raise ValueError('Invalid private backend registry')
        registry = json.loads(path.read_text())
        entry = registry.get(identifier)
        if not isinstance(entry,dict) or set(entry) != {'port','key'}:
            raise ValueError('This account is not connected to a secretary yet')
        if type(entry['port']) is not int or not 1024 <= entry['port'] <= 65535 or not re.fullmatch('[A-Za-z0-9_-]{43}',entry['key']):
            raise ValueError('Invalid private backend configuration')
        return entry

    def proxy(self, identifier, host, path, method, body, headers):
        backend = self.backend(identifier)
        parsed = urlsplit(path)
        if not (POST_ROUTES if method=='POST' else GET_ROUTES).fullmatch(parsed.path):
            raise Denied('Not found')
        if parsed.path in ('/','/index.html'):
            path = '/chat' if self.hosts[host] == 'sec' else '/'+self.hosts[host]+'.html'
        forwarded = {'Authorization':'Bearer '+backend['key'],'X-GoodMorning-Origin':'https://'+host}
        if body is not None:
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
            data=response.read(4_000_001)
            if len(data)>4_000_000:
                raise ValueError('Secretary response exceeds its limit')
            return response.status,dict(response.headers),data

    def ticket(self):
        with self.accounts.db() as db:
            row=db.execute('SELECT value FROM metadata WHERE key=?',('generation',)).fetchone()
            return json.loads(row[0]) if row else None

    def clear_ticket(self,ticket):
        with self.accounts.db() as db:
            db.execute('DELETE FROM metadata WHERE key=? AND value=?',('generation',json.dumps(ticket,separators=(',',':'))))

    def reconcile_ticket(self):
        current = self.ticket()
        if current and (current.get('job') or current.get('chat')):
            try:
                path = '/api/chats/' + current['chat'] if current.get('chat') else '/api/jobs/' + current['job']
                status, _, data = self.proxy(current['user'], current['host'], path, 'GET', None, {})
                terminal = ('idle',) if current.get('chat') else ('ready', 'stopped')
                if status == 200 and json.loads(data).get('state') in terminal:
                    self.clear_ticket(current)
            except Exception:
                pass  # Uncertain work keeps its reservation. Never launch work blindly.

    def chat_message(self, identifier, host, path, raw, headers):
        from goodmorning.web.briefing_chat import identifier as chat_id, message, MODES
        body = json.loads(raw)
        if path == '/api/chats':
            if set(body) != {'id', 'mode', 'text'} or body['mode'] not in MODES:
                raise ValueError('Invalid secretary mode')
            chat = chat_id(body['id'])
        else:
            if set(body) != {'id', 'text'}:
                raise ValueError('Invalid conversation message')
            chat = re.fullmatch(r'/api/chats/([a-f0-9]{32})/messages', path)[1]
        request = chat_id(body['id'])
        message(body['text'])
        candidate = {'user': identifier, 'host': host, 'chat': chat, 'request': request}
        self.reconcile_ticket()
        created = False
        with self.accounts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value FROM metadata WHERE key=?', ('generation',)).fetchone()
            if row:
                current = json.loads(row[0])
                if current != candidate:
                    return 409, {'Content-Type': 'application/json'}, b'{"error":"The secretary is busy with another request. Try again after it finishes."}'
                # The backend verifies duplicate payloads without dispatching them again.
            else:
                db.execute('INSERT INTO metadata VALUES (?,?)', ('generation', json.dumps(candidate, separators=(',', ':'))))
                created = True
        status, upstream, data = self.proxy(identifier, host, path, 'POST', raw, headers)
        if created and 400 <= status < 500:
            self.clear_ticket(candidate)
        return status, upstream, data

    def generate(self,identifier,host,raw,headers):
        body=json.loads(raw)
        if set(body)!={'date','kind'} or not isinstance(body['date'],str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',body['date']) or body['kind'] not in ('gm','gn'):
            raise ValueError('Invalid generation request')
        self.reconcile_ticket()
        candidate={'user':identifier,'host':host,'date':body.get('date'),'kind':body.get('kind')}
        with self.accounts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT value FROM metadata WHERE key=?',('generation',)).fetchone()
            if row:
                current=json.loads(row[0])
                if {k:current.get(k) for k in candidate}!=candidate:
                    return 409,{'Content-Type':'application/json'},b'{"error":"Another briefing is being prepared. Try again after it finishes."}'
                if not current.get('job'):
                    return 409,{'Content-Type':'application/json'},b'{"error":"A generation request needs administrator reconciliation before retrying."}'
                return 202,{'Content-Type':'application/json'},json.dumps({'job':current['job']}).encode()
            db.execute('INSERT INTO metadata VALUES (?,?)',('generation',json.dumps(candidate,separators=(',',':'))))
        status,upstream,data=self.proxy(identifier,host,'/api/generate','POST',raw,headers)
        result=json.loads(data)
        if status<300 and re.fullmatch('[a-f0-9]{32}',result.get('job','')):
            updated={**candidate,'job':result['job']}
            with self.accounts.db() as db:
                db.execute('UPDATE metadata SET value=? WHERE key=? AND value=?',
                           (json.dumps(updated,separators=(',',':')),'generation',json.dumps(candidate,separators=(',',':'))))
        elif status<500:
            self.clear_ticket(candidate)
        return status,upstream,data

    def recover(self, identifier, host, path, raw, headers):
        body = json.loads(raw)
        if set(body) != {'id'} or not isinstance(body['id'], str) or not re.fullmatch('[a-f0-9]{32}', body['id']):
            raise ValueError('Invalid recovery request')
        job = re.fullmatch(r'/api/jobs/([a-f0-9]{32})/recover', path)[1]
        candidate = {'user':identifier, 'host':host, 'job':job, 'request':body['id']}
        self.reconcile_ticket()
        observed = self.ticket()
        refreshable = False
        if observed and all(observed.get(k) == candidate[k] for k in ('user','host','job')) and observed.get('request') != body['id']:
            status, _, data = self.proxy(identifier, host, '/api/jobs/'+job, 'GET', None, {})
            refreshable = status == 200 and json.loads(data).get('recovery') == 'Refresh task list'
        with self.accounts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT value FROM metadata WHERE key='generation'").fetchone()
            previous = json.loads(row[0]) if row else None
            if row:
                current = json.loads(row[0])
                if any(current.get(k) != candidate[k] for k in ('user', 'host', 'job')):
                    return 409, {'Content-Type':'application/json'}, b'{"error":"The secretary is busy with another request."}'
                if current.get('request') == body['id']:
                    return 202, {'Content-Type':'application/json'}, json.dumps({'job':job}).encode()
                # Only an undispatched preflight can replace its own reservation.
                if current != observed or not refreshable:
                    return 409, {'Content-Type':'application/json'}, b'{"error":"Refresh status before trying recovery again."}'
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('generation', json.dumps(candidate, separators=(',',':'))))
        status, upstream, data = self.proxy(identifier, host, path, 'POST', raw, headers)
        if 400 <= status < 500:
            if previous:
                with self.accounts.db() as db:
                    db.execute('UPDATE metadata SET value=? WHERE key=? AND value=?',
                               (json.dumps(previous,separators=(',',':')),'generation',json.dumps(candidate,separators=(',',':'))))
            else:
                self.clear_ticket(candidate)
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
            '<title>'+html.escape(title)+'</title><link rel="stylesheet" href="/auth.css?v='+AUTH_VERSION+'"></head><body><main class="account-card">'
            '<p class="eyebrow">Your personal secretary</p><h1>'+html.escape(title)+'</h1><p>'+note+'</p>'+
            ('' if login else '<p id="password-rules">'+PASSWORD_RULE+'</p>')+
            '<form id="account-form" data-action="'+('login' if login else 'password')+'" data-csrf="'+session['csrf']+'" '
            'data-password-min="'+str(PASSWORD_MIN)+'" data-password-max="'+str(PASSWORD_MAX)+'">'+fields+
            '<button type="submit">'+('Sign in' if login else 'Change password')+'</button></form><p id="account-error" role="alert"></p>'+
            ('' if login or temporary else '<a href="/">Back to briefing</a>')+
            '<script src="/auth.js?v='+AUTH_VERSION+'" defer></script></main></body></html>').encode()


def handler_for(gateway):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'GoodMorning'

        def log_message(self,*_):
            pass  # Never log paths, passwords, answers, cookies or rendered briefings.

        def setup(self):
            super().setup()
            self.connection.settimeout(25)

        def respond(self,data,status=200,mime='application/json',*,token=None,cookie_age=SESSION_SECONDS,location=None,cache='no-store',etag=None):
            if not isinstance(data,bytes):
                data=json.dumps(data,separators=(',',':')).encode()
            encoded=bool(data) and accepts_gzip(self.headers.get('Accept-Encoding','')) and mime.startswith(('text/','application/json'))
            if encoded:
                data=gzip.compress(data,mtime=0)
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control',cache)
            self.send_header('Vary','Accept-Encoding')
            self.send_header('Content-Security-Policy',POLICY)
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
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
            except (KeyError,ValueError):
                raise Denied('Login required')

        def address(self):
            value=self.headers.get('X-Real-IP','')
            import ipaddress
            return str(ipaddress.ip_address(value))  # NGINX overwrites it, never trusts clients.

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            try:
                host=self.host()
                path=urlsplit(self.path).path
                resource=gateway.icons.paths.get(path) or gateway.icons.alias(path)
                if resource:
                    cached=self.headers.get('If-None-Match')==resource.etag
                    return self.respond(b'' if cached else resource.data,304 if cached else 200,resource.mime,
                                        cache='public, max-age=31536000, immutable' if path in gateway.icons.paths else 'public, max-age=3600',etag=resource.etag)
                if path in ('/auth.css','/auth.js'):
                    data=(ASSETS/path.lstrip('/')).read_bytes()
                    return self.respond(data,mime='text/css' if path.endswith('css') else 'text/javascript',cache='public, max-age=3600')
                try:
                    session=self.session(host)
                except Denied:
                    if path!='/login':
                        return self.respond({'error':'Login required'},401) if path.startswith('/api/') else self.respond(b'',302,location='/login')
                    gateway.accounts.limit([('prelogin-ip:'+self.address(),60)])
                    token,csrf=gateway.accounts.anonymous(host)
                    return self.respond(gateway.icons.rewrite(account_page({'csrf':csrf},'Sign in',gateway.hosts[host]).decode()).encode(),mime='text/html; charset=utf-8',token=token,cookie_age=600)
                if path=='/login' and not session['user_id']:
                    return self.respond(gateway.icons.rewrite(account_page(session,'Sign in',gateway.hosts[host]).decode()).encode(),mime='text/html; charset=utf-8')
                if not session['user_id']:
                    return self.respond({'error':'Login required'},401) if path.startswith('/api/') else self.respond(b'',302,location='/login')
                if path=='/password' or session['temporary']:
                    if path!='/password':
                        return self.respond({'error':'Password change required'},403) if path.startswith('/api/') else self.respond(b'',302,location='/password')
                    return self.respond(gateway.icons.rewrite(account_page(session,'Change password',gateway.hosts[host]).decode()).encode(),mime='text/html; charset=utf-8')
                if path=='/login':
                    return self.respond(b'',302,location='/')
                status,headers,data=gateway.proxy(session['user_id'],host,self.path,'GET',None,self.headers)
                mime=headers.get('Content-Type','application/json')
                if mime.startswith('text/html'):
                    # Replace backend-wide CSRF with the authenticated session's CSRF.
                    text=data.decode()
                    text=re.sub(r'(&quot;csrf&quot;:\s*&quot;)[A-Za-z0-9_-]{43}(&quot;)',r'\g<1>'+session['csrf']+r'\g<2>',text)
                    controls='<nav class="account-tools" aria-label="Account"><a href="/password">Change password</a><button id="sign-out" data-csrf="'+session['csrf']+'">Sign out</button></nav><script src="/auth.js?v='+AUTH_VERSION+'" defer></script>'
                    data=text.replace('</body>',controls+'</body>').encode()
                # Personal pages/media never enter durable browser or shared proxy caches.
                static=path.startswith('/assets/')
                return self.respond(data,status,mime,cache=headers.get('Cache-Control','no-store') if static else 'no-store',etag=headers.get('ETag') if static else None)
            except Limited as error:
                return self.respond({'error':str(error)},429)
            except Denied:
                return self.respond({'error':'Forbidden'},403)
            except Exception:
                return self.respond({'error':'Secretary temporarily unavailable; records are unchanged'},503)

        def do_POST(self):
            try:
                host=self.host()
                if self.headers.get('Origin')!='https://'+host or self.headers.get('Sec-Fetch-Site','same-origin')!='same-origin':
                    raise Denied('Forbidden')
                session=self.session(host)
                if not secrets.compare_digest(self.headers.get('X-Briefing-CSRF',''),session['csrf']):
                    raise Denied('Forbidden')
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[]))!=1:
                    raise ValueError('Invalid request body')
                size=int(self.headers['Content-Length'])
                if not 0<size<=20000 or self.headers.get('Content-Type')!='application/json':
                    raise ValueError('Invalid request body')
                raw=self.rfile.read(size)
                if len(raw)!=size:
                    raise ValueError('Incomplete request')
                body=json.loads(raw)
                if not isinstance(body,dict):
                    raise ValueError('A JSON object is required')
                path=urlsplit(self.path).path
                if path=='/api/auth/login' and not session['user_id']:
                    if set(body) not in ({'username','password'},{'username','password','remember'}) or type(body.get('remember',False)) is not bool:
                        raise ValueError('Invalid login')
                    remember=body.get('remember',False)
                    token,csrf,temporary=gateway.accounts.login(body['username'],body['password'],host,self.address(),session,remember=remember)
                    return self.respond({'next':'/password' if temporary else '/'},token=token,cookie_age=REMEMBER_SECONDS if remember else SESSION_SECONDS)
                if not session['user_id']:
                    raise Denied('Login required')
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
                if path=='/api/generate':
                    status,headers,data=gateway.generate(session['user_id'],host,raw,self.headers)
                elif re.fullmatch(r'/api/jobs/[a-f0-9]{32}/recover', path):
                    status,headers,data=gateway.recover(session['user_id'],host,path,raw,self.headers)
                elif path == '/api/chats' or re.fullmatch(r'/api/chats/[a-f0-9]{32}/messages', path):
                    status,headers,data=gateway.chat_message(session['user_id'],host,path,raw,self.headers)
                else:
                    status,headers,data=gateway.proxy(session['user_id'],host,self.path,'POST',raw,self.headers)
                return self.respond(data,status,headers.get('Content-Type','application/json'))
            except Limited as error:
                return self.respond({'error':str(error)},429)
            except Denied as error:
                return self.respond({'error':str(error)},403)
            except (ValueError,KeyError,TypeError):
                return self.respond({'error':'Invalid request. '+PASSWORD_RULE},400)
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
    parser.add_argument('--gn-host',required=True)
    parser.add_argument('--sec-host')
    args=parser.parse_args()
    os.umask(0o077)
    hosts = {args.gm_host:'gm',args.gn_host:'gn'}
    if args.sec_host:
        hosts[args.sec_host] = 'sec'
    gateway=Gateway(Accounts(args.account_mount),hosts)
    # systemd owns RuntimeDirectory and removes the Unix socket on service stop.
    with Server(str(args.socket),handler_for(gateway)) as server:
        os.chmod(args.socket,0o660)
        server.serve_forever()


if __name__=='__main__':
    main()
