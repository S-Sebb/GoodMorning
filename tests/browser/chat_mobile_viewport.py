"""Mobile scrolling and keyboard viewport changes with isolated synthetic messages.

Playwright does not open a phone keyboard. Simulate its visual-only resize and
pan separately from a layout resize; a smaller desktop viewport misses this bug.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[2]
GEOMETRY = """() => {
    const rect = selector => {
        const box = document.querySelector(selector).getBoundingClientRect();
        return {top: box.top, bottom: box.bottom, height: box.height};
    };
    const scroll = document.querySelector('#chat-scroll');
    return {panel: rect('#conversation'), composer: rect('#chat-compose'),
        row: rect('.chat-input-row'), text: rect('#chat-text'),
        scrollTop: scroll.scrollTop, scrollHeight: scroll.clientHeight,
        pageHeight: document.documentElement.scrollHeight, pageTop: scrollY,
        layoutHeight: innerHeight, visibleHeight: visualViewport.height,
        visibleTop: visualViewport.offsetTop};
}"""


def settle(page):
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


def keyboard_viewport(page, height, top=0, scale=1):
    page.evaluate("""([height, top, scale]) => {
        const resized = height !== visualViewport.height || scale !== visualViewport.scale;
        const panned = top !== visualViewport.offsetTop;
        Object.assign(window.keyboardViewport, {height, offsetTop: top, scale});
        if (resized) visualViewport.dispatchEvent(new Event('resize'));
        if (panned) visualViewport.dispatchEvent(new Event('scroll'));
    }""", [height, top, scale])
    settle(page)


def swipe(page, client, direction):
    box = page.locator('#chat-scroll').bounding_box()
    # The centered "Jump to latest" button can cover a short message viewport.
    x = box['x'] + 8
    # Short keyboard-reduced viewports still need a gesture beyond Chromium's
    # touch slop, with both endpoints inside the message area.
    y = box['y'] + (6 if direction > 0 else box['height'] - 6)
    distance = min(100, box['height'] - 12) * direction
    client.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x, 'y': y}]})
    for step in range(1, 9):
        client.send('Input.dispatchTouchEvent', {'type': 'touchMove',
                    'touchPoints': [{'x': x, 'y': y + distance * step / 8}]})
        settle(page)
    # Cancel avoids inertial scrolling racing the geometry assertions.
    client.send('Input.dispatchTouchEvent', {'type': 'touchCancel', 'touchPoints': []})
    settle(page)


def check_mobile(browser, address, artifacts, width, height):
    page = browser.new_page(viewport={'width': width, 'height': height},
                            is_mobile=True, has_touch=True, reduced_motion='reduce')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script("""(() => {
        window.keyboardViewport = {};
        for (const key of ['height', 'offsetTop', 'scale']) {
            const read = Object.getOwnPropertyDescriptor(VisualViewport.prototype, key).get;
            Object.defineProperty(visualViewport, key, {
                get: () => window.keyboardViewport[key] ?? read.call(visualViewport)
            });
        }
    })();""")
    messages = [{'id': f'message-{index}', 'role': 'assistant',
                 'text': f'Synthetic message {index}.\nA useful update.\nKeep earlier messages readable.'}
                for index in range(24)]
    status = {'mode': 'secretary', 'state': 'idle', 'language': 'en', 'label': '',
              'messages': messages, 'forms': [], 'permissions': []}
    page.route('**/api/chats', lambda route: route.fulfill(json={
        'defaultMode': 'secretary', 'connected': True, 'chats': []}))
    page.route('**/api/chats/*', lambda route: route.fulfill(json=status))
    page.goto(address + '/chat?id=' + 'f' * 32)
    expect(page.locator('.chat-message')).to_have_count(24)
    page.evaluate('document.fonts.ready')
    # Phone history and secretary calls sit below the chat; bring the chat itself into view.
    page.locator('#conversation').evaluate("node => node.scrollIntoView({block: 'end'})")
    text = page.get_by_label('Your message', exact=True)
    text.tap()
    text.fill('Keep this unsent draft')
    settle(page)
    baseline = page.evaluate(GEOMETRY)
    client = page.context.new_cdp_session(page)
    checks = []

    def check_scroll():
        page.locator('#chat-scroll').evaluate('node => node.scrollTop = 400')
        before = page.evaluate(GEOMETRY)
        swipe(page, client, 1)
        earlier = page.evaluate(GEOMETRY)
        assert earlier['scrollTop'] < before['scrollTop'], (before, earlier)
        swipe(page, client, -1)
        later = page.evaluate(GEOMETRY)
        assert later['scrollTop'] > earlier['scrollTop'], (earlier, later)
        for key in ('panel', 'composer', 'row', 'text', 'pageHeight', 'pageTop'):
            assert before[key] == earlier[key] == later[key], (key, before, earlier, later)
        position = later['scrollTop']
        messages.append({'id': f'update-{len(messages)}', 'role': 'assistant', 'text': 'A new synthetic reply.'})
        page.evaluate('pollChat()')
        expect(page.locator('.chat-message')).to_have_count(len(messages))
        assert abs(page.evaluate(GEOMETRY)['scrollTop'] - position) < 1

    check_scroll()
    for index, (visible_height, top) in enumerate(((height - 280, 0), (height - 320, 80),
                                                  (height - 320, 160), (height - 280, 0),
                                                  (height, 0), (height - 300, 0), (height, 0))):
        follow = index % 2 == 0
        if follow:
            page.evaluate('scrollToLatest()')
        previous_top = page.evaluate(GEOMETRY)['scrollTop']
        keyboard_viewport(page, visible_height, top)
        geometry = page.evaluate(GEOMETRY)
        # Capture only the simulated visible screen, not the area behind the keyboard.
        page.screenshot(path=str(artifacts / f'mobile-{width}-{visible_height}-{top}.png'),
                        clip={'x': 0, 'y': top, 'width': width, 'height': visible_height})
        panel_top = page.locator('#conversation').evaluate('node => node.getBoundingClientRect().top + scrollY')
        minimum = 280 if page.locator('#conversation').evaluate("node => node.classList.contains('is-keyboard-open')") else 240
        assert abs(geometry['panel']['height'] - max(minimum, visible_height - panel_top - 12)) < 1, geometry
        assert geometry['composer']['bottom'] <= top + visible_height, geometry
        assert geometry['composer']['top'] >= top, geometry
        assert geometry['layoutHeight'] == height, 'Simulation resized the layout instead of the visual viewport'
        assert abs(geometry['pageHeight'] - baseline['pageHeight']) <= max(0, minimum - (visible_height - panel_top - 12)) + 1, geometry
        if follow:
            assert page.evaluate('nearLatest()'), 'Viewport resize lost the latest reply'
        else:
            assert abs(geometry['scrollTop'] - previous_top) < 1, geometry
        text.tap()
        expect(text).to_be_focused()
        expect(text).to_have_value('Keep this unsent draft')
        check_scroll()
        checks.append({'visibleHeight': visible_height, 'pan': top, 'composerAccessible': True})

    # A keyboard must not turn the five-line draft into an unbounded input.
    text.fill('\n'.join(f'Draft line {index}' for index in range(8)))
    keyboard_viewport(page, height - 300)
    expect(text).to_have_css('overflow-y', 'auto')
    geometry = page.evaluate(GEOMETRY)
    assert geometry['text']['height'] <= min(120, geometry['visibleHeight'] / 4), geometry
    assert geometry['composer']['bottom'] <= geometry['visibleHeight'], geometry
    assert text.evaluate('node => node.scrollTop >= node.scrollHeight - node.clientHeight - 1'), 'Keyboard hid the current draft line'
    check_scroll()
    page.locator('#chat-scroll').evaluate('node => node.scrollTop = node.scrollHeight - node.clientHeight - 280')
    previous_top = page.evaluate(GEOMETRY)['scrollTop']
    keyboard_viewport(page, height)
    maximum_top = page.locator('#chat-scroll').evaluate('node => node.scrollHeight - node.clientHeight')
    assert abs(page.evaluate(GEOMETRY)['scrollTop'] - min(previous_top, maximum_top)) < 1, page.evaluate(GEOMETRY)

    # Ordinary page scrolling must still reach the sidebar, including while typing.
    keyboard_viewport(page, height - 300)
    page.evaluate('window.scrollTo(0, 0)')
    settle(page)
    assert page.evaluate('scrollY') == 0, 'Viewport handler hijacked ordinary page scrolling'
    keyboard_viewport(page, height)
    keyboard_viewport(page, height / 2, scale=2)
    assert abs(page.locator('#conversation').bounding_box()['height'] - baseline['panel']['height']) < 1, 'Pinch zoom stretched the panel'
    keyboard_viewport(page, height)

    # Also cover browsers that resize the layout when the keyboard opens.
    page.evaluate('window.keyboardViewport = {}')
    page.set_viewport_size({'width': width, 'height': height - 300})
    settle(page)
    geometry = page.evaluate(GEOMETRY)
    panel_top = page.locator('#conversation').evaluate('node => node.getBoundingClientRect().top + scrollY')
    assert abs(geometry['panel']['height'] - max(280, height - 300 - panel_top - 12)) < 1, geometry
    assert geometry['composer']['bottom'] <= height - 300, geometry
    page.set_viewport_size({'width': 1440, 'height': 900})
    settle(page)
    desktop = page.evaluate("""() => {
        const panel = document.querySelector('#conversation').getBoundingClientRect();
        const composer = document.querySelector('#chat-compose').getBoundingClientRect();
        return {height: panel.height, composerBottom: composer.bottom,
            pageScrollable: document.documentElement.scrollHeight - innerHeight};
    }""")
    assert desktop['pageScrollable'] <= 1, desktop
    assert 400 < desktop['height'] < 900, desktop
    assert desktop['composerBottom'] <= 900, desktop
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
    assert not errors, errors
    page.close()
    return {'width': width, 'height': height, 'touchScrollBothDirections': True,
            'draftPreserved': True, 'readingPositionPreserved': True, 'checks': checks}


def check_without_visual_viewport(browser, address):
    page = browser.new_page(viewport={'width': 390, 'height': 844}, has_touch=True)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script("Object.defineProperty(window, 'visualViewport', {value: undefined});")
    page.goto(address + '/chat?mode=secretary')
    text = page.get_by_label('Your message', exact=True)
    text.fill('\n'.join(f'Line {index}' for index in range(8)))
    expect(text).to_have_css('height', '120px')
    expect(page.locator('#chat-send')).to_be_in_viewport()
    page.set_viewport_size({'width': 390, 'height': 400})
    expect(text).to_have_css('height', '100px')
    expect(page.locator('#chat-send')).to_be_in_viewport()
    assert not errors, errors
    page.close()


def main():
    artifacts = Path(sys.argv[1])
    artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-mobile-viewport-') as directory:
        (Path(directory)/'profile.md').write_text('secretary_language: English\ncity: London\ntimezone: Europe/London\nnews_country: GB\n')
        server = subprocess.Popen([sys.executable, str(REPO / 'tests/test_briefing_chat.py'),
                                   '--serve-fixture', directory],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            address = server.stdout.readline().strip().removeprefix('Private live viewer: ')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                checks = [check_mobile(browser, address, artifacts, width, height)
                          for width, height in ((390, 844), (320, 568))]
                check_without_visual_viewport(browser, address)
                browser.close()
        finally:
            server.terminate()
            server.communicate(timeout=5)
    report = {'modelCalls': 0, 'physicalKeyboardTested': False, 'viewportFallback': True, 'checks': checks}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
