"""Public request boundaries and private account routing with synthetic data."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from support import TEMP_ROOT
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning.security.briefing_accounts import Accounts, COOKIE, REMEMBER_SECONDS, SESSION_SECONDS
from goodmorning.security.briefing_gateway import Gateway, handler_for


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args): return None


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=TEMP_ROOT);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=Accounts(self.root,testing=True,n=1024)
        self.id=self.store.create('alice','temporary-alice-secret1')
        self.other=self.store.create('bob','temporary-bob-secret1')
        self.received=[]
        received=self.received
        class Backend(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append((self.path,dict(self.headers)))
                self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers()
                self.wfile.write(('<body><div data-config="{&quot;csrf&quot;: &quot;'+('a'*43)+'&quot;}"></div>Alice private record</body>').encode())
            def do_POST(self):
                received.append((self.path,dict(self.headers)))
                self.send_response(202);self.end_headers();self.wfile.write(b'{"accepted":true}')
            def log_message(self,*_): pass
        self.backend=ThreadingHTTPServer(('127.0.0.1',0),Backend)
        self.serve(self.backend)
        self.key=secrets.token_urlsafe(32)
        (self.root/'backends.json').write_text(json.dumps({self.id:{'port':self.backend.server_port,'key':self.key}}))
        self.gateway=Gateway(self.store,{'gm.example.test':'gm','gn.example.test':'gn'},testing=True)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.gateway))
        self.serve(self.server)
        self.opener=build_opener(NoRedirect())
        self.cookie=None
        self.csrf=None

    def serve(self,server):
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)

    def request(self,path='/',body=None,*,headers=None,method=None):
        values={'Host':'gm.example.test','X-Forwarded-Proto':'https','X-Real-IP':'192.0.2.1'}
        if self.cookie: values['Cookie']=self.cookie
        if body is not None:
            values.update({'Origin':'https://gm.example.test','Content-Type':'application/json','X-Briefing-CSRF':self.csrf or ''})
        values.update(headers or {})
        raw=json.dumps(body).encode() if body is not None else None
        try:
            response=self.opener.open(Request(f'http://127.0.0.1:{self.server.server_port}'+path,data=raw,headers=values,method=method),timeout=3)
        except HTTPError as error: response=error
        with response:
            content=response.read()
            return response.status,dict(response.headers),content

    def login(self,remember=False):
        status,headers,content=self.request('/login')
        self.assertEqual(status,200)
        self.cookie=headers['Set-Cookie'].split(';')[0]
        self.csrf=re.search(b'data-csrf="([a-f0-9]+)"',content)[1].decode()
        status,headers,_=self.request('/api/auth/login',{'username':'alice','password':'temporary-alice-secret1','remember':remember})
        self.assertEqual(status,200)
        self.assertIn('Max-Age='+str(REMEMBER_SECONDS if remember else SESSION_SECONDS),headers['Set-Cookie'])
        self.cookie=headers['Set-Cookie'].split(';')[0]
        return self.store.session(self.cookie.split('=',1)[1],'gm.example.test')

    def permanent(self):
        self.login()
        _,_,content=self.request('/password')
        self.csrf=re.search(b'data-csrf="([a-f0-9]+)"',content)[1].decode()
        status,headers,_=self.request('/api/auth/password',{'current':'temporary-alice-secret1','replacement':'permanent-alice-secret1'})
        self.assertEqual(status,200)
        self.cookie=headers['Set-Cookie'].split(';')[0]
        self.csrf=self.store.session(self.cookie.split('=',1)[1],'gm.example.test')['csrf']

    def test_recovery_uses_global_reservation_and_never_replays_duplicate(self):
        job='a'*32;path='/api/jobs/'+job+'/recover';raw=json.dumps({'id':'b'*32}).encode()
        with patch.object(self.gateway,'proxy',return_value=(202,{},json.dumps({'job':job}).encode())) as proxy:
            self.assertEqual(self.gateway.recover(self.id,'gm.example.test',path,raw,{})[0],202)
            self.assertEqual(self.gateway.ticket()['user'],self.id)
            self.assertEqual(self.gateway.recover(self.id,'gm.example.test',path,raw,{})[0],202)
            self.assertEqual(sum(call.args[3]=='POST' for call in proxy.call_args_list),1)
            self.assertEqual(self.gateway.recover(self.other,'gm.example.test',path,raw,{})[0],409)
        with patch.object(self.gateway,'proxy',return_value=(200,{},b'{"state":"waiting","recovery":"Refresh task list","recovery_action":"refresh"}')):
            self.assertEqual(self.gateway.recover(self.id,'gm.example.test',path,json.dumps({'id':'c'*32}).encode(),{})[0],200)
        self.assertEqual(self.gateway.ticket()['request'],'c'*32)
        def rejected(*args):
            return (400,{},b'{"error":"Feedback requires reconciliation"}') if args[3]=='POST' else (200,{},b'{"state":"waiting","recovery":"Refresh task list","recovery_action":"refresh"}')
        with patch.object(self.gateway,'proxy',side_effect=rejected):
            self.assertEqual(self.gateway.recover(self.id,'gm.example.test',path,json.dumps({'id':'d'*32}).encode(),{})[0],400)
        self.assertEqual(self.gateway.ticket()['request'],'c'*32)

    def test_no_private_route_or_generation_before_login(self):
        for path in ('/','/d/2026-10-11/gm.json','/media/'+('a'*64)+'.webp'):
            self.assertEqual(self.request(path)[0],302)
        self.assertEqual(self.request('/api/jobs/'+('a'*32))[0],401)
        self.assertEqual(self.request('/api/generate',{'date':'2026-10-11','kind':'gm'})[0],403)
        self.assertEqual(self.received,[])

    def test_public_icons_match_each_host_without_exposing_private_routes(self):
        self.gateway.hosts['sec.example.test']='sec'
        for host,kind in (('gm.example.test','gm'),('gn.example.test','gn'),('sec.example.test','secretary')):
            status,_,page=self.request('/login',headers={'Host':host})
            self.assertEqual(status,200)
            links=re.findall(rb'<link rel="icon"[^>]+href="([^"]+)"',page)
            self.assertEqual(len(links),2)
            for link in links:
                path=link.decode()
                self.assertIn('/icons/'+kind+'.',path)
                status,headers,data=self.request(path,headers={'Host':host})
                self.assertEqual(status,200)
                self.assertIn('immutable',headers['Cache-Control'])
                if path.endswith('.png'):
                    self.assertEqual(headers['Content-Type'],'image/png')
                    self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
                else:
                    self.assertEqual(headers['Content-Type'],'image/svg+xml')
                    self.assertIn(b'<svg',data)
                self.assertEqual(self.request(path,headers={'Host':host,'If-None-Match':headers['ETag']})[0],304)
                self.assertEqual(self.request(path,headers={'Host':host},method='HEAD')[2],b'')
        self.assertEqual(self.received,[])
        self.assertEqual(self.request('/icons/../accounts.sqlite')[0],302)
        self.assertEqual(self.request('/icons/gm.svg',headers={'Host':'evil.test'})[0],403)

    def test_login_cookie_and_initial_password_gate(self):
        session=self.login()
        self.assertTrue(session['temporary'])
        self.assertEqual(self.request('/')[1]['Location'],'/password')
        self.csrf=session['csrf']
        self.assertEqual(self.request('/api/generate',{})[0],403)
        _,headers,_=self.request('/login',headers={'Cookie':''})
        cookie=headers['Set-Cookie']
        for value in ('Secure','HttpOnly','SameSite=Strict','Path=/'): self.assertIn(value,cookie)
        self.assertNotIn('Domain=',cookie)
        self.assertEqual(self.received,[])

    def test_remembered_login_cookie_survives_password_replacement(self):
        session=self.login(remember=True)
        self.csrf=session['csrf']
        status,headers,_=self.request('/api/auth/password',{'current':'temporary-alice-secret1','replacement':'permanent-alice-secret1'})
        self.assertEqual(status,200)
        cookie=headers['Set-Cookie']
        for value in ('Secure','HttpOnly','SameSite=Strict','Max-Age='+str(REMEMBER_SECONDS)):
            self.assertIn(value,cookie)
        self.assertNotIn('Domain=',cookie)
        self.assertEqual(self.store.session(cookie.split(';')[0].split('=',1)[1],'gm.example.test')['remembered'],1)

    def test_password_controls_and_cache_versioned_assets(self):
        _,_,page=self.request('/login')
        self.assertIn(b'data-password-target="password-password"',page)
        self.assertIn(b'aria-pressed="false"',page)
        self.assertIn(b'name="remember"',page)
        self.assertNotIn(b'checked',page)
        versions=re.findall(rb'/auth\.(?:css|js)\?v=([a-f0-9]{16})',page)
        self.assertEqual(len(versions),2)
        self.assertEqual(versions[0],versions[1])
        self.login()
        _,_,page=self.request('/password')
        for name in ('current','replacement','repeat'):
            self.assertIn(('data-password-target="password-'+name+'"').encode(),page)

    def test_non_boolean_remember_is_rejected(self):
        _,headers,content=self.request('/login')
        self.cookie=headers['Set-Cookie'].split(';')[0]
        self.csrf=re.search(b'data-csrf="([a-f0-9]+)"',content)[1].decode()
        self.assertEqual(self.request('/api/auth/login',{'username':'alice','password':'temporary-alice-secret1','remember':'false'})[0],400)
        self.assertEqual(self.received,[])

    def test_account_scoped_backend_and_csrf_translation(self):
        self.permanent()
        status,headers,content=self.request('/')
        self.assertEqual(status,200)
        self.assertIn(self.csrf.encode(),content)
        self.assertNotIn(('a'*43).encode(),content)
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(self.received[-1][0],'/gm.html')
        upstream=self.received[-1][1]
        self.assertEqual(upstream['Authorization'],'Bearer '+self.key)
        self.assertNotIn('Cookie',upstream)
        self.assertEqual(self.request('/api/generate',{'date':'2026-10-11','kind':'gm'})[0],202)

    def test_secretary_host_maps_root_to_chat_with_separate_host_cookie(self):
        self.gateway.hosts['sec.example.test']='sec'
        self.permanent()
        headers={'Host':'sec.example.test'}
        self.assertEqual(self.request('/',headers=headers)[0],302)
        token,csrf=self.store.anonymous('sec.example.test')
        pre=self.store.session(token,'sec.example.test')
        token,_,_=self.store.login('alice','permanent-alice-secret1','sec.example.test','192.0.2.3',pre)
        self.cookie=COOKIE+'='+token
        status,_,page=self.request('/',headers=headers)
        self.assertEqual(status,200)
        self.assertIn(b'Alice private record',page)
        self.assertEqual(self.received[-1][0],'/chat')
        self.assertEqual({key.lower():value for key,value in self.received[-1][1].items()}['x-goodmorning-origin'],'https://sec.example.test')
        self.assertEqual(self.request('/')[0],302)

    def test_cross_origin_missing_csrf_and_sibling_cookie_are_rejected(self):
        self.permanent()
        count=len(self.received)
        for headers in ({'Origin':'https://evil.test'},{'X-Briefing-CSRF':'wrong'}, {'Sec-Fetch-Site':'cross-site'}, {'Host':'gn.example.test'}):
            self.assertEqual(self.request('/api/generate',{},headers=headers)[0],403)
        self.assertEqual(count,len(self.received))

    def test_no_web_registration_username_change_or_arbitrary_agent_api(self):
        self.permanent()
        for path in ('/api/auth/create','/api/auth/rename','/api/control','/api/session/other/form/foreign/reply'):
            self.assertEqual(self.request(path,{})[0],403)
        for path in ('/../accounts.sqlite','/api/session','/auth/session'):
            self.assertEqual(self.request(path)[0],403)

    def test_second_account_cannot_select_alice_backend(self):
        token,_=self.store.anonymous('gm.example.test');pre=self.store.session(token,'gm.example.test')
        token,_,_=self.store.login('bob','temporary-bob-secret1','gm.example.test','192.0.2.2',pre)
        session=self.store.session(token,'gm.example.test')
        token,_=self.store.change_password(session,'temporary-bob-secret1','permanent-bob-secret1','192.0.2.2')
        self.cookie=COOKIE+'='+token
        self.assertEqual(self.request('/?user='+self.id)[0],503)
        self.assertEqual(self.received,[])

    def test_logout_revokes_cookie(self):
        self.permanent()
        self.assertEqual(self.request('/api/auth/logout',{})[0],200)
        self.assertEqual(self.request('/')[0],302)

    def test_generation_reservation_is_global_and_unknown_work_is_not_replayed(self):
        self.permanent()
        self.gateway.proxy=lambda *args:(202,{'Content-Type':'application/json'},b'{"job":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}')
        self.assertEqual(self.request('/api/generate',{'date':'2026-10-11','kind':'gm'})[0],202)
        ticket=self.gateway.ticket()
        self.assertEqual(ticket['user'],self.id)
        self.assertEqual(ticket['job'],'a'*32)
        status,_,_=self.gateway.generate(self.other,'gm.example.test',b'{"date":"2026-10-11","kind":"gn"}',{})
        self.assertEqual(status,409)
        reopened=Gateway(self.store,self.gateway.hosts,testing=True)
        self.assertEqual(reopened.ticket(),ticket)
        self.gateway.clear_ticket(ticket)
        self.assertIsNone(self.gateway.ticket())

    def test_invalid_generation_never_reserves_slot(self):
        self.permanent()
        self.assertEqual(self.request('/api/generate',{'kind':'gm'})[0],400)
        self.assertIsNone(self.gateway.ticket())

    def test_chat_routes_require_login_and_remain_account_scoped(self):
        self.assertEqual(self.request('/chat')[0],302)
        self.assertEqual(self.request('/api/chats')[0],401)
        self.permanent()
        status,_,content=self.request('/chat')
        self.assertEqual(status,200)
        self.assertIn(self.csrf.encode(),content)
        self.assertEqual(self.received[-1][0],'/chat')
        self.assertEqual(self.request('/api/chats/'+('b'*32))[0],200)

    def test_chat_and_briefing_share_global_reservation(self):
        self.permanent()
        calls=[]
        def proxy(*args):
            calls.append(args)
            if args[3]=='GET': return 200,{},b'{"state":"waiting"}'
            return 202,{},b'{"chat":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        self.gateway.proxy=proxy
        body={'id':'a'*32,'mode':'secretary','text':'Hello'}
        self.assertEqual(self.request('/api/chats',body)[0],202)
        self.assertEqual(self.gateway.ticket()['chat'],'a'*32)
        self.assertEqual(self.request('/api/generate',{'date':'2026-10-11','kind':'gm'})[0],409)
        other={**body,'id':'b'*32}
        self.assertEqual(self.gateway.chat_message(self.other,'gm.example.test','/api/chats',json.dumps(other).encode(),{})[0],409)
        self.assertEqual(sum(args[3]=='POST' for args in calls),1)

    def test_uncertain_chat_reservation_is_preserved_on_invalid_duplicate(self):
        self.permanent()
        body={'id':'a'*32,'mode':'secretary','text':'Hello'}
        self.gateway.proxy=lambda *args:(503,{},b'{"state":"uncertain"}')
        self.assertEqual(self.request('/api/chats',body)[0],503)
        ticket=self.gateway.ticket()
        self.gateway.proxy=lambda *args:(400,{},b'{"error":"Invalid duplicate"}')
        self.assertEqual(self.request('/api/chats',{**body,'text':'Changed'})[0],400)
        self.assertEqual(self.gateway.ticket(),ticket)

    def test_idle_chat_releases_reservation_before_next_request(self):
        self.permanent()
        self.gateway.proxy=lambda *args:(200,{},b'{"state":"idle"}') if args[3]=='GET' else (202,{},b'{"chat":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}')
        self.assertEqual(self.request('/api/chats',{'id':'a'*32,'mode':'initialize','text':''})[0],202)
        self.assertEqual(self.request('/api/chats',{'id':'b'*32,'mode':'todo','text':'Capture this task'})[0],202)
        self.assertEqual(self.gateway.ticket()['chat'],'b'*32)

    def test_unsupported_chat_mode_does_not_reserve_or_dispatch(self):
        self.permanent()
        count=len(self.received)
        self.assertEqual(self.request('/api/chats',{'id':'a'*32,'mode':'gm','text':''})[0],400)
        self.assertEqual(len(self.received),count)
        self.assertIsNone(self.gateway.ticket())

    def test_password_policy_is_enforced_without_browser_validation(self):
        session=self.login()
        self.csrf=session['csrf']
        for value in ('abc12','abcdef','123456','a1'+'x'*31):
            status,_,data=self.request('/api/auth/password',{'current':'temporary-alice-secret1','replacement':value})
            self.assertEqual(status,400)
            self.assertIn('6–32 characters',json.loads(data)['error'])
        status,_,_=self.request('/api/auth/password',{'current':'temporary-alice-secret1','replacement':'abcde1'})
        self.assertEqual(status,200)
        self.assertTrue(self.store.check_password('alice','abcde1'))


if __name__=='__main__': unittest.main()
