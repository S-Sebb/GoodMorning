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
                    settled(browser,address,width,artifacts)
                browser.close()
        finally:
            server.terminate();server.communicate(timeout=5)
    print(json.dumps({'modelCalls':0,'transientHistoryResponseRecovered':True,'persistentFailureReadable':True,
                     'noticeClearsAfterRecovery':True,'draftPreserved':True,'uncertainSendNeverReplayed':True,
                     'unsentMessageSentAgainOnce':True,'earlierMessagesLoadInPlace':True}))


def settled(browser,address,width,artifacts):
    """A delivery check settles by itself; an unsent message is sent again once, by choice.
    Earlier messages load above the reading position."""
    chat='a'*32
    page=browser.new_page(viewport={'width':width,'height':900},reduced_motion='reduce')
    history=[{'id':f'm{index}','role':'assistant' if index%2 else 'user','text':f'Synthetic message {index}','attachments':[]} for index in range(150)]
    unsent={'id':'undelivered:'+'b'*32,'role':'user','kind':'undelivered','text':'Synthetic unsent reminder',
            'attachments':[],'turn':'b'*32}
    phase={'value':'checking'};reads=[];posts=[]
    def status(route):
        limit=int(route.request.url.partition('limit=')[2] or 100)
        reads.append(limit)
        state,label,messages={'checking':('uncertain','Checking whether your last message reached your secretary…',history[-100:]),
            'unsent':('idle','Your last message wasn’t sent. Send it again or write a new one.',history[-100:]+[unsent]),
            'resent':('idle','Ready for your reply',history[-limit:]+[{**unsent,'id':'m-new','kind':None,'turn':posts[-1]['id'] if posts else None}])}[phase['value']]
        route.fulfill(json={'chat':chat,'mode':'secretary','state':state,'label':label,'forms':[],'permissions':[],
                            'messages':messages,'history_limited':limit<len(history)})
    def send(route):
        posts.append(json.loads(route.request.post_data));phase['value']='resent'
        route.fulfill(status=202,json={'chat':chat})
    page.route('**/api/chats',lambda route:route.fulfill(json={'defaultMode':'secretary','connected':True,'chats':[]}))
    page.route(f'**/api/chats/{chat}?*',status);page.route(f'**/api/chats/{chat}',status)
    page.route(f'**/api/chats/{chat}/messages',send)
    page.goto(address+'/chat?id='+chat)
    expect(page.locator('#chat-status')).to_contain_text('Checking whether your last message')
    expect(page.locator('#chat-send')).to_be_disabled()
    checks=len(reads)
    phase['value']='unsent'
    bubble=page.locator('[data-special="undelivered"]')
    expect(bubble).to_contain_text('Synthetic unsent reminder',timeout=8000)
    assert len(reads)>checks,'The page stopped checking an uncertain delivery'
    expect(bubble).to_contain_text('Not sent')
    expect(bubble).to_contain_text('nothing in it was saved or done')
    expect(page.locator('#chat-send')).to_be_enabled()
    page.locator('#chat-scroll').evaluate('node=>node.scrollTop=node.scrollHeight')
    page.locator('.conversation-panel').screenshot(path=str(artifacts/f'not-sent-{width}.png'))
    bubble.get_by_role('button',name='Send again').click()
    expect(page.locator('[data-special="undelivered"]')).to_have_count(0)
    expect(page.locator('#chat-messages')).to_contain_text('Synthetic unsent reminder')
    assert len(posts)==1 and posts[0]['text']=='Synthetic unsent reminder' and posts[0]['id']!='b'*32,posts
    # Earlier messages load above without moving what the reader is looking at.
    earlier=page.get_by_role('button',name='Show earlier messages')
    expect(page.locator('#chat-status')).to_contain_text('Ready for your reply')
    page.wait_for_timeout(300)
    page.locator('#chat-scroll').evaluate('node=>node.scrollTop=0')
    expect(earlier).to_be_visible()
    anchor=page.locator('[data-message="m50"]')
    before=anchor.evaluate('node=>node.getBoundingClientRect().top')
    earlier.click()
    expect(page.locator('[data-message="m0"]')).to_be_attached()
    after=anchor.evaluate('node=>node.getBoundingClientRect().top')
    assert abs(after-before)<2,(before,after)
    assert 200 in reads,reads
    expect(earlier).to_be_hidden()
    expect(page.locator('#chat-earlier')).to_be_hidden()
    assert len(posts)==1,'Loading history sent a message'
    page.close()


if __name__=='__main__':main()
