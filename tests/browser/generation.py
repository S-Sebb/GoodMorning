"""Browser generation round-trip against the isolated mock engine fixture."""
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[2]


def recovery_fixture(root):
    sys.path.insert(0, str(REPO / 'src'))
    sys.path.insert(0, str(REPO / 'tests'))
    from goodmorning.web.briefing_server import BrowserApp, serve_live
    from support import FakeChamber
    from support import returning_viewer
    returning_viewer(root)
    class IdleChamber(FakeChamber):
        def __init__(self):
            super().__init__()
            self.forms=[];self.permissions=[];self.busy=False
        def control(self, action, **kwargs):
            if action == 'session.send':
                path=root/'sends'
                path.write_text(str(int(path.read_text())+1 if path.exists() else 1))
            return super().control(action, **kwargs)
    serve_live(BrowserApp(root,IdleChamber(),preflight=True),0)


def check_recovery(browser, artifacts):
    with tempfile.TemporaryDirectory(dir='/tmp/opencode',prefix='gm-browser-recovery-') as directory:
        root=Path(directory)
        (root/'profile.md').write_text('secretary_language: English\ntimezone: Europe/London\ncity: London, GB\nnews_country: GB\n')
        (root/'daily').mkdir()
        process=subprocess.Popen([sys.executable,__file__,'--serve-recovery',directory],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        address=process.stdout.readline().strip().removeprefix('Private live viewer: ')
        page=browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        try:
            page.goto(address+'/gn')
            date=json.loads(page.locator('#browser-config').get_attribute('data-config'))['date']
            daily=root/'daily'/(date+'.md')
            daily.write_text('# '+date+'\n\n## must-do\n- [ ] Original task\n')
            page.locator('#generate').click()
            expect(page.get_by_text('Original task',exact=True)).to_be_visible()
            # A stale duplicate queue entry must not conceal an existing form.
            page.route('**/api/edition/*/gn', lambda route:route.fulfill(json={'job':None}), times=1)
            page.route('**/api/queue', lambda route:route.fulfill(json={'queue':[
                {'work':'generate','date':date,'edition':'gn','position':1}], 'depth':1}))
            page.reload()
            expect(page.get_by_text('Original task',exact=True)).to_be_visible()
            expect(page.locator('#generation-status')).not_to_contain_text('In queue')
            page.unroute('**/api/queue')
            daily.write_text(daily.read_text()+'- [ ] New user task\n')
            # The check-in dialog covers the page; closing it reaches the refresh, which reopens it.
            page.keyboard.press('Escape')
            page.get_by_role('button',name='Refresh task list').click()
            dialog=page.get_by_role('dialog')
            expect(dialog.get_by_text('Original task',exact=True)).to_be_visible()
            assert not (root/'sends').exists()
            dialog.get_by_role('button',name='Not done').click()
            expect(dialog.get_by_text('New user task',exact=True)).to_be_visible()
            dialog.get_by_role('button',name='Not done').click()
            job=json.loads((root/'browser-jobs/jobs.json').read_text())[date+'.gn']['id']
            form=json.loads((root/'browser-jobs'/(job+'.context.json')).read_text())['form']['id']
            reply=f'/api/jobs/{job}/form/{form}/reply'
            queued={'queue':[{'work':'reply','job':job,'position':1}], 'depth':1}
            page.route('**/api/queue',lambda route:route.fulfill(json=queued))
            page.route('**'+reply,lambda route:route.fulfill(status=202,json={'queued':True,'job':job,'position':1,'depth':1}),times=1)
            dialog.get_by_role('button',name='Save and write my briefing').click()
            expect(page.locator('#generation-status')).to_contain_text('In queue')
            expect(page.locator('dialog.checkin')).to_have_count(0)
            page.reload()
            expect(page.locator('#generation-status')).to_contain_text('In queue')
            expect(page.get_by_role('dialog')).to_have_count(0)
            assert not (root/'sends').exists()
            csrf=json.loads(page.locator('#browser-config').get_attribute('data-config'))['csrf']
            receipt=page.request.post(address+reply,data={'answer':{'completed':['none'],'details':'No other updates'}},
                headers={'Origin':address,'X-Briefing-CSRF':csrf})
            assert receipt.ok
            queued['queue']=[];queued['depth']=0
            expect(page.get_by_role('button',name='Continue existing session')).to_be_visible()
            page.unroute('**/api/queue')
            page.get_by_role('button',name='Continue existing session').click()
            expect(page.get_by_role('button',name='Continue existing session')).to_be_visible()
            assert (root/'sends').read_text()=='2'
            job=json.loads((root/'browser-jobs/jobs.json').read_text())[date+'.gn']['id']
            def command(action,payload):
                result=subprocess.run([sys.executable,str(REPO/'scripts/goodmorning.py'),'job','--secretary-dir',directory,
                    '--job',job,'--session','ses_fixture',action],input=json.dumps(payload),capture_output=True,text=True)
                assert result.returncode==0,result.stdout+result.stderr
            command('init',{'greeting':'Good night.','opening':'Your actual feedback is saved.','plan':[['today','Today']]})
            command('publish',{'position':0,'section':['today',[['p','Both listed tasks remain open.']]]})
            page.reload()
            expect(page.get_by_role('article').get_by_text('Both listed tasks remain open.',exact=True)).to_be_visible()
            command('finish',{})
            page.reload()
            expect(page.locator('.briefing-tools')).to_have_count(0)
            assert '- [x]' not in daily.read_text()
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert not errors,errors
            if artifacts:page.screenshot(path=str(artifacts/'recovered-night-mobile.png'),full_page=True)
        finally:
            page.close();process.terminate();process.communicate(timeout=5)


def main():
    arguments = sys.argv[1:]
    artifacts = Path(arguments[0]) if arguments else None
    if artifacts:
        artifacts.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode',prefix='gm-browser-generation-') as directory:
        root=Path(directory)
        (root/'profile.md').write_text('secretary_language: English\ntimezone: Europe/London\ncity: London, GB\nnews_country: GB\n')
        (root/'daily').mkdir()
        process=subprocess.Popen([sys.executable,str(Path(__file__).resolve().parents[1] / 'test_briefing_server.py'),'--serve-fixture',directory],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        address=process.stdout.readline().strip().removeprefix('Private live viewer: ')
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch()
                for viewport in [{'width':1440,'height':900},{'width':390,'height':844},{'width':320,'height':568}]:
                    page=browser.new_page(viewport=viewport,reduced_motion='reduce')
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(address+'/gm')
                    expect(page.locator('.week-picker a')).to_have_count(7)
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    if viewport['width']==1440:
                        expect(page.locator('#generate')).to_be_visible()
                        assert page.locator('.avatar-display #generate').count() == 0
                        if artifacts:page.screenshot(path=str(artifacts/'not-generated-desktop.png'))
                        page.locator('#generate').click()
                        expect(page.get_by_role('heading',name='How did today go?')).to_be_visible()
                        expect(page.get_by_role('heading',name='Permission needed')).to_be_visible()
                        expect(page.locator('#agent-questions')).to_be_visible()
                        assert page.locator('.avatar-display #agent-questions').count() == 0
                        assert page.locator('#agent-questions').bounding_box()['width'] > 600
                        page.get_by_placeholder('Or write your own answer').fill('Leave progress unreported, please.')
                        # A live status refresh must preserve the draft.
                        page.evaluate('poll()')
                        expect(page.get_by_placeholder('Or write your own answer')).to_have_value('Leave progress unreported, please.')
                        if artifacts:page.screenshot(path=str(artifacts/'agent-question-and-permission.png'),full_page=True)
                        page.reload()
                        expect(page.get_by_role('heading',name='How did today go?')).to_be_visible()
                        expect(page.locator('.desk-animation')).to_have_class('desk-animation is-paused')
                        page.get_by_text('No completion report',exact=True).click()
                        page.get_by_role('button',name='Send answer').click()
                        expect(page.get_by_role('heading',name='How did today go?')).to_have_count(0)
                        page.get_by_role('button',name='Allow once').click()
                        expect(page.locator('article')).to_be_visible()
                        expect(page.locator('h1')).to_have_text('Good morning')
                        config = json.loads(page.locator('#browser-config').get_attribute('data-config'))
                        expect(page.locator('.briefing-tools')).to_have_count(0)
                        assert not list((root/'daily').glob('*.gm.md'))
                    else:
                        expect(page.locator('article')).to_be_visible()
                    # Past editions never offer historical generation.
                    page.locator('.week-picker a').first.click()
                    expect(page.locator('#generate')).to_have_count(0)
                    expect(page.get_by_text('No briefing was prepared for this day.')).to_be_visible()
                    expect(page.get_by_role('link', name='Open this day in Schedule')).to_have_attribute('href', re.compile(r'^/schedule\?view=day&day=-\d$'))
                    if artifacts:page.screenshot(path=str(artifacts/f'archive-missing-{viewport["width"]}.png'))
                    pinned=page.url
                    page.route('**/api/day',lambda route:route.fulfill(json={'date':'2099-01-01'}),times=1)
                    page.evaluate('checkDay()')
                    assert page.url==pinned,'Archive date was redirected'
                    page.unroute('**/api/day')
                    with page.expect_response(lambda response: response.url==address+'/api/day'):
                        page.goto(address+'/gn')
                    page.route('**/api/day',lambda route:route.fulfill(json={'date':'2099-01-01'}),times=1)
                    with page.expect_navigation():page.evaluate('checkDay()')
                    assert page.url==address+'/gn','Rollover changed the selected edition'
                    assert not errors,errors
                    page.close()
                check_recovery(browser,artifacts)
                browser.close()
            print(json.dumps({'format':'native-json','generation':'pass','question_reply':'pass','permission_reply':'pass','resume':'pass','draft_during_poll':'preserved','archive':'read-only and pinned','rollover':'preserves edition','explicit_recovery':'fresh task confirmation and existing-session continuation','viewports':3,'model_calls':0}))
        finally:
            process.terminate();process.communicate(timeout=5)


if __name__=='__main__':
    if '--serve-recovery' in sys.argv:recovery_fixture(Path(sys.argv[-1]))
    else:main()
