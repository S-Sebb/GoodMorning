"""Render preserved synthetic native-model output; no new model calls or original writes."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from goodmorning.web.briefing_server import BrowserApp
from support import start_server
from support import returning_viewer


class FrozenQuestion:
    def __init__(self, session, status):
        self.session,self.saved=session,status

    def pending(self, session):
        assert session==self.session
        return self.saved['forms'],self.saved['permissions']

    def control(self, action, **parameters):
        assert action=='session.status' and parameters['sessionId']==self.session
        return {'sessionStatus':{'type':'idle'}}

    def request(self, *args, **kwargs):
        raise ValueError('Read-only synthetic preview; no answer is submitted')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    trial=args.trial.resolve();output=args.output.resolve()
    if not trial.is_relative_to('/tmp/opencode') or not output.is_relative_to('/tmp/opencode'):
        parser.error('Use private synthetic trial/output directories beneath /tmp/opencode')
    output.mkdir(mode=0o700)
    results=[]
    from playwright.sync_api import sync_playwright,expect
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch()
        for name,kind in (('morning-resume','gm'),('evening-ambiguous','gn')):
            folder=trial/name
            result=json.loads((folder/'result.json').read_text())
            runtime=output/(name+'-account')
            shutil.copytree(folder/'account',runtime)
            language=result['language'];day=result['date']
            (runtime/'website-language.json').write_text(json.dumps({'language':language}))
            returning_viewer(runtime)
            status=json.loads((folder/'original.status.json').read_text())
            info=json.loads((folder/'original.session.json').read_text())
            bridge=FrozenQuestion(info['id'],status) if status['forms'] else None
            app=BrowserApp(runtime,bridge,preflight=True,
                           now=lambda:datetime.fromisoformat(day).replace(hour=12,tzinfo=timezone.utc))
            server=start_server(app)
            try:
                page=browser.new_page(viewport={'width':1440,'height':1000})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/{kind}')
                expect(page.locator('html')).to_have_attribute('lang',language)
                if bridge:
                    form=page.locator('.agent-form')
                    expect(form).to_be_visible()
                    expect(form.locator('h2')).not_to_have_text('Questions')
                    for field in status['forms'][0]['fields']:
                        expect(form.get_by_text(field['description'],exact=True)).to_be_visible()
                    heading=form.locator('h2').inner_text()
                else:
                    document=json.loads((folder/'original.document.json').read_text())
                    expect(page.locator('h1')).to_have_text(document['greeting'])
                    heading=document['greeting']
                raw=json.loads((folder/'original.messages.json').read_text())['messages']
                page_text=page.locator('body').inner_text()
                native_only=[message['text'] for message in raw if message['role']=='assistant'
                             and message['text'] not in page_text]
                assert not errors,errors
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                page.screenshot(path=str(output/(name+'-desktop.png')),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                page.screenshot(path=str(output/(name+'-mobile.png')),full_page=True)
                results.append({'case':name,'language':language,'heading':heading,
                                'native_transcript_messages_not_shown':native_only,'page_errors':errors})
                page.close()
            finally:
                server.shutdown();server.server_close()
        browser.close()
    (output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps(results,ensure_ascii=False))


if __name__=='__main__':
    main()
