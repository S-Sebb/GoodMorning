"""Synthetic mobile auth layout: repeated touch scrolling and viewport changes."""
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from goodmorning.security.briefing_gateway import account_page, ASSETS
from goodmorning.web import language
from goodmorning.web.briefing_resources import Resources
from goodmorning.web.release import VERSION


def geometry(page):
    return page.evaluate('''() => {
        const card = document.querySelector('.account-card').getBoundingClientRect();
        return {top: card.top + scrollY, height: card.height,
            documentHeight: document.documentElement.scrollHeight};
    }''')


def main():
    artifacts = Path(sys.argv[1])
    artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []
    resources = Resources(ASSETS, types={'auth.css': 'text/css', 'auth.js': 'text/javascript',
                                       'language.js': 'text/javascript', 'model.js': 'text/javascript',
                                       'update.css': 'text/css', 'update.js': 'text/javascript'})
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width in (320, 390):
            for lang in ('en', 'zh-CN'):
                for action in ('login', 'password'):
                    context = browser.new_context(viewport={'width': width, 'height': 700},
                                                  is_mobile=True, has_touch=True)
                    page = context.new_page()
                    errors = []
                    submissions = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    session = {'csrf': 'a' * 64}
                    if action == 'password':
                        session.update(user_id='synthetic', temporary=True)
                    token = language.CURRENT.set(lang)
                    try:
                        title = 'Sign in' if action == 'login' else 'Change password'
                        document = resources.rewrite(language.page(account_page(session, title).decode(), session['csrf']))
                    finally:
                        language.CURRENT.reset(token)

                    def route(request):
                        path = urlsplit(request.request.url).path
                        resource = resources.paths.get(path)
                        if path == '/api/release':
                            request.fulfill(json={'version': VERSION})
                        elif resource:
                            request.fulfill(body=resource.data, content_type=resource.mime)
                        elif path == '/api/auth/' + action:
                            submissions.append(request.request.post_data_json)
                            request.fulfill(status=403, json={'error': 'Synthetic rejection'})
                        else:
                            request.fulfill(body=document, content_type='text/html')

                    page.route('https://gm.example.test/**', route)
                    page.goto('https://gm.example.test/' + action)
                    submit = page.locator('#account-form button[type=submit]')
                    expect(submit).to_be_enabled()
                    initial = geometry(page)
                    toolbar_bottom = page.locator('#prefs-menu').evaluate(
                        '(element) => element.getBoundingClientRect().bottom + scrollY')
                    assert 0 <= initial['top'] - toolbar_bottom <= 24, initial
                    cdp = context.new_cdp_session(page)
                    # Simulate browser-bar and keyboard viewport changes, then restore height.
                    for height in (844, 700, 780, 380, 700) * 3:
                        page.set_viewport_size({'width': width, 'height': height})
                        for distance in (-500, 500):
                            cdp.send('Input.synthesizeScrollGesture', {
                                'x': width // 2, 'y': height // 2,
                                'yDistance': distance, 'gestureSourceType': 'touch',
                            })
                        current = geometry(page)
                        assert abs(current['top'] - initial['top']) <= 1, (initial, current)
                        assert abs(current['height'] - initial['height']) <= 1, (initial, current)
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.set_viewport_size({'width': width, 'height': 380})
                    for field in page.locator('#account-form input:not([type=checkbox])').all():
                        field.fill('synthetic123')
                    submit.scroll_into_view_if_needed()
                    expect(submit).to_be_in_viewport()
                    submit.tap()
                    expect(page.locator('#account-error')).to_have_text('Synthetic rejection')
                    assert len(submissions) == 1
                    assert abs(geometry(page)['top'] - initial['top']) <= 1
                    page.screenshot(path=str(artifacts / f'{action}-{width}-{lang}.png'), full_page=True)
                    assert not errors, errors
                    results.append({'width': width, 'language': lang, 'action': action,
                                    'viewportChanges': 15, 'touchScrolls': 30,
                                    'cardDrift': 0, 'submitTappedInShortViewport': True})
                    context.close()
        browser.close()
    report = {'modelCalls': 0, 'realLogin': False, 'checks': results}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
