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


def check_reading_states(page):
    """Exactly one chip and its section are current at every reading position, the last one at the bottom."""
    targets = page.locator('.briefing-section').evaluate_all("""sections => [0, ...sections.map(section =>
        section.offsetTop + section.offsetHeight / 2 - Math.min(innerHeight * .3, 180)),
        document.documentElement.scrollHeight]""")
    for target in targets:
        page.evaluate('top => scrollTo({top, behavior: "instant"})', target)
        # Scroll handlers update on animation frames; observe that rendering cycle.
        page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        states = page.evaluate("""() => [Array.from(document.querySelectorAll('.briefing-section-nav a'), link => link.hasAttribute('aria-current')),
            Array.from(document.querySelectorAll('.briefing-section'), section => section.classList.contains('is-current'))]""")
        assert states[0].count(True) == 1 and states[0] == states[1], states
    assert states[0][-1], states


def check(page, kind, touch, screenshot=None, errors=None):
    sections = page.locator('.briefing-section')
    chips = page.locator('.briefing-section-nav a')
    count = sections.count()
    assert count > 0
    expect(chips).to_have_count(count)
    assert page.locator('.scroll-map, .section-number').count() == 0
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
    assert page.evaluate("""() => { const main=document.querySelector('main'); const style=getComputedStyle(main);
      return Math.abs(document.querySelector('article').getBoundingClientRect().width -
        (main.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight))) < 1; }""")
    errors = [] if errors is None else errors
    expect(chips.first).to_have_attribute('aria-current', 'location')
    expect(page.locator('.back-to-top')).to_be_hidden()
    page.evaluate('document.fonts.ready')
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
        chip = chips.nth(index)
        page.evaluate('scrollTo({top: 0, behavior: "instant"})')
        chip.scroll_into_view_if_needed()  # Phones reach later chips by scrolling the row sideways.
        assert chip.bounding_box()['height'] >= 44
        chip.tap() if touch else chip.click()
        expect(page).to_have_url(f'{page.url.split("#")[0]}#section-{index + 1}')
        # Wait on the observable scroll result, never a fixed sleep.
        wait_anchor_scroll(page, index)
        expect(chip).to_have_attribute('aria-current', 'location')
    # Use a fresh document for exact geometry checks.
    page.emulate_media(reduced_motion='reduce')
    page.goto(page.url.split('#')[0])
    page.evaluate('window.scrollTo({top: document.documentElement.scrollHeight, behavior: "instant"})')
    page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    expect(chips.last).to_have_attribute('aria-current', 'location')
    page.wait_for_function('() => document.querySelector(".reading-progress").getBoundingClientRect().width / document.documentElement.clientWidth > .99')
    check_reading_states(page)
    settle_motion(page)
    if page.viewport_size['width'] <= 700:
        # Phones offer Back to top in the section picker instead of a floating button.
        expect(page.locator('.back-to-top')).to_be_hidden()
    else:
        expect(page.locator('.back-to-top')).to_be_visible()
        button_box = page.locator('.back-to-top').bounding_box()
        assert button_box['width'] >= 44 and button_box['height'] >= 44
        page.locator('.back-to-top').click()
        page.wait_for_function('() => scrollY <= 2')
        expect(page.locator('.back-to-top')).to_be_hidden()
        assert chips.first.get_attribute('aria-current') == 'location'
    assert page.locator('.briefing-section.is-current').count() == 1
    assert page.evaluate('document.getAnimations().filter(animation => animation.playState === "running").length') == 0
    assert not errors, errors
    return {'edition': kind, 'sections': count, 'touch': touch, 'overflow': False, 'navigation': 'pass', 'reading_states': 'pass', 'motion': 'pass', 'idle_animations': 0, 'back_to_top': 'pass'}


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
                page.goto(f'{args.url.rstrip("/")}/{kind}')
                screenshot = args.artifacts / f'{args.browser}-{name}-{kind}.png' if args.artifacts else None
                result = check(page, kind, options.get('has_touch', False), screenshot, errors)
                report.append({'browser': args.browser, 'device': name, **result})
                page.close()
            context.close()
        context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, reduced_motion='reduce')
        page = context.new_page()
        page.goto(args.url.rstrip('/') + '/gm')
        assert page.evaluate('getComputedStyle(document.documentElement).scrollBehavior') == 'auto'
        assert page.evaluate('getComputedStyle(document.querySelector(".briefing-section-nav a")).transitionDuration') == '0s'
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
        page.goto(args.url.rstrip('/') + '/gm')
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.locator('.briefing-section-nav a').nth(2).tap()
        expect(page).to_have_url(args.url.rstrip('/') + '/gm#section-3')
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
