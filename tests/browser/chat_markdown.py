"""Rendered Markdown, privacy, history and all palettes with a synthetic agent."""
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[2]
SAMPLE = '''## A little room to plan

**Done and saved.** Your *confirmed* priorities are easier to scan.
Keep `projects/ST-Morph.md` handy; ~~old wording~~ is replaced.

- **Must-do:** prepare the project update.
  - Review the findings first.
- **Nice-to-do:** tidy the notes if there is time.

3. Review the plan.
4. Share the summary.

- [x] Saved your correction
- [ ] Prepare the update

> Focus on the confirmed work, not a new deadline.

[Project notes](/chat?mode=secretary) · [Reference][source]

[source]: https://example.org/notes?a=1&amp;b=2 "Reference notes"

---

| Project | Priority | Next action |
| :--- | :---: | ---: |
| ST-Morph | Must-do | Prepare the update |
| Research | Nice-to-do | Review one useful paper |

```python
print("<img> stays code &amp; stays literal")
'''+ 'result = "' + 'long_code_' * 35 + '''"
```

### 下一步
保留已确认的计划。 **不要虚构进度。**
'''
UNSAFE = '''<img src="/api/private-record" onerror="window.markdownExecuted = true">
<script>window.markdownExecuted = true</script>
<svg onload="window.markdownExecuted = true"></svg>

[Script](javascript:alert(1)) [Encoded](java&#x73;cript:alert(1))
[Control](jav&#x09;ascript:alert(1)) [Data](data:text/html,hello)
[File](file:///etc/passwd) [Credentials](https://user:password@example.org)
![Private image](/api/private-image) ![Remote image](https://example.org/tracker.png)

&lt;img src=x onerror=alert(1)&gt; &amp; &#x4e2d;
'''


def contrast(foreground, background):
    def luminance(color):
        if color.startswith('color(srgb '):
            values = [float(value) for value in color.removeprefix('color(srgb ').removesuffix(')').split()]
        else:
            values = [float(value.strip()) / 255 for value in color.removeprefix('rgb(').removesuffix(')').split(',')]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in values]
        return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))
    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + .05) / (dark + .05)


def check_markdown(browser, address, artifacts):
    checks = []
    for width in (1440, 768, 390, 320):
        page = browser.new_page(viewport={'width': width, 'height': 1000}, reduced_motion='reduce')
        errors, image_requests = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: image_requests.append(request.url)
                if '/api/private-' in request.url or 'tracker.png' in request.url else None)
        page.clock.set_system_time(datetime.fromisoformat('2026-10-12T10:00:00+00:00'))
        messages = [{'id': 'user', 'role': 'user', 'text': '**Keep my wording**\n<img>'},
                    {'id': 'reply', 'role': 'assistant', 'text': SAMPLE, 'language': 'en'},
                    {'id': 'unsafe', 'role': 'assistant', 'text': UNSAFE},
                    {'id': 'question', 'role': 'assistant', 'kind': 'question', 'text': '**Literal question**\n- Original option'}]
        status = {'mode': 'secretary', 'state': 'idle', 'label': 'Ready for your reply', 'language': 'en',
                  'messages': messages, 'forms': [], 'permissions': []}
        page.route('**/api/chats/*', lambda route: route.fulfill(json=status))
        page.goto(address + '/chat?id=' + 'f' * 32)
        content = page.locator('[data-message="reply"] .message-text')
        expect(content.locator('h2')).to_have_text('A little room to plan')
        expect(content.locator('strong').first).to_have_text('Done and saved.')
        expect(content.locator('em')).to_have_text('confirmed')
        expect(content.locator('del')).to_have_text('old wording')
        expect(content.locator('ul ul li')).to_have_text('Review the findings first.')
        expect(content.locator('ol')).to_have_attribute('start', '3')
        expect(content.get_by_role('checkbox', name='Saved your correction')).to_be_checked()
        expect(content.get_by_role('checkbox', name='Prepare the update')).not_to_be_checked()
        expect(content.get_by_role('checkbox').first).to_be_disabled()
        expect(content.locator('th')).to_have_count(3)
        expect(content.locator('th').nth(1)).to_have_css('text-align', 'center')
        expect(content.locator('blockquote')).to_contain_text('Focus on the confirmed work')
        expect(content.locator('pre code')).to_contain_text('<img> stays code &amp; stays literal')
        expect(content.locator('h3')).to_have_text('下一步')
        expect(content).not_to_contain_text('[source]:')
        external = content.get_by_role('link', name='Reference', exact=True)
        expect(external).to_have_attribute('href', 'https://example.org/notes?a=1&b=2')
        expect(external).to_have_attribute('target', '_blank')
        expect(external).to_have_attribute('rel', 'noopener noreferrer')
        expect(content.get_by_role('link', name='Project notes')).not_to_have_attribute('target')
        expect(page.locator('.chat-message.user .message-text')).to_have_text('**Keep my wording**\n<img>')
        expect(page.locator('.chat-message.user strong, .chat-message.question strong')).to_have_count(0)
        unsafe = page.locator('[data-message="unsafe"] .message-text')
        expect(unsafe.locator('a, img, script, svg, iframe, style')).to_have_count(0)
        expect(unsafe).to_contain_text('<img src="/api/private-record"')
        expect(unsafe).to_contain_text('Private image')
        expect(unsafe).to_contain_text('<img src=x onerror=alert(1)> & 中')
        assert not page.evaluate('Boolean(window.markdownExecuted)')
        assert not image_requests, image_requests
        page.evaluate('window.savedHeading = document.querySelector("[data-message=reply] h2")')
        page.evaluate("messageSignature = ''; pollChat()")
        page.wait_for_function('() => !polling')
        assert page.evaluate('window.savedHeading === document.querySelector("[data-message=reply] h2")')
        page.evaluate('document.fonts.ready')
        for edition, scheme in (('gm', 'classic'), ('gm', 'warm'), ('gn', 'classic')):
            page.evaluate('''([edition, scheme]) => {
                clearTimeout(themeTimer); document.documentElement.dataset.edition = edition;
                document.documentElement.dataset.dayScheme = scheme;
                document.querySelector('#chat-scroll').scrollTop = 0;
            }''', [edition, scheme])
            palette = content.evaluate('''node => {
                const style = getComputedStyle(node), bubble = getComputedStyle(node.parentElement);
                const sample = selector => getComputedStyle(node.querySelector(selector));
                return {ink: style.color, bubble: bubble.backgroundColor,
                    link: sample('a').color, quote: sample('blockquote').color,
                    codeInk: sample('code').color, codePaper: sample('code').backgroundColor,
                    headerInk: sample('th').color, headerPaper: sample('th').backgroundColor};
            }''')
            ratios = {name: round(contrast(palette[foreground], palette[background]), 2)
                      for name, foreground, background in (
                          ('body', 'ink', 'bubble'), ('link', 'link', 'bubble'), ('quote', 'quote', 'bubble'),
                          ('code', 'codeInk', 'codePaper'), ('table', 'headerInk', 'headerPaper'))}
            assert all(value >= 4.5 for value in ratios.values()), (edition, scheme, ratios)
            assert content.locator('h2').evaluate('node => parseFloat(getComputedStyle(node).fontSize)') < 24
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            assert page.locator('#chat-scroll').evaluate('node => node.scrollWidth <= node.clientWidth')
            page.locator('#chat-scroll').screenshot(path=str(artifacts / f'markdown-{edition}-{scheme}-{width}-top.png'))
            content.locator('table').scroll_into_view_if_needed()
            page.locator('#chat-scroll').screenshot(path=str(artifacts / f'markdown-{edition}-{scheme}-{width}-table.png'))
            if width < 400:
                assert content.locator('.markdown-table').evaluate('node => node.scrollWidth > node.clientWidth')
                content.locator('.markdown-table').focus()
                page.keyboard.press('ArrowRight')
                page.wait_for_function('() => document.querySelector(".markdown-table").scrollLeft > 0')
            assert content.locator('pre').evaluate('node => node.scrollWidth > node.clientWidth')
            checks.append({'width': width, 'edition': edition, 'scheme': scheme, 'contrast': ratios, 'overflow': False})
        messages[1]['text'] = '### Updated reply\n\n**Still formatted.**'
        page.evaluate('pollChat()')
        expect(content.locator('h3')).to_have_text('Updated reply')
        page.reload()
        expect(page.locator('[data-message="reply"] h3')).to_have_text('Updated reply')
        page.evaluate('''() => {
            const original = secretaryMarkdown;
            secretaryMarkdown = () => { throw new Error('Synthetic parse failure'); };
            showMessages([{id: 'fallback', role: 'assistant', text: '**Keep the reply readable**'}]);
            secretaryMarkdown = original;
        }''')
        expect(page.locator('[data-message="fallback"] .message-text')).to_have_text('**Keep the reply readable**')
        assert not errors, errors
        # Only the tab-scoped conversation reference may persist, never message text.
        assert page.evaluate(r'''() => localStorage.length === 0 && Object.keys(sessionStorage).every(key => {
            if (!/^goodmorning\.chat\.workspace\.[a-f0-9]{64}$/.test(key)) return false;
            const value = JSON.parse(sessionStorage.getItem(key));
            return Object.keys(value).sort().join(',') === 'away,chat,draft,resume'
                && [value.chat, value.resume].every(id => id === null || /^[a-f0-9]{32}$/.test(id));
        })''')
        page.close()
    return checks


def main():
    artifacts = Path(sys.argv[1]); artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-markdown-') as directory:
        process = subprocess.Popen([sys.executable, str(REPO / 'tests/test_briefing_chat.py'), '--serve-fixture', directory],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            address = process.stdout.readline().strip().removeprefix('Private live viewer: ')
            if not address.startswith('http://'): raise RuntimeError('Synthetic chat fixture did not start')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                checks = check_markdown(browser, address, artifacts)
                browser.close()
        finally:
            process.terminate(); process.communicate(timeout=5)
    report = {'modelCalls': 0, 'checks': checks, 'unsafeMarkup': 'literal', 'imageRequests': 0,
              'historyRefresh': True, 'streamingUpdate': True, 'parseFailureFallback': True}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
