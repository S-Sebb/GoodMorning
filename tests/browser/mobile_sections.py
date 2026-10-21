"""Touch section picker on saved synthetic briefings; no accounts or model calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import expect, sync_playwright

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'src'))
from goodmorning.briefings.briefing_day import briefing_day
from goodmorning.briefings.briefing_document import encode


def main():
    artifacts=Path(sys.argv[1]);artifacts.mkdir(mode=0o700,parents=True,exist_ok=True)
    checks=[]
    with tempfile.TemporaryDirectory(dir='/tmp/opencode',prefix='gm-mobile-sections-') as directory:
        root=Path(directory);(root/'daily').mkdir()
        (root/'profile.md').write_text('secretary_language: English\ntimezone: Europe/London\ncity: London, GB\nnews_country: GB\n')
        document=encode({'v':1,'lang':'en','greeting':'Synthetic navigation test.','opening':'Preserved sample records.',
            'sections':[['news',[['news','World',[['Synthetic headline '+str(story),'Synthetic summary. '*12,[['Publisher','https://example.org/a']]]
                                                  for story in range(4)]]],'','Synthetic section 7'] if index==6 else
                        ['notes',[['p','Synthetic reading content, unchanged by navigation. '*12] for _ in range(4)],'',
                         'Synthetic section '+str(index+1)] for index in range(10)]})
        day=briefing_day('Europe/London')
        for kind in ('gm','gn'):(root/'daily'/f'{day}.{kind}.json').write_text(document)
        server=subprocess.Popen([sys.executable,str(REPO/'tests/test_briefing_server.py'),'--serve-fixture',directory],
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            address=server.stdout.readline().strip().removeprefix('Private live viewer: ')
            with sync_playwright() as playwright:
                for engine in (playwright.chromium,):
                    browser=engine.launch()
                    for width,height in ((390,844),(320,568),(844,390)):
                        page=browser.new_page(viewport={'width':width,'height':height},is_mobile=True,has_touch=True,reduced_motion='reduce')
                        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                        for kind,scheme in (('gm','classic'),('gm','warm'),('gn','classic')):
                            for language in ('en','zh-CN'):
                                page.goto(address+f'/{kind}.html')
                                page.locator('#prefs-menu > summary').click()
                                page.locator('#website-language').select_option(language)
                                expect(page.locator('html')).to_have_attribute('lang',language)
                                page.locator('#prefs-menu > summary').click()
                                page.evaluate('scheme=>document.documentElement.dataset.dayScheme=scheme',scheme)
                                button=page.locator('#mobile-sections');dialog=page.locator('#mobile-section-dialog')
                                if width>700:
                                    expect(button).to_be_hidden();expect(page.locator('.scroll-map')).to_be_visible()
                                    continue
                                expect(button).to_be_visible()
                                page.locator('#section-6').scroll_into_view_if_needed()
                                expect(page.locator('.briefing-section-nav')).not_to_be_in_viewport()
                                expect(button).to_be_in_viewport()
                                previous=page.evaluate('scrollY')
                                button.tap();expect(dialog).to_be_visible()
                                expect(button).to_have_attribute('aria-expanded','true')
                                assert abs(page.evaluate('scrollY')-previous)<2
                                links=dialog.locator('a');expect(links).to_have_count(10)
                                expect(dialog.locator('[aria-current]')).to_have_count(1)
                                assert links.first.bounding_box()['height']>=44
                                bounds=dialog.bounding_box()
                                assert 0<=bounds['x'] and bounds['y']>=0 and bounds['y']+bounds['height']<=height,bounds
                                page.screenshot(path=str(artifacts/f'picker-{engine.name}-{kind}-{scheme}-{width}-{language}.png'))
                                links.nth(1).tap()
                                expect(dialog).not_to_be_visible()
                                expect(page).to_have_url(address+f'/{kind}.html#section-2')
                                expect(page.locator('#section-2')).to_be_focused()
                                expect(page.locator('#section-2')).to_be_in_viewport()
                                button.tap();expect(dialog).to_be_visible()
                                expect(dialog.locator('a[href="#section-2"]')).to_have_attribute('aria-current','location')
                                page.keyboard.press('Escape');expect(dialog).not_to_be_visible()
                                expect(button).to_be_focused()
                                page.wait_for_function('() => !document.documentElement.classList.contains("section-picker-open")')
                                button.tap();page.locator('#close-sections').tap();expect(dialog).not_to_be_visible()
                                button.tap();page.touchscreen.tap(width/2,10);expect(dialog).not_to_be_visible()
                                # Updated/hidden sections never leave stale choices in the sheet.
                                page.evaluate("document.querySelector('#section-10').hidden=true;document.dispatchEvent(new Event('briefing:updated'))")
                                expect(dialog.locator('a')).to_have_count(9)
                                page.set_viewport_size({'width':1200,'height':900})
                                expect(button).to_be_hidden()
                                page.set_viewport_size({'width':width,'height':height})
                                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                                checks.append({'engine':engine.name,'width':width,'edition':kind,'scheme':scheme,'language':language,
                                               'jumpFromMidPage':True,'twoTapNavigation':True,'currentSectionMarked':True,'dismissal':True,'dynamicSections':True})
                        assert not errors,errors
                        page.close()
                    page=browser.new_page(viewport={'width':390,'height':844},java_script_enabled=False)
                    page.goto(address+'/gm.html');expect(page.locator('#mobile-sections')).to_be_hidden()
                    page.locator('.briefing-section-nav a').nth(1).click()
                    expect(page).to_have_url(address+'/gm.html#section-2')
                    page.close()
                    # The app's News widget opens ?section=news and lands on the news section's own anchor.
                    page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
                    page.goto(address+'/gm.html?section=news')
                    expect(page).to_have_url(address+'/gm.html#section-7')
                    expect(page.locator('#section-7')).to_be_in_viewport()
                    # The page's 32px scroll padding plus the section's 32px scroll margin.
                    top=page.evaluate("document.querySelector('#section-7').getBoundingClientRect().top")
                    assert abs(top-64)<2,top
                    page.goto(address+'/gn.html?section=missing')
                    expect(page).to_have_url(address+'/gn.html');assert page.evaluate('scrollY')==0
                    page.close();browser.close()
            assert all((root/'daily'/f'{day}.{kind}.json').read_text()==document for kind in ('gm','gn'))
        finally:
            server.terminate();server.communicate(timeout=5)
    report={'modelCalls':0,'checks':checks,'nativeAnchorsWithoutJavaScript':True,'savedBriefingsUnchanged':True}
    (artifacts/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))


if __name__=='__main__':main()
