"""Compact chat layout, centered welcome, private history preference and readable avatar note."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright, expect
from chat_markdown import contrast

REPO = Path(__file__).resolve().parents[2]


def check_compact(browser, address, artifacts):
    checks = []
    for width in (1440, 768, 390, 320):
        page = browser.new_page(viewport={'width':width, 'height':1000}, reduced_motion='reduce')
        errors = []; page.on('pageerror', lambda error:errors.append(str(error)))
        title = 'Secretary Review ST-Morph priorities'
        title_reads = []
        def listing(route):
            title_reads.append(True)
            pending = len(title_reads)==1
            route.fulfill(json={'defaultMode':'secretary', 'connected':True,
                'chats':[{'id':'a'*32, 'mode':'secretary', 'title':'Secretary' if pending else title,'title_pending':pending}]
                       +[{'id':format(index,'032x'),'mode':'todo','title':'Synthetic saved task '+str(index)} for index in range(40)]})
        page.route('**/api/chats', listing)
        page.goto(address+'/chat?mode=secretary')
        expect(page.locator('#chat-history a').first).to_contain_text(title)
        assert len(title_reads)>=2, 'Late native title never refreshed'
        expect(page.locator('#secretary-heading')).to_have_text('Your secretary')
        expect(page.locator('#mode-description')).to_have_count(0)
        expect(page.locator('#compose-note')).to_have_count(0)
        expect(page.locator('.attachment-controls')).to_have_count(0)
        clip = page.get_by_role('button',name='Attach files',exact=True)
        expect(clip.locator('svg')).to_have_count(1)
        assert clip.text_content()==''
        assert clip.evaluate("node => node.parentElement.classList.contains('chat-input-row') && node===node.parentElement.firstElementChild")
        if width>700:
            expect(page.locator('#conversation-history')).to_have_attribute('open', '')
        else:
            expect(page.locator('#conversation-history')).not_to_have_attribute('open')
        expect(page.locator('.chat-room-header')).to_have_count(0)
        expect(page.locator('#conversation-name')).to_have_css('clip', 'rect(0px, 0px, 0px, 0px)')
        page.evaluate('document.fonts.ready')
        for edition, scheme in (('gm','classic'), ('gm','warm'), ('gn','classic')):
            page.evaluate("([edition, scheme]) => { clearTimeout(themeTimer); document.documentElement.dataset.edition=edition; document.documentElement.dataset.dayScheme=scheme; }", [edition,scheme])
            geometry = page.evaluate('''() => {
                const scroll=document.querySelector('#chat-scroll'), box=scroll.getBoundingClientRect();
                const heading=document.querySelector('#chat-welcome').getBoundingClientRect();
                const hint=document.querySelector('#chat-hint').getBoundingClientRect();
                const symbol=document.querySelector('.desk-symbol').getBoundingClientRect();
                const style=getComputedStyle(scroll);
                const centerX=box.left+scroll.clientLeft+scroll.clientWidth/2;
                const centerY=box.top+scroll.clientTop+(scroll.clientHeight+parseFloat(style.paddingTop)-parseFloat(style.paddingBottom))/2;
                const controls=document.querySelector('.mode-controls').getBoundingClientRect();
                const panel=document.querySelector('.conversation-panel').getBoundingClientRect();
                return {headingOffset:heading.left+heading.width/2-centerX, hintOffset:hint.left+hint.width/2-centerX,
                    verticalOffset:(symbol.top+hint.bottom)/2-centerY, controlsTop:controls.top-panel.top,
                    scrollOverflow:scroll.scrollHeight-scroll.clientHeight};
            }''')
            assert abs(geometry['headingOffset']) <= 1 and abs(geometry['hintOffset']) <= 1, geometry
            assert abs(geometry['verticalOffset']) <= 2, geometry
            assert geometry['controlsTop'] <= 28 and geometry['scrollOverflow'] <= 1, geometry
            expect(page.locator('#mode-guide')).to_be_hidden()
            page.get_by_role('button', name='Which mode should I use?', exact=True).click()
            expect(page.locator('#mode-guide')).to_be_visible()
            expect(page.locator('#mode-guide strong')).to_have_count(4)
            expect(page.locator('#mode-guide')).to_contain_text('When in doubt, try it')
            expect(page.locator('#mode-guide')).to_contain_text('does not automatically start the work')
            page.locator('.conversation-panel').screenshot(path=str(artifacts/f'mode-guide-{edition}-{scheme}-{width}.png'))
            expect(page.locator('#mode-help')).to_have_attribute('aria-expanded','true')
            page.keyboard.press('Escape')
            expect(page.locator('#mode-guide')).to_be_hidden()
            expect(page.locator('#mode-help')).to_be_focused()
            labels = page.locator('[data-mode]').evaluate_all('''nodes => nodes.map(node => {
                const range=document.createRange();range.selectNodeContents(node);
                const text=range.getBoundingClientRect(), button=node.getBoundingClientRect();
                return text.left >= button.left && text.right <= button.right;
            })''')
            assert all(labels), (width,labels)
            page.locator('[data-avatar-toggle]').click()
            note = page.locator('.avatar-upload-note')
            expect(note).to_be_visible()
            colors = note.evaluate('node => ({ink:getComputedStyle(node).color, paper:getComputedStyle(node).backgroundColor})')
            assert colors['paper'] != 'rgba(0, 0, 0, 0)' and contrast(colors['ink'],colors['paper']) >= 4.5, colors
            page.locator('.avatar-menu').screenshot(path=str(artifacts/f'avatar-note-{edition}-{scheme}-{width}.png'))
            page.keyboard.press('Escape')
            page.locator('.conversation-panel').screenshot(path=str(artifacts/f'compact-chat-{edition}-{scheme}-{width}.png'))
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            if width>700:
                # Viewport-fit desktop: no page scroll, composer visible without scrolling.
                expect(page.locator('#chat-send')).to_be_in_viewport()
                aligned = page.evaluate('''() => {
                    const panel=document.querySelector('.conversation-panel').getBoundingClientRect();
                    const avatar=document.querySelector('.desk-figure').getBoundingClientRect();
                    const scroll=document.querySelector('#chat-scroll').getBoundingClientRect();
                    const composer=document.querySelector('#chat-compose').getBoundingClientRect();
                    const hist=document.querySelector('#chat-history');
                    return {panelTop:panel.top,avatarTop:avatar.top,panelBottom:panel.bottom,
                        scrollHeight:scroll.height,composerBottom:composer.bottom,
                        pageScrollable:document.documentElement.scrollHeight-innerHeight,
                        histClient:hist.clientHeight,histScroll:hist.scrollHeight};
                }''')
                assert aligned['pageScrollable']<=1, aligned
                assert 100<aligned['panelTop']<300 and abs(aligned['avatarTop']-aligned['panelTop'])<1, aligned
                assert aligned['panelBottom']<=1000 and aligned['composerBottom']<=1000, aligned
                assert 350<=aligned['scrollHeight']<=700, aligned
                assert aligned['histClient']<=241 and aligned['histScroll']>aligned['histClient'], aligned
                page.screenshot(path=str(artifacts/f'desktop-bottom-{edition}-{scheme}-{width}.png'))
            checks.append({'width':width,'edition':edition,'scheme':scheme, **geometry, 'avatarNoteContrast':round(contrast(colors['ink'],colors['paper']),2)})
        history = page.locator('#conversation-history')
        summary = history.locator('summary')
        if width>700:
            expect(history).to_have_attribute('open', '')
            summary.click()
            expect(history).not_to_have_attribute('open')
        else:
            # Small screens start collapsed so the chat is in view.
            expect(history).not_to_have_attribute('open')
            summary.click()
            expect(history).to_have_attribute('open', '')
            summary.click()
            expect(history).not_to_have_attribute('open')
        page.wait_for_function("() => localStorage.getItem('goodmorning.chat.history') === 'closed'")
        page.reload(); expect(history).not_to_have_attribute('open')
        summary.click()
        page.wait_for_function("() => localStorage.getItem('goodmorning.chat.history') === 'open'")
        page.reload(); expect(history).to_have_attribute('open','')
        assert page.evaluate("JSON.stringify(Object.keys(localStorage)) === '[\"goodmorning.chat.history\"]' && sessionStorage.length === 0")
        assert not errors, errors
        page.evaluate("secretaryName='Aurora';applySecretaryName()")
        expect(page.locator('#secretary-heading')).to_have_text('Aurora')
        if width>700:
            page.set_viewport_size({'width':width,'height':600})
            expect(page.locator('#chat-send')).to_be_in_viewport()
            short = page.locator('.conversation-panel').bounding_box()
            avatar = page.locator('.desk-figure').bounding_box()
            assert page.evaluate('document.documentElement.scrollHeight-innerHeight')<=1
            assert 100<short['y']<300 and abs(avatar['y']-short['y'])<1, (short,avatar)
            assert short['y']+short['height']<=601, short
            page.locator('#mode-help').click()
            expect(page.locator('#chat-send')).to_be_in_viewport()
            page.locator('.conversation-panel').screenshot(path=str(artifacts/f'short-desktop-help-{width}.png'))
        page.close()
    page = browser.new_page(viewport={'width':390,'height':1000})
    page.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new Error('Synthetic disabled storage'); }});")
    page.goto(address+'/chat?mode=secretary')
    expect(page.locator('#conversation-history')).not_to_have_attribute('open')
    page.locator('#conversation-history summary').click()
    expect(page.locator('#conversation-history')).to_have_attribute('open', '')
    page.close()
    return checks


def main():
    artifacts=Path(sys.argv[1]);artifacts.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode',prefix='gm-compact-') as directory:
        server=subprocess.Popen([sys.executable,str(REPO/'tests/test_briefing_chat.py'),'--serve-fixture',directory],
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            address=server.stdout.readline().strip().removeprefix('Private live viewer: ')
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch()
                checks=check_compact(browser,address,artifacts)
                browser.close()
        finally:
            server.terminate();server.communicate(timeout=5)
    report={'modelCalls':0,'checks':checks,'historyDefaultOpen':True,'historyChoiceRestored':True,'storageDisabledWorks':True}
    (artifacts/'result.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':main()
