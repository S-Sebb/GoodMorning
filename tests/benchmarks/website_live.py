"""Opt-in, paid website-model trial through real chat, Schedule and briefing pages.

Uses a synthetic returning account on loopback and a private production-like engine.
Public login/encryption are covered separately. No mock model, no private production records.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent/'src'))
from benchmarks import trial_engine
from benchmarks.trial_engine import TrialBridge
from support import start_server
from support import returning_viewer
from goodmorning.records.inbox_store import initialize, InboxStore
from goodmorning.records.task_store import TaskStore
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web.models import MODELS, session_payload, for_language


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    trial_engine.add_arguments(parser)
    parser.add_argument('--blocked-report', action='store_true', help='Submit an explicit Atlas blocker and check canonical reconciliation')
    parser.add_argument('--model', choices=MODELS, default='muse-spark', help='English browser trial uses the automatically routed Muse XHigh model')
    parser.add_argument('--ambiguity', action='store_true', help='Check scheduling clarification before any capture or pending note')
    parser.add_argument('--resume', action='store_true', help='Continue a preserved trial stopped at the TBC confirmation; never replay its completed captures')
    args = parser.parse_args()
    if args.model!=for_language('en'):
        parser.error('This browser trial is English-only and uses automatic Muse routing; use the task/tone matrix for Chinese DeepSeek trials')
    output = trial_engine.private_output(parser, args.output)
    if not args.resume:
        output.mkdir(mode=0o700)
    source, runtime = output/'source', output/'account'
    selected = session_payload(args.model)
    if args.resume:
        results=json.loads((output/'results.json').read_text())
        if (len(results['checks'])!=3 or results['model']!=selected['providerID']+'/'+selected['id']
                or results['variant']!=selected['variant']):
            parser.error('Resume supports only this preserved three-check TBC trial and its original model')
        if not (output/'results-original.json').exists():
            shutil.copyfile(output/'results.json', output/'results-original.json')
        results['initial_failure']=results.pop('failure',None)
        results['resumed_without_replaying_captures']=True
        for name in ('core-rules.md','item-taxonomy.md','calendar-pipeline.md'):
            shutil.copyfile(args.source/'docs'/name,source/'docs'/name)
    else:
        trial_engine.copy_release(source, args.source.resolve()); runtime.mkdir(mode=0o700)
        (runtime/'profile.md').write_text('city: London, GB\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\nsecretary_name: Nora\nsecretary_tone: warm and concise\ncalendar_source: custom\n')
        (runtime/'browser-policy.json').write_text(json.dumps({key:False for key in ('live_project_access','calendar_sync','publisher_images','news_acknowledgement')}))
        initialize(runtime); CalendarStore(str(runtime/'calendar.sqlite')).close()
        returning_viewer(runtime)
        results = {'model':selected['providerID']+'/'+selected['id'], 'variant':selected['variant'], 'checks':[], 'limitations':[
            'Loopback returning-account trial, not public HTTPS registration or encrypted-container deployment.',
            'Private production-like OpenChamber engine; model and website routes are real.']}
    bridge = TrialBridge(trial_engine.Engine(source, runtime).start())
    if args.resume:
        registry=json.loads((runtime/'browser-chats/chats.json').read_text())
        for item in registry.values():
            if item.get('session'):
                bridge.sessions.append(item['session'])
    app = BrowserApp(runtime, bridge, now=lambda:datetime.now(timezone.utc), preflight=True)
    server = start_server(app)
    address = f'http://127.0.0.1:{server.server_port}'
    results['blocked_report'] = args.blocked_report
    results['ambiguity'] = args.ambiguity
    print('Synthetic live trial viewer: '+address, flush=True)
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
            page.locator('#website-language').select_option('en')
            page.locator('#prefs-menu summary').click()
            def send(text, fresh=False):
                if fresh:
                    page.goto(address+'/chat?mode=secretary')
                page.get_by_label('Your message',exact=True).fill(text)
                page.locator('#chat-send').click()
                expect(page.locator('#chat-status')).to_contain_text(re.compile('Ready for your reply|Your secretary needs your answer'))
                assert page.locator('#chat-questions .agent-form').count()==0, 'Unexpected question on unambiguous capture'
                expect(page.locator('#chat-status')).to_have_text('Ready for your reply')
                page.screenshot(path=str(output/f'chat-{len(results["checks"])}.png'),full_page=True)
            if args.resume:
                current=tasks()
                changed=[task for task in current if task['due_date']]
                assert len(changed)==1 and changed[0]['planned_date'], current
                identifier=changed[0]['id']
                paused=[item for item in registry.values() if item['mode']=='secretary']
                assert len(paused)==1, 'Expected the preserved secretary conversation'
                page.goto(address+'/chat?id='+paused[0]['id'])
                form=page.locator('#chat-questions form.agent-form')
                expect(form).to_be_visible()
                # This answers only the already-inspected synthetic TBC question;
                # no permissions or arbitrary forms are approved automatically.
                expect(form).to_contain_text('Dentist appointment')
                form.get_by_text('Save TBC Oct 15 (Recommended)',exact=True).click()
                form.get_by_role('button',name='Send answer',exact=True).click()
                expect(page.locator('#chat-status')).to_have_text('Ready for your reply')
            else:
                send('Remind me to send the Atlas report by Friday.', True)
                first=tasks(); assert len(first)==1 and first[0]['due_date'] and not first[0]['planned_date'], first
                identifier=first[0]['id']
                results['checks'].append('A to-do saves a deadline without assigning a workday')
                send('Also work on that report tomorrow.')
                changed=tasks(); assert len(changed)==1 and changed[0]['id']==identifier and changed[0]['planned_date'], changed
                results['checks'].append('Same-conversation follow-up updates the existing action without duplicate capture')
                page.reload(); expect(page.locator('#chat-messages')).to_contain_text('Also work on that report tomorrow.')
                send('I had an idea: maybe build a dashboard for Atlas.', True)
                assert len(tasks())==1
                results['checks'].append('An idea is saved without work or clarification questions; transcript survives reload')
                send('Record buying groceries today (no fixed time), and washing towels every Saturday. Also save my confirmed dentist appointment Thursday at Town Clinic; the time is unknown.', True)
            current=tasks(); assert len(current)==3 and sum(bool(t['repeat']) for t in current)==1, current
            results['checks'].append('Secretary records supplied workday, untimed recurrence and a confirmed TBC appointment')
            inbox = InboxStore(runtime)
            try:drafts = list(TaskStore(inbox).all(draft=True))
            finally:inbox.close()
            assert len(drafts)==1, drafts
            # Near a weekend the appointment falls in next week: open the week that holds it.
            monday = lambda day:day-timedelta(days=day.weekday())
            weeks = (monday(date.fromisoformat(drafts[0]['date']))-monday(date.fromisoformat(str(app.today())))).days//7
            page.goto(address+f'/schedule?week={weeks}')
            expect(page.locator('.schedule-event.is-tbc')).to_have_count(1)
            expect(page.locator('.schedule-event.is-tbc')).to_contain_text('Town Clinic')
            page.goto(address+'/schedule')
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
            form.get_by_text('None of these today.',exact=True).click()
            if args.blocked_report:
                details=form.locator('textarea, input[type="text"]').last
                details.fill('The Atlas report is blocked awaiting the dataset. Groceries were not done. No new dates or rollover are agreed.')
            else:
                form.get_by_text('Nothing else to add.',exact=True).click()
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
            results['checks'].append('Real evening preflight accepts no listed completions before creating an agent session, and finishes a v2 edition')
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
            if args.resume:
                page.goto(address+'/chat')
                send('Save my confirmed optician appointment Friday at Town Clinic. The time is unknown; it should be shown as TBC.', True)
                results['checks'].append('Fresh session with the clarified prompts saves an already-confirmed TBC appointment without asking again')
            if args.ambiguity:
                page.goto(address+'/chat?mode=secretary')
                before=(runtime/'inbox.sqlite').read_bytes()
                page.get_by_label('Your message',exact=True).fill('Remind me to review the notes every few days.')
                page.locator('#chat-send').click()
                expect(page.locator('#chat-questions form.agent-form')).to_be_visible()
                assert (runtime/'inbox.sqlite').read_bytes()==before, 'Ambiguous recurrence was recorded before clarification'
                page.screenshot(path=str(output/'ambiguous-recurrence.png'),full_page=True)
                results['checks'].append('Ambiguous recurrence uses a native question before any task or pending-note write')
            browser.close()
    except Exception as error:
        results['failure']=str(error)[:2000]
        raise
    finally:
        results['sessions']=[]
        for session in list(bridge.sessions):
            info=bridge.session(session)
            results['sessions'].append({k:info.get(k) for k in ('id','model','tokens','cost','outcome')})
            messages=bridge.control('session.messages',sessionId=session,limit=100)
            (output/f'{session}.messages.json').write_text(json.dumps(messages,ensure_ascii=False))
        results['model_verified'] = bool(results['sessions']) and all(
            all((item.get('model') or {}).get(key)==value for key,value in selected.items())
            for item in results['sessions'])
        if not results['model_verified'] and 'failure' not in results:
            results['failure']='A trial session did not use the requested model and variant'
        (output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
        server.shutdown(); server.server_close(); bridge.close()
    assert results['model_verified'], results.get('failure')
    print(json.dumps(results,ensure_ascii=False))


if __name__=='__main__':
    main()
