"""Release notices, draft safety and refresh using isolated synthetic records."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/'src'));sys.path.insert(0, str(REPO/'tests'))
from goodmorning.briefings.briefing_day import briefing_day
from test_briefing_web import GM


def main():
    artifacts=Path(sys.argv[1]);artifacts.mkdir(parents=True,exist_ok=True,mode=0o700)
    cases=[]
    with tempfile.TemporaryDirectory(dir='/tmp/opencode',prefix='gm-update-browser-') as directory:
        root=Path(directory);(root/'daily').mkdir()
        (root/'profile.md').write_text('city: London\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n')
        day=briefing_day('Europe/London')
        for kind in ('gm','gn'):(root/'daily'/(day+'.'+kind+'.json')).write_text(GM)
        process=subprocess.Popen([sys.executable,str(REPO/'tests/test_briefing_chat.py'),'--serve-fixture',directory],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        address=process.stdout.readline().strip().removeprefix('Private live viewer: ')
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch()
                for path in ('/chat','/gm.html','/gn.html'):
                    for width in (320,390,1440):
                        context=browser.new_context(viewport={'width':width,'height':900},reduced_motion='reduce')
                        page=context.new_page();page.clock.install();errors=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        version={'value':None,'offline':False}
                        def release(route):
                            if version['offline']:route.abort();return
                            if version['value'] is None:route.continue_();return
                            route.fulfill(json={'version':version['value']},headers={'Cache-Control':'no-store'})
                        page.route('**/api/release',release)
                        page.goto(address+path)
                        page.locator('#website-language').select_option('en')
                        expect(page.locator('html')).to_have_attribute('lang','en')
                        expect(page.locator('#site-update')).to_be_hidden()
                        version['offline']=True;page.clock.run_for(61000)
                        expect(page.locator('#site-update')).to_be_hidden()
                        version['offline']=False
                        if path=='/chat':page.locator('#chat-text').fill('Preserve this unsent draft.')
                        version['value']='f'*64
                        page.clock.run_for(61000)
                        expect(page.locator('#site-update')).to_be_visible()
                        expect(page.get_by_role('button',name='Refresh',exact=True)).to_be_visible()
                        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                        if path=='/chat':
                            expect(page.locator('#chat-text')).to_have_value('Preserve this unsent draft.')
                            page.once('dialog',lambda dialog:dialog.dismiss())
                            page.get_by_role('button',name='Refresh',exact=True).click()
                            expect(page.locator('#chat-text')).to_have_value('Preserve this unsent draft.')
                        page.locator('#website-language').select_option('zh-CN')
                        expect(page.locator('html')).to_have_attribute('lang','zh-CN')
                        expect(page.locator('#site-update')).to_contain_text('网站有新版本可用')
                        page.screenshot(path=str(artifacts/(path.strip('/').replace('.html','')+'-'+str(width)+'.png')),full_page=True)
                        page.get_by_role('button',name='稍后',exact=True).click()
                        page.clock.run_for(61000)
                        expect(page.locator('#site-update')).to_be_hidden()
                        version['value']='e'*64;page.clock.run_for(61000)
                        expect(page.locator('#site-update')).to_be_visible()
                        # A reload must receive the new document, not merely update a label.
                        def new_document(route):
                            response=route.fetch()
                            source=re.sub(r'(id="site-release"[^>]*data-version=")[a-f0-9]{64}',r'\g<1>'+version['value'],response.text())
                            route.fulfill(response=response,body=source)
                        page.route('**'+path,new_document)
                        if path=='/chat':page.once('dialog',lambda dialog:dialog.accept())
                        with page.expect_event('domcontentloaded'):
                            page.get_by_role('button',name='刷新',exact=True).click()
                        expect(page.locator('#site-release')).to_have_attribute('data-version',version['value'])
                        expect(page.locator('#site-update')).to_be_hidden()
                        assert page.evaluate('localStorage.length===0 && sessionStorage.length===0')
                        assert not errors,errors
                        cases.append({'path':path,'width':width,'languages':['en','zh-CN'],'noAutomaticReload':True,'newReleaseLoaded':True,'persistentPrivateStorage':False})
                        context.close()
                # Outgoing requests must not be interrupted by the refresh button.
                page=browser.new_page();page.clock.install();page.goto(address+'/chat')
                page.locator('#website-language').select_option('en')
                expect(page.locator('html')).to_have_attribute('lang','en')
                page.route('**/api/release',lambda route:route.fulfill(json={'version':'f'*64}))
                held=[]
                def hold(route):
                    if route.request.method=='POST':held.append(route)
                    else:route.continue_()
                page.route('**/api/chats',hold)
                page.locator('#chat-text').fill('Synthetic pending request')
                with page.expect_request(lambda request:request.method=='POST' and request.url.endswith('/api/chats')):
                    page.locator('#chat-send').click()
                page.clock.run_for(61000)
                page.get_by_role('button',name='Refresh',exact=True).click()
                expect(page.locator('#update-feedback')).to_contain_text('finish sending')
                expect(page.locator('#chat-text')).to_have_value('Synthetic pending request')
                assert len(held)==1
                held[0].fulfill(status=400,json={'error':'Synthetic rejected request; no dispatch.'})
                page.close()
                page=browser.new_page();page.goto(address+'/chat?id='+('a'*32))
                expect(page).to_have_url(address+'/chat')
                expect(page.locator('#chat-send')).to_be_enabled()
                expect(page.locator('#chat-error')).not_to_be_empty()
                page.close();browser.close()
            result={'modelCalls':0,'cases':cases,'pendingMutationBlocksRefresh':True,'unsentDraftDismissAndConfirm':True,'deletedConversationRecoversToFreshChat':True}
            (artifacts/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
        finally:
            process.terminate();process.communicate(timeout=5)


if __name__=='__main__':main()
