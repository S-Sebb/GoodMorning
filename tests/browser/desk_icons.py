"""Check decorative icons, translations and narrow layouts with synthetic records."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import TEMP_ROOT, returning_viewer
from support import start_server
from test_weekly_schedule import make_runtime


def check(app, url, shots):
    from playwright.sync_api import expect, sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        errors, failures = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('response', lambda response: failures.append(response.url) if response.status >= 400 and '/assets/' in response.url else None)
        cases = 0
        for language in ('en', 'zh-CN'):
            page.goto(url + '/schedule')
            page.locator('#prefs-menu summary').click()
            page.locator('#website-language').select_option(language)
            expect(page.locator('html')).to_have_attribute('lang', language)
            for theme, hour in (('gm', 12), ('gn', 21)):
                app.now = lambda hour=hour: datetime(2026, 10, 13, hour, tzinfo=timezone.utc)
                for route in ('/gm.html', '/gn.html', '/schedule', '/chat'):
                    for width in (1440, 820, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 900})
                        page.goto(url + route)
                        page.evaluate('document.fonts.ready')
                        links = page.locator('.edition-switch .edition-link')
                        expect(links).to_have_count(4)
                        labels = ['Morning', 'Evening', 'Schedule', 'Secretary'] if language == 'en' else ['早报', '晚报', '日程', '秘书']
                        for link, label in zip(links.all(), labels):
                            expect(link).to_have_accessible_name(label)
                            icon = link.evaluate('el => { const s = getComputedStyle(el, "::before"); return {image: s.backgroundImage, width: parseFloat(s.width), height: parseFloat(s.height)}; }')
                            size = 18 if route == '/chat' and width <= 700 else 20  # Compact phone chat header.
                            assert '/assets/' in icon['image'] and icon['width'] >= size and icon['height'] >= size, icon
                        boxes = links.evaluate_all('nodes => nodes.map(node => {const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};})')
                        assert all(0 <= box['left'] < box['right'] <= width for box in boxes), boxes
                        assert all(a['right'] <= b['left'] + 1 for a, b in zip(boxes, boxes[1:])), boxes
                        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), (route, width, language)
                        if route == '/chat':
                            expect(page.locator('.mode-switch button')).to_have_count(3)
                            page.locator('[data-mode="eureka"]').click()
                            expect(page.locator('[data-mode="eureka"]')).to_have_attribute('aria-checked', 'true')
                        if shots and route in ('/schedule', '/chat') and width in (1440, 390):
                            page.mouse.move(0, 0)
                            page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                            page.locator('html').evaluate('element => Promise.all(element.getAnimations({subtree: true}).map(animation => animation.finished.catch(() => {})))')
                            page.screenshot(path=str(shots / f'{route[1:]}-{theme}-{language}-{width}.png'))
                        cases += 1
        assert not errors, errors
        assert not failures, failures
        browser.close()
        print(f'{cases} page/language/theme/viewport combinations passed; no asset failures or browser errors.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshots', type=Path)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
        app = make_runtime(Path(temporary))
        returning_viewer(app.runtime)
        server = start_server(app)
        try:
            check(app, f'http://127.0.0.1:{server.server_address[1]}', args.screenshots)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
