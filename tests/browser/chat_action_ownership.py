"""Real chat API renders native, browser-chat and browser-turn audit owners."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'tests'))
sys.path.insert(0, str(REPO / 'src'))


def fixture(directory):
    from goodmorning.records.inbox_store import InboxStore, initialize, stamp
    from goodmorning.web.briefing_chat import MODES
    from goodmorning.web.briefing_server import BrowserApp, serve_live
    from test_briefing_chat import MockChamber, ImmediateThread
    from support import returning_viewer

    root = Path(directory)
    returning_viewer(root)
    (root / 'profile.md').write_text('city: London\ntimezone: UTC\nnews_country: GB\nsecretary_language: English\n')
    initialize(root)
    chamber = MockChamber(root)
    app = BrowserApp(root, chamber)
    store = InboxStore(root, write=True)
    try:
        for index, mode in enumerate(MODES):
            chat, turn = str(index + 1) * 32, str(index + 5) * 32
            with patch('goodmorning.web.briefing_chat.threading.Thread', ImmediateThread):
                app.chats.start({'id': chat, 'mode': mode, 'text': f'{mode} request'})
                if mode == 'initialize':
                    app.chats.reply(chat, 'form', 'form_city', {'answer': {'city': 'London'}})
                    app.chats.reply(chat, 'permission', 'permission_setup', {'decision': 'reject'})
                app.chats.send(chat, {'id': turn, 'text': 'Save confirmed changes'})
            session = app.chats.get(chat)['session']
            for owner, label in ((chat, 'Legacy chat'), (turn, 'Legacy turn'), (session, 'Native session')):
                store.mutate('add', {'kind': 'todo', 'raw': f'{label} {mode}'}, owner, owner, stamp(root))
    finally:
        store.close()
    serve_live(app, 0)


def main():
    artifacts = Path(sys.argv[1])
    artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    checks = []
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-action-owners-') as directory:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve-fixture', directory],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        address = process.stdout.readline().strip().removeprefix('Private live viewer: ')
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                for width in (1440, 390):
                    page = browser.new_page(viewport={'width': width, 'height': 1000}, reduced_motion='reduce')
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    for index, mode in enumerate(('initialize', 'secretary', 'todo', 'eureka')):
                        page.goto(address + '/chat?id=' + str(index + 1) * 32)
                        cards = page.locator('#chat-messages [data-special="action"]')
                        expect(cards).to_have_count(3)
                        for label in ('Legacy chat', 'Legacy turn', 'Native session'):
                            expect(cards.filter(has_text=f'{label} {mode}')).to_have_count(1)
                        page.reload()
                        expect(cards).to_have_count(3)
                        expect(page.locator('.message-enter')).to_have_count(0)
                        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                        checks.append({'width': width, 'mode': mode, 'owners': 3, 'refresh': True})
                    assert not errors, errors
                    page.screenshot(path=str(artifacts / f'ownership-{width}.png'), full_page=True)
                    page.close()
                browser.close()
        finally:
            process.terminate()
            process.communicate(timeout=5)
    report = {'modelCalls': 0, 'mockedChatResponses': 0, 'checks': checks}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    if '--serve-fixture' in sys.argv:
        fixture(sys.argv[-1])
    else:
        main()
