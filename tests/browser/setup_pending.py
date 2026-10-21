"""Synthetic gateway failures stay readable, localized and usable on all layouts."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from support import GatewayFixture
from goodmorning.web.release import patch_notes


def main():
    artifacts=Path(sys.argv[1]);artifacts.mkdir(parents=True,exist_ok=True,mode=0o700)
    results=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch()
        try:
            for pending in (True,False):
                for width in (390,768,1440):
                    fixture=GatewayFixture();fixture.setUp()
                    try:
                        fixture.permanent()
                        fixture.store.release_seen(fixture.id,patch_notes()[0]['version'])
                        if pending:(fixture.root/'backends.json').write_text('{}')
                        else:
                            failure=patch.object(fixture.gateway,'proxy',side_effect=RuntimeError('Synthetic outage'))
                            failure.start();fixture.addCleanup(failure.stop)
                        page=browser.new_page(viewport={'width':width,'height':900})
                        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                        def route(handler):
                            request=handler.request;parsed=urlsplit(request.url)
                            path=parsed.path+('?' + parsed.query if parsed.query else '')
                            body=request.post_data_json if request.method=='POST' else None
                            status,headers,data=fixture.request(path,body,method=request.method)
                            handler.fulfill(status=status,headers={key:value for key,value in headers.items()
                                if key.lower() not in ('content-length','set-cookie','connection','transfer-encoding')},body=data)
                        page.route('https://gm.example.test/**',route)
                        response=page.goto('https://gm.example.test/chat',wait_until='networkidle')
                        assert response.status==503
                        expect(page.get_by_role('heading',name='Secretary setup pending' if pending else 'Secretary temporarily unavailable',exact=True)).to_be_visible()
                        page.locator('details.menu:has(#website-language) > summary').click()
                        page.get_by_label('Website language',exact=True).select_option('zh-CN')
                        expect(page.get_by_role('heading',name='秘书服务尚未完成配置' if pending else '秘书服务暂时不可用',exact=True)).to_be_visible()
                        expect(page.locator('html')).to_have_attribute('lang','zh-CN')
                        page.get_by_role('button',name='关闭菜单',exact=True).click()
                        expect(page.get_by_role('link',name='重试',exact=True)).to_be_visible()
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        page.screenshot(path=str(artifacts/(('pending' if pending else 'outage')+'-'+str(width)+'.png')),full_page=True)
                        with page.expect_response('https://gm.example.test/chat') as retry:
                            page.get_by_role('link',name='重试',exact=True).click()
                        assert retry.value.status==503
                        page.locator('#account-menu > summary').click()
                        expect(page.get_by_role('link',name='修改密码',exact=True)).to_have_attribute('href','/password')
                        page.get_by_role('button',name='退出登录',exact=True).click()
                        expect(page).to_have_url('https://gm.example.test/login')
                        assert not errors,errors
                        results.append({'pending':pending,'width':width,'languages':['en','zh-CN'],'retry':True,'signOut':True,'overflow':False,'pageErrors':0})
                        page.close()
                    finally:fixture.doCleanups()
        finally:browser.close()
    report={'modelCalls':0,'productionAccounts':False,'checks':results}
    (artifacts/'result.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':main()
