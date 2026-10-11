"""Account-wide language, secure switching, pinned requests and original-data preservation."""
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

from support import TEMP_ROOT
from goodmorning.web import language as ui
from goodmorning.web.briefing_chat import Chats
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.setup_check import profile_status, main as setup
from goodmorning.records.workflow import prepare
from goodmorning.runtime_files import profile_fields
from goodmorning.briefings import briefing_document as native
from goodmorning.briefings.briefing_job import act
import test_briefing_gateway as gateway_tests
from test_briefing_chat import MockChamber, ImmediateThread
from test_briefing_server import FakeChamber


@contextmanager
def selected(value):
    token=ui.CURRENT.set(value)
    try:yield
    finally:ui.CURRENT.reset(token)


class LanguageTests(unittest.TestCase):
    def gateway(self):
        fixture=gateway_tests.GatewayTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.gateway.hosts['sec.example.test']='sec'
        return fixture

    def root(self):
        temporary=tempfile.TemporaryDirectory(dir=TEMP_ROOT);self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        (root/'profile.md').write_text('city: London, GB\ntimezone: Europe/London\nnews_country: GB\nsecretary_tone: Keep this tone.\n')
        return root

    def test_language_sync_is_account_wide_not_an_authentication_cookie(self):
        fixture=self.gateway();fixture.permanent()
        original=fixture.cookie
        status,headers,_=fixture.request('/api/language',{'language':'zh-CN'})
        self.assertEqual(status,200)
        self.assertIn('GoodMorningLanguage=zh-CN',headers['Set-Cookie'])
        self.assertIn('Domain=example.test',headers['Set-Cookie'])
        self.assertEqual(fixture.cookie,original)
        for host in ('gm.example.test','gn.example.test','sec.example.test'):
            with fixture.store.db() as db:
                row=db.execute('SELECT * FROM users WHERE id=?',(fixture.id,)).fetchone()
                token,_=fixture.store.issue(db,host,row)
            status,_,body=fixture.request('/api/language',headers={'Host':host,'Cookie':'__Host-GoodMorning='+token})
            self.assertEqual((status,json.loads(body)['language']),(200,'zh-CN'))
        with fixture.store.db() as db:
            row=db.execute('SELECT * FROM users WHERE id=?',(fixture.other,)).fetchone()
            token,_=fixture.store.issue(db,'gm.example.test',row)
        _,_,body=fixture.request('/api/language',headers={'Cookie':'__Host-GoodMorning='+token+'; GoodMorningLanguage=zh-CN'})
        self.assertEqual(json.loads(body)['language'],'en')
        self.assertIsNone(fixture.store.website_language(fixture.other))
        # The harmless sibling preference cannot authenticate a user on another host.
        self.assertEqual(fixture.request('/api/chats',headers={'Host':'gn.example.test','Cookie':original+'; GoodMorningLanguage=zh-CN'})[0],401)
        fixture.store.administer('alice',new_name='alice-new')
        self.assertEqual(fixture.store.website_language(fixture.id),'zh-CN')

    def test_anonymous_temporary_and_invalid_language_requests_keep_security_boundaries(self):
        fixture=self.gateway()
        fixture.request('/login')
        status,headers,body=fixture.request('/login')
        fixture.cookie=headers['Set-Cookie'].split(';')[0]
        fixture.csrf=__import__('re').search(rb'data-csrf="([a-f0-9]+)"',body)[1].decode()
        self.assertEqual(fixture.request('/api/language',{'language':'zh-CN'})[0],200)
        self.assertEqual(fixture.request('/api/language',{'language':'zh-CN'},headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(fixture.request('/api/language',{'language':'zh-CN'},headers={'X-Briefing-CSRF':'wrong'})[0],403)
        for bad in ('zh-TW','fr','<script>',None,{},True):
            self.assertEqual(fixture.request('/api/language',{'language':bad})[0],400)
        fixture.cookie=None
        status,_,body=fixture.request('/login',headers={'Cookie':'GoodMorningLanguage=zh-CN'})
        self.assertEqual(status,200);self.assertIn('登录',body.decode());self.assertIn('lang="zh-CN"',body.decode())
        logged=fixture.login();fixture.csrf=logged['csrf']
        self.assertEqual(fixture.request('/api/language',{'language':'zh-CN'})[0],200)
        self.assertEqual(fixture.request('/api/chats')[0],403)
        _,_,page=fixture.request('/password')
        self.assertIn('修改密码',page.decode())

    def test_non_javascript_switch_has_csrf_and_safe_redirect(self):
        fixture=self.gateway();fixture.permanent()
        for target in ('/chat','//evil.example','/chat?x=\r\nInjected: yes'):
            raw=urlencode({'language':'zh-CN','csrf':fixture.csrf,'return_to':target}).encode()
            headers={'Host':'gm.example.test','X-Forwarded-Proto':'https','X-Real-IP':'192.0.2.1',
                     'Cookie':fixture.cookie,'Origin':'https://gm.example.test','Content-Type':'application/x-www-form-urlencoded'}
            try:response=fixture.opener.open(Request(f'http://127.0.0.1:{fixture.server.server_port}/api/language',data=raw,headers=headers))
            except HTTPError as error:response=error
            with response:
                self.assertEqual(response.status,303)
                self.assertEqual(response.headers['Location'],'/chat' if target=='/chat' else '/')
        self.assertEqual(fixture.store.website_language(fixture.id),'zh-CN')

    def test_language_headers_are_server_owned_and_settings_survive_logout(self):
        fixture=self.gateway();fixture.permanent()
        fixture.store.website_language(fixture.id,'zh-CN')
        fixture.request('/',headers={'X-GoodMorning-Language':'en'})
        headers={key.lower():value for key,value in fixture.received[-1][1].items()}
        self.assertEqual(headers['x-goodmorning-language'],'zh-CN')
        self.assertEqual(fixture.request('/api/auth/logout',{})[0],200)
        self.assertEqual(fixture.store.website_language(fixture.id),'zh-CN')

    def test_interface_and_default_labels_translate_without_translating_authored_content(self):
        root=self.root();(root/'daily').mkdir()
        document={'v':1,'lang':'en','greeting':'Sign in','opening':'Website language','sections':[
            ['notes',[['p','Password'],['weather',[['temperature','14°C','Original forecast.']]],['tasks',[['partial','Today','Original detail.']]]]] ]}
        source=root/'daily/2026-10-11.gm.json';source.write_text(native.encode(document));original=source.read_bytes()
        app=BrowserApp(root,FakeChamber(),now=lambda:datetime(2026,10,11,12,tzinfo=timezone.utc))
        for value in ('en','zh-CN'):
            with selected(value):
                page=app.page('2026-10-11','gm',False).decode()
                self.assertIn(f'<html lang="{value}"',page)
                self.assertIn('>Sign in</h1>',page)
                self.assertIn('<p>Password</p>',page)
                self.assertIn('>Today</div>',page)
                self.assertNotIn('class="briefing-tools"',page)
                self.assertIn('气温' if value=='zh-CN' else 'Temperature',page)
                self.assertIn('部分完成' if value=='zh-CN' else 'Partial',page)
                self.assertIn('data-ui-date="2026-10-11"',page)
                self.assertEqual(app.chat_settings()['defaultMode'],'secretary')
        self.assertEqual(source.read_bytes(),original)
        self.assertEqual(len(app.cache.items),2)
        with selected('zh-CN'):
            page=ui.page(app.chat_page().decode(),'new-csrf','/chat?id='+'a'*32)
            self.assertIn('name="return_to" value="/chat?id='+'a'*32+'"',page)
            self.assertIn('name="csrf" value="new-csrf"',page)
            self.assertEqual(page.count('id="language-form"'),1)

    def test_browser_setup_uses_website_language_without_changing_local_preferences(self):
        root=self.root();original=(root/'profile.md').read_bytes()
        self.assertIn('secretary_language',profile_status(root,profile_fields(root))['missing_fields'])
        context=prepare(root,'todo',website_language='zh-CN')
        self.assertTrue(context['ready']);self.assertEqual(context['profile']['secretary_language'],'Simplified Chinese')
        output=io.StringIO()
        with redirect_stdout(output):self.assertEqual(setup(['--secretary-dir',str(root),'--website-language','zh-CN']),0)
        self.assertEqual(json.loads(output.getvalue())['language_status'],'website')
        self.assertEqual((root/'profile.md').read_bytes(),original)

    def test_chat_turns_pin_language_and_keep_request_idempotence(self):
        root=self.root();chamber=MockChamber(root);chats=Chats(root,chamber)
        with patch('goodmorning.web.briefing_chat.threading.Thread',ImmediateThread):
            with selected('zh-CN'):chats.start({'id':'a'*32,'mode':'todo','text':'Keep original wording.'})
            with selected('en'):
                chats.start({'id':'a'*32,'mode':'todo','text':'Keep original wording.'})
                chats.send('a'*32,{'id':'b'*32,'text':'A new reply.'})
        prompts=[body['prompt'] for action,body in chamber.calls if action=='session.send']
        self.assertEqual(len(prompts),2)
        self.assertIn('Website language: zh-CN',prompts[0]);self.assertIn('Website language: en',prompts[1])
        self.assertEqual(chats.get('a'*32)['turns'][0]['language'],'zh-CN')
        self.assertEqual(chats.status('a'*32)['messages'][0]['text'],'Keep original wording.')

    def test_briefing_language_stays_pinned_after_interface_change(self):
        root=self.root();(root/'daily').mkdir();chamber=FakeChamber()
        app=BrowserApp(root,chamber,now=lambda:datetime(2026,10,11,12,tzinfo=timezone.utc),preflight=True)
        with selected('zh-CN'):
            with patch('goodmorning.web.briefing_server.threading.Thread',ImmediateThread):job=app.start('2026-10-11','gm')['job']
        with selected('en'):
            receipt=act(root,job,'ses_fixture','prepare')
            self.assertEqual(receipt['website_language'],'zh-CN')
            self.assertEqual(receipt['profile']['secretary_language'],'Simplified Chinese')
            initialized=act(root,job,'ses_fixture','init',{'greeting':'早上好。','opening':'今天的计划。','plan':[['notes','备注']]})
            self.assertEqual(initialized['next']['section'],['notes','备注'])
            act(root,job,'ses_fixture','publish',{'position':0,'section':['notes',[['p','保留实际信息。']]]})
            act(root,job,'ses_fixture','finish',{})
        document=native.parse((root/'daily/2026-10-11.gm.json').read_text())
        self.assertEqual(document['lang'],'zh-CN')
        self.assertFalse('secretary_language' in profile_fields(root))


if __name__=='__main__':unittest.main()
