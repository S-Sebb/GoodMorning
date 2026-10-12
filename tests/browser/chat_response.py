"""Unreadable background responses recover safely; uncertain sends never replay."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from playwright.sync_api import sync_playwright, expect

REPO=Path(__file__).resolve().parents[2]


def main():
    artifacts=Path(sys.argv[1]);artifacts.mkdir(mode=0o700,parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode',prefix='gm-chat-response-') as directory:
        server=subprocess.Popen([sys.executable,str(REPO/'tests/test_briefing_chat.py'),'--serve-fixture',directory],
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            address=server.stdout.readline().strip().removeprefix('Private live viewer: ')
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch()
                for width in (1440,390):
                    page=browser.new_page(viewport={'width':width,'height':900},reduced_motion='reduce')
                    reads=[];healthy=[False];persistent=[False]
                    def listing(route):
                        reads.append(True)
                        if not healthy[0] and (persistent[0] or len(reads)==1):
                            route.fulfill(status=502,content_type='text/html',body='<html>synthetic upstream failure</html>')
                        else:route.fulfill(json={'defaultMode':'secretary','connected':True,'chats':[]})
                    page.route('**/api/chats',listing)
                    page.goto(address+'/chat?mode=secretary')
                    page.wait_for_function('() => document.querySelector("#chat-send").disabled===false')
                    expect(page.locator('#chat-error')).to_be_empty()
                    assert len(reads)==2,'History did not recover from an unreadable response'
                    text=page.locator('#chat-text');text.fill('Preserve this unsent draft.')
                    persistent[0]=True
                    page.evaluate('historyList().catch(error=>errorBox.textContent=error.message)')
                    expect(page.locator('#chat-error')).to_contain_text('Your draft is safe.')
                    expect(text).to_have_value('Preserve this unsent draft.')
                    healthy[0]=True
                    page.evaluate('historyList()')
                    expect(page.locator('#chat-error')).to_be_empty()
                    posts=[]
                    def uncertain(route):
                        if route.request.method=='POST':
                            posts.append(True);route.fulfill(status=502,content_type='text/html',body='<html>synthetic unknown delivery</html>')
                        else:listing(route)
                    page.unroute('**/api/chats');page.route('**/api/chats',uncertain)
                    page.route('**/api/chats/*',lambda route:route.fulfill(json={'chat':'a'*32,'mode':'secretary','state':'uncertain',
                        'label':'Synthetic unresolved delivery','forms':[],'permissions':[],'messages':[]}))
                    page.get_by_role('button',name='Start conversation',exact=True).click()
                    expect(page.locator('#chat-error')).to_contain_text('Refresh to check delivery')
                    expect(text).to_have_value('Preserve this unsent draft.')
                    expect(page.locator('#chat-send')).to_be_disabled()
                    assert len(posts)==1,'An uncertain send was replayed'
                    page.locator('.conversation-panel').screenshot(path=str(artifacts/f'friendly-error-{width}.png'))
                    page.close()
                browser.close()
        finally:
            server.terminate();server.communicate(timeout=5)
    print(json.dumps({'modelCalls':0,'transientHistoryResponseRecovered':True,'persistentFailureReadable':True,
                     'noticeClearsAfterRecovery':True,'draftPreserved':True,'uncertainSendNeverReplayed':True}))


if __name__=='__main__':main()
