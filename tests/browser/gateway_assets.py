"""Browser asset/error checks through a real gateway and isolated synthetic viewer.

Run locally with: python tests/browser/gateway_assets.py
Every browser request is intercepted; no production requests or model calls occur.
"""
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
from support import TEMP_ROOT, returning_viewer
from support import GatewayFixture
from support import start_server
from test_weekly_schedule import make_runtime, canonical_records
from support import FakeChamber
from goodmorning.web.release import patch_notes
from playwright.sync_api import sync_playwright, expect


def main():
    fixture=GatewayFixture();fixture.setUp()
    viewer=None
    try:
        fixture.permanent()
        fixture.store.release_seen(fixture.id,patch_notes()[0]['version'])
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT,prefix='assets-gateway-') as directory:
            app=make_runtime(Path(directory));canonical_records(app.runtime);returning_viewer(app.runtime)
            app.chamber=FakeChamber()
            viewer=start_server(app)
            (fixture.root/'backends.json').write_text(json.dumps({fixture.id:{'port':viewer.server_port,'key':fixture.key}}))
            origin=f'http://127.0.0.1:{viewer.server_port}'
            fault={'status':None};posts=[];asset_errors=[];browser_errors=[];seen_assets=set();cases=0

            def forward(route):
                req=route.request;parsed=urlsplit(req.url)
                assert req.url.startswith(origin+'/'), 'External browser traffic is forbidden'
                target=parsed.path+('?' + parsed.query if parsed.query else '')
                if parsed.path=='/api/generate' and req.method=='POST':
                    posts.append(fault['status'])
                    assert fault['status'] in (429,502), 'No model dispatch is allowed'
                    return route.fulfill(status=fault['status'],content_type='text/html',body='<html>Synthetic upstream error</html>')
                body=json.loads(req.post_data) if req.method=='POST' and req.post_data else None
                headers={key:value for key,value in req.headers.items() if key.lower() in ('if-none-match','content-type','x-briefing-csrf')}
                status,returned,data=fixture.request(target,body=body,headers=headers,method=req.method)
                if parsed.path.startswith('/assets/'):
                    seen_assets.add(parsed.path)
                    if status not in (200,304):asset_errors.append({'path':parsed.path,'status':status})
                # Real gateway responses, with only the NGINX-facing transport simulated.
                returned={key:value for key,value in returned.items() if key.lower() not in ('content-length','set-cookie','transfer-encoding')}
                route.fulfill(status=status,headers=returned,body=data)

            with sync_playwright() as p:
                browser=p.chromium.launch()
                for language in ('en','zh-CN'):
                    fixture.store.website_language(fixture.id,language)
                    for width in (1440,390):
                        context=browser.new_context(viewport={'width':width,'height':950})
                        context.route('**/*',forward)
                        page=context.new_page();page.on('pageerror',lambda e:browser_errors.append(str(e)))
                        for path in ('/gm.html','/gn.html','/schedule','/letters','/chat'):
                            page.goto(origin+path);page.evaluate('document.fonts.ready')
                            links=page.locator('.edition-switch .edition-link');expect(links).to_have_count(5)
                            for link in links.all():
                                value=link.evaluate('el => getComputedStyle(el,"::before").backgroundImage')
                                assert '/assets/' in value
                                page.evaluate('''async url => {
                                    const image=new Image(); image.src=url; await image.decode();
                                    if (!image.naturalWidth) throw new Error('Icon failed');
                                }''',value.split('"')[1])
                            # Closed avatar pickers intentionally contain hidden lazy images.
                            for image in page.locator('img[src*="/assets/"]:visible').all():
                                expect(image).to_be_visible()
                                assert image.evaluate('el => el.complete && el.naturalWidth > 0')
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                            cases+=1
                        page.goto(origin+'/gm.html')
                        for code,english,chinese in ((429,'Too many requests','请求过于频繁'),(502,'temporarily unavailable','暂时不可用')):
                            fault['status']=code;count=len(posts)
                            page.locator('#generate').click()
                            expect(page.locator('#generation-error')).to_contain_text(english if language=='en' else chinese)
                            expect(page.locator('#generate')).to_be_enabled()
                            assert len(posts)==count+1, 'Mutation was replayed'
                        fault['status']=None;context.close()
                browser.close()
            assert not asset_errors,asset_errors
            assert not browser_errors,browser_errors
            print(json.dumps({'modelCalls':0,'productionRequests':0,'syntheticGatewayPageCases':cases,
                'languages':['en','zh-CN'],'widths':[1440,390],'distinctPublicAssets':len(seen_assets),
                'assetFailures':0,'browserErrors':0,'html429And502Readable':True,'mutationsNotReplayed':True}))
    finally:
        if viewer:viewer.shutdown();viewer.server_close()
        fixture.doCleanups()


if __name__=='__main__':main()
