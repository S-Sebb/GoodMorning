"""Public request boundaries and private account routing with synthetic data."""
import json
from pathlib import Path
import re
import sys
import threading
import unittest
from unittest.mock import patch

from support import GatewayFixture, ImmediateThread, MockChamber
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning.security.briefing_accounts import COOKIE, REMEMBER_SECONDS
from goodmorning.security.briefing_gateway import Gateway
from goodmorning.web.generation_clock import REQUESTED_AT


class GatewayTests(GatewayFixture):
    def test_single_host_serves_all_tabs_and_rejects_removed_hosts(self):
        single = Gateway(self.store, {'gm.example.test': 'gm'}, testing=True)
        self.gateway.hosts = single.hosts
        self.gateway.language_domain = single.language_domain
        self.permanent()
        for path, expected in (('/', '/gm.html'), ('/gm.html', '/gm.html'),
                               ('/gn.html', '/gn.html'), ('/chat', '/chat'),
                               ('/schedule?week=-3', '/schedule?week=-3'),
                               ('/api/schedule?week=3', '/api/schedule?week=3'),
                               ('/chat?id='+'a'*32, '/chat?id='+'a'*32)):
            self.assertEqual(self.request(path)[0], 200)
            self.assertEqual(self.received[-1][0], expected)
        for host in ('gn.example.test', 'sec.example.test'):
            self.assertEqual(self.request('/chat', headers={'Host': host})[0], 403)

    def test_every_public_asset_is_served_without_login_or_account_proxy(self):
        from goodmorning.web.briefing_resources import Resources
        from goodmorning.paths import WEB_ASSETS
        viewer=Resources(WEB_ASSETS)
        for name,path in viewer.urls.items():
            with self.subTest(asset=name):
                self.assertEqual(self.gateway.icons.urls[name],path)
                status,headers,body=self.request(path)
                self.assertEqual(status,200)
                self.assertEqual(headers['Content-Type'].split(';')[0],viewer.paths[path].mime)
                self.assertEqual(body,viewer.paths[path].data)
                self.assertIn('immutable',headers['Cache-Control'])
                self.assertNotIn('Set-Cookie',headers)
                if name.endswith('.css'):
                    for url in re.findall(r'url\([\"\']?([^\"\')]+)',body.decode()):
                        self.assertIn(url.split('#')[0],self.gateway.icons.paths)
        self.assertEqual(self.received,[])
        self.assertEqual(self.request('/api/chats')[0],401)

    def test_generation_clock_is_trusted_and_client_headers_are_not_forwarded(self):
        header={'X-GoodMorning-Requested-At':'123'}
        self.gateway.proxy(self.id,'gm.example.test','/api/generate','POST',b'{}',header)
        self.assertNotIn('x-goodmorning-requested-at',{k.lower() for k in self.received[-1][1]})
        token=REQUESTED_AT.set(456)
        try:
            self.gateway.proxy(self.id,'gm.example.test','/api/generate','POST',b'{}',header)
        finally:
            REQUESTED_AT.reset(token)
        normalized={k.lower():v for k,v in self.received[-1][1].items()}
        self.assertEqual(normalized['x-goodmorning-requested-at'],'456')

    def test_queued_generation_retains_arrival_time_not_later_dispatch_time(self):
        first={'user':self.id,'host':'gm.example.test','chat':'a'*32,'request':'a'*32}
        with self.store.db() as db:
            db.execute('INSERT INTO metadata VALUES (?,?)',('generation',json.dumps(first,separators=(',',':'))))
        observed=[]
        def proxy(user,host,path,method,raw,headers):
            if path.startswith('/api/edition/'):
                return 200,{},b'{"job":null}'
            if method=='GET':
                return 200,{},b'{"state":"running"}'
            observed.append(REQUESTED_AT.get())
            return 202,{},json.dumps({'job':'b'*32}).encode()
        with patch.object(self.gateway,'proxy',side_effect=proxy), patch('goodmorning.security.briefing_gateway.time.time',return_value=1000):
            status,_,_=self.gateway.generate(self.other,'gm.example.test',json.dumps({'date':'2026-10-13','kind':'gm'}).encode(),{})
            self.assertEqual(status,202)
            self.assertEqual(observed,[])
        with patch.object(self.gateway,'proxy',side_effect=proxy), patch('goodmorning.security.briefing_gateway.time.time',return_value=1100):
            self.gateway.clear_ticket(first)
            self.gateway.pump_queue()
        self.assertEqual(observed,[1000])
        self.assertIsNone(REQUESTED_AT.get())

    def test_orphan_generation_receipt_releases_stopped_job_without_replay(self):
        candidate = {'user':self.id, 'host':'gm.example.test', 'date':'2026-10-15', 'kind':'gm'}
        self.gateway._reserve_or_queue('generate', candidate, '/api/generate', {}, 'en')
        def proxy(user, host, path, method, raw, headers):
            self.assertEqual(method, 'GET')
            return 200, {}, json.dumps({'job':'a'*32} if '/edition/' in path else {'state':'stopped'}).encode()
        with patch.object(self.gateway, 'proxy', side_effect=proxy):
            self.gateway.pump_queue()
        self.assertIsNone(self.gateway.ticket())

    def test_lost_generation_response_reconciles_matching_receipt_only(self):
        candidate = {'user':self.id, 'host':'gm.example.test', 'date':'2026-10-15', 'kind':'gm', 'request':'b'*32}
        self.gateway._reserve_or_queue('regenerate', candidate, '/api/regenerate', {}, 'en')
        with patch.object(self.gateway, 'proxy', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                self.gateway.dispatch_generation(candidate, '/api/regenerate', b'{}', {})
        for receipt in ({'job':None}, {'job':'a'*32, 'regeneration_request':'c'*32}, {'job':123}):
            with patch.object(self.gateway, 'proxy', return_value=(200, {}, json.dumps(receipt).encode())):
                self.gateway.reconcile_ticket()
            self.assertEqual(self.gateway.ticket(), candidate)
        with patch.object(self.gateway, 'proxy', side_effect=[
                (200, {}, json.dumps({'job':'a'*32,'regeneration_request':'b'*32}).encode()),
                (200, {}, b'{"state":"running"}')]):
            self.gateway.reconcile_ticket()
        self.assertEqual(self.gateway.ticket()['job'], 'a'*32)

    def test_generation_reconciliation_cannot_release_inflight_post(self):
        candidate = {'user':self.id, 'host':'gm.example.test', 'date':'2026-10-15', 'kind':'gm'}
        self.gateway._reserve_or_queue('generate', candidate, '/api/generate', {}, 'en')
        def proxy(user, host, path, method, raw, headers):
            self.assertEqual(method, 'POST')
            self.gateway.reconcile_ticket()
            self.assertEqual(self.gateway.ticket(), candidate)
            return 202, {}, json.dumps({'job':'a'*32}).encode()
        with patch.object(self.gateway, 'proxy', side_effect=proxy):
            self.gateway.dispatch_generation(candidate, '/api/generate', b'{}', {})
        self.assertEqual(self.gateway.ticket()['job'], 'a'*32)

    def test_receipt_lookup_race_cannot_release_a_newly_inflight_post(self):
        candidate = {'user':self.id, 'host':'gm.example.test', 'date':'2026-10-15', 'kind':'gm'}
        self.gateway._reserve_or_queue('generate', candidate, '/api/generate', {}, 'en')
        reading, release = threading.Event(), threading.Event()
        def proxy(*args):
            reading.set()
            self.assertTrue(release.wait(3))
            return 200, {}, json.dumps({'job':'a'*32}).encode()
        with patch.object(self.gateway, 'proxy', side_effect=proxy):
            worker = threading.Thread(target=self.gateway.reconcile_ticket)
            worker.start()
            try:
                self.assertTrue(reading.wait(3))
                with self.gateway.generation_lock:
                    self.gateway.generation_inflight.add(json.dumps(candidate, separators=(',', ':')))
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.gateway.ticket(), candidate)

    def test_ready_without_generation_job_releases_slot_for_next_waiter(self):
        candidate = {'user':self.id, 'host':'gm.example.test', 'date':'2026-10-15', 'kind':'gm'}
        self.gateway._reserve_or_queue('generate', candidate, '/api/generate', {}, 'en')
        with patch.object(self.gateway, 'proxy', return_value=(200, {}, b'{"ready":true}')):
            self.gateway.dispatch_generation(candidate, '/api/generate', b'{}', {})
        self.assertIsNone(self.gateway.ticket())

    def test_same_active_chat_request_never_dispatches_an_interrupt(self):
        body = {'id':'a'*32, 'mode':'secretary', 'text':'Synthetic request'}
        with patch.object(self.gateway, 'proxy', side_effect=lambda *args:
                (202, {}, b'{"accepted":true}') if args[3]=='POST' else (200, {}, b'{"state":"running"}')) as calls:
            for _ in range(3):
                self.gateway.chat_message(self.id, 'gm.example.test', '/api/chats', json.dumps(body).encode(), {})
        self.assertEqual(sum(call.args[3]=='POST' for call in calls.call_args_list), 1)

    def test_ambiguous_generation_response_keeps_reservation(self):
        candidate = {'user':self.id, 'host':'gm.example.test', 'date':'2026-10-15', 'kind':'gm'}
        for status, raw in ((200,b'not json'), (202,b'[]'), (302,b'{}'), (503,b'{}')):
            with self.subTest(status=status, raw=raw):
                self.gateway.clear_ticket(candidate)
                self.gateway._reserve_or_queue('generate', candidate, '/api/generate', {}, 'en')
                with patch.object(self.gateway, 'proxy', return_value=(status, {}, raw)):
                    self.gateway.dispatch_generation(candidate, '/api/generate', b'{}', {})
                self.assertEqual(self.gateway.ticket(), candidate)

    def test_accepted_requests_do_not_expire_or_reappear_after_reload(self):
        active = self.preflight_ticket()
        candidate = {'user':self.other, 'host':'gm.example.test', 'chat':'b'*32, 'request':'b'*32, 'dispatching':True}
        body = {'id':'b'*32, 'mode':'secretary', 'text':'Synthetic durable request'}
        self.gateway._reserve_or_queue('chat', candidate, '/api/chats', body, 'en', enqueued=1)
        reopened = Gateway(self.store, self.gateway.hosts, testing=True)
        with patch.object(reopened, 'proxy', return_value=(200, {}, b'{"state":"running"}')):
            self.assertEqual(reopened.queue_status(self.other)['depth'], 1)
        reopened.clear_ticket(active)
        def proxy(user, host, path, method, raw, headers):
            return (202, {}, b'{"accepted":true}') if method == 'POST' else (200, {}, b'{"state":"running"}')
        with patch.object(reopened, 'proxy', side_effect=proxy) as calls:
            reopened.pump_queue()
            reopened.chat_message(self.other, candidate['host'], '/api/chats', json.dumps(body).encode(), {})
            self.assertEqual(sum(call.args[3]=='POST' for call in calls.call_args_list), 1)
            self.assertEqual(reopened.queue_status(self.other)['depth'], 0)

    def test_unprovisioned_login_gets_localized_setup_page_and_account_controls(self):
        self.permanent()
        (self.root/'backends.json').write_text('{}')
        for language,heading in (('en','Secretary setup pending'),('zh-CN','秘书服务尚未完成配置')):
            self.store.website_language(self.id,language)
            for path in ('/','/gm.html','/gn.html','/chat','/schedule','/d/2026-10-11/gm.html'):
                status,headers,data=self.request(path)
                self.assertEqual(status,503)
                self.assertTrue(headers['Content-Type'].startswith('text/html'))
                self.assertEqual(headers['Cache-Control'],'no-store')
                self.assertEqual(headers['Content-Language'],language)
                self.assertIn(heading,data.decode())
                self.assertIn(b'id="sign-out"',data)
                self.assertIn(b'href="/password"',data)
                self.assertIn(b'id="language-form"',data)
                self.assertNotIn(self.id.encode(),data)
                self.assertNotIn(self.key.encode(),data)
        self.assertEqual(self.received,[])
        status,headers,data=self.request('/api/day')
        self.assertEqual(status,503)
        self.assertEqual(headers['Content-Type'],'application/json')
        self.assertIn('管理员',json.loads(data)['error'])
        self.assertEqual(self.request('/password')[0],200)
        self.assertEqual(self.request('/api/auth/logout',{})[0],200)

    def test_unprovisioned_mutations_do_not_reserve_or_queue_work(self):
        self.permanent()
        (self.root/'backends.json').write_text('{}')
        for path,body in (('/api/generate',{'date':'2026-10-11','kind':'gm'}),
                          ('/api/chats',{'mode':'secretary','text':'Synthetic request'}),
                          ('/api/jobs/'+'a'*32+'/recover',{'id':'b'*32})):
            self.assertEqual(self.request(path,body)[0],503)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM metadata WHERE key IN ('generation','generation_queue','generation_waiting')").fetchone()[0],0)
        self.assertEqual(self.received,[])

    def test_backend_failure_returns_safe_html_but_apis_keep_json(self):
        self.permanent()
        private='synthetic-private-path-and-secret'
        with patch.object(self.gateway,'proxy',side_effect=RuntimeError(private)):
            with self.assertLogs('goodmorning.security.briefing_gateway',level='WARNING') as logs:
                status,headers,data=self.request('/chat?id='+'a'*32)
            self.assertEqual(status,503)
            self.assertTrue(headers['Content-Type'].startswith('text/html'))
            self.assertIn(b'Secretary temporarily unavailable',data)
            self.assertNotIn(private.encode(),data)
            self.assertNotIn(private,' '.join(logs.output))
            self.assertIn('RuntimeError',' '.join(logs.output))
            with self.assertLogs('goodmorning.security.briefing_gateway',level='WARNING'):
                status,headers,data=self.request('/api/day')
            self.assertEqual(status,503)
            self.assertEqual(headers['Content-Type'],'application/json')
            self.assertNotIn(private.encode(),data)
        with patch.object(self.gateway,'proxy',return_value=(503,{'Content-Type':'application/json'},b'{"error":"private"}')):
            self.assertIn(b'Secretary temporarily unavailable',self.request('/')[2])

    def test_malformed_backend_is_not_reported_as_unprovisioned(self):
        self.permanent()
        for registry in ({self.id:{'port':self.backend.server_port}},[]):
            (self.root/'backends.json').write_text(json.dumps(registry))
            with self.assertLogs('goodmorning.security.briefing_gateway',level='WARNING'):
                data=self.request('/')[2]
            self.assertIn(b'Secretary temporarily unavailable',data)
            self.assertNotIn(b'Secretary setup pending',data)

    def test_recovery_uses_global_reservation_and_never_replays_duplicate(self):
        job='a'*32;path='/api/jobs/'+job+'/recover';raw=json.dumps({'id':'b'*32}).encode()
        with patch.object(self.gateway,'proxy',return_value=(202,{},json.dumps({'job':job}).encode())) as proxy:
            self.assertEqual(self.gateway.recover(self.id,'gm.example.test',path,raw,{})[0],202)
            self.assertEqual(self.gateway.ticket()['user'],self.id)
            self.assertEqual(self.gateway.recover(self.id,'gm.example.test',path,raw,{})[0],202)
            self.assertEqual(sum(call.args[3]=='POST' for call in proxy.call_args_list),1)
            status,_,data=self.gateway.recover(self.other,'gm.example.test',path,raw,{})
            self.assertEqual(status,202)
            queued=json.loads(data)
            self.assertTrue(queued.get('queued'))
            self.assertEqual(queued.get('position'),1)
            self.assertEqual(self.gateway.ticket()['user'],self.id)
            self.assertEqual(sum(call.args[3]=='POST' for call in proxy.call_args_list),1)
            status=self.gateway.queue_status(self.other)
            self.assertEqual(len(status['queue']),1)
            self.assertEqual(status['queue'][0]['job'],job)
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
        self.assertEqual(self.request('/api/regenerate',{'date':'2026-10-11','kind':'gm','id':'b'*32,'previous':'a'*32})[0],403)
        self.assertEqual(self.received,[])

    def test_regeneration_reserves_global_slot_and_retries_do_not_dispatch_twice(self):
        old='a'*32;new='c'*32;request='b'*32
        body={'date':'2026-10-11','kind':'gm','id':request,'previous':old}
        editions={self.id:{'job':old},self.other:{'job':old}}
        def proxy(user,host,path,method,raw,headers):
            if path.startswith('/api/edition/'):
                return 200,{},json.dumps(editions[user]).encode()
            if method=='GET':return 200,{},b'{"state":"running"}'
            self.assertEqual(path,'/api/regenerate')
            self.assertEqual(json.loads(raw),body)
            editions[user]={'job':new,'regeneration_request':request}
            return 202,{},json.dumps({'job':new}).encode()
        with patch.object(self.gateway,'proxy',side_effect=proxy) as forwarded:
            raw=json.dumps(body).encode()
            self.assertEqual(self.gateway.generate(self.id,'gm.example.test',raw,{},regenerate=True)[0],202)
            self.assertEqual(self.gateway.ticket()['job'],new)
            self.assertEqual(self.gateway.generate(self.id,'gm.example.test',raw,{},regenerate=True)[0],202)
            self.assertEqual(sum(call.args[3]=='POST' for call in forwarded.call_args_list),1)
            _,_,data=self.gateway.generate(self.other,'gm.example.test',raw,{},regenerate=True)
            self.assertTrue(json.loads(data)['queued'])
            queue=self.gateway.queue_status(self.other)
            self.assertEqual(queue['queue'][0],{'work':'regenerate','date':'2026-10-11','edition':'gm','previous':old,'position':1})
            self.assertEqual(self.gateway.queue_status(self.id)['queue'],[])
            self.assertEqual(sum(call.args[3]=='POST' for call in forwarded.call_args_list),1)
            self.gateway.clear_ticket(self.gateway.ticket())
            self.gateway.pump_queue()
            self.assertEqual(sum(call.args[3]=='POST' for call in forwarded.call_args_list),2)
            self.assertEqual(self.gateway.ticket()['user'],self.other)
            self.assertEqual(self.gateway.ticket()['job'],new)

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

    def test_failed_logins_are_indistinguishable_unpromoted_and_rate_limited(self):
        _,headers,content=self.request('/login')
        self.cookie=headers['Set-Cookie'].split(';')[0]
        self.csrf=re.search(b'data-csrf="([a-f0-9]+)"',content)[1].decode()
        wrong=self.request('/api/auth/login',{'username':'alice','password':'wrong-alice-secret1'})
        unknown=self.request('/api/auth/login',{'username':'mallory','password':'temporary-alice-secret1'})
        self.assertEqual((wrong[0],wrong[2]),(unknown[0],unknown[2]))
        self.assertEqual(wrong[0],403)
        self.assertNotIn('Set-Cookie',wrong[1])
        self.assertEqual(self.request('/')[1]['Location'],'/login')
        self.assertIsNone(self.store.session(self.cookie.split('=',1)[1],'gm.example.test')['user_id'])
        statuses=[self.request('/api/auth/login',{'username':'alice','password':'wrong-alice-secret1'})[0] for _ in range(5)]
        self.assertEqual(statuses[-1],429)
        self.assertEqual(self.request('/api/auth/login',{'username':'alice','password':'temporary-alice-secret1'})[0],429)
        self.assertEqual(self.received,[])

    def test_requests_not_forwarded_over_https_are_refused(self):
        for proto in ('http',''):
            self.assertEqual(self.request('/login',headers={'X-Forwarded-Proto':proto})[0],403)
            self.assertEqual(self.request('/api/auth/login',{'username':'alice','password':'temporary-alice-secret1'},headers={'X-Forwarded-Proto':proto})[0],403)
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
        self.assertNotRegex(page,rb'name="remember"[^>]*checked')
        versions=re.findall(rb'/assets/([a-f0-9]{64})/auth\.(?:css|js)',page)
        self.assertEqual(len(versions),2)
        for path in re.findall(rb'(?:href|src)="([^"]+/auth\.(?:css|js))"',page):
            status,headers,_=self.request(path.decode())
            self.assertEqual(status,200)
            self.assertIn('immutable',headers['Cache-Control'])
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
        status,_,data=self.gateway.generate(self.other,'gm.example.test',b'{"date":"2026-10-11","kind":"gn"}',{})
        self.assertEqual(status,202)
        queued=json.loads(data)
        self.assertTrue(queued.get('queued'))
        self.assertEqual(queued.get('position'),1)
        self.assertEqual(self.gateway.ticket(),ticket)
        reopened=Gateway(self.store,self.gateway.hosts,testing=True)
        self.assertEqual(reopened.ticket(),ticket)
        self.assertEqual(reopened.queue_status(self.other)['depth'],1)
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
        status,_,data=self.request('/api/generate',{'date':'2026-10-11','kind':'gm'})
        self.assertEqual(status,202)
        self.assertTrue(json.loads(data).get('queued'))
        other={**body,'id':'b'*32}
        status,_,data=self.gateway.chat_message(self.other,'gm.example.test','/api/chats',json.dumps(other).encode(),{})
        self.assertEqual(status,202)
        self.assertTrue(json.loads(data).get('queued'))
        self.assertEqual(sum(args[3]=='POST' for args in calls),1)
        self.assertEqual(self.gateway.queue_status(self.other)['depth'],2)

    def test_global_queue_is_bounded_fifo_and_deduplicated(self):
        from goodmorning.security.briefing_gateway import MAX_QUEUE
        self.permanent()
        calls=[]
        def proxy(*args):
            calls.append(args)
            if args[3]=='GET': return 200,{},b'{"state":"running"}'
            return 202,{},b'{"chat":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        self.gateway.proxy=proxy
        first={'id':'a'*32,'mode':'secretary','text':'First'}
        self.assertEqual(self.request('/api/chats',first)[0],202)
        second={'id':'b'*32,'mode':'secretary','text':'Second'}
        status,_,data=self.gateway.chat_message(self.other,'gm.example.test','/api/chats',json.dumps(second).encode(),{})
        self.assertEqual(status,202)
        self.assertEqual(json.loads(data)['position'],1)
        status,_,repeat=self.gateway.chat_message(self.other,'gm.example.test','/api/chats',json.dumps(second).encode(),{})
        self.assertEqual(status,202)
        self.assertEqual(json.loads(repeat)['position'],1)
        self.assertEqual(self.gateway.queue_status(self.other)['depth'],1)
        for index in range(MAX_QUEUE - 1):
            body={'id':format(index,'032x'),'mode':'secretary','text':'Filler %d' % index}
            status,_,_=self.gateway.chat_message(self.other,'gm.example.test','/api/chats',json.dumps(body).encode(),{})
            self.assertEqual(status,202)
        status,_,data=self.gateway.chat_message(self.other,'gm.example.test','/api/chats',json.dumps({'id':'f'*32,'mode':'secretary','text':'Overflow'}).encode(),{})
        self.assertEqual(status,429)
        self.assertIn('queue',json.loads(data)['error'].lower())
        self.assertEqual(sum(args[3]=='POST' for args in calls),1)

    def test_pump_dispatches_queued_work_in_order_after_idle(self):
        self.permanent()
        states={'active':True}
        dispatched=[]
        def proxy(user,host,path,method,raw,headers):
            if method=='GET':
                return (200,{},b'{"state":"idle"}') if not states['active'] else (200,{},b'{"state":"running"}')
            dispatched.append(json.loads(raw)['id'])
            states['active']=True
            return 202,{},b'{"chat":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        self.gateway.proxy=proxy
        self.assertEqual(self.gateway.chat_message(self.id,'gm.example.test','/api/chats',json.dumps({'id':'a'*32,'mode':'secretary','text':'First'}).encode(),{})[0],202)
        self.assertEqual(self.gateway.chat_message(self.other,'gm.example.test','/api/chats',json.dumps({'id':'b'*32,'mode':'secretary','text':'Second'}).encode(),{})[0],202)
        self.assertEqual(dispatched,['a'*32])
        states['active']=False
        status=self.gateway.queue_status(self.other)
        self.assertEqual(status['queue'],[])
        self.assertEqual(dispatched,['a'*32,'b'*32])
        self.assertEqual(self.gateway.ticket()['chat'],'b'*32)

    def test_idle_ticket_is_released_without_new_traffic(self):
        self.permanent()
        states={'active':True}
        def proxy(user,host,path,method,raw,headers):
            if method=='GET':
                return (200,{},b'{"state":"idle"}') if not states['active'] else (200,{},b'{"state":"running"}')
            return 202,{},b'{"chat":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        self.gateway.proxy=proxy
        self.assertEqual(self.request('/api/chats',{'id':'a'*32,'mode':'secretary','text':'Hello'})[0],202)
        self.assertIsNotNone(self.gateway.ticket())
        # The holder goes idle and stops polling; nothing else arrives.
        # The background pump still releases the finished slot on its own.
        self.gateway.pump_queue()
        self.assertIsNotNone(self.gateway.ticket())
        states['active']=False
        self.gateway.pump_queue()
        self.assertIsNone(self.gateway.ticket())

    def test_queue_reconciliation_uses_transcript_independent_chat_status(self):
        first = {'id': 'a' * 32, 'mode': 'secretary', 'text': 'First'}
        second = {'id': 'b' * 32, 'mode': 'secretary', 'text': 'Second'}
        finished = False
        dispatched = []
        def proxy(user, host, path, method, raw, headers):
            if method == 'GET':
                self.assertTrue(path.endswith('/status'), 'Queue attempted to load a transcript')
                state = 'idle' if finished and path == '/api/chats/' + first['id'] + '/status' else 'running'
                return 200, {}, json.dumps({'state': state}).encode()
            dispatched.append((user, json.loads(raw)['id']))
            return 202, {}, b'{"accepted":true}'
        self.gateway.proxy = proxy
        self.gateway.chat_message(self.id, 'gm.example.test', '/api/chats', json.dumps(first).encode(), {})
        self.gateway.chat_message(self.other, 'gm.example.test', '/api/chats', json.dumps(second).encode(), {})
        self.assertEqual(dispatched, [(self.id, first['id'])])
        finished = True
        self.gateway.pump_queue()
        self.assertEqual(dispatched, [(self.id, first['id']), (self.other, second['id'])])
        self.assertEqual(self.gateway.ticket()['user'], self.other)
        self.assertEqual(self.gateway.queue_status(self.other)['queue'], [])

    def preflight_ticket(self):
        ticket = {'user':self.id, 'host':'gm.example.test', 'date':'2026-10-11', 'kind':'gn', 'job':'a'*32}
        with self.store.db() as db:
            db.execute('INSERT INTO metadata VALUES (?,?)', ('generation', json.dumps(ticket, separators=(',', ':'))))
        return ticket

    def test_preflight_yields_slot_and_dispatches_other_user_without_an_answer(self):
        self.preflight_ticket()
        waiting = {'user':self.other, 'host':'gm.example.test', 'chat':'b'*32, 'request':'b'*32}
        self.gateway._reserve_or_queue('chat', waiting, '/api/chats', {'id':'b'*32,'mode':'secretary','text':'Hello'}, 'en')
        def proxy(user, host, path, method, raw, headers):
            if method == 'POST': return 202, {}, b'{"accepted":true}'
            return 200, {}, json.dumps({'state':'waiting','reservation_required':False} if '/jobs/' in path else {'state':'running'}).encode()
        with patch.object(self.gateway, 'proxy', side_effect=proxy) as calls:
            self.gateway.pump_queue()
        self.assertEqual(self.gateway.ticket(), waiting)
        self.assertEqual(sum(call.args[3] == 'POST' for call in calls.call_args_list), 1)

    def test_waiting_native_session_and_unavailable_work_never_yield(self):
        ticket = self.preflight_ticket()
        for status, body in ((200, {'state':'waiting'}), (503, {'state':'waiting','reservation_required':False}),
                             (200, {'state':'uncertain','reservation_required':False})):
            with patch.object(self.gateway, 'proxy', return_value=(status, {}, json.dumps(body).encode())):
                self.gateway.reconcile_ticket()
            self.assertEqual(self.gateway.ticket(), ticket)

    def test_reopening_existing_briefing_does_not_join_its_own_queue(self):
        ticket = self.preflight_ticket()
        with patch.object(self.gateway, 'proxy', return_value=(200, {}, json.dumps({'job':ticket['job']}).encode())) as proxy:
            status, _, raw = self.gateway.generate(self.id, ticket['host'], b'{"date":"2026-10-11","kind":"gn"}', {})
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(raw), {'job':ticket['job']})
        proxy.assert_called_once()
        with self.store.db() as db:self.assertEqual(self.gateway._read_queue(db), [])

    def test_answer_queues_durably_then_reacquires_slot_before_dispatch(self):
        active = {'user':self.other,'host':'gm.example.test','chat':'b'*32,'request':'b'*32}
        with self.store.db() as db:
            db.execute('INSERT INTO metadata VALUES (?,?)', ('generation', json.dumps(active, separators=(',', ':'))))
        form = 'preflight_'+'a'*32
        path = '/api/jobs/'+('a'*32)+'/form/'+form+'/reply'
        raw = b'{"answer":{"completed":["none"],"details":"No other updates"}}'
        state = {'active':True, 'answered':False}
        def proxy(user, host, path, method, body, headers):
            if method == 'POST':
                self.assertTrue(self.gateway.ticket()['dispatching'])
                # A concurrent maintenance tick must not release an in-flight answer.
                self.gateway.reconcile_ticket()
                self.assertTrue(self.gateway.ticket()['dispatching'])
                state['answered'] = True
                return 200, {}, b'{"answered":true}'
            if '/chats/' in path:
                return 200, {}, json.dumps({'state':'running' if state['active'] else 'idle'}).encode()
            return 200, {}, json.dumps({'state':'running'} if state['answered'] else {
                'state':'waiting', 'reservation_required':False, 'forms':[{'id':form}], 'date':'2026-10-11', 'kind':'gn'}).encode()
        with patch.object(self.gateway, 'proxy', side_effect=proxy):
            for _ in range(2):
                status, _, response = self.gateway.input_reply(self.id, 'gm.example.test', path, raw, {})
                self.assertEqual(status, 202);self.assertTrue(json.loads(response)['queued'])
            self.assertFalse(state['answered'])
            with self.store.db() as db:
                queue = self.gateway._read_queue(db)
                self.assertEqual(len(queue), 1)
                queue[0]['enqueued'] = 1
                self.gateway._write_queue(db, queue)
            reopened = Gateway(self.store, self.gateway.hosts, testing=True)
            with patch.object(reopened, 'proxy', side_effect=proxy):
                self.assertEqual(reopened.queue_status(self.id)['queue'][0]['work'], 'reply')
            state['active'] = False
            self.gateway.pump_queue()
            self.assertTrue(state['answered'])
            self.assertEqual(self.gateway.ticket()['job'], 'a'*32)
            self.assertNotIn('dispatching', self.gateway.ticket())

    def test_uncertain_answer_dispatch_keeps_reservation(self):
        form = 'preflight_'+'a'*32
        def proxy(user, host, path, method, raw, headers):
            if method == 'POST': raise TimeoutError('Synthetic uncertain delivery')
            return 200, {}, json.dumps({'state':'waiting','reservation_required':False,'forms':[{'id':form}]}).encode()
        with patch.object(self.gateway, 'proxy', side_effect=proxy):
            with self.assertRaises(TimeoutError):
                self.gateway.input_reply(self.id, 'gm.example.test', '/api/jobs/'+('a'*32)+'/form/'+form+'/reply', b'{"answer":{}}', {})
            self.gateway.pump_queue()
        self.assertTrue(self.gateway.ticket()['dispatching'])

    def test_native_question_waits_indefinitely_and_reply_resumes_original_session(self):
        from goodmorning.web.briefing_chat import Chats
        runtime=self.root/'synthetic-waiting-chat';runtime.mkdir()
        chamber=MockChamber(runtime);chats=Chats(runtime,chamber)
        def proxy(user, host, path, method, raw, headers):
            if user == self.other:
                return 200, {}, b'{"state":"running"}'
            if method == 'GET':
                return 200, {}, json.dumps(chats.status('a'*32)).encode()
            if path == '/api/chats':
                value=chats.start(json.loads(raw))
            else:
                parts=path.split('/')
                value=chats.reply(parts[3],parts[4],parts[5],json.loads(raw))
            return 202, {}, json.dumps(value).encode()
        with patch.object(self.gateway,'proxy',side_effect=proxy), patch('goodmorning.web.briefing_chat.threading.Thread',ImmediateThread):
            self.gateway.chat_message(self.id,'gm.example.test','/api/chats',
                json.dumps({'id':'a'*32,'mode':'initialize','text':''}).encode(),{})
            original_session=chats.get('a'*32)['session']
            self.gateway.pump_queue()
            self.assertIsNone(self.gateway.ticket())
            # Long consideration and a viewer reload preserve the native question.
            reloaded=Chats(runtime,chamber)
            self.assertEqual(reloaded.status('a'*32)['forms'][0]['id'],'form_city')
            self.assertEqual(chamber.replies,[])
            active={'user':self.other,'host':'gm.example.test','chat':'b'*32,'request':'b'*32}
            self.gateway._reserve_or_queue('chat',active,'/api/chats',{'id':'b'*32,'mode':'secretary','text':'Other work'},'en')
            path='/api/chats/'+('a'*32)+'/form/form_city/reply'
            status,_,raw=self.gateway.input_reply(self.id,'gm.example.test',path,b'{"answer":{"city":"London"}}',{})
            self.assertEqual(status,202);self.assertTrue(json.loads(raw)['queued'])
            self.assertEqual(chamber.replies,[])
            with self.store.db() as db:
                queue=self.gateway._read_queue(db);queue[0]['enqueued']=1;self.gateway._write_queue(db,queue)
            self.gateway.clear_ticket(active)
            self.gateway.pump_queue()
            self.assertEqual(chamber.replies[0][0],'/api/session/'+original_session+'/form/form_city/reply')
            self.assertEqual(chamber.replies[0][1],{'answer':{'city':'London'}})
            self.assertEqual(len(chamber.sessions),1)
            self.assertIsNone(self.gateway.ticket())  # The next permission also yields.
            permission='/api/chats/'+('a'*32)+'/permission/permission_setup/reply'
            self.assertEqual(self.gateway.input_reply(self.id,'gm.example.test',permission,b'{"decision":"once"}',{})[0],202)
            self.gateway.pump_queue()
            self.assertEqual(chats.status('a'*32)['state'],'idle')
            self.assertIsNone(self.gateway.ticket())
            self.assertEqual(len(chamber.replies),2)

    def test_uncertain_chat_reservation_is_preserved_on_invalid_duplicate(self):
        self.permanent()
        body={'id':'a'*32,'mode':'secretary','text':'Hello'}
        self.gateway.proxy=lambda *args:(503,{},b'{"state":"uncertain"}')
        self.assertEqual(self.request('/api/chats',body)[0],503)
        ticket=self.gateway.ticket()
        self.gateway.proxy=lambda *args:(400,{},b'{"error":"Invalid duplicate"}')
        self.assertEqual(self.request('/api/chats',{**body,'text':'Changed'})[0],409)
        self.assertEqual(self.gateway.ticket(),ticket)

    def test_idle_chat_releases_reservation_before_next_request(self):
        self.permanent()
        self.gateway.proxy=lambda *args:(200,{},b'{"state":"idle"}') if args[3]=='GET' else (202,{},b'{"chat":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}')
        self.assertEqual(self.request('/api/chats',{'id':'a'*32,'mode':'initialize','text':''})[0],202)
        self.assertEqual(self.request('/api/chats',{'id':'b'*32,'mode':'secretary','text':'Capture this task'})[0],202)
        self.assertEqual(self.gateway.ticket()['chat'],'b'*32)

    def test_real_native_message_limit_releases_finished_and_waiting_chat(self):
        from goodmorning.web.briefing_chat import Chats
        runtime=self.root/'synthetic-secretary';runtime.mkdir()
        chats=Chats(runtime,MockChamber(runtime))
        def proxy(user,host,path,method,raw,headers):
            result=chats.status(path.split('/')[3], include_messages=not path.endswith('/status')) if method=='GET' else chats.start(json.loads(raw))
            return 200 if method=='GET' else 202,{},json.dumps(result).encode()
        self.gateway.proxy=proxy
        with patch('goodmorning.web.briefing_chat.threading.Thread',ImmediateThread):
            for identifier,mode in (('a','secretary'),('b','secretary'),('c','initialize')):
                body={'id':identifier*32,'mode':mode,'text':'' if mode=='initialize' else 'Synthetic capture'}
                self.assertEqual(self.gateway.chat_message(self.id,'gm.example.test','/api/chats',json.dumps(body).encode(),{})[0],202)
            status,_,data=self.gateway.chat_message(self.other,'gm.example.test','/api/chats',json.dumps({'id':'d'*32,'mode':'secretary','text':'Other request'}).encode(),{})
            self.assertEqual(status,202)
            self.assertFalse(json.loads(data).get('queued',False))
            self.assertEqual(self.gateway.ticket()['chat'],'d'*32)

    def test_public_release_check_does_not_touch_login_sessions(self):
        from goodmorning.web.release import release_info
        with self.store.db() as db:before=[tuple(row) for row in db.execute('SELECT * FROM sessions')]
        status,headers,data=self.request('/api/release')
        self.assertEqual(status,200);self.assertEqual(json.loads(data),release_info())
        self.assertEqual(headers['Cache-Control'],'public, no-cache')
        self.assertNotIn('Set-Cookie',headers)
        self.assertEqual(self.request('/api/release',headers={'If-None-Match':headers['ETag']})[0],304)
        with self.store.db() as db:self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM sessions')],before)

    def test_private_html_cache_is_bound_to_account_session_path_and_language(self):
        from goodmorning.web import language as ui
        self.permanent()
        html='<html><head></head><body><p>Alice preserved content</p></body></html>'
        self.gateway.proxy=lambda user,*args:(200,{'Content-Type':'text/html'},html.encode())
        with patch.object(ui,'page',wraps=ui.page) as render:
            first=self.request('/chat')[2];second=self.request('/chat')[2]
            self.assertEqual(first,second);self.assertEqual(render.call_count,1)
            self.assertIn(self.csrf.encode(),first)
            self.request('/gm.html');self.assertEqual(render.call_count,2)
            self.store.website_language(self.id,'zh-CN');self.request('/chat');self.assertEqual(render.call_count,3)
            anonymous,_=self.store.anonymous('gm.example.test')
            session=self.store.session(anonymous,'gm.example.test')
            token,csrf,_=self.store.login('alice','permanent-alice-secret1','gm.example.test','192.0.2.2',session)
            previous=self.csrf;self.cookie=COOKIE+'='+token;self.csrf=csrf
            content=self.request('/chat')[2];self.assertEqual(render.call_count,4)
            self.assertIn(csrf.encode(),content);self.assertNotIn(previous.encode(),content)
            html=html.replace('preserved','changed');self.request('/chat');self.assertEqual(render.call_count,5)
        status,headers,_=self.request('/chat',headers={'Accept-Encoding':'gzip'})
        self.assertEqual(headers['Cache-Control'],'no-store');self.assertNotIn('Content-Encoding',headers)
        self.request('/api/auth/logout',{})
        self.assertEqual(self.request('/chat')[0],302)
        self.assertLessEqual(self.gateway.html_cache.size,8*1024*1024)

    def test_chat_workspace_namespace_is_public_and_changes_between_logins(self):
        import hashlib
        self.permanent()
        backend_scope='a'*64
        source='<body><div data-config="{&quot;workspaceScope&quot;: &quot;'+backend_scope+'&quot;}"></div></body>'
        self.gateway.proxy=lambda user,*args:(200,{'Content-Type':'text/html'},source.encode())
        def namespace():
            status,headers,content=self.request('/chat')
            self.assertEqual(status,200)
            self.assertEqual(headers['Cache-Control'],'no-store')
            return re.search(rb'workspaceScope&quot;:\s*&quot;([a-f0-9]{64})',content)[1].decode()
        first=namespace()
        self.assertEqual(first,hashlib.sha256(('chat-workspace:'+self.csrf).encode()).hexdigest())
        self.assertNotIn(first,(backend_scope,self.csrf,self.cookie.split('=',1)[1]))
        self.assertEqual(namespace(),first)
        self.request('/api/auth/logout',{})
        anonymous,_=self.store.anonymous('gm.example.test')
        token,csrf,_=self.store.login('alice','permanent-alice-secret1','gm.example.test','192.0.2.2',self.store.session(anonymous,'gm.example.test'))
        self.cookie=COOKIE+'='+token;self.csrf=csrf
        self.assertNotEqual(namespace(),first)

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
            self.assertEqual(self.request('/api/auth/password',{'current':'temporary-alice-secret1','replacement':value})[0],400)
            self.assertTrue(self.store.check_password('alice','temporary-alice-secret1'))
        status,_,_=self.request('/api/auth/password',{'current':'temporary-alice-secret1','replacement':'abcde1'})
        self.assertEqual(status,200)
        self.assertTrue(self.store.check_password('alice','abcde1'))


if __name__=='__main__': unittest.main()
