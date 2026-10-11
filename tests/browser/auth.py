"""Synthetic form rendering: visibility toggles preserve text and login preferences."""
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from goodmorning.security.briefing_gateway import account_page, ASSETS


def main():
    artifacts = Path(sys.argv[1]); artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []
    secret = 'synthetic secret symbol & Unicode 中文'
    replacement = 'New中文123&'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width in (390, 768, 1440):
            page = browser.new_page(viewport={'width': width, 'height': 900})
            errors = []; bodies = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def route(request):
                path = urlsplit(request.request.url).path
                if path in ('/auth.js', '/auth.css'):
                    request.fulfill(body=(ASSETS / path.lstrip('/')).read_bytes(),
                                    content_type='text/javascript' if path.endswith('js') else 'text/css')
                elif path == '/api/auth/login' or path == '/api/auth/password':
                    bodies.append(request.request.post_data_json)
                    request.fulfill(status=403, json={'error': 'Synthetic rejection; no real login attempted'})
                else:
                    session = {'csrf': 'a' * 64}
                    if path == '/password': session.update(user_id='synthetic', temporary=True)
                    request.fulfill(body=account_page(session, 'Sign in' if path != '/password' else 'Change password'), content_type='text/html')
            page.route('https://gm.example.test/**', route)
            page.goto('https://gm.example.test/login')
            password = page.get_by_label('Password', exact=True)
            password.fill(secret)
            toggle = page.get_by_role('button', name='Show password', exact=True)
            toggle.click()
            expect(password).to_have_attribute('type', 'text')
            expect(password).to_have_value(secret)
            expect(page.get_by_role('button', name='Hide password', exact=True)).to_have_attribute('aria-pressed', 'true')
            page.get_by_role('button', name='Hide password', exact=True).click()
            expect(password).to_have_attribute('type', 'password')
            page.get_by_label('Username', exact=True).fill('synthetic-user')
            remember = page.get_by_role('checkbox', name='Remember me for 60 days on this device')
            expect(remember).not_to_be_checked()
            page.get_by_role('button', name='Sign in', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('Synthetic rejection')
            assert bodies[-1] == {'username': 'synthetic-user', 'password': secret, 'remember': False}
            remember.check()
            with page.expect_response('**/api/auth/login'):
                page.get_by_role('button', name='Sign in', exact=True).click()
            assert bodies[-1]['remember'] is True and bodies[-1]['password'] == secret
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.screenshot(path=str(artifacts / ('login-' + str(width) + '.png')), full_page=True)
            page.goto('https://gm.example.test/password')
            for name, value in (('Current password', secret), ('New password', replacement), ('Repeat new password', replacement)):
                field = page.get_by_label(name, exact=True); field.fill(value)
                page.get_by_role('button', name='Show ' + name.lower(), exact=True).click()
                expect(field).to_have_attribute('type', 'text'); expect(field).to_have_value(value)
                page.get_by_role('button', name='Hide ' + name.lower(), exact=True).click()
            with page.expect_response('**/api/auth/password'):
                page.get_by_role('button', name='Change password', exact=True).click()
            assert bodies[-1] == {'current': secret, 'replacement': replacement}
            for value in ('abc12','abcdef','123456','a1'+'x'*31):
                page.get_by_label('New password',exact=True).fill(value)
                page.get_by_label('Repeat new password',exact=True).fill(value)
                count=len(bodies)
                page.get_by_role('button',name='Change password',exact=True).click()
                expect(page.get_by_role('alert')).to_contain_text('6–32 characters')
                assert len(bodies)==count
            for value in ('abcde1','a1'+'x'*30,'a1'+'🙂'*30):
                page.get_by_label('New password',exact=True).fill(value)
                page.get_by_label('Repeat new password',exact=True).fill(value)
                with page.expect_response('**/api/auth/password'):
                    page.get_by_role('button',name='Change password',exact=True).click()
                assert bodies[-1]['replacement']==value
            assert page.evaluate('localStorage.length === 0 && sessionStorage.length === 0')
            assert not errors, errors
            results.append({'width': width, 'toggleFields': 4, 'inputPreserved': True, 'rememberBoolean': True,
                            'passwordPolicy':'6–32 inclusive, letter and digit required, optional symbols', 'pageErrors': 0})
            page.close()
        browser.close()
    report = {'modelCalls': 0, 'realLogin': False, 'checks': results}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
