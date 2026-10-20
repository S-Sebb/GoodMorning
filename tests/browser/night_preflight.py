"""Evening check-in dialog, its completion choices and the empty state; synthetic data, no models."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[2]


def fixture(root, scenario):
    sys.path.insert(0, str(REPO/'src'))
    sys.path.insert(0, str(REPO/'tests'))
    from support import returning_viewer
    from support import FakeChamber
    from goodmorning.web.briefing_server import BrowserApp, serve_live
    from goodmorning.records.inbox_store import initialize, InboxStore, stamp
    from goodmorning.records.routing import prepare
    from goodmorning.briefings.briefing_document import encode
    returning_viewer(root)
    initialize(root)
    class IdleChamber(FakeChamber):
        def __init__(self):
            super().__init__()
            self.forms=[]; self.permissions=[]; self.busy=False
    app = BrowserApp(root, IdleChamber(), preflight=True)
    # Archive gaps must not add a question to either edition.
    from datetime import date, timedelta
    (root/'daily').mkdir(exist_ok=True)
    old=(date.fromisoformat(app.today())-timedelta(days=1)).isoformat()
    (root/'daily'/(old+'.md')).write_text('# '+old+'\n- gn: yes (session ses_old)\n')
    if scenario == 'tasks':
        inbox = InboxStore(root, write=True)
        try:
            inbox.mutate('add', {'kind':'todo','raw':'Morning option','task':{'title':'Morning option'}},
                         'ses_fixture','morning-option',stamp(root))
            for key,title,project in [('atlas-first','Review results','Atlas'),
                                      ('paper','Review results','Paper <review>'),
                                      ('atlas-second','Write summary','Atlas')]:
                inbox.mutate('add',{'kind':'todo','raw':title,'task':{'title':title,'project':project}},
                             'ses_fixture',key,stamp(root))
            day = app.today()
            block = prepare(root,day,'gm')['blocks']['tasks']
            (root/'daily').mkdir(exist_ok=True)
            (root/'daily'/f'{day}.gm.json').write_text(encode(
                {'v':2,'greeting':'Morning.','opening':'Choices.','sections':[['tasks',[block]]]}))
            inbox.mutate('add', {'kind':'todo','raw':'Unshown backlog'},'ses_fixture','unshown',stamp(root))
            inbox.mutate('add', {'kind':'todo','raw':'Planned errand','task':{'title':'Planned errand','planned_date':day}},
                         'ses_fixture','planned',stamp(root))
        finally:
            inbox.close()
    serve_live(app,0)


def main():
    artifacts = Path(sys.argv[1]) if len(sys.argv)>1 else None
    if artifacts:
        artifacts.mkdir(parents=True,exist_ok=True,mode=0o700)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for language,scenario in [('en','empty'),('en','tasks'),('zh-CN','empty'),('zh-CN','tasks')]:
            copy = ({'title':'Let’s look back on today','empty':'How did today go?','not_done':'Not done',
                     'early':'Anything finished early?','other':'Other tasks','next':'Next','close':'Close',
                     'continue':'Continue check-in','save':'Save and write my briefing','open':'stays open'} if language=='en' else
                    {'title':'一起回顾一下今天','empty':'今天过得怎么样？','not_done':'未完成',
                     'early':'有提前完成的吗？','other':'其他任务','next':'接下来','close':'关闭',
                     'continue':'继续回顾','save':'保存并写简报','open':'先留着'})
            for width in (390,1440):
                # Each viewport answers its own fresh job.
                with tempfile.TemporaryDirectory(dir='/tmp/opencode',prefix='gm-night-preflight-') as directory:
                    root = Path(directory)
                    (root/'profile.md').write_text('secretary_language: English\ntimezone: Europe/London\ncity: London, GB\nnews_country: GB\n')
                    (root/'website-language.json').write_text(json.dumps({'language':language}))
                    process = subprocess.Popen([sys.executable,__file__,'--serve',directory,scenario],
                                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                    address = process.stdout.readline().strip().removeprefix('Private live viewer: ')
                    try:
                        page = browser.new_page(viewport={'width':width,'height':900},reduced_motion='reduce')
                        errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
                        page.goto(address+'/gn.html')
                        page.locator('#generate').click()
                        # The check-in opens by itself in a modal dialog.
                        dialog = page.get_by_role('dialog')
                        expect(dialog).to_be_visible()
                        expect(dialog.get_by_role('heading',name=copy['title'],exact=True)).to_be_visible()
                        expect(page.get_by_text('Past missing editions',exact=True)).to_have_count(0)
                        if scenario == 'empty':
                            expect(dialog.get_by_text(copy['empty'],exact=True)).to_be_visible()
                            expect(dialog.locator('.checkin-steps')).to_have_count(0)
                            expect(dialog.locator('input[type=checkbox]')).to_have_count(0)
                        else:
                            expect(dialog.locator('.checkin-steps li')).to_have_count(3)
                            expect(dialog.get_by_role('heading',name='Planned errand',exact=True)).to_be_visible()
                            dialog.get_by_role('button',name=copy['not_done']).click()
                            expect(dialog.get_by_text(copy['early'],exact=True)).to_be_visible()
                            expect(dialog.get_by_text('Unshown backlog',exact=True)).to_have_count(0)
                            expect(dialog.locator('.checkin-group h4')).to_have_text(['Atlas','Paper <review>',copy['other']])
                            expect(dialog.locator('.checkin-group img')).to_have_count(0)
                            atlas=dialog.locator('.checkin-group').nth(0); paper=dialog.locator('.checkin-group').nth(1)
                            expect(atlas.get_by_role('checkbox')).to_have_count(2)
                            expect(dialog.locator('.checkin-group').nth(2).get_by_text('Morning option',exact=True)).to_be_visible()
                            atlas.get_by_role('checkbox',name='Review results',exact=True).check()
                            paper.get_by_role('checkbox',name='Review results',exact=True).check()
                            # Polling and closing keep answers; the page offers a way back in.
                            page.evaluate('poll()')
                            dialog.get_by_role('button',name=copy['close']).click()
                            expect(dialog).to_be_hidden()
                            page.get_by_role('button',name=copy['continue']).click()
                            expect(atlas.get_by_role('checkbox',name='Review results',exact=True)).to_be_checked()
                            expect(paper.get_by_role('checkbox',name='Review results',exact=True)).to_be_checked()
                            dialog.get_by_role('button',name=copy['next']).click()
                            expect(dialog.locator('.checkin-summary')).to_contain_text('Planned errand · '+copy['open'])
                        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                        if artifacts:
                            page.screenshot(path=str(artifacts/f'{language}-{scenario}-{width}.png'))
                        with page.expect_response(lambda response:'/form/' in response.url and response.request.method=='POST') as receipt:
                            dialog.get_by_role('button',name=copy['save']).click()
                        assert receipt.value.ok
                        expect(page.locator('dialog.checkin')).to_have_count(0)
                        assert not errors, errors
                        jobs=json.loads((root/'browser-jobs/jobs.json').read_text())
                        job=next(j for j in jobs.values() if j['kind']=='gn')
                        context=json.loads((root/'browser-jobs'/(job['id']+'.context.json')).read_text())
                        assert context['feedback']['saved']
                        assert context['feedback']['completed']==(['Review results','Review results'] if scenario=='tasks' else [])
                        if scenario=='tasks':
                            assert context['browser_answer']['completed']==['none']
                            selected=[t for t in context['feedback_tasks'] if t['done']]
                            assert len({t['task_id'] for t in selected})==2
                        page.close()
                    finally:
                        process.terminate();process.communicate(timeout=5)
        browser.close()
    print(json.dumps({'opens_as_dialog':'pass','due_step':'pass','project_groups':'pass','unassigned_group':'last',
                      'answers_kept_after_poll_and_close':True,'not_done_stays_open':'pass','languages':['en','zh-CN'],
                      'archive_gap_question':'absent','adaptive_empty_state':'pass','feedback_save':'pass','viewports':2,'model_calls':0}))


if __name__ == '__main__':
    if '--serve' in sys.argv:
        fixture(Path(sys.argv[-2]),sys.argv[-1])
    else:
        main()
