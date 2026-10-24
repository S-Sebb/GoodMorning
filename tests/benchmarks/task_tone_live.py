"""Opt-in paid task/tone matrix. Synthetic records; native models, no production users.

Two repetitions of English/Chinese and default/formal/playful tones. Checkpoints
preserve request identities; resume never resends an in-flight model request.
Tone is reviewed from transcripts, not inferred from keyword/emoji counts.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import hashlib
import fcntl
import os
from pathlib import Path
import sys
import time
import uuid
from zoneinfo import ZoneInfo
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from benchmarks import trial_engine
from benchmarks.trial_engine import TrialBridge
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.records.inbox_store import InboxStore, initialize
from goodmorning.records.task_store import TaskStore
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import language, models

TONES = {
    'default': None,
    'formal': 'Professional and reserved. Use clear complete sentences. Avoid jokes, emojis, pet names and casual chatter.',
    'playful': 'Warm, helpful and lightly playful. Use gentle relevant wit and encouragement when appropriate. Stay respectful; no pressure, pet names or invented intimacy.',
}

# Only the copied trial CLI gets this shim. Production code is not faulted.
FAULT_CLI = '''from pathlib import Path
import contextlib, io, json, os, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning.cli import main
marker = Path(os.environ['SECRETARY_DIR'])/'.trial-fault.json'
fault = json.loads(marker.read_text()) if 'task' in sys.argv[1:2] and '--update' in sys.argv and marker.exists() else None
if fault:
    with (marker.parent/'.trial-fault-log.jsonl').open('a') as log:
        log.write(json.dumps({'kind':fault['kind']})+'\\n')
    if not fault.get('persistent'):
        marker.unlink()
    if fault['kind'] == 'outcome_unknown':
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            code = main()
        if code:
            print(captured.getvalue(), end='')
            raise SystemExit(code)
    print(json.dumps({'error':fault['kind'], 'next':fault['next']}))
    raise SystemExit(1)
raise SystemExit(main())
'''


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


@contextmanager
def context(lang, selected):
    a = language.CURRENT.set(lang)
    b = models.CURRENT.set(selected)
    try:
        yield
    finally:
        language.CURRENT.reset(a)
        models.CURRENT.reset(b)


def records(runtime):
    inbox = InboxStore(runtime)
    try:
        return list(TaskStore(inbox).all())
    finally:
        inbox.close()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def chat_structure_issues(stage, observation):
    """Progress is allowed; check reply presence and unresolved question fields only."""
    issues=[]
    if stage=='ambiguity-before-write':
        forms=observation['forms']
        if len(forms)!=1 or len(forms[0].get('fields',[]))!=1:
            issues.append('Interval-only ambiguity asked for additional fields instead of using the start-date default')
    elif not observation['assistant']:
        issues.append('No secretary reply accompanied the record operation')
    return issues


def verify_trial_system(bridge,folder,system):
    """Wait only for read-only location configuration; never dispatch or reload."""
    checks=[]
    expected=hashlib.sha256(system.encode()).hexdigest()
    for _ in range(10):
        try:
            agent=bridge.request('/api/agent/build?location%5Bdirectory%5D='+quote(bridge.directory,safe=''))['data']
        except (OSError,KeyError):
            agent={}
        actual=agent.get('system')
        checks.append({'agent':agent.get('id'),
                       'system_sha256':hashlib.sha256(actual.encode()).hexdigest() if isinstance(actual,str) else None})
        save(folder/'base-prompt-preflight.json',{'expected_sha256':expected,'checks':checks})
        if agent.get('id')=='build' and actual==system:
            return
        time.sleep(.5)
    raise AssertionError('Experimental base prompt was not confirmed; no model requests dispatched')


@contextmanager
def matrix_lock(output):
    """One runner owns a matrix, including across server restarts."""
    lock_path=output.parent/('.'+output.name+'.lock')
    with lock_path.open('a+') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('This matrix already has an active runner; observe it instead of resuming') from None
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()))
        lock.flush()
        try:
            yield
        finally:
            fcntl.flock(lock,fcntl.LOCK_UN)


def run_case(output, source, config, day, extended=True, selected='muse-spark', strict_chat=False):
    name = f'{config[0]}-{config[1]}-r{config[2]}'
    folder = output/name
    runtime = folder/'account'
    target = folder/'result.json'
    lang, tone, repeat = config
    chinese = lang == 'zh-CN'
    text = lambda en, zh: zh if chinese else en
    if target.exists():
        result = json.loads(target.read_text())
        if result.get('complete'):
            return result
    else:
        runtime.mkdir(parents=True, mode=0o700)
        profile = 'city: London, GB\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\nsecretary_name: Nora\ncalendar_source: custom\n'
        if TONES[tone]:
            profile += 'secretary_tone: '+TONES[tone]+'\n'
        (runtime/'profile.md').write_text(profile)
        (runtime/'browser-policy.json').write_text(json.dumps({key:False for key in ('live_project_access','calendar_sync','publisher_images','news_acknowledgement')}))
        initialize(runtime)
        CalendarStore(str(runtime/'calendar.sqlite')).close()
        result = {'case':name,'language':lang,'tone':TONES[tone] or 'default warm and helpful',
                  'repeat':repeat,'chat':uuid.uuid4().hex,'stages':{},'complete':False,
                  'tone_review':'pending manual transcript review'}
        save(target,result)
    system = source/'trial-base-prompt.md'
    bridge = TrialBridge(trial_engine.Engine(source,runtime).start(),agent='build' if system.is_file() else None)
    registry = runtime/'browser-chats/chats.json'
    if registry.exists():
        for item in json.loads(registry.read_text()).values():
            if item.get('session'):
                bridge.sessions.append(item['session'])  # Observe existing work; never redispatch it.
    app = BrowserApp(runtime,bridge)
    due = (day+timedelta(days=3)).isoformat()
    planned = (day+timedelta(days=1)).isoformat()
    moved = (day+timedelta(days=2)).isoformat()
    today = day.isoformat()

    def wait():
        deadline = time.monotonic()+420
        while time.monotonic()<deadline:
            with context(lang,selected):
                status = app.chats.status(result['chat'])
            if status['permissions']:
                raise AssertionError('Unexpected permission; retained for scoped review, not auto-approved')
            if status['state'] in ('idle','waiting'):
                return status
            if status['state'] in ('uncertain','unavailable'):
                raise AssertionError('Uncertain/unavailable delivery; inspect preserved request, never replay')
            time.sleep(3)
        raise TimeoutError('Preserved native request did not settle within seven minutes')

    def perform(stage, message, check, expected='idle', answer=False, fault=None):
        if stage in result['stages']:
            return
        pending = result.get('inflight')
        if not pending:
            pending = {'stage':stage,'request':uuid.uuid4().hex,'message':message,
                       'messages_before':len(app.chats.status(result['chat']).get('messages',[])) if app.chats.items else 0}
            result['inflight']=pending
            save(target,result)  # Intent before dispatch.
            if fault:
                save(runtime/'.trial-fault.json',fault)
            with context(lang,selected):
                if answer:
                    status=app.chats.status(result['chat'])
                    assert len(status['forms'])==1, 'Expected one clarification form'
                    form=status['forms'][0]
                    values={}
                    for field in form['fields']:
                        if field.get('format')=='date':
                            values[field['key']]=today
                            if strict_chat:
                                result['clarification_start_was_test_supplied']=True
                        elif field['type']=='string' and (field.get('custom') or not field.get('options')):
                            values[field['key']]=message
                        elif field['type'] in ('integer','number'):
                            values[field['key']]=3
                        else:
                            raise AssertionError('Unsupported synthetic answer field; needs review, not guessed approval')
                    app.chats.reply(result['chat'],'form',form['id'],{'answer':values})
                elif not app.chats.items:
                    app.chats.start({'id':result['chat'],'mode':'secretary','text':message})
                else:
                    app.chats.send(result['chat'],{'id':pending['request'],'text':message})
        assert pending['stage']==stage, 'Resume only the preserved in-flight stage'
        status=wait()
        observation={'assistant':[m['text'] for m in status['messages'][pending['messages_before']:] if m['role']=='assistant' and not m.get('kind') and m['text'].strip()],
                     'forms':status['forms'],'state':status['state']}
        result.setdefault('observations',{})[stage]=observation
        if strict_chat:
            result.setdefault('structure_issues',{})[stage]=chat_structure_issues(stage,observation)
        save(target,result)  # Preserve even a failed assertion's actual prose/forms.
        assert status['state']==expected, f'{stage}: expected {expected}, got {status["state"]}'
        check()
        result['stages'][stage]=observation
        result.pop('inflight',None)
        result.pop('failure',None)
        save(target,result)
        print(name+': '+stage+' passed',flush=True)

    def initial():
        rows=records(runtime)
        assert len(rows)==1 and rows[0]['due_date']==due and not rows[0]['planned_date'], rows
        result['report_id']=rows[0]['id']
    def report():
        return next(item for item in records(runtime) if item['id']==result['report_id'])
    def planned_check():
        assert len(records(runtime))==1 and report()['planned_date']==planned and report()['due_date']==due
    def recurrence_check():
        rows=[item for item in records(runtime) if item['id']!=result['report_id']]
        assert len(rows)==1 and rows[0]['repeat']['interval_days']==3 and rows[0]['repeat']['start']==today, rows
        result['notes_id']=rows[0]['id']
    def notes():
        return next(item for item in records(runtime) if item['id']==result['notes_id'])
    def idea_check(count):
        require(len(records(runtime))==count,'Idea became work')
        inbox=InboxStore(runtime)
        try:
            ideas=inbox.list(kind='idea')['items']
            require(len(ideas)==1 and ideas[0]['status']=='pending','Idea capture state is incorrect')
            result['idea_id']=ideas[0]['id']
        finally:
            inbox.close()
    def adoption_check(count):
        rows=records(runtime)
        adopted=[item for item in rows if item['source_entry_id']==result['idea_id']]
        require(len(rows)==count+2 and len(adopted)==2 and all(item['status']=='open' for item in adopted),'Adoption did not preserve source identity or created incorrect actions')
        inbox=InboxStore(runtime)
        try:
            require(inbox.show(result['idea_id'])['status']=='confirmed','Adopted idea was not confirmed')
        finally:
            inbox.close()
    try:
        if system.is_file():
            verify_trial_system(bridge,folder,system.read_text())
        perform('deadline',text(f'Record a to-do: send the Atlas report by {due}.',f'记录一条待办：在 {due} 前发送 Atlas 报告。'),initial)
        perform('workday-followup',text(f'Also work on that report on {planned}.',f'另外，安排在 {planned} 做这份报告。'),planned_check)
        if 'duplicate-request-retry' not in result['stages']:
            turns=app.chats.get(result['chat'])['turns']
            last=turns[-1]
            before=(runtime/'inbox.sqlite').read_bytes()
            count=len(turns)
            with context(lang,selected):
                app.chats.send(result['chat'],{'id':last['id'],'text':last['text']})
            require(len(app.chats.get(result['chat'])['turns'])==count and (runtime/'inbox.sqlite').read_bytes()==before,'Duplicate request changed records or created another turn')
            result['stages']['duplicate-request-retry']={'assistant':[],'state':'verified without model redispatch'}
            save(target,result)
        if 'ambiguity_sha256' not in result:
            result['ambiguity_sha256']=hashlib.sha256((runtime/'inbox.sqlite').read_bytes()).hexdigest()
            save(target,result)
        perform('ambiguity-before-write',text('Record a recurring to-do: review my notes every few days.','记录一条重复待办：每隔几天复习我的笔记。'),
                lambda: require(hashlib.sha256((runtime/'inbox.sqlite').read_bytes()).hexdigest()==result['ambiguity_sha256'],'Ambiguous input wrote records'),expected='waiting')
        answer=text('Every 3 days, without a fixed time. Keep this as a recurring task, not a calendar booking or automatic notification job.',
                    '每隔 3 天一次，不设固定时间。保存为重复待办，不要创建日历预约或自动通知作业。') if strict_chat else text(
                    f'Every 3 days starting {today}, without a fixed time. Keep this as a recurring task, not a calendar booking or automatic notification job.',
                    f'从 {today} 开始，每隔 3 天一次，不设固定时间。保存为重复待办，不要创建日历预约或自动通知作业。')
        perform('clarification-roundtrip',answer,recurrence_check,answer=True)
        if strict_chat:
            def clear_repeat_check():
                rows=[row for row in records(runtime) if row['id'] not in (result['report_id'],result['notes_id'])]
                require(len(rows)==1 and rows[0]['repeat']['interval_days']==4 and rows[0]['repeat']['start']==today
                        and rows[0]['timezone']=='Europe/London','Clear forward recurrence did not apply the local capture-date default')
            perform('clear-recurrence-default',text('Record a recurring to-do: stretch every 4 days, without a fixed time.',
                    '记录一条重复待办：每隔 4 天做拉伸，不设固定时间。'),clear_repeat_check)

        # Deep task semantics once per language; all six tone/language settings
        # repeat capture, follow-up, clarification and failure conversations twice.
        if extended and tone=='default' and repeat==1:
            perform('reschedule',text(f'Move the report workday to {moved}; keep the deadline unchanged.',f'把报告的安排日期改为 {moved}，截止日期保持不变。'),
                    lambda: require(report()['planned_date']==moved and report()['due_date']==due,'Reschedule changed deadline'))
            if 'adoption_before_count' not in result:
                result['adoption_before_count']=len(records(runtime))
                save(target,result)
            count=result['adoption_before_count']
            perform('idea-only',text('Save an idea: build an Atlas dashboard. Capture only; do not implement it.','保存一个灵感：做一个 Atlas 仪表盘。只记录，不要实施。'),
                    lambda: idea_check(count))
            perform('explicit-adoption',text('Turn that dashboard idea into exactly two tasks: draft the layout and list the data fields. Do not implement them.','把刚才的仪表盘灵感转成两条待办：起草布局、列出数据字段。不要实施。'),
                    lambda: adoption_check(count))
            perform('recurrence-edit',text('Change the recurring notes task to every 5 days. Keep its original start date.','把复习笔记的重复待办改成每隔 5 天一次，原始开始日期保持不变。'),
                    lambda: require(notes()['repeat']['interval_days']==5 and notes()['repeat']['start']==today,'Recurrence edit changed identity/start'))
            perform('selective-completion',text(f'I completed the Atlas report on {today}. The dashboard tasks and recurring notes are not complete; do not mark them done.',
                    f'我在 {today} 完成了 Atlas 报告。仪表盘待办和复习笔记都没有完成，不要把它们标成完成。'),
                    lambda: require(report()['status']=='done' and report()['planned_date']==moved and all(item['status']!='done' for item in records(runtime) if item['id']!=result['report_id']),'Incorrect completion or rollover'))
            title=text('Review research notes','复习研究笔记')
            perform('revision-conflict',text(f'Rename the recurring notes task to "{title}". Keep its schedule unchanged.',f'把复习笔记的重复待办重命名为“{title}”，安排不变。'),
                    lambda: require(notes()['title']==title and not (runtime/'.trial-fault.json').exists(),'Refused-write recovery not verified'),
                    fault={'kind':'write_conflict','next':'Reread the exact target/current revision and reconcile before retrying.'})
            detail=text('Compare the two saved summaries.','比较两份已保存的摘要。')
            if 'lost_ack_revision' not in result:
                result['lost_ack_revision']=notes()['revision']
                save(target,result)
            revision=result['lost_ack_revision']
            perform('lost-write-acknowledgement',text(f'Set the recurring notes task detail to exactly "{detail}". Keep the schedule and title unchanged.',f'把复习笔记的重复待办详情设为“{detail}”，安排和标题不变。'),
                    lambda: require(notes()['detail']==detail and notes()['revision']==revision+1 and not (runtime/'.trial-fault.json').exists(),'Lost-ack write duplicated or not verified'),
                    fault={'kind':'outcome_unknown','next':'The write may have committed. Inspect the exact target/receipt first; never blindly replay or use a new operation key.'})

        if 'refused_title_before' not in result:
            result['refused_title_before']=notes()['title']
            save(target,result)
        previous=result['refused_title_before']
        wanted=text('Review field notes','复习现场笔记')
        perform('refused-save-tone',text(f'Rename the recurring notes task to exactly "{wanted}"; keep everything else unchanged.',f'把复习笔记的重复待办重命名为“{wanted}”，其他内容不变。'),
                lambda: require(notes()['title']==previous and 'storage_unavailable' in (runtime/'.trial-fault-log.jsonl').read_text(),'Refused-save path not verified'),
                fault={'kind':'storage_unavailable','persistent':True,'next':'The requested task write was refused; the canonical task is unchanged. Stop and report the affected change. Do not retry until the administrator resolves this prerequisite.'})
        result['sessions']=[]
        for session in bridge.sessions:
            info=bridge.session(session)
            assert info['model']==models.session_payload(selected), info.get('model')
            result['sessions'].append({key:info.get(key) for key in ('id','agent','model','cost','outcome')})
        result['records']=records(runtime)
        result['complete']=True
    except Exception as error:
        result['failure']=str(error)[:1500]
    finally:
        for session in bridge.sessions:
            try:
                transcript=bridge.control('session.messages',sessionId=session,limit=100)
                save(folder/(session+'.messages.json'),transcript)
            except Exception as error:
                result['transcript_read_error']=str(error)[:500]
        bridge.close()
        save(target,result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    trial_engine.add_arguments(parser)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--workers',type=int,choices=(1,2),default=2)
    parser.add_argument('--tone-only',action='store_true',help='Fresh six-setting tone retest, one repetition and no extended task sequence')
    parser.add_argument('--model',choices=models.MODELS,help='Override the website model; by default each language runs on its production model')
    parser.add_argument('--language',choices=('en','zh-CN'),help='Test only this website language; default tests both')
    parser.add_argument('--strict-chat',action='store_true',help='Check reply presence, interval-only clarification and implicit recurrence start; progress remains visible')
    parser.add_argument('--system-file',type=Path,help='Experimental base prompt for build in the copied trial location only; permissions remain unchanged')
    args=parser.parse_args()
    output=trial_engine.private_output(parser,args.output)
    try:
        with matrix_lock(output):
            return run_matrix(args,output,parser)
    except ValueError as error:
        parser.error(str(error))


def matrix_model(chosen):
    """(model, variant) recorded for the matrix: the override, or each language's production model."""
    if not chosen:
        return 'production model per language',None
    selected=models.session_payload(chosen)
    return selected['providerID']+'/'+selected['id'],selected['variant']


def run_matrix(args,output,parser):
    system=args.system_file.read_text() if args.system_file else None
    system_sha=hashlib.sha256(system.encode()).hexdigest() if system is not None else None
    if not args.resume:
        output.mkdir(mode=0o700)
    runner_lock=(output/'.matrix.lock').open('a')
    try:
        fcntl.flock(runner_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        runner_lock.close()
        parser.error('This matrix already has a running owner. Observe it; do not start another runner or replay requests.')
    source=output/'source'
    if args.resume:
        previous=json.loads((output/'matrix.json').read_text())
        if (previous['model']!=matrix_model(args.model)[0] or previous['variant']!=matrix_model(args.model)[1]
                or previous.get('tone_only',False)!=args.tone_only or previous.get('language')!=args.language
                or previous.get('strict_chat',False)!=args.strict_chat or previous.get('system_sha256')!=system_sha
                or args.strict_chat and previous.get('progress_policy')!='visible'):
            runner_lock.close()
            parser.error('Resume must keep the original model, variant, language and matrix scope')
        day=datetime.fromisoformat(previous['date']).date()
    else:
        trial_engine.copy_release(source,args.source.resolve())
        configuration={'skills':['.']}
        if system is not None:
            configuration['agents']={'build':{'system':system}}
            (source/'trial-base-prompt.md').write_text(system)
        (source/'opencode.json').write_text(json.dumps(configuration))
        (source/'scripts/goodmorning.py').write_text(FAULT_CLI)
        day=datetime.now(ZoneInfo('Europe/London')).date()
    languages=(args.language,) if args.language else ('en','zh-CN')
    configs=[(lang,tone,repeat) for repeat in ((1,) if args.tone_only else (1,2)) for lang in languages for tone in TONES]
    model,variant=matrix_model(args.model)
    matrix={'date':day.isoformat(),'model':model,'variant':variant,
            'cases':[],'tone_only':args.tone_only,'language':args.language,'strict_chat':args.strict_chat,
            'system_sha256':system_sha,
            'progress_policy':'visible',
            'tone_review':'pending manual review; functional assertions and structural checks do not prove style',
            'limitations':['Synthetic native chat-controller trial, not public HTTPS/account isolation.',
                           'Faults are deliberately injected in the copied trial CLI only.',
                           'One repetition per setting in tone-only mode; otherwise two, not a statistical reliability guarantee.']}
    save(output/'matrix.json',matrix)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(run_case,output,source,config,day,not args.tone_only,args.model or models.for_language(config[0]),args.strict_chat)
                 for config in configs]
        for future in futures:
            result=future.result()
            if system is not None and result.get('sessions'):
                require(all(session['agent']=='build' for session in result['sessions']),
                        'Experimental trial did not keep the same build agent')
            matrix['cases'].append({key:result.get(key) for key in ('case','language','tone','complete','failure','sessions','structure_issues','clarification_start_was_test_supplied')})
            save(output/'matrix.json',matrix)
    matrix['functional_passes']=sum(case['complete'] for case in matrix['cases'])
    matrix['structural_passes']=sum(case['complete'] and not any((case.get('structure_issues') or {}).values()) for case in matrix['cases'])
    save(output/'matrix.json',matrix)
    print(json.dumps(matrix,ensure_ascii=False))
    runner_lock.close()
    return 0 if matrix['functional_passes']==len(configs) and matrix['structural_passes']==len(configs) else 1


if __name__=='__main__':
    raise SystemExit(main())
