"""Section publication browser experiment with an isolated agent, never a paid model."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'src'))
sys.path.insert(0, str(REPO / 'tests'))
from goodmorning.web.briefing_server import BrowserApp, serve_live
from test_briefing_server import FakeChamber


def fixture(root):
    class StreamChamber(FakeChamber):
        def pending(self, session):
            if (root / 'outage').exists():
                raise TimeoutError('Mock secretary outage')
            forms, permissions = super().pending(session)
            if (root / 'ask').exists():
                forms = [{'id': 'frm_later', 'title': 'One detail before the next section', 'fields': [
                    {'key': 'detail', 'title': 'Your preference', 'type': 'string', 'required': True}]}]
            return forms, permissions

        def request(self, path, body):
            if '/frm_later/' in path:
                (root / 'ask').unlink()
                return {}
            return super().request(path, body)

        def control(self, action, **kwargs):
            if action == 'session.status':
                self.busy = not (root / 'stop').exists()
            return super().control(action, **kwargs)
    serve_live(BrowserApp(root, StreamChamber()), 0)


def run(artifacts):
    from playwright.sync_api import sync_playwright, expect
    if artifacts:
        artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for kind in ('gm', 'gn'):
            for width, height in ((1440, 900), (390, 844), (320, 568)):
                with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-stream-') as directory:
                    root = Path(directory)
                    (root / 'profile.md').write_text('secretary_language: English\ntimezone: Europe/London\ncity: London, GB\nnews_country: GB\n')
                    (root / 'daily').mkdir()
                    server = subprocess.Popen([sys.executable, __file__, '--serve', directory], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    address = server.stdout.readline().strip().removeprefix('Private live viewer: ')
                    page = browser.new_page(viewport={'width': width, 'height': height}, reduced_motion='no-preference', has_touch=width < 700)
                    errors, previews = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    def response(response):
                        if '/preview?' in response.url:
                            previews.append({**response.json(), '_after': int(response.url.rsplit('after=', 1)[1])})
                    page.on('response', response)
                    def screenshot(label):
                        if artifacts:
                            page.evaluate('if (document.activeElement.matches(".skip-link")) document.activeElement.blur()')
                            page.screenshot(path=str(artifacts / f'{kind}-{width}-{label}.png'), full_page=True)
                    def command(script, *args):
                        result = subprocess.run([sys.executable, str(REPO / 'scripts/goodmorning.py'), script, '--secretary-dir', directory, *args], capture_output=True, text=True)
                        assert result.returncode == 0, result.stdout + result.stderr
                        return json.loads(result.stdout)
                    try:
                        page.goto(address + f'/{kind}.html')
                        expect(page.locator('#generate')).to_be_visible()
                        page.locator('#generate').click()
                        expect(page.get_by_role('heading', name='How did today go?')).to_be_visible()
                        page.get_by_text('No completion report', exact=True).click()
                        page.get_by_role('button', name='Send answer').click()
                        page.get_by_role('button', name='Allow once').click()
                        expect(page.locator('#agent-questions')).to_be_empty()
                        config = json.loads(page.locator('#browser-config').get_attribute('data-config'))
                        date = config['date']
                        jobs = json.loads((root / 'browser-jobs/jobs.json').read_text())
                        job = jobs[date + '.' + kind]['id']
                        tags = ['weather', 'news', 'schedule', 'nice-to-do', 'reminders'] if kind == 'gm' else ['today', 'still-open', 'tomorrow', 'notes']
                        titles = ['Weather', 'Yesterday’s news', 'Schedule', 'Nice-to-do', 'Reminders'] if kind == 'gm' else ['Today', 'Still open', 'Tomorrow', 'Notes']
                        plan = list(map(list, zip(tags, titles)))
                        draft, plan_file = root / 'draft.json', root / 'plan.json'
                        document = {'v': 1, 'greeting': 'Morning, let’s begin.' if kind == 'gm' else 'Evening, take a breath.', 'opening': 'We’ll take this one section at a time.', 'sections': []}
                        draft.write_text(json.dumps(document)); plan_file.write_text(json.dumps(plan))
                        command('stream', '--job', job, '--answer-file', str(draft), '--plan-file', str(plan_file))
                        expect(page.locator('h1')).to_have_text(document['greeting'])
                        expect(page.locator('.briefing-section[data-pending]')).to_have_count(len(plan))
                        expect(page.locator('.briefing-section.is-working')).to_have_count(1)
                        page.emulate_media(reduced_motion='reduce')
                        assert page.locator('.is-working .section-loader span').first.evaluate('el => getComputedStyle(el).animationName') == 'none'
                        assert page.locator('.is-working .skeleton-lines').evaluate('el => getComputedStyle(el).animationName') == 'none'
                        page.emulate_media(reduced_motion='no-preference')
                        screenshot('section-loaders')
                        first_block = ['weather', [['temperature', '14°C', 'Synthetic forecast; take a jacket.'], ['precipitation', '40%', 'Rain possible after 15:00.'], ['air', '31', 'Good air.']]] if kind == 'gm' else ['tasks', [['partial', 'Read the paper', 'Two methods sections reviewed; the conclusion remains open.']]]
                        notes = ['Allow room for the rain.' if kind == 'gm' else 'The methods review is useful progress.']
                        for index, (tag, title) in enumerate(plan):
                            if tag in ('nice-to-do', 'still-open'):
                                command('stream', '--job', job, '--skip-next')
                                expect(page.locator(f'#section-{index + 1}')).to_be_hidden()
                                continue
                            block = first_block if index == 0 else (
                                ['news', 'World', [['Synthetic headline', 'A full cited summary for the experiment.', [['Publisher', 'https://example.org/story']]]]] if tag == 'news' else
                                ['agenda', [[date, '10:00', 'Synthetic planning meeting', 'Office', 'Bring the notes.']]] if tag in ('schedule', 'tomorrow') else
                                ['p', 'Clarify the pending idea before changing the plan.'])
                            note = notes[0] if index == 0 else 'Keep a little space around the next step.'
                            document['sections'].append([tag, [block], note, title])
                            draft.write_text(json.dumps(document))
                            command('stream', '--job', job, '--answer-file', str(draft))
                            expect(page.locator(f'#section-{index + 1}')).not_to_have_attribute('data-pending', 'true')
                            assert not (root / 'daily' / f'{date}.{kind}.json').exists()
                            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                            if index == 0:
                                page.locator('#section-1').scroll_into_view_if_needed()
                                page.evaluate('window.firstPublished = document.querySelector("#section-1")')
                                expect(page.locator('.briefing-section[data-pending]')).to_have_count(len(plan) - 1)
                                screenshot('first-section-readable')
                                (root / 'ask').write_text('ask')
                                expect(page.get_by_role('heading', name='One detail before the next section')).to_be_visible()
                                expect(page.locator('.briefing-section.is-working')).to_have_count(0)
                                page.get_by_role('textbox', name='Your preference').fill('Keep the already published section unchanged.')
                                page.evaluate('poll()')
                                expect(page.get_by_role('textbox', name='Your preference')).to_have_value('Keep the already published section unchanged.')
                                screenshot('paused-with-first-section')
                                page.reload()
                                expect(page.locator('#section-1')).not_to_have_attribute('data-pending', 'true')
                                expect(page.get_by_role('heading', name='One detail before the next section')).to_be_visible()
                                page.get_by_role('textbox', name='Your preference').fill('Continue.')
                                page.get_by_role('button', name='Send answer').click()
                                expect(page.locator('#agent-questions')).to_be_empty()
                                # A secretary outage must not hide a durable preview on refresh.
                                (root / 'outage').write_text('outage'); page.reload()
                                expect(page.locator('#generation-status')).to_contain_text('connection is unavailable')
                                expect(page.locator('#section-1')).not_to_have_attribute('data-pending', 'true')
                                expect(page.locator('.briefing-section.is-working')).to_have_count(0)
                                (root / 'outage').unlink(); page.reload()
                                expect(page.locator('#section-1')).not_to_have_attribute('data-pending', 'true')
                                page.evaluate('window.firstPublished = document.querySelector("#section-1")')
                            else:
                                assert page.evaluate('window.firstPublished === document.querySelector("#section-1")'), 'Earlier section was replaced'
                                expect(page.locator('#section-1 .section-takeaway')).to_have_text(notes[0])
                        # Stopping before the final save leaves the preview readable and recoverable.
                        (root / 'stop').write_text('stop')
                        expect(page.locator('#generation-status')).to_contain_text('Preparation stopped')
                        expect(page.locator('.preview-notice')).to_contain_text('Unfinished preview')
                        assert (root / 'browser-jobs' / (job + '.preview.json')).exists()
                        screenshot('interrupted-preview')
                        (root / 'stop').unlink(); page.reload()
                        expect(page.locator('.briefing-section[data-pending]:visible')).to_have_count(0)
                        document['closing'] = 'Take care.'
                        draft.write_text(json.dumps(document))
                        command('stream', '--job', job, '--answer-file', str(draft))
                        expect(page.locator('.briefing-closing')).to_have_text('Take care.')
                        # No prior-section HTML is resent after restoration unless the page itself reloaded.
                        assert any(item.get('changes') and 'sections' not in item for item in previews)
                        for item in previews:
                            if item['_after'] >= 0 and item.get('changes'):
                                assert all(change['index'] >= item['_after'] for change in item['changes'])
                        command('state', '--today', date, f'--mark-{kind}', '--session', 'ses_fixture', '--browser-job', job, '--answer-file', str(draft), '--json')
                        (root / 'stop').write_text('stop')
                        expect(page.locator('.source-link')).to_have_attribute('href', f'/d/{date}/{kind}.json')
                        expect(page.locator('.preview-notice')).to_have_count(0)
                        expect(page.locator('.briefing-section')).to_have_count(len(document['sections']))
                        expect(page.locator('.scroll-chunk')).to_have_count(len(document['sections']))
                        assert not (root / 'browser-jobs' / (job + '.preview.json')).exists()
                        assert len(json.loads((root / 'browser-jobs/jobs.json').read_text())) == 1
                        assert not (root / 'browser').exists()
                        assert not errors, errors
                        page.emulate_media(reduced_motion='reduce')
                        assert page.evaluate('[...document.getAnimations()].every(a => a.playState !== "running")')
                        screenshot('completed-save')
                        results.append({'kind': kind, 'width': width, 'partial_before_save': True, 'earlier_nodes_preserved': True, 'refresh': 'pass', 'pause': 'pass', 'save': 'pass', 'model_calls': 0})
                    finally:
                        page.close(); server.terminate(); server.communicate(timeout=5)
        browser.close()
    print(json.dumps({'cases': results, 'baseline': 'No section readable until completed save', 'streaming': 'First section readable while all later sections remain unresolved', 'devices': 'Chromium emulation, not physical phones'}))


if __name__ == '__main__':
    if '--serve' in sys.argv:
        fixture(Path(sys.argv[-1]))
    else:
        run(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
