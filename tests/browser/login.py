"""Public HTTPS login rendering only; no passwords, account access or model calls."""
import argparse
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright, expect


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts',type=Path,required=True)
    args=parser.parse_args()
    args.artifacts.mkdir(parents=True,exist_ok=True,mode=0o700)
    results=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch()
        try:
            for host in ('gm.love765.me','gn.love765.me','sec.love765.me'):
                for width in (390,768,1440):
                    context=browser.new_context(viewport={'width':width,'height':900},
                                                is_mobile=width==390,has_touch=width==390)
                    page=context.new_page();errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    response=page.goto('https://'+host+'/',wait_until='networkidle')
                    expect(page).to_have_url('https://'+host+'/login')
                    expect(page.get_by_role('heading',name='Sign in')).to_be_visible()
                    kind='secretary' if host.startswith('sec.') else host.split('.')[0]
                    icons=page.locator('head link[rel="icon"]')
                    expect(icons).to_have_count(2)
                    for href in icons.evaluate_all('(elements) => elements.map(element => element.href)'):
                        assert '/icons/'+kind+'.' in href
                        icon=context.request.get(href)
                        assert icon.status==200
                        assert icon.headers['content-type'] in ('image/png','image/svg+xml')
                    expect(page.get_by_label('Username',exact=True)).to_be_editable()
                    expect(page.get_by_label('Password',exact=True)).to_have_attribute('type','password')
                    password=page.get_by_label('Password',exact=True)
                    password.fill('Synthetic visibility check only')
                    page.get_by_role('button',name='Show password',exact=True).click()
                    expect(password).to_have_attribute('type','text')
                    expect(password).to_have_value('Synthetic visibility check only')
                    page.get_by_role('button',name='Hide password',exact=True).click()
                    expect(password).to_have_attribute('type','password')
                    password.fill('')
                    page.locator('#website-language').select_option('zh-CN')
                    expect(page.locator('#language-form button[type=submit]')).to_have_count(0)
                    expect(page.get_by_role('heading',name='登录',exact=True)).to_be_visible()
                    expect(page.locator('html')).to_have_attribute('lang','zh-CN')
                    expect(page.get_by_role('button',name='显示密码',exact=True)).to_be_visible()
                    expect(page.get_by_role('checkbox',name='在此设备上保持登录 60 天')).not_to_be_checked()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(args.artifacts/(host.split('.')[0]+'-'+str(width)+'-zh-CN.png')),full_page=True)
                    page.locator('#website-language').select_option('en')
                    expect(page.get_by_role('heading',name='Sign in',exact=True)).to_be_visible()
                    expect(page.get_by_role('checkbox',name='Remember me for 60 days on this device')).not_to_be_checked()
                    expect(page.get_by_role('button',name='Sign in',exact=True)).to_be_enabled()
                    assert response.status==200 and response.headers['cache-control']=='no-store'
                    assert 'frame-ancestors' in response.headers['content-security-policy']
                    cookies=context.cookies()
                    session=next(cookie for cookie in cookies if cookie['name']=='__Host-GoodMorning')
                    assert session['secure'] and session['httpOnly'] and session['sameSite']=='Strict'
                    assert session['domain']==host
                    measurements=page.evaluate('''() => ({width:innerWidth, content:document.documentElement.scrollWidth,
                        labels:[...document.querySelectorAll('input:not([type=hidden])')].map(input => input.labels.length)})''')
                    assert measurements['content']<=measurements['width']
                    assert all(measurements['labels'])
                    assert not errors
                    page.screenshot(path=str(args.artifacts/(host.split('.')[0]+'-'+str(width)+'.png')),full_page=True)
                    api=context.request.get('https://'+host+'/api/jobs/'+('a'*32))
                    assert api.status==401
                    results.append({'host':host,'width':width,'overflow':False,'pageErrors':0,
                                    'hostOnlySecureCookie':True,'privateAPIStatus':api.status,'tabIcon':kind,'iconFormats':['PNG','SVG'],
                                    'languages':['en','zh-CN']})
                    context.close()
                    time.sleep(4)  # Respect the production auth rate limit, not an assertion wait.
            plain=browser.new_context(java_script_enabled=False,viewport={'width':320,'height':760})
            page=plain.new_page();page.goto('https://gm.love765.me/login')
            page.locator('#website-language').select_option('zh-CN')
            page.get_by_role('button',name='Apply',exact=True).click()
            expect(page.get_by_role('heading',name='登录',exact=True)).to_be_visible()
            expect(page.locator('#account-form button[type=submit]')).to_be_disabled()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            for host in ('gn.love765.me','sec.love765.me'):
                page.goto('https://'+host+'/login')
                expect(page.get_by_role('heading',name='登录',exact=True)).to_be_visible()
            results.append({'noJavascriptNativeRedirect':True,'anonymousLanguageSharedAcrossThreeHosts':True})
            plain.close()
        finally:
            browser.close()
    report={'modelCalls':0,'loggedIntoAccount':False,'engine':'Chromium','checks':results}
    (args.artifacts/'result.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':main()
