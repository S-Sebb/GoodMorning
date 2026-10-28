"""Account-wide language, secure switching, pinned requests and original-data preservation."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT, HOSTS, FakeChamber, ImmediateThread, MockChamber, form_post, gateway, selected, session_cookie
from goodmorning.web import language as ui
from goodmorning.web.briefing_chat import Chats
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.setup_check import profile_status, main as setup
from goodmorning.records.workflow import prepare
from goodmorning.runtime_files import profile_fields
from goodmorning.briefings import briefing_document as native
from goodmorning.briefings.briefing_job import act


def language(value): return selected(ui.CURRENT, value)


class LanguageTests(unittest.TestCase):
    def root(self):
        temporary=tempfile.TemporaryDirectory(dir=TEMP_ROOT);self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        (root/'profile.md').write_text('city: London, GB\ntimezone: Europe/London\nnews_country: GB\nsecretary_tone: Keep this tone.\n')
        return root

    def test_language_sync_is_account_wide_not_an_authentication_cookie(self):
        fixture=gateway(self);fixture.permanent()
        original=fixture.cookie
        status,headers,_=fixture.request('/api/language',{'language':'zh-CN'})
        self.assertEqual(status,200)
        self.assertIn('GoodMorningLanguage=zh-CN',headers['Set-Cookie'])
        self.assertIn('Domain=example.test',headers['Set-Cookie'])
        self.assertEqual(fixture.cookie,original)
        for host in HOSTS:
            status,_,body=fixture.request('/api/language',headers={'Host':host,'Cookie':session_cookie(fixture,fixture.id,host)})
            self.assertEqual((status,json.loads(body)['language']),(200,'zh-CN'))
        _,_,body=fixture.request('/api/language',headers={'Cookie':session_cookie(fixture,fixture.other)+'; GoodMorningLanguage=zh-CN'})
        self.assertEqual(json.loads(body)['language'],'en')
        self.assertIsNone(fixture.store.website_language(fixture.other))
        # The harmless sibling preference cannot authenticate a user on another host.
        self.assertEqual(fixture.request('/api/chats',headers={'Host':'gn.example.test','Cookie':original+'; GoodMorningLanguage=zh-CN'})[0],401)
        fixture.store.administer('alice',new_name='alice-new')
        self.assertEqual(fixture.store.website_language(fixture.id),'zh-CN')

    def test_anonymous_temporary_and_invalid_language_requests_keep_security_boundaries(self):
        fixture=gateway(self)
        fixture.request('/login')
        status,headers,body=fixture.request('/login')
        fixture.cookie=headers['Set-Cookie'].split(';')[0]
        fixture.csrf=re.search(rb'data-csrf="([a-f0-9]+)"',body)[1].decode()
        self.assertEqual(fixture.request('/api/language',{'language':'zh-CN'})[0],200)
        self.assertEqual(fixture.request('/api/language',{'language':'zh-CN'},headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(fixture.request('/api/language',{'language':'zh-CN'},headers={'X-Briefing-CSRF':'wrong'})[0],403)
        for bad in ('zh-TW','fr','<script>',None,{},True):
            self.assertEqual(fixture.request('/api/language',{'language':bad})[0],400)
        fixture.cookie=None
        status,_,body=fixture.request('/login',headers={'Cookie':'GoodMorningLanguage=zh-CN'})
        self.assertEqual(status,200);self.assertIn(ui.text('Sign in',lang='zh-CN'),body.decode());self.assertIn('lang="zh-CN"',body.decode())
        logged=fixture.login();fixture.csrf=logged['csrf']
        self.assertEqual(fixture.request('/api/language',{'language':'zh-CN'})[0],200)
        self.assertEqual(fixture.request('/api/chats')[0],403)
        _,_,page=fixture.request('/password')
        self.assertIn(ui.text('Change password',lang='zh-CN'),page.decode())

    def test_non_javascript_switch_has_csrf_and_safe_redirect(self):
        fixture=gateway(self);fixture.permanent()
        for target,expected in (('/chat','/chat'),('//evil.example','/'),('/chat?x=\r\nInjected: yes','/'),
                                ('/d/2026-10-11/gn','/d/2026-10-11/gn'),('/d/2026-10-11/gn.html','/d/2026-10-11/gn'),
                                ('/gm.html?section=news','/gm?section=news'),('/evil/gm.html','/')):
            status,headers=form_post(fixture,'/api/language',{'language':'zh-CN','csrf':fixture.csrf,'return_to':target})
            self.assertEqual((status,headers['Location']),(303,expected))
        self.assertEqual(fixture.store.website_language(fixture.id),'zh-CN')

    def test_language_headers_are_server_owned_and_settings_survive_logout(self):
        fixture=gateway(self);fixture.permanent()
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
            with language(value):
                page=app.page('2026-10-11','gm',False).decode()
                self.assertIn(f'<html lang="{value}"',page)
                self.assertIn('>Sign in</h1>',page)
                self.assertIn('<p>Password</p>',page)
                self.assertIn('>Today</div>',page)
                self.assertNotIn('class="briefing-tools"',page)
                self.assertIn(ui.text('Temperature',lang=value),page)
                self.assertIn(ui.text('Partial',lang=value),page)
                self.assertIn('data-ui-date="2026-10-11"',page)
                self.assertEqual(app.chat_settings()['defaultMode'],'secretary')
        self.assertEqual(source.read_bytes(),original)
        self.assertEqual(len(app.cache.items),2)
        with language('zh-CN'):
            page=ui.page(app.chat_page().decode(),'new-csrf','/chat?id='+'a'*32)
            self.assertIn('name="return_to" value="/chat?id='+'a'*32+'"',page)
            self.assertIn('name="csrf" value="new-csrf"',page)
            self.assertEqual(page.count('id="language-form"'),1)

    def test_browser_setup_uses_website_language_without_changing_local_preferences(self):
        root=self.root();original=(root/'profile.md').read_bytes()
        self.assertEqual(profile_status(root,profile_fields(root))['missing_fields'],['secretary_language'])
        context=prepare(root,'todo',website_language='zh-CN')
        self.assertTrue(context['ready']);self.assertEqual(context['profile']['secretary_language'],'Simplified Chinese')
        output=io.StringIO()
        with redirect_stdout(output):self.assertEqual(setup(['--secretary-dir',str(root),'--website-language','zh-CN']),0)
        self.assertEqual(json.loads(output.getvalue())['language_status'],'website')
        self.assertEqual((root/'profile.md').read_bytes(),original)

    def test_chinese_followups_keep_language_in_workers_with_english_defaults(self):
        root=self.root();profile=root/'profile.md'
        profile.write_text(profile.read_text()+'secretary_language: English\n')
        original=profile.read_bytes()
        chamber=MockChamber(root);chats=Chats(root,chamber);pending=[]
        class DeferredThread:
            def __init__(self,target,args,**_):
                self.target,self.args=target,args
            def start(self):
                pending.append(lambda:self.target(*self.args))
        messages=('像素格介于之前两版之间。','再微调一点，保留 Pixel size 标签。')
        with patch('goodmorning.web.briefing_chat.threading.Thread',DeferredThread):
            with language('zh-CN'):
                chats.start({'id':'a'*32,'mode':'secretary','text':messages[0]})
            with language('en'):pending.pop(0)()
            with language('zh-CN'):
                chats.send('a'*32,{'id':'b'*32,'text':messages[1]})
            with language('en'):pending.pop(0)()
        prompts=[body['prompt'] for action,body in chamber.calls if action=='session.send']
        self.assertEqual(len(prompts),2)
        for prompt,text in zip(prompts,messages):
            metadata,raw=prompt.split('\n\n',1)
            self.assertIn('Website language: zh-CN',metadata)
            self.assertEqual(raw,text)
        self.assertEqual([turn['language'] for turn in chats.get('a'*32)['turns']],['zh-CN','zh-CN'])
        self.assertEqual(profile.read_bytes(),original)

    def test_briefing_language_stays_pinned_after_interface_change(self):
        root=self.root();(root/'daily').mkdir();chamber=FakeChamber()
        app=BrowserApp(root,chamber,now=lambda:datetime(2026,10,11,12,tzinfo=timezone.utc),preflight=True)
        with language('zh-CN'):
            with patch('goodmorning.web.briefing_server.threading.Thread',ImmediateThread):job=app.start('2026-10-11','gm')['job']
        with language('en'):
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
