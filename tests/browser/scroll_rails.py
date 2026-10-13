"""Phone drag rails, nested touch ownership and briefing reuse; synthetic data only."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright, expect
from chat_mobile_viewport import settle, keyboard_viewport

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'src'))
from goodmorning.briefings.briefing_day import briefing_day
from goodmorning.briefings.briefing_document import encode


def touch_drag(page, client, x, start, end):
    client.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x, 'y': start}]})
    for step in range(1, 9):
        client.send('Input.dispatchTouchEvent', {'type': 'touchMove',
                    'touchPoints': [{'x': x, 'y': start + (end - start) * step / 8}]})
        settle(page)
    client.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
    settle(page)


def drag_rail(page, client, rail, bottom):
    bounds = rail.bounding_box()
    thumb = rail.locator('.scroll-rail-thumb').bounding_box()
    touch_drag(page, client, bounds['x'] + bounds['width'] / 2,
               thumb['y'] + thumb['height'] / 2,
               bounds['y'] + bounds['height'] - 1 if bottom else bounds['y'] + 1)


def check_chat(browser, address, artifacts, width, height):
    page = browser.new_page(viewport={'width': width, 'height': height}, is_mobile=True,
                            has_touch=True, reduced_motion='reduce')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script("""(() => {
        window.keyboardViewport = {};
        for (const key of ['height', 'offsetTop', 'scale']) {
            const read = Object.getOwnPropertyDescriptor(VisualViewport.prototype, key).get;
            Object.defineProperty(visualViewport, key, {get: () => window.keyboardViewport[key] ?? read.call(visualViewport)});
        }
    })();""")
    messages = [{'id': str(index), 'role': 'assistant', 'text': f'Synthetic reply {index}.\nUseful context.\nPreserved history.'}
                for index in range(24)]
    status = {'mode': 'secretary', 'state': 'idle', 'language': 'en', 'label': '',
              'messages': messages, 'forms': [], 'permissions': []}
    page.route('**/api/chats', lambda route: route.fulfill(json={'defaultMode': 'secretary', 'connected': True, 'chats': []}))
    page.route('**/api/chats/*', lambda route: route.fulfill(json=status))
    page.goto(address + '/chat?id=' + 'f' * 32)
    expect(page.locator('.chat-message')).to_have_count(24)
    page.evaluate('document.fonts.ready')
    page.clock.install()
    page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
    text = page.get_by_label('Your message', exact=True)
    text.tap()
    text.fill('Keep this draft')
    page.clock.run_for(1500)
    outer = page.get_by_role('scrollbar', name='Scroll page', exact=True)
    inner = page.get_by_role('scrollbar', name='Scroll messages', exact=True)
    expect(outer).to_have_css('opacity', '0')
    expect(inner).to_have_css('opacity', '0')
    assert inner.evaluate('node => getComputedStyle(node).pointerEvents') == 'none'
    client = page.context.new_cdp_session(page)
    scroll = page.locator('#chat-scroll')
    scroll.evaluate('node => node.scrollTop = 400')
    expect(inner).to_have_css('opacity', '1')
    expect(outer).to_have_css('opacity', '1')
    expect(inner.locator('.scroll-rail-label')).to_contain_text('Messages')
    bounds = [rail.bounding_box() for rail in (inner, outer)]
    assert bounds[0]['x'] + bounds[0]['width'] <= bounds[1]['x'], bounds
    for rail in (inner, outer):
        assert rail.bounding_box()['width'] >= 24
        assert rail.locator('.scroll-rail-thumb').bounding_box()['height'] >= 44
        expect(rail).to_have_css('touch-action', 'none')
        expect(rail).to_have_css('transition-duration', '0s')

    # The message grip moves only history and never dismisses the draft keyboard.
    page_top = page.evaluate('scrollY')
    drag_rail(page, client, inner, True)
    assert page.evaluate('nearLatest()')
    assert page.evaluate('scrollY') == page_top
    expect(inner).to_have_attribute('aria-valuenow', '100')
    expect(inner.locator('.scroll-rail-label')).to_have_text('Messages · Latest')
    expect(text).to_be_focused()
    drag_rail(page, client, inner, False)
    assert scroll.evaluate('node => node.scrollTop') == 0
    assert page.evaluate('scrollY') == page_top

    # At both history boundaries, swiping the messages cannot hand off to the page.
    box = scroll.bounding_box()
    for bottom in (False, True):
        scroll.evaluate('''(node, bottom) => node.scrollTop = bottom ? node.scrollHeight : 0''', bottom)
        touch_drag(page, client, box['x'] + 8, box['y'] + box['height'] / 2,
                   box['y'] + box['height'] / 2 + (-100 if bottom else 100))
        page.clock.run_for(300)
        assert page.evaluate('scrollY') == page_top, 'History swipe spilled into the page'

    # The outer page has its own grip, even when the input remains focused.
    scroll.evaluate('node => node.scrollTop = 400')
    page.evaluate('window.scrollBy(0, -1)')
    expect(outer).to_have_css('opacity', '1')
    drag_rail(page, client, outer, False)
    assert page.evaluate('scrollY') == 0
    if scroll.bounding_box()['y'] >= height - 66:
        expect(inner).to_be_hidden()
    else:
        assert inner.bounding_box()['y'] >= scroll.bounding_box()['y'] + 10
    assert scroll.evaluate('node => node.scrollTop') == 400
    drag_rail(page, client, outer, True)
    assert abs(page.evaluate('scrollY - (document.documentElement.scrollHeight - innerHeight)')) < 1
    assert scroll.evaluate('node => node.scrollTop') == 400
    expect(text).to_be_focused()
    expect(text).to_have_value('Keep this draft')
    page.screenshot(path=str(artifacts / f'chat-rails-{width}.png'))

    # Keyboard resizing and panning keep both grips in the visible screen.
    keyboard_viewport(page, height - 280, top=40)
    for rail in (inner, outer):
        box = rail.bounding_box()
        assert box['y'] >= 40 and box['y'] + box['height'] <= 40 + height - 280, box
    drag_rail(page, client, inner, True)
    assert page.evaluate('nearLatest()')
    expect(text).to_be_focused()
    keyboard_viewport(page, height)

    # Rail keyboard navigation is scoped and remains discoverable after fading.
    page.clock.run_for(1500)
    inner.focus()
    expect(inner).to_have_css('opacity', '1')
    inner.press('Home')
    expect(inner).to_have_attribute('aria-valuenow', '0')
    inner.press('End')
    expect(inner).to_have_attribute('aria-valuenow', '100')
    inner.press('PageUp')
    expect(inner).not_to_have_attribute('aria-valuenow', '100')
    assert 0 < int(inner.get_attribute('aria-valuenow')) < 100
    outer.focus()
    outer.press('Home')
    assert page.evaluate('scrollY') == 0
    outer.press('End')
    expect(outer).to_have_attribute('aria-valuenow', '100')
    page.evaluate("applyWebsiteLanguage('zh-CN')")
    inner = page.get_by_role('scrollbar', name='滚动消息', exact=True)
    outer = page.get_by_role('scrollbar', name='滚动页面', exact=True)
    expect(inner).to_have_attribute('aria-label', '滚动消息')
    expect(outer).to_have_attribute('aria-label', '滚动页面')
    expect(outer.locator('.scroll-rail-label')).to_have_text('页面 · 底部')

    # Growing or clearing the history updates scrollability without stale handles.
    status['messages'] = []
    page.evaluate('pollChat()')
    expect(page.locator('.chat-message')).to_have_count(0)
    page.clock.run_for(100)  # Deliver the resize observer and its animation frame.
    metrics=scroll.evaluate('node => ({top:node.scrollTop, maximum:node.scrollHeight-node.clientHeight})')
    if metrics['maximum'] <= 1:
        expect(inner).to_be_hidden()
    else:
        # The welcome panel can overflow a short screen even without messages.
        expect(inner).to_be_visible()
        expect(inner).to_have_attribute('aria-valuenow',str(round(metrics['top']/metrics['maximum']*100)))
    page.set_viewport_size({'width': 1200, 'height': 900})
    expect(outer).to_be_hidden()
    expect(page.locator('html')).not_to_have_class('scroll-rails-ready')
    assert not errors, errors
    page.close()
    return {'width': width, 'touchDragIndependent': True, 'boundarySwipesContained': True,
            'keyboardAndDraftPreserved': True, 'keyboardAccessible': True, 'localized': True}


def check_briefing(browser, address, artifacts):
    page = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True,
                            has_touch=True, reduced_motion='reduce')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(address + '/gm.html')
    page.evaluate('document.fonts.ready')
    outer = page.get_by_role('scrollbar', name='Scroll page', exact=True)
    expect(page.get_by_role('scrollbar')).to_have_count(1)
    page.evaluate('window.scrollTo(0, 100)')
    expect(outer).to_have_css('opacity', '1')
    drag_rail(page, page.context.new_cdp_session(page), outer, True)
    expect(outer).to_have_attribute('aria-valuenow', '100')
    page.screenshot(path=str(artifacts / 'briefing-page-rail.png'))
    page.locator('#mobile-sections').tap()
    expect(page.locator('#mobile-section-dialog')).to_be_visible()
    expect(outer).to_have_css('opacity', '0')
    page.locator('#mobile-section-list a').first.tap()
    expect(page.locator('#mobile-section-dialog')).not_to_be_visible()
    expect(page).to_have_url(address + '/gm.html#section-1')
    page.goto(address + '/d/' + briefing_day('Europe/London') + '/gn.html')
    expect(page.get_by_role('scrollbar')).to_have_count(1)
    assert not errors, errors
    page.close()


def main():
    artifacts = Path(sys.argv[1])
    artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-scroll-rails-') as directory:
        root = Path(directory)
        (root / 'daily').mkdir()
        (root / 'profile.md').write_text('timezone: Europe/London\ncity: London, GB\nnews_country: GB\nsecretary_language: English\n')
        day = briefing_day('Europe/London')
        document = encode({'v': 1, 'lang': 'en', 'greeting': 'Synthetic scroll controls.', 'opening': 'Preserved sample records.',
            'sections': [['notes', [['p', 'Synthetic reading content. ' * 30] for _ in range(3)], '',
                          f'Synthetic section {index + 1}'] for index in range(6)]})
        for kind in ('gm', 'gn'):
            (root / 'daily' / f'{day}.{kind}.json').write_text(document)
        server = subprocess.Popen([sys.executable, str(REPO / 'tests/test_briefing_chat.py'), '--serve-fixture', directory],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            address = server.stdout.readline().strip().removeprefix('Private live viewer: ')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                checks = [check_chat(browser, address, artifacts, width, height)
                          for width, height in ((390, 844), (320, 568))]
                check_briefing(browser, address, artifacts)
                browser.close()
            for kind in ('gm', 'gn'):
                assert (root / 'daily' / f'{day}.{kind}.json').read_text() == document
        finally:
            server.terminate()
            server.communicate(timeout=5)
    report = {'modelCalls': 0, 'checks': checks, 'briefingReuse': True, 'savedRecordsUnchanged': True}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
