"""Optional real-browser checks; requires Playwright and installed browser engines.

Run against a private preview: python tests/browser/briefing.py --url URL
Screenshots are opt-in and belong in a private directory outside Git.
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def settle_motion(page, selector='html'):
    page.locator(selector).evaluate('''element => Promise.all(
        element.getAnimations({subtree: true}).map(animation => animation.finished.catch(() => {})))''')


def wait_anchor_scroll(page, index):
    page.wait_for_function('''index => {
        const section = document.querySelectorAll('.briefing-section')[index];
        const inset = parseFloat(getComputedStyle(section).scrollMarginTop) +
            parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop);
        const max = document.documentElement.scrollHeight - innerHeight;
        const target = Math.max(0, Math.min(max, section.offsetTop - inset));
        return Math.abs(scrollY - target) <= 2;
    }''', arg=index)


def check_reading_states(page, screenshot=None):
    targets = page.locator('.briefing-section').evaluate_all('''sections => [0, ...sections.map(section =>
        section.offsetTop + section.offsetHeight / 2 - Math.min(innerHeight * .3, 180)),
        Math.max(0, document.documentElement.scrollHeight - innerHeight - 40),
        document.documentElement.scrollHeight]''')
    page.keyboard.press('Escape')
    page.mouse.move(0, 0)
    page.evaluate('document.activeElement.blur()')
    for index, target in enumerate(targets):
        page.evaluate('top => scrollTo({top, behavior: "instant"})', target)
        # Scroll handlers update on animation frames; observe that rendering cycle.
        page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        states = page.locator('.scroll-chunk').evaluate_all('''links => links.map(link => ({
            active: link.classList.contains('active'),
            fill: Number(link.style.getPropertyValue('--section-progress'))
        }))''')
        active = [i for i, state in enumerate(states) if state['active']]
        assert len(active) == 1, states
        for number, state in enumerate(states):
            assert 0 <= state['fill'] <= 1, states
            if number < active[0]:
                assert state['fill'] == 1, f'Earlier segment has an empty patch: {states}'
            if number > active[0]:
                assert state['fill'] == 0, f'Future segment filled early: {states}'
        if screenshot and index == 5:
            settle_motion(page)
            page.locator('.scroll-map').screenshot(path=str(screenshot.with_name(screenshot.stem + '-fifth-section-minimap.png')))
        if screenshot and index == len(targets) - 2:
            settle_motion(page)
            page.locator('.scroll-map').screenshot(path=str(screenshot.with_name(screenshot.stem + '-before-bottom-minimap.png')))
    assert all(state['fill'] == 1 for state in states), states


def check(page, kind, touch, screenshot=None, errors=None):
    sections = page.locator('.briefing-section')
    chunks = page.locator('.scroll-chunk')
    count = sections.count()
    assert count > 0
    expect(chunks).to_have_count(count)
    assert page.locator('.rail').count() == 0
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
    assert page.evaluate('''() => { const main=document.querySelector('main'); const style=getComputedStyle(main);
      return Math.abs(document.querySelector('article').getBoundingClientRect().width -
        (main.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight))) < 1; }''')
    errors = [] if errors is None else errors
    expect(chunks.first).to_have_attribute('aria-current', 'location')
    expect(page.locator('.back-to-top')).to_be_hidden()
    assert page.locator('.briefing-tools .source-link').count() == 1
    page.evaluate('document.fonts.ready')
    expect(page.locator('.scroll-cursor')).to_have_css('border-top-width', '0px')
    expect(page.locator('.scroll-chunk.active .chunk-bar')).to_have_css('border-top-color', 'rgba(0, 0, 0, 0)')
    if kind == 'gm':
        assert page.locator('.weather-tile').count() > 0
        assert page.locator('.agenda-event').count() > 0
        assert page.locator('.news-card').count() > 0
        page.locator('.news-visual img').evaluate_all('images => images.forEach(image => image.loading = "eager")')
        page.wait_for_function('() => Array.from(document.querySelectorAll(".news-visual img")).every(image => image.complete && image.naturalWidth > 0)')
    settle_motion(page)
    assert page.evaluate('document.getAnimations().filter(animation => animation.playState === "running").length') == 0
    if not touch:
        page.evaluate('scrollTo({top: 120, behavior: "instant"})')
        page.wait_for_function('() => parseFloat(document.querySelector(".hero").style.getPropertyValue("--sun-drift")) > 0')
        page.evaluate('scrollTo({top: 0, behavior: "instant"})')
        page.wait_for_function('() => parseFloat(document.querySelector(".hero").style.getPropertyValue("--sun-drift")) === 0')
    if screenshot:
        page.screenshot(path=str(screenshot))
    for index in range(count):
        chunk = chunks.nth(index)
        tooltip = page.locator(f'#preview-{index + 1}')
        if touch:
            old_hash = page.evaluate('location.hash')
            chunk.tap()
            expect(tooltip).to_be_visible()
            expect(chunk).to_have_attribute('aria-expanded', 'true')
            assert page.evaluate('location.hash') == old_hash
            assert chunk.bounding_box()['height'] >= 44
        else:
            chunk.hover()
            expect(tooltip).to_be_visible()
        expect(tooltip).to_have_css('opacity', '1')
        settle_motion(page, f'#preview-{index + 1}')
        box = tooltip.bounding_box()
        viewport = page.viewport_size
        assert box['x'] >= 0 and box['y'] >= 0
        assert box['x'] + box['width'] <= viewport['width']
        assert box['y'] + box['height'] <= viewport['height']
        expect(tooltip.locator('.preview-title')).to_have_text(sections.nth(index).locator('h2').inner_text())
        if screenshot and index == 1:
            page.screenshot(path=str(screenshot.with_name(screenshot.stem + '-preview.png')))
        if touch:
            if index % 2:
                tooltip.locator('.preview-footer').tap()
            else:
                chunk.tap()
        else:
            chunk.click()
        expect(page).to_have_url(f'{page.url.split("#")[0]}#section-{index + 1}')
        expect(tooltip).to_be_hidden()
        # Wait on the observable scroll result, never a fixed sleep.
        wait_anchor_scroll(page, index)
        expect(chunk).to_have_attribute('aria-current', 'location')
    page.keyboard.press('Escape')
    if not touch:
        chunks.first.focus()
        expect(page.locator('#preview-1')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.locator('#preview-1')).to_be_hidden()
    else:
        chunks.first.tap()
        expect(page.locator('#preview-1')).to_be_visible()
        page.locator('h1').tap()
        expect(page.locator('#preview-1')).to_be_hidden()
        page.keyboard.press('Tab')
        chunks.first.focus()
        expect(page.locator('#preview-1')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.locator('#preview-1')).to_be_hidden()
        page.keyboard.press('Enter')
        expect(page).to_have_url(f'{page.url.split("#")[0]}#section-1')
        expect(sections.first).to_be_in_viewport()
    # Use a fresh document for exact geometry checks. A pending keyboard/native
    # scroll from the interaction checks must not compete with these test jumps.
    page.emulate_media(reduced_motion='reduce')
    page.goto(page.url.split('#')[0])
    page.evaluate('window.scrollTo({top: document.documentElement.scrollHeight, behavior: "instant"})')
    page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    expect(chunks.last).to_have_attribute('aria-current', 'location')
    fills = chunks.evaluate_all('(links) => links.map(link => Number(link.style.getPropertyValue("--section-progress")))')
    assert fills == [1] * count, f'Page bottom left incomplete segment fills: {fills}; viewport={page.viewport_size}; scroll={page.evaluate("({y: scrollY, height: document.documentElement.scrollHeight, viewport: innerHeight})")}'
    page.wait_for_function('() => document.querySelector(".reading-progress").getBoundingClientRect().width / document.documentElement.clientWidth > .99')
    check_reading_states(page, screenshot)
    settle_motion(page)
    expect(page.locator('.back-to-top')).to_be_visible()
    map_box = page.locator('.scroll-map').bounding_box()
    button_box = page.locator('.back-to-top').bounding_box()
    assert page.locator('.back-to-top').evaluate('''button => {
      const contentRight = document.querySelector('.briefing-section').getBoundingClientRect().right;
      const safeRight = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--safe-right')) || 0;
      const expected = (contentRight + document.documentElement.clientWidth - safeRight) / 2;
      const box = button.getBoundingClientRect();
      return Math.abs(box.x + box.width / 2 - expected) < 1;
    }'''), 'Back-to-top is not centered in the content gutter'
    assert map_box['y'] + map_box['height'] + 6 <= button_box['y'], 'Navigation overlaps back-to-top'
    assert button_box['width'] >= 44 and button_box['height'] >= 44
    page.locator('.back-to-top').click()
    page.wait_for_function('() => scrollY <= 2')
    expect(page.locator('.back-to-top')).to_be_hidden()
    assert page.locator('.scroll-chunk').first.get_attribute('aria-current') == 'location'
    if not touch:
        assert page.locator('.orbit-caption').count() == 0
    assert page.locator('.briefing-tools .source-link').bounding_box()['y'] < sections.first.bounding_box()['y']
    cursor = page.locator('.scroll-cursor').bounding_box()
    active_bar = page.locator('.scroll-chunk.active .chunk-bar').bounding_box()
    assert abs(cursor['y'] - active_bar['y']) < 1
    assert abs(cursor['height'] - active_bar['height']) < 1
    assert page.locator('.briefing-section.is-current').count() == 1
    assert page.evaluate('document.getAnimations().filter(animation => animation.playState === "running").length') == 0
    if screenshot:
        page.locator('.scroll-map').screenshot(path=str(screenshot.with_name(screenshot.stem + '-bottom-minimap.png')))
    assert not errors, errors
    return {'edition': kind, 'sections': count, 'touch': touch, 'overflow': False, 'previews': 'pass', 'navigation': 'pass', 'bottom_fills': 'pass', 'intermediate_fills': 'pass', 'motion': 'pass', 'idle_animations': 0, 'back_to_top': 'pass'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--browser', choices=('chromium', 'webkit'), default='chromium')
    parser.add_argument('--artifacts', type=Path)
    args = parser.parse_args()
    if args.artifacts:
        args.artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = []
    with sync_playwright() as p:
        browser = getattr(p, args.browser).launch()
        cases = [
            ('desktop', {'viewport': {'width': 1440, 'height': 1000}}),
            ('android-pixel', dict(p.devices['Pixel 7'])),
            ('iphone-se', dict(p.devices['iPhone SE'])),
            ('iphone-13', dict(p.devices['iPhone 13'])),
            ('small-phone', {'viewport': {'width': 320, 'height': 568}, 'is_mobile': True, 'has_touch': True}),
            ('landscape', {'viewport': {'width': 844, 'height': 390}, 'is_mobile': True, 'has_touch': True}),
            ('small-landscape', {'viewport': {'width': 568, 'height': 320}, 'is_mobile': True, 'has_touch': True}),
            ('tablet', {'viewport': {'width': 768, 'height': 1024}, 'is_mobile': True, 'has_touch': True}),
        ]
        for name, options in cases:
            # Device descriptors may suggest another engine; engine choice stays explicit.
            options.pop('default_browser_type', None)
            context = browser.new_context(**options)
            for kind in ('gm', 'gn'):
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'{args.url.rstrip("/")}/{kind}.html')
                screenshot = args.artifacts / f'{args.browser}-{name}-{kind}.png' if args.artifacts else None
                result = check(page, kind, options.get('has_touch', False), screenshot, errors)
                report.append({'browser': args.browser, 'device': name, **result})
                page.close()
            context.close()
        context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, reduced_motion='reduce')
        page = context.new_page()
        page.goto(args.url.rstrip('/') + '/gm.html')
        assert page.evaluate('getComputedStyle(document.documentElement).scrollBehavior') == 'auto'
        assert page.evaluate('getComputedStyle(document.querySelector(".nav-preview")).transitionDuration') == '0s'
        assert page.evaluate('getComputedStyle(document.querySelector(".scroll-cursor")).transitionDuration') == '0s'
        assert page.evaluate('document.getAnimations().length') == 0
        page.evaluate('scrollTo({top: 120, behavior: "instant"})')
        page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        assert page.evaluate('parseFloat(document.querySelector(".hero").style.getPropertyValue("--sun-drift"))') == 0
        page.emulate_media(reduced_motion='no-preference')
        page.emulate_media(reduced_motion='reduce')
        assert page.evaluate('document.getAnimations().length') == 0
        context.close()
        context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, java_script_enabled=False)
        page = context.new_page()
        page.goto(args.url.rstrip('/') + '/gm.html')
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.locator('.scroll-chunk').nth(2).tap()
        expect(page).to_have_url(args.url.rstrip('/') + '/gm.html#section-3')
        assert page.locator('.agenda-event').count() > 0
        context.close()
        browser.close()
    result = {'cases': report, 'reduced_motion': 'pass', 'no_javascript': 'pass'}
    if args.artifacts:
        target = args.artifacts / f'{args.browser}-check.json'
        target.write_text(json.dumps(result, indent=2))
        target.chmod(0o600)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
