"""Evening completion choices and adaptive empty state; synthetic data, no models."""
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
    from test_briefing_server import FakeChamber
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
            copy = ({'title':'Let’s look back on today','empty':'How did today go?',
                     'none':'None of these today.','extra':'Nothing else to add.',
                     'empty_extra':'Nothing extra to add today.','other':'Other tasks',
                     'future':'Future tasks (optional)','background':'Background',
                     'placeholder':'Share any progress or updates…','send':'Send answer'} if language=='en' else
                    {'title':'一起回顾一下今天','empty':'今天过得怎么样？',
                     'none':'这些任务今天都还没做完','extra':'没有其他要补充的了',
                     'empty_extra':'今天没有别的要补充了','other':'其他任务',
                     'future':'以后要做的任务（可选）','background':'无固定日期',
                     'placeholder':'写下今天的进展，或其他想补充的事……','send':'提交回答'})
            with tempfile.TemporaryDirectory(dir='/tmp/opencode',prefix='gm-night-preflight-') as directory:
                root = Path(directory)
                (root/'profile.md').write_text('secretary_language: English\ntimezone: Europe/London\ncity: London, GB\nnews_country: GB\n')
                (root/'website-language.json').write_text(json.dumps({'language':language}))
                process = subprocess.Popen([sys.executable,__file__,'--serve',directory,scenario],
                                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                address = process.stdout.readline().strip().removeprefix('Private live viewer: ')
                try:
                    for width in (390,1440):
                        page = browser.new_page(viewport={'width':width,'height':900},reduced_motion='reduce')
                        errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
                        page.goto(address+'/gn.html')
                        if width == 390:
                            page.locator('#generate').click()
                        expect(page.get_by_text('Past missing editions',exact=True)).to_have_count(0)
                        expect(page.get_by_text('Continue today',exact=True)).to_have_count(0)
                        expect(page.get_by_role('heading',name=copy['title'],exact=True)).to_be_visible()
                        if scenario == 'empty':
                            expect(page.get_by_text(copy['empty'],exact=True)).to_be_visible()
                            expect(page.get_by_text(copy['none'],exact=True)).to_have_count(0)
                            expect(page.locator('input[type=checkbox]')).to_have_count(0)
                            expect(page.get_by_text(copy['empty_extra'],exact=True)).to_be_visible()
                        else:
                            expect(page.get_by_text(f"Morning option · {copy['background']}",exact=True)).to_be_visible()
                            expect(page.get_by_text('Unshown backlog',exact=True)).to_have_count(0)
                            expect(page.get_by_text(copy['future'],exact=True)).to_be_visible()
                            expect(page.get_by_text(copy['none'],exact=True)).to_have_count(0)
                            expect(page.locator('.answer-project-group')).to_have_count(3)
                            expect(page.locator('.answer-project-group > legend')).to_have_text(['Atlas','Paper <review>',copy['other']])
                            atlas=page.get_by_role('group',name='Atlas',exact=True)
                            paper=page.get_by_role('group',name='Paper <review>',exact=True)
                            other=page.get_by_role('group',name=copy['other'],exact=True)
                            expect(atlas.get_by_role('checkbox')).to_have_count(2)
                            expect(other.get_by_text(f"Morning option · {copy['background']}",exact=True)).to_be_visible()
                            expect(page.locator('.answer-project-group img')).to_have_count(0)
                            expect(page.locator('.answer-project-group').get_by_text(copy['none'],exact=True)).to_have_count(0)
                            atlas.get_by_role('checkbox',name=f"Review results · {copy['background']}",exact=True).check()
                            paper.get_by_role('checkbox',name=f"Review results · {copy['background']}",exact=True).check()
                            page.evaluate('poll()')
                            expect(atlas.get_by_role('checkbox',name=f"Review results · {copy['background']}",exact=True)).to_be_checked()
                            expect(paper.get_by_role('checkbox',name=f"Review results · {copy['background']}",exact=True)).to_be_checked()
                        updates=page.get_by_placeholder(copy['placeholder'],exact=True)
                        no_extra=page.get_by_role('radio',name=copy['empty_extra'] if scenario=='empty' else copy['extra'],exact=True)
                        assert updates.evaluate('node => Boolean(node.compareDocumentPosition(node.parentElement.querySelector(".answer-option")) & Node.DOCUMENT_POSITION_FOLLOWING)')
                        no_extra.check()
                        updates.fill('A little progress to share.' if language=='en' else '今天又推进了一点。')
                        expect(no_extra).not_to_be_checked()
                        no_extra.check()
                        expect(updates).to_have_value('')
                        updates.fill('Some work is still in progress.' if language=='en' else '有些事情还在继续做。')
                        expect(no_extra).not_to_be_checked()
                        page.evaluate('poll()')
                        expect(updates).not_to_be_empty()
                        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                        assert not errors, errors
                        if artifacts:
                            page.screenshot(path=str(artifacts/f'{language}-{scenario}-{width}.png'),full_page=True)
                        if width == 1440:
                            no_extra.check()
                            with page.expect_response(lambda response:'/form/' in response.url and response.request.method=='POST') as receipt:
                                page.get_by_role('button',name=copy['send']).click()
                            assert receipt.value.ok
                            jobs=json.loads((root/'browser-jobs/jobs.json').read_text())
                            job=next(j for j in jobs.values() if j['kind']=='gn')
                            context=json.loads((root/'browser-jobs'/(job['id']+'.context.json')).read_text())
                            assert context['feedback']['saved']
                            assert context['feedback']['completed']==(['Review results','Review results'] if scenario=='tasks' else [])
                            if scenario=='tasks':
                                selected=[t for t in context['feedback_tasks'] if t['done']]
                                assert len({t['task_id'] for t in selected})==2
                        page.close()
                finally:
                    process.terminate();process.communicate(timeout=5)
        browser.close()
    print(json.dumps({'morning_choices':'pass','project_groups':'pass','unassigned_group':'last','selection_during_poll':'preserved',
                      'text_box_above_no_extra_choice':True,'text_and_no_extra_choice':'mutually exclusive',
                      'languages':['en','zh-CN'],'archive_gap_question':'absent','adaptive_empty_state':'pass',
                      'feedback_save':'pass','viewports':2,'model_calls':0}))


if __name__ == '__main__':
    if '--serve' in sys.argv:
        fixture(Path(sys.argv[-2]),sys.argv[-1])
    else:
        main()
