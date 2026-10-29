"""Bilingual browser flow through the real gateway and isolated synthetic backends."""
import json
from datetime import date as Date, timedelta
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import time

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'src'));sys.path.insert(0,str(REPO/'tests'))


def fixture(root, hosts=None):
    from http.server import ThreadingHTTPServer
    from goodmorning.security.briefing_accounts import Accounts
    from goodmorning.security.briefing_gateway import Gateway, handler_for
    from goodmorning.web.briefing_server import BrowserApp, serve_live
    from goodmorning.briefings.briefing_day import briefing_day
    from goodmorning.briefings.briefing_document import encode
    from support import MockChamber
    if hosts is None:
        hosts={kind+'.language.test':kind for kind in ('gm','gn','sec')}
    origins=['https://'+host for host in hosts]
    (root/'accounts').mkdir(mode=0o700)
    store=Accounts(root/'accounts',testing=True,n=1024)
    registry={};runtimes={};day=briefing_day('Europe/London')
    class LanguageChamber(MockChamber):
        def control(self,action,**body):
            result=super().control(action,**body)
            if action=='session.send' and body['prompt'].startswith('/initialize') and 'Website language: zh-CN' in body['prompt']:
                session=self.sessions[body['sessionId']]
                session['messages'][-1]['text']='请确认你的所在地，回复使用网站语言。'
                session['forms'][0]['title']='确认所在地'
                session['forms'][0]['fields'][0]['title']='城市'
            return result
    for name in ('alice','bob'):
        identifier=store.create(name,'a1'+name+'-temporary')
        runtime=root/name;runtime.mkdir(mode=0o700);runtimes[name]=str(runtime)
        if name=='alice':
            (runtime/'profile.md').write_text('city: London\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n')
            (runtime/'daily').mkdir()
            document={'v':1,'lang':'en','greeting':'Existing English briefing','opening':'Original saved introduction.',
                      'sections':[['notes',[['p','Password']]],['today',[['tasks',[['open','Original task','Keep this exact wording.']]]]],
                                  ['schedule',[['agenda',[[(Date.fromisoformat(day)+timedelta(days=offset)).isoformat(),'09:00',f'Original event {offset}','Room','Bring notes'] for offset in (1,2)]],
                                               ['flexible',[[(Date.fromisoformat(day)+timedelta(days=1)).isoformat(),'open','Original untimed work','Keep this detail.']]]]]]}
            for kind in ('gm','gn'):(runtime/'daily'/(day+'.'+kind+'.json')).write_text(encode(document))
        with socket.socket() as check:
            check.bind(('127.0.0.1',0));port=check.getsockname()[1]
        key=secrets.token_urlsafe(32)
        app=BrowserApp(runtime,LanguageChamber(runtime),preflight=True)
        threading.Thread(target=serve_live,args=(app,port),kwargs={'gateway_key':key,'public_origins':origins},daemon=True).start()
        deadline=time.monotonic()+15
        while True:
            try:
                request=Request('http://127.0.0.1:'+str(port)+'/api/chats',headers={'Authorization':'Bearer '+key,'X-GoodMorning-Origin':origins[-1]})
                with urlopen(request,timeout=2) as response:assert response.status==200
                break
            except Exception:
                if time.monotonic()>=deadline:raise
                time.sleep(.1)
        registry[identifier]={'port':port,'key':key}
    (root/'accounts/backends.json').write_text(json.dumps(registry))
    gateway=ThreadingHTTPServer(('127.0.0.1',0),handler_for(Gateway(store,hosts,testing=True)))
    print(json.dumps({'gateway':'http://127.0.0.1:'+str(gateway.server_port),'runtimes':runtimes,'date':day}),flush=True)
    gateway.serve_forever()


def run(artifacts):
    from playwright.sync_api import sync_playwright, expect
    artifacts.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode',prefix='gm-language-browser-') as directory:
        root=Path(directory)
        process=subprocess.Popen([sys.executable,__file__,'--serve',directory],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        while True:
            line=process.stdout.readline()
            if line.startswith('{'):settings=json.loads(line);break
            if not line:
                raise RuntimeError('Language fixture failed to start: '+process.stderr.read()[-1500:])
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch()
                def context(**kwargs):
                    result=browser.new_context(**kwargs)
                    def forward(route):
                        request=route.request;parsed=urlsplit(request.url)
                        headers={**request.all_headers(),'Host':parsed.hostname,'X-Forwarded-Proto':'https','X-Real-IP':'192.0.2.1'}
                        response=route.fetch(url=settings['gateway']+parsed.path+('?' + parsed.query if parsed.query else ''),headers=headers,max_redirects=0)
                        route.fulfill(response=response)
                    result.route('https://*.language.test/**',forward)
                    return result
                def login(page,host,name,password):
                    page.goto('https://'+host+'.language.test/login')
                    page.locator('input[name=username]').fill(name)
                    page.locator('#password-password').fill(password)
                    page.locator('#account-form button[type=submit]').click()
                    expect(page).not_to_have_url('https://'+host+'.language.test/login')
                def open_prefs(page):
                    if page.locator('details.menu:has(#website-language)').get_attribute('open') is None:
                        page.locator('details.menu:has(#website-language) > summary').click()
                def switch(page,value):
                    expect(page.locator('#language-form button[type=submit]')).to_have_count(0)
                    open_prefs(page)
                    page.locator('#website-language').select_option(value)
                    expect(page.locator('html')).to_have_attribute('lang',value)
                    if page.locator('details.menu:has(#website-language)').get_attribute('open') is not None:
                        page.locator('details.menu:has(#website-language) > summary').click()
                def no_overflow(page):
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                desktop=context(viewport={'width':1440,'height':900},reduced_motion='reduce')
                page=desktop.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto('https://sec.language.test/login')
                page.locator('#password-password').fill('a1alice-temporary')
                page.get_by_role('button',name='Show password').click()
                switch(page,'zh-CN')
                expect(page.locator('#password-password')).to_have_value('a1alice-temporary')
                expect(page.locator('#password-password')).to_have_attribute('type','text')
                expect(page.get_by_role('button',name='隐藏密码')).to_be_visible()
                for host in ('gm','gn'):
                    other=desktop.new_page();other.goto('https://'+host+'.language.test/login')
                    expect(other.get_by_role('heading',name='登录',exact=True)).to_be_visible();other.close()
                login(page,'sec','alice','a1alice-temporary')
                expect(page.get_by_role('heading',name='修改密码',exact=True)).to_be_visible()
                expect(page.get_by_role('dialog',name='更新日志',exact=True)).to_be_visible()
                page.locator('#patch-note-dismiss').click()
                expect(page.locator('#site-patch-note')).to_be_hidden()
                page.locator('input[name=current]').fill('a1alice-temporary')
                page.locator('input[name=replacement]').fill('a1alice-permanent')
                page.locator('input[name=repeat]').fill('a1alice-permanent')
                page.locator('#account-form button[type=submit]').click()
                expect(page.locator('#chat-compose')).to_be_visible()
                def avatar(page, selected):
                    if page.locator('#account-menu').get_attribute('open') is None:
                        page.locator('#account-menu > summary').click()
                    page.locator(f'#account-menu [data-avatar-choice="{selected}"]').click()
                    expect(page.locator('#avatar-settings')).to_have_attribute('aria-busy','false')
                    expect(page.locator('.avatar-display')).to_have_attribute('data-avatar',selected)
                    page.keyboard.press('Escape')
                avatar(page,'f2')
                page.get_by_role('button',name='提醒我…',exact=True).click()
                expect(page.locator('#chat-text')).to_have_value('提醒我')
                page.locator('#chat-text').fill('Keep this unsent draft: 原文。')
                switch(page,'en');expect(page.locator('#chat-text')).to_have_value('Keep this unsent draft: 原文。')
                expect(page.get_by_role('button',name='Remind me to…',exact=True)).to_be_visible()
                switch(page,'zh-CN')
                expect(page.locator('#chat-text')).to_have_value('Keep this unsent draft: 原文。')
                page.get_by_role('button',name='我可以问点什么？',exact=True).click()
                expect(page.locator('#chat-guide [data-guide="secretary"]')).to_contain_text('秘书会告诉你')
                page.screenshot(path=str(artifacts/'chinese-chat-desktop.png'),full_page=True)
                no_overflow(page)
                # Each host has its own login, but the same account's saved language wins.
                for host in ('gm','gn'):
                    other=desktop.new_page();login(other,host,'alice','a1alice-permanent')
                    other.on('pageerror',lambda error:errors.append(str(error)))
                    expect(other.locator('html')).to_have_attribute('lang','zh-CN')
                    expect(other.locator('.avatar-display')).to_have_attribute('data-avatar','f2')
                    expect(other.get_by_role('heading',name='Existing English briefing',exact=True)).to_be_visible()
                    expect(other.locator('article')).to_contain_text('Password')
                    expect(other.locator('.briefing-tools')).to_have_count(0)
                    expect(other.locator('.agenda-day').first).to_contain_text('明天')
                    expect(other.locator('.agenda .agenda-day')).to_have_count(2)
                    expect(other.locator('.agenda-event')).to_have_count(2)
                    expect(other.locator('.flexible-title')).to_have_text('灵活安排')
                    expect(other.locator('.flexible-schedule .agenda-day')).to_contain_text('明天')
                    expect(other.locator('.flexible-schedule')).to_contain_text('Original untimed work')
                    switch(other,'en')
                    expect(other.locator('.flexible-title')).to_have_text('Flexible schedule')
                    expect(other.locator('.flexible-schedule .agenda-day')).to_contain_text('Tomorrow')
                    expect(other.locator('.agenda-day').first).to_contain_text('Tomorrow')
                    tomorrow=Date.fromisoformat(settings['date'])+timedelta(days=1)
                    expect(other.locator('.agenda-day').first).to_contain_text(tomorrow.strftime('%A'))
                    expect(other.locator('.agenda-day').first).to_contain_text(tomorrow.strftime('%B ') + str(tomorrow.day))
                    for width in (320,390,1440):
                        other.set_viewport_size({'width':width,'height':900})
                        no_overflow(other)
                        expect(other.locator('.agenda-day').first).to_be_visible()
                        other.locator('.agenda').screenshot(path=str(artifacts/(host+'-agenda-'+str(width)+'-en.png')))
                        other.locator('.flexible-schedule').screenshot(path=str(artifacts/(host+'-flexible-'+str(width)+'-en.png')))
                    switch(other,'zh-CN')
                    for width in (320,390,1440):
                        other.set_viewport_size({'width':width,'height':900})
                        no_overflow(other)
                        expect(other.locator('.agenda-day').first).to_contain_text('明天')
                        other.locator('.agenda').screenshot(path=str(artifacts/(host+'-agenda-'+str(width)+'-zh-CN.png')))
                        expect(other.locator('.flexible-title')).to_have_text('灵活安排')
                        other.locator('.flexible-schedule').screenshot(path=str(artifacts/(host+'-flexible-'+str(width)+'-zh-CN.png')))
                    other.goto(f'https://{host}.language.test/d/{settings["date"]}/{host}')
                    expect(other.get_by_role('heading',name='Existing English briefing',exact=True)).to_be_visible()
                    no_overflow(other);other.screenshot(path=str(artifacts/(host+'-chinese-archive.png')),full_page=True);other.close()
                # A separate device inherits account language rather than its default English cookie.
                second=context(viewport={'width':320,'height':760},reduced_motion='reduce')
                mobile=second.new_page();mobile.on('pageerror',lambda error:errors.append(str(error)))
                login(mobile,'sec','alice','a1alice-permanent');expect(mobile.locator('html')).to_have_attribute('lang','zh-CN')
                expect(mobile.locator('#site-update-toggle')).to_be_visible()
                expect(mobile.locator('#site-patch-note')).to_be_hidden()
                expect(mobile.locator('.avatar-display')).to_have_attribute('data-avatar','f2')
                avatar(mobile,'m2')
                page.evaluate("window.dispatchEvent(new Event('focus'))")
                expect(page.locator('.avatar-display')).to_have_attribute('data-avatar','m2')
                no_overflow(mobile);mobile.screenshot(path=str(artifacts/'chinese-chat-320.png'),full_page=True)
                switch(mobile,'en')
                page.evaluate('syncWebsiteLanguage()');expect(page.locator('html')).to_have_attribute('lang','en')
                expect(page.locator('#chat-text')).to_have_value('Keep this unsent draft: 原文。')
                # Existing account content is byte-for-byte unchanged by language switches.
                documents=[(Path(settings['runtimes']['alice'])/'daily'/(settings['date']+'.'+kind+'.json')).read_bytes() for kind in ('gm','gn')]
                assert all(b'Original saved introduction.' in data for data in documents)
                # Fresh account: password change and setup in Chinese, with no reply-language question.
                fresh=context(viewport={'width':390,'height':844},reduced_motion='reduce');new=fresh.new_page()
                new.on('pageerror',lambda error:errors.append(str(error)));new.goto('https://sec.language.test/login');switch(new,'zh-CN')
                login(new,'sec','bob','a1bob-temporary')
                expect(new.get_by_role('dialog',name='更新日志',exact=True)).to_be_visible()
                new.locator('#patch-note-dismiss').click()
                expect(new.locator('#site-patch-note')).to_be_hidden()
                new.locator('input[name=current]').fill('a1bob-temporary');new.locator('input[name=replacement]').fill('a1bob-permanent');new.locator('input[name=repeat]').fill('a1bob-permanent')
                new.locator('#account-form button[type=submit]').click();expect(new.get_by_role('button',name='开始初始化')).to_be_visible()
                expect(new.locator('.avatar-display')).to_have_attribute('data-avatar','f1')
                avatar(new,'m1')
                page.evaluate("window.dispatchEvent(new Event('focus'))")
                expect(page.locator('.avatar-display')).to_have_attribute('data-avatar','m2')
                new.get_by_role('button',name='开始初始化').click()
                # Storage consent first, then setup's first question from code, both in Chinese.
                expect(new.get_by_role('heading',name='开始之前：GoodMorning 怎么保管你的信息')).to_be_visible()
                new.get_by_role('radio',name='我同意').check();new.get_by_role('button',name='提交回答').click()
                expect(new.get_by_role('heading',name='你想叫我什么？')).to_be_visible()
                new.get_by_role('radio',name='先跳过').check();new.get_by_role('button',name='提交回答').click()
                expect(new.get_by_role('heading',name='确认所在地')).to_be_visible()
                new.get_by_placeholder('或填写你自己的回答').fill('London, GB')
                switch(new,'en');expect(new.get_by_placeholder('Or write your own answer')).to_have_value('London, GB')
                expect(new.locator('#request-language-note')).to_contain_text('Simplified Chinese')
                new.get_by_role('button',name='Send answer',exact=True).click();expect(new.get_by_role('button',name='Allow once')).to_be_visible()
                new.get_by_role('button',name='Allow once').click();expect(new.get_by_role('button',name='Send reply')).to_be_enabled()
                expect(new.locator('.avatar-display')).to_have_attribute('data-avatar','m1')
                for name, selected in (('alice','m2'),('bob','m1')):
                    stored=json.loads((Path(settings['runtimes'][name])/'website-avatar.json').read_text())
                    assert stored=={'avatar':selected}
                from goodmorning.runtime_files import profile_fields
                assert not profile_fields(settings['runtimes']['bob']).get('secretary_language')  # Never a reply-language answer.
                switch(new,'zh-CN');new.get_by_role('button',name='新建对话').click()
                expect(new.locator('#chat-topic-mode')).to_have_text('秘书')
                expect(new.locator('#chat-welcome')).not_to_be_empty();expect(new.get_by_role('button',name='这周有什么安排？',exact=True)).to_be_visible();no_overflow(new)
                new.goto('https://sec.language.test/gm');expect(new.get_by_role('button',name='准备我的早报')).to_be_visible()
                no_overflow(new);new.screenshot(path=str(artifacts/'chinese-waiting-mobile.png'),full_page=True)
                new.goto('https://sec.language.test/gn');new.get_by_role('button',name='准备我的晚报').click()
                checkin=new.get_by_role('dialog')
                expect(checkin.get_by_role('heading',name='一起回顾一下今天')).to_be_visible()
                expect(checkin.locator('input[type=checkbox]')).to_have_count(0)
                checkin.get_by_placeholder('写下今天的进展，或其他想补充的事……').fill('保留这份未提交的进展。')
                new.keyboard.press('Escape')
                switch(new,'en')
                # Request text keeps its language; the dialog's own labels follow the website.
                new.get_by_role('button',name='Continue check-in').click()
                expect(checkin.get_by_role('heading',name='一起回顾一下今天')).to_be_visible()
                expect(checkin.get_by_placeholder('写下今天的进展，或其他想补充的事……')).to_have_value('保留这份未提交的进展。')
                expect(checkin.get_by_role('button',name='Save and write my briefing')).to_be_visible()
                expect(new.locator('#request-language-note')).to_contain_text('Simplified Chinese')
                new.keyboard.press('Escape')
                # Recovery uses a stable action, not a translated button label.
                switch(new,'zh-CN')
                with new.expect_response(lambda response:response.url.endswith('/recover')) as recovered:
                    new.get_by_role('button',name='刷新任务列表',exact=True).click()
                assert recovered.value.status==202
                expect(new.get_by_role('dialog').get_by_role('heading',name='一起回顾一下今天')).to_be_visible()
                assert not errors,errors
                assert page.evaluate('''() => localStorage.length === 0 && Object.entries(sessionStorage).every(([key,raw]) => {
                    if (!/^goodmorning\\.chat\\.workspace\\.[a-f0-9]{64}$/.test(key)) return false;
                    const saved=JSON.parse(raw);
                    return Object.keys(saved).sort().join(',') === 'away,chat,draft,resume'
                        && [saved.chat,saved.resume].every(value => value === null || /^[a-f0-9]{32}$/.test(value))
                        && typeof saved.draft === 'boolean'
                        && (saved.away === null || Number.isFinite(saved.away) && saved.away >= 0);
                })''')
                cookies=desktop.cookies()
                assert all(cookie['domain'].startswith('.') is False and cookie['httpOnly'] for cookie in cookies if cookie['name']=='__Host-GoodMorning')
                assert any(cookie['domain']=='.language.test' and not cookie['httpOnly'] for cookie in cookies if cookie['name']=='GoodMorningLanguage')
                plain=context(viewport={'width':320,'height':760},java_script_enabled=False)
                model_page=plain.new_page();model_page.goto('https://gm.language.test/login')
                expect(model_page.locator('#website-model')).to_have_count(0)
                expect(model_page.locator('#model-form')).to_have_count(0)
                model_page.close()
                fallback=plain.new_page();fallback.goto('https://gm.language.test/login')
                fallback.locator('details.menu:has(#website-language) > summary').click()
                fallback.locator('#website-language').select_option('zh-CN')
                # Redirected navigations bypass Playwright routing. Follow the verified
                # native redirect explicitly here; live HTTPS checks use no routing.
                with fallback.expect_response('https://gm.language.test/api/language') as changed:
                    fallback.locator('#language-form').get_by_role('button',name='Apply',exact=True).click()
                assert changed.value.status==303
                assert changed.value.headers['location']=='/login'
                fallback.close();fallback=plain.new_page()
                fallback.goto('https://gm.language.test/login')
                expect(fallback).to_have_url('https://gm.language.test/login')
                expect(fallback.locator('html')).to_have_attribute('lang','zh-CN')
                expect(fallback.get_by_role('heading',name='登录',exact=True)).to_be_visible()
                expect(fallback.locator('#account-form button[type=submit]')).to_be_disabled()
                expect(fallback.get_by_text('请启用 JavaScript 以登录或修改密码。',exact=True)).to_be_visible()
                no_overflow(fallback);fallback.screenshot(path=str(artifacts/'chinese-login-no-javascript-320.png'),full_page=True)
                plain.close()
                fresh.close();second.close();desktop.close();browser.close()
            report={'modelCalls':0,'localSyntheticGateway':True,'subdomains':3,'accountSync':True,'crossDeviceSync':True,
                    'avatarPerAccountIsolation':True,'avatarAcrossHostsAndDevices':True,'avatarSurvivesSetup':True,
                    'loginAndPasswordPages':True,'modeGuidance':True,'draftsAndPasswordVisibilityPreserved':True,
                    'activeRequestLanguagePinned':True,'savedContentPreserved':True,'nightPreflightAndRecoveryTranslated':True,
                    'noJavascriptLanguageSwitch':True,'instantLanguageSelectionWithoutApply':True,'prominentAgendaDayHeadings':True,
                    'mobileWidths':[320,390],'desktopWidth':1440}
            (artifacts/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
        finally:
            process.terminate();process.communicate(timeout=5)


if __name__=='__main__':
    if '--serve' in sys.argv:fixture(Path(sys.argv[-1]))
    else:run(Path(sys.argv[1]))
