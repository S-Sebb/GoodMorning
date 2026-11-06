"""Check decorative icons, translations and narrow layouts with synthetic records."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import TEMP_ROOT, returning_viewer
from support import start_server
from goodmorning.briefings.briefing_document import encode
from goodmorning.runtime_files import set_profile_fields
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
                bar = {}  # Phone page-bar item sizes by route and width.
                for route in ('/gm', '/gn', '/schedule', '/letters', '/chat', '/about-me'):
                    for width in (1500, 1440, 1280, 1024, 820, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 900})
                        page.goto(url + route)
                        page.evaluate('document.fonts.ready')
                        links = page.locator('.edition-switch .edition-link')
                        expect(links).to_have_count(6)
                        labels = ['Morning', 'Evening', 'Schedule', 'Letters', 'Secretary', 'About me'] if language == 'en' else ['早报', '晚报', '日程', '来信', '秘书', '关于我']
                        for link, label in zip(links.all(), labels):
                            expect(link).to_have_accessible_name(label)
                            icon = link.evaluate('el => { const s = getComputedStyle(el, "::before"); return {image: s.backgroundImage, width: parseFloat(s.width), height: parseFloat(s.height)}; }')
                            size = 18 if route == '/chat' and width <= 700 else 20  # Compact phone chat header.
                            assert '/assets/' in icon['image'] and icon['width'] >= size and icon['height'] >= size, icon
                        boxes = links.evaluate_all('nodes => nodes.map(node => {const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};})')
                        assert all(0 <= box['left'] < box['right'] <= width for box in boxes), boxes
                        assert all(a['right'] <= b['left'] + 1 for a, b in zip(boxes, boxes[1:])), boxes
                        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), (route, width, language)
                        if width in (1500, 1280, 1024):
                            # Top controls, page bar and date tiles end on the page content's edge: the frame less its gutter.
                            edges = page.evaluate('''() => {
                                const right = nodes => Math.max(...[...nodes].map(node => node.getBoundingClientRect().right));
                                const main = document.querySelector('main'), page = document.documentElement.clientWidth;
                                const gutter = parseFloat(getComputedStyle(main).getPropertyValue('--content-gutter'));
                                const picker = document.querySelector('.week-picker');
                                return {content: (page + Math.min(page, 1440)) / 2 - gutter, toolbar: right(document.querySelectorAll('.toolbar-row > :not(#update-slot), #update-slot > *')),
                                    bar: right(document.querySelectorAll('.edition-switch .edition-link')), tiles: picker && picker.getBoundingClientRect().right};
                            }''')
                            assert edges['tiles'] is not None or route not in ('/gm', '/gn'), edges
                            assert all(abs(edge - edges['content']) <= 1 for edge in edges.values() if edge is not None), (route, width, language, edges)
                        if width <= 390:
                            # The highlight is the ::after pill; each corner of the label's ink box must sit inside its rounded shape.
                            label = page.locator('.edition-link.selected').evaluate('''el => {
                                const r = el.getBoundingClientRect(), s = getComputedStyle(el), pill = getComputedStyle(el, '::after'), range = document.createRange();
                                range.selectNodeContents(document.createTreeWalker(el, NodeFilter.SHOW_TEXT).nextNode());
                                const lines = [...range.getClientRects()], context = document.createElement('canvas').getContext('2d');
                                context.font = `${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
                                const m = context.measureText(el.textContent.trim()), first = lines[0], baseline = first.top + (first.height - m.fontBoundingBoxAscent - m.fontBoundingBoxDescent) / 2 + m.fontBoundingBoxAscent;
                                const ink = lines.length === 1 ? {left: first.left, right: first.right, top: baseline - m.actualBoundingBoxAscent, bottom: baseline + m.actualBoundingBoxDescent}
                                    : {left: Math.min(...lines.map(line => line.left)), right: Math.max(...lines.map(line => line.right)), top: first.top, bottom: lines.at(-1).bottom};
                                const left = r.left + parseFloat(pill.left), right = r.right - parseFloat(pill.right), top = r.top + parseFloat(pill.top), bottom = r.bottom - parseFloat(pill.bottom);
                                const radius = Math.min(parseFloat(pill.borderTopLeftRadius), (right - left) / 2, (bottom - top) / 2);
                                const inside = (x, y) => Math.hypot(x - Math.min(Math.max(x, left + radius), right - radius), y - Math.min(Math.max(y, top + radius), bottom - radius)) <= radius;
                                return [[ink.left, ink.top], [ink.right, ink.top], [ink.left, ink.bottom], [ink.right, ink.bottom]].every(([x, y]) => inside(x, y));
                            }''')
                            assert label, (route, width, language)
                            bar[route, width] = [(round(box['right'] - box['left']), round(box['bottom'] - box['top'])) for box in boxes]
                            if route in ('/letters', '/about-me'):
                                assert bar[route, width] == bar['/gm', width], (route, width, language, bar[route, width], bar['/gm', width])
                        # Header: the wordmark stands alone; Settings is a gear, menus keep their ▾, and while up to date What's new is a sparkle.
                        expect(page.locator('.wordmark > *')).to_have_count(0)
                        settings = page.locator('#prefs-menu > summary')
                        expect(settings).to_have_accessible_name('Settings' if language == 'en' else '设置')
                        expect(settings.locator('svg.menu-icon')).to_be_visible()
                        expect(settings.locator('.menu-label')).to_have_css('width', '1px')
                        assert settings.bounding_box()['height'] >= 36
                        for menu in page.locator('.toolbar-row .menu > summary').all():
                            # The arrow is decorative: empty alt text keeps it out of the accessible name.
                            assert menu.evaluate('el => getComputedStyle(el, "::after").content').startswith('"▾"'), menu
                        notes = page.locator('#site-update-toggle')
                        expect(notes).to_have_attribute('data-state', 'current')
                        expect(notes).to_have_accessible_name('What’s new: view patch notes' if language == 'en' else '新变化：查看更新日志')
                        expect(notes.locator('span')).to_be_hidden()
                        expect(notes.locator('svg')).to_be_visible()
                        if route == '/chat':
                            expect(page.locator('[data-starter]')).to_have_count(3)
                        if route == '/letters':
                            # No letters yet: the envelope and one sentence; the tab names the page.
                            empty = page.locator('.letters-empty')
                            assert '/assets/' in empty.evaluate('el => getComputedStyle(el, "::before").backgroundImage')
                            expect(empty.locator('p')).to_have_count(1)
                            expect(empty.locator('h1')).to_have_class('visually-hidden')
                        if shots and route in ('/schedule', '/chat') and width in (1440, 390):
                            page.mouse.move(0, 0)
                            page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                            page.locator('html').evaluate('element => Promise.all(element.getAnimations({subtree: true}).map(animation => animation.finished.catch(() => {})))')
                            page.screenshot(path=str(shots / f'{route[1:]}-{theme}-{language}-{width}.png'))
                        cases += 1
        # The About me icon follows the saved gender and is neutral until one is saved.
        page.set_viewport_size({'width': 390, 'height': 900})
        for gender, person in (('', 'neutral'), ('woman', 'woman'), ('man', 'man'), ('unspecified', 'neutral')):
            set_profile_fields(app.runtime, {'gender': gender})
            page.goto(url + '/schedule')
            link = page.locator('.edition-switch .edition-link[href="/about-me"]')
            expect(link).to_have_attribute('data-person', person)
            image = link.evaluate('el => getComputedStyle(el, "::before").backgroundImage')
            assert f'desk-person-{person}.svg' in image, image
            if shots:
                page.locator('.masthead').screenshot(path=str(shots / f'bar-{gender or "unset"}-390.png'))
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
        # A saved briefing brings the date tiles and the quick-chat corner beside the reading column.
        document = encode({'v': 1, 'lang': 'en', 'greeting': 'Synthetic layout test.', 'opening': 'Synthetic records.',
                           'sections': [['notes', [['p', 'Synthetic reading content.']], '', 'Synthetic section']]})
        for kind in ('gm', 'gn'):
            (Path(temporary) / 'daily' / f'2026-10-13.{kind}.json').write_text(document)
        returning_viewer(app.runtime)
        server = start_server(app)
        try:
            check(app, f'http://127.0.0.1:{server.server_address[1]}', args.screenshots)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
