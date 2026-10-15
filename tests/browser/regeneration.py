"""Today's confirmed replacement through the real viewer, using only synthetic records."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]


def fixture(root, port=0):
    sys.path.insert(0, str(REPO / 'src'))
    sys.path.insert(0, str(REPO / 'tests'))
    from goodmorning.briefings.briefing_job import act
    from goodmorning.briefings.briefing_preflight import initialize, answer
    from goodmorning.web.briefing_server import BrowserApp, serve_live
    from support import returning_viewer
    from support import FakeChamber

    class IdleChamber(FakeChamber):
        def __init__(self):
            super().__init__()
            self.forms=[];self.permissions=[];self.busy=False;self.count=0

        def pending(self, session):
            return [], []

        def control(self, action, **kwargs):
            if action == 'session.create':
                self.count += 1
                (root/'session-count').write_text(str(self.count))
                return {'sessionId':'ses_replacement_'+str(self.count)}
            return super().control(action, **kwargs)

    returning_viewer(root)
    app=BrowserApp(root,IdleChamber(),preflight=True)
    day=app.today()
    (root/'daily'/(day+'.md')).write_text('# '+day+'\n\n## must-do\n- [x] Finished task\n- [ ] Open task\n')
    for kind,identifier in [('gm','a'*32),('gn','b'*32)]:
        job={'id':identifier,'date':day,'kind':kind,'session':'ses_original_'+kind,'state':'running'}
        app.jobs[day+'.'+kind]=job;app.save_jobs()
        initialize(root,job)
        if kind=='gn':answer(root,job,{'completed':['none'],'details':'Open task is still partial.'})
        tag,title=('must-do','Project steps') if kind=='gm' else ('today','Today')
        act(root,identifier,job['session'],'init',{'greeting':'Good morning.' if kind=='gm' else 'Good night.',
            'opening':'Your plans and progress are safely recorded.','plan':[[tag,title]]})
        section=[tag,[['tasks',[['open','Open task','Continue when ready.']]]]] if kind=='gm' else [tag,[['p','Finished task is complete. Open task is still partial.']]]
        act(root,identifier,job['session'],'publish',{'position':0,'section':section})
        act(root,identifier,job['session'],'finish',{})
        app.status(identifier)
    serve_live(app,port)


def main():
    artifacts=Path(sys.argv[1]) if len(sys.argv)>1 else None
    if artifacts:artifacts.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode',prefix='gm-regeneration-') as directory:
        root=Path(directory)
        (root/'profile.md').write_text('secretary_language: English\ntimezone: Europe/London\ncity: London, GB\nnews_country: GB\n')
        (root/'daily').mkdir()
        server=subprocess.Popen([sys.executable,__file__,'--serve',directory],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        address=server.stdout.readline().strip().removeprefix('Private live viewer: ')
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch()
                for index,(width,kind) in enumerate([(1440,'gm'),(390,'gn'),(320,'gm')]):
                    page=browser.new_page(viewport={'width':width,'height':900 if width==1440 else 844},reduced_motion='reduce')
                    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(address+'/'+kind+'.html')
                    expect(page.get_by_role('button',name='Regenerate today’s briefing',exact=True)).to_be_visible()
                    config=json.loads(page.locator('#browser-config').get_attribute('data-config'))
                    source=root/'daily'/(config['date']+'.'+kind+'.json');original=source.read_bytes()
                    if artifacts:page.screenshot(path=str(artifacts/f'{kind}-saved-{width}.png'))
                    page.locator('#regenerate').click()
                    expect(page.get_by_role('dialog')).to_be_visible()
                    expect(page.locator('#regenerate-description')).to_contain_text('Tasks, completions and saved feedback are kept.')
                    if artifacts:page.screenshot(path=str(artifacts/f'{kind}-confirmation-{width}.png'))
                    page.get_by_role('button',name='Keep this briefing').click()
                    expect(page.get_by_role('dialog')).not_to_be_visible()
                    self_count=(root/'session-count').read_text() if (root/'session-count').exists() else '0'
                    page.locator('#regenerate').click()
                    queued={'queue':[{'work':'regenerate','date':config['date'],'edition':kind,'previous':config['job'],'position':1}], 'depth':1}
                    page.route('**/api/queue',lambda route:route.fulfill(json=queued))
                    page.route('**/api/regenerate',lambda route:route.fulfill(status=202,json={'queued':True,'position':1,'depth':1}),times=1)
                    page.get_by_role('button',name='Regenerate briefing',exact=True).click()
                    expect(page.locator('#regeneration-status')).to_contain_text('In queue')
                    self_count_after=(root/'session-count').read_text() if (root/'session-count').exists() else '0'
                    assert self_count_after==self_count
                    page.reload()
                    expect(page.locator('#regeneration-status')).to_contain_text('In queue')
                    assert source.read_bytes()==original
                    body={'date':config['date'],'kind':kind,'previous':config['job'],'id':f'{index+12:032x}'}
                    headers={'Origin':address,'X-Briefing-CSRF':config['csrf']}
                    result=page.request.post(address+'/api/regenerate',data=body,headers=headers)
                    assert result.ok,result.text()
                    new=result.json()['job']
                    queued['queue']=[];queued['depth']=0
                    expect(page.get_by_role('button',name='Continue existing session')).to_be_visible()
                    page.unroute('**/api/queue')
                    assert source.read_bytes()==original
                    repeat=page.request.post(address+'/api/regenerate',data=body,headers=headers)
                    assert repeat.ok and repeat.json()['job']==new
                    job=json.loads((root/'browser-jobs/jobs.json').read_text())[config['date']+'.'+kind]
                    def command(action,payload):
                        result=subprocess.run([sys.executable,str(REPO/'scripts/goodmorning.py'),'job','--secretary-dir',directory,
                            '--job',new,'--session',job['session'],action],input=json.dumps(payload),capture_output=True,text=True)
                        assert result.returncode==0,result.stdout+result.stderr
                    command('init',{'greeting':'Your fresh briefing.','opening':f'All previous progress is preserved. Edition {index+1}.','plan':[['weather','Weather']] if kind=='gm' else [['today','Today']]})
                    command('publish',{'position':0,'section':['weather' if kind=='gm' else 'today',[['p','A fresh edition, with your records preserved.']]]})
                    command('finish',{})
                    page.reload()
                    expect(page.locator('h1')).to_have_text('Your fresh briefing.')
                    expect(page.locator('#regenerate')).to_be_enabled()
                    assert source.read_bytes()!=original
                    daily=(root/'daily'/(config['date']+'.md')).read_text()
                    assert '- [x] Finished task' in daily and '- [ ] Open task' in daily
                    assert daily.count('Open task is still partial.')==1
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    page.locator('.week-picker a').first.click()
                    expect(page.locator('#regenerate')).to_have_count(0)
                    assert not errors,errors
                    page.close()
                page=browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
                page.goto(address+'/gn.html')
                config=json.loads(page.locator('#browser-config').get_attribute('data-config'))
                assert page.request.post(address+'/api/language',data={'language':'zh-CN'},
                    headers={'Origin':address,'X-Briefing-CSRF':config['csrf']}).ok
                page.reload()
                expect(page.get_by_role('button',name='重新生成今日简报',exact=True)).to_be_visible()
                page.locator('#regenerate').click()
                expect(page.locator('#regenerate-title')).to_have_text('重新生成今日简报？')
                if artifacts:page.screenshot(path=str(artifacts/'gn-confirmation-zh-mobile.png'))
                page.get_by_role('button',name='保留当前简报').click()
                page.close()
                browser.close()
            print(json.dumps({'regeneration':'pass','confirmation':'pass','queue_reload':'pass','record_preservation':'pass','viewports':3,'model_calls':0}))
        finally:
            server.terminate();server.communicate(timeout=5)


if __name__=='__main__':
    if '--serve' in sys.argv:fixture(Path(sys.argv[sys.argv.index('--serve')+1]),int(sys.argv[-1]) if sys.argv[-1].isdigit() else 0)
    else:main()
