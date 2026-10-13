"""Opt-in, paid DeepSeek High trial through real chat, Schedule and briefing pages.

Uses a synthetic returning account on loopback and fresh native agent sessions.
Public login/encryption are covered separately; the native bridge substitutes
OpenChamber's control envelope only. No mock model, no private production records.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent/'src'))
from benchmarks.native_bridge import NativeBridge
from test_weekly_schedule import start_server
from support import returning_viewer
from goodmorning.records.inbox_store import initialize, InboxStore
from goodmorning.records.task_store import TaskStore
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.web.briefing_server import BrowserApp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New private directory beneath /tmp/opencode')
    parser.add_argument('--blocked-report', action='store_true', help='Submit an explicit Atlas blocker and check canonical reconciliation')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to('/tmp/opencode'):
        parser.error('Synthetic trial output must be inside /tmp/opencode')
    output.mkdir(mode=0o700)
    source, runtime = output/'source', output/'account'
    source.mkdir(); runtime.mkdir(mode=0o700)
    for name in ('src','scripts','docs','templates','assets','skill-source'):
        shutil.copytree(ROOT.parent/name, source/name, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copyfile(ROOT.parent/'AGENTS.md', source/'AGENTS.md')
    # Native project skills override a developer's installed global copy.
    # Flat named Markdown keeps the package base at this copied release root.
    shutil.copyfile(ROOT.parent/'skill-source/goodmorning.md', source/'goodmorning.md')
    (source/'opencode.json').write_text(json.dumps({'skills':['.']}))
    (runtime/'profile.md').write_text('city: London, GB\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\nsecretary_name: Nora\nsecretary_tone: warm and concise\ncalendar_source: custom\n')
    (runtime/'browser-policy.json').write_text(json.dumps({key:False for key in ('live_project_access','calendar_sync','publisher_images','news_acknowledgement')}))
    initialize(runtime); CalendarStore(str(runtime/'calendar.sqlite')).close()
    returning_viewer(runtime)
    bridge = NativeBridge(source, runtime)
    app = BrowserApp(runtime, bridge, now=lambda:datetime.now(timezone.utc), preflight=True)
    server = start_server(app)
    address = f'http://127.0.0.1:{server.server_port}'
    results = {'model':'opencode-go/deepseek-v4.1-flash', 'variant':'high', 'checks':[], 'limitations':[
        'Loopback returning-account trial, not public HTTPS registration or encrypted-container deployment.',
        'Native V2 bridge substitutes OpenChamber control envelope; model and website routes are real.']}
    results['blocked_report'] = args.blocked_report
    def tasks():
        inbox = InboxStore(runtime)
        try:return list(TaskStore(inbox).all())
        finally:inbox.close()
    try:
        from playwright.sync_api import expect, sync_playwright
        expect.set_options(timeout=300000)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={'width':1440,'height':1000})
            page.set_default_timeout(300000)
            errors=[]; page.on('pageerror', lambda error:errors.append(str(error)))
            page.goto(address+'/chat')
            page.locator('#prefs-menu summary').click()
            page.locator('#website-model').select_option('deepseek-flash')
            page.locator('#prefs-menu summary').click()
            def send(text, mode=None):
                if mode:
                    page.get_by_role('button',name='New conversation',exact=True).click()
                    page.locator(f'[data-mode="{mode}"]').click()
                page.get_by_label('Your message',exact=True).fill(text)
                page.locator('#chat-send').click()
                expect(page.locator('#chat-status')).to_have_text('Ready for your reply')
                assert page.locator('#chat-questions .agent-form').count()==0, 'Unexpected question on unambiguous capture'
                page.screenshot(path=str(output/f'chat-{len(results["checks"])}.png'),full_page=True)
            send('Send Atlas report by Friday.', 'todo')
            first=tasks(); assert len(first)==1 and first[0]['due_date'] and not first[0]['planned_date'], first
            identifier=first[0]['id']
            results['checks'].append('To-do saves a deadline without assigning a workday')
            send('Also work on that report tomorrow.')
            changed=tasks(); assert len(changed)==1 and changed[0]['id']==identifier and changed[0]['planned_date'], changed
            results['checks'].append('Same-conversation follow-up updates the existing action without duplicate capture')
            page.reload(); expect(page.locator('#chat-messages')).to_contain_text('Also work on that report tomorrow.')
            send('Maybe build a dashboard for Atlas.', 'eureka')
            assert len(tasks())==1
            results['checks'].append('Eureka saves an idea without work or clarification questions; transcript survives reload')
            send('Record buying groceries today (no fixed time), and washing towels every Saturday. Also save my confirmed dentist appointment Thursday at Town Clinic; the time is unknown.', 'secretary')
            current=tasks(); assert len(current)==3 and sum(bool(t['repeat']) for t in current)==1, current
            results['checks'].append('Secretary records supplied workday, untimed recurrence and a confirmed TBC appointment')
            page.goto(address+'/schedule')
            expect(page.locator('.schedule-event.is-tbc')).to_have_count(1)
            expect(page.locator('.schedule-event.is-tbc')).to_contain_text('Town Clinic')
            expect(page.locator('.schedule-task')).not_to_have_count(0)
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.screenshot(path=str(output/'schedule-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.screenshot(path=str(output/'schedule-mobile.png'),full_page=True)
            results['checks'].append('Actual captures appear in the real Schedule tab on desktop and mobile')
            page.set_viewport_size({'width':1440,'height':1000})
            page.goto(address+'/gn.html')
            page.get_by_role('button', name='Prepare my evening briefing', exact=True).click()
            expect(page.locator('.agent-form')).to_be_visible()
            form=page.locator('.agent-form')
            if form.get_by_text('Continue today',exact=True).count():
                form.get_by_text('Continue today',exact=True).click()
            form.get_by_text('None yet',exact=True).click()
            if args.blocked_report:
                details=form.locator('textarea, input[type="text"]').last
                details.fill('The Atlas report is blocked awaiting the dataset. Groceries were not done. No new dates or rollover are agreed.')
            else:
                form.get_by_text('No other updates',exact=True).click()
            form.get_by_role('button',name='Send answer',exact=True).click()
            # Regenerate is also offered on unfinished previews. Only the final
            # ready reload removes generation controls and proves a saved edition.
            expect(page.locator('#generation-status')).to_have_count(0)
            expect(page.locator('#regenerate')).to_be_visible()
            edition=runtime/'daily'/f'{app.today()}.gn.json'
            assert edition.is_file(), 'Evening native save missing'
            if args.blocked_report:
                report=next(t for t in tasks() if t['id']==identifier)
                assert report['status']=='blocked' and report['planned_date']==changed[0]['planned_date'], report
                results['checks'].append('Explicit browser blocker updates the existing action without changing the agreed workday')
            before=(runtime/'inbox.sqlite').read_bytes()
            feedback_before=(runtime/'daily'/f'{app.today()}.md').read_text().split('## feedback',1)[1]
            results['checks'].append('Real evening preflight accepts None yet before creating an agent session, and finishes a v2 edition')
            page.locator('#regenerate').click()
            page.get_by_role('button',name='Regenerate briefing',exact=True).click()
            expect(page.locator('#generation-status')).to_be_visible()
            expect(page.locator('#generation-status')).to_have_count(0)
            expect(page.locator('#regenerate')).to_be_visible()
            assert (runtime/'inbox.sqlite').read_bytes()==before, 'Regeneration changed task records'
            assert (runtime/'daily'/f'{app.today()}.md').read_text().split('## feedback',1)[1]==feedback_before, 'Regeneration replayed feedback'
            results['checks'].append('Regeneration reuses saved feedback without repeating the form or mutating records')
            assert not errors, errors
            page.screenshot(path=str(output/'evening.png'),full_page=True)
            browser.close()
    except Exception as error:
        results['failure']=str(error)[:2000]
        raise
    finally:
        results['sessions']=[]
        for session in list(bridge.sessions):
            info=bridge.api('get',f'/api/session/{session}')['data']
            results['sessions'].append({k:info.get(k) for k in ('id','model','tokens','cost','outcome')})
            messages=bridge.control('session.messages',sessionId=session,limit=100)
            (output/f'{session}.messages.json').write_text(json.dumps(messages,ensure_ascii=False))
        (output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
        server.shutdown(); server.server_close()
    print(json.dumps(results,ensure_ascii=False))


if __name__=='__main__':
    main()
