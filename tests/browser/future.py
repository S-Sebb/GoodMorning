"""Load varied 2034 editions in real browsers without an agent or personal data."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from playwright.sync_api import sync_playwright,expect


def main():
    arguments = sys.argv[1:]
    artifacts=Path(arguments[0]) if arguments else None
    if artifacts:artifacts.mkdir(parents=True,exist_ok=True,mode=0o700)
    cases=[]
    with tempfile.TemporaryDirectory(dir='/tmp/opencode',prefix='gm-future-') as directory:
        fixture = 'test_briefing_document.py'
        process=subprocess.Popen([sys.executable,str(Path(__file__).resolve().parents[1] / fixture),'--serve-fixture',directory],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        address=process.stdout.readline().strip().removeprefix('Private live viewer: ')
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch()
                for width in (1440,390,320):
                    context=browser.new_context(viewport={'width':width,'height':900 if width==1440 else 844},reduced_motion='reduce')
                    for day in range(11,18):
                        for kind in ('gm','gn'):
                            page=context.new_page();errors=[]
                            page.on('pageerror',lambda error:errors.append(str(error)))
                            response=page.goto(f'{address}/d/2034-03-{day}/{kind}')
                            assert response.status==200
                            page.evaluate('document.fonts.ready')
                            expect(page.locator('article')).to_be_visible()
                            expect(page.locator('.scroll-chunk')).to_have_count(page.locator('.briefing-section').count())
                            assert f'CONTENT_END_{kind}_2034-03-{day}' in page.locator('article').inner_text()
                            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                            if day in (16,17):
                                schedule=page.locator('.schedule' if kind=='gm' else '.tomorrow')
                                expect(schedule.locator('.flexible-schedule')).to_have_count(1)
                                expect(schedule.locator('.flexible-schedule .task-card')).to_have_count(2)
                                expect(schedule.locator('.flexible-title')).to_have_text('Flexible schedule')
                                expect(schedule.locator('.flexible-schedule')).to_contain_text('Synthetic reimbursement')
                                expect(schedule.locator('.flexible-schedule')).to_contain_text('No fixed time; keep the receipt.')
                                if day==16:expect(schedule.locator('.agenda-event')).to_have_count(0)
                                else:
                                    assert schedule.locator('.agenda-event').count()>0
                                    assert schedule.locator('.flexible-schedule').bounding_box()['y']>schedule.locator('.agenda').bounding_box()['y']
                                if artifacts:schedule.screenshot(path=str(artifacts/f'flexible-{day}-{kind}-{width}.png'))
                            if artifacts and day == 17:
                                page.screenshot(path=str(artifacts/f'native-full-{kind}-{width}.png'), full_page=True)
                            page.evaluate("scrollTo({top:document.documentElement.scrollHeight,behavior:'instant'})")
                            page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                            expect(page.locator('.scroll-chunk').last).to_have_attribute('aria-current','location')
                            page.wait_for_function("Array.from(document.querySelectorAll('.scroll-chunk')).every(n=>Number(n.style.getPropertyValue('--section-progress'))===1)")
                            if artifacts and day in (11,14,17):page.screenshot(path=str(artifacts/f'future-{day}-{kind}-{width}.png'))
                            assert not errors,errors
                            cases.append({'date':f'2034-03-{day}','kind':kind,'width':width,'sections':page.locator('.briefing-section').count(),'pass':True})
                            page.close()
                    context.close()
                browser.close()
            print(json.dumps({'cases':len(cases),'format':'native-json','editions':'synthetic future gm/gn','widths':[1440,390,320],'longest_navigation':max(c['sections'] for c in cases),'overflow':False,'page_errors':False,'agent_calls':0}))
        finally:
            process.terminate();process.communicate(timeout=5)


if __name__=='__main__':main()
