"""Opt-in paid briefing-prompt checks with synthetic records and unavailable providers.

Real models author through the real browser job helpers. Provider faults and a
prepublished checkpoint are synthetic; no live news/weather or account data is used.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import io
from contextlib import redirect_stdout
import json
from pathlib import Path
import re
import shutil
import sys
import time
import uuid
from urllib.parse import quote
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from benchmarks import trial_engine
from benchmarks.trial_engine import TrialBridge
from benchmarks.task_tone_live import context, matrix_lock, records, save, TONES
from goodmorning.briefings.briefing_document import HEADLINE_LIMIT
from goodmorning.briefings.briefing_job import act, context_path, default_plan, timings_path
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.records.inbox_store import initialize, InboxStore
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web.models import for_language, session_payload


# Only this private source copy has provider faults and command instrumentation.
TRIAL_CLI = '''from pathlib import Path
import contextlib,io,json,os,sys,uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from goodmorning.cli import main
runtime=Path(os.environ['SECRETARY_DIR'])
entry={'call':uuid.uuid4().hex,'argv':sys.argv[1:]}
action=next((arg for arg in sys.argv[2:] if arg in ('prepare','init','publish','skip','finish')),None)
if sys.argv[1:2]==['job'] and action!='prepare' and '--help' not in sys.argv:
    raw=sys.stdin.buffer.read()
    try:entry['input']=json.loads(raw)
    except (ValueError,UnicodeError):entry['invalid_input']=True
    sys.stdin=io.TextIOWrapper(io.BytesIO(raw),encoding='utf-8')
with (runtime/'trial-commands.jsonl').open('a') as log:
    log.write(json.dumps(entry,ensure_ascii=False)+'\\n')
FAULT={'error':'provider_unavailable','next':'Provider unavailable in this isolated test. Publish material unavailability; do not retry or use external sources.'}
WEATHER=runtime/'trial-weather.json'
def weather(argv):
    """A synthetic reading from the real weather code, when the case supplies one."""
    if not WEATHER.exists():return 1,FAULT
    reading=json.loads(WEATHER.read_text())
    return 0,(reading['json'] if '--json' in argv else reading['brief'])
if sys.argv[1:2]==['job']:
    # Receipts run section reads in-process; log and fault them like agent-run reads.
    import shlex
    from goodmorning.briefings import briefing_job
    real=briefing_job.run_reads
    def reads(commands):
        results=[]
        for command in commands:
            argv=shlex.split(command)[2:]
            call=uuid.uuid4().hex
            with (runtime/'trial-commands.jsonl').open('a') as log:
                log.write(json.dumps({'call':call,'argv':argv,'receipt':True},ensure_ascii=False)+'\\n')
            if argv[:1]==['weather']:
                code,value=weather(argv);result={'command':command,'exit':code,'output':value}
            else:
                result={'command':command,'exit':1,'output':FAULT} if argv[:1]==['news'] else real([command])[0]
            output=result['output'] if isinstance(result['output'],dict) else {}
            with (runtime/'trial-commands.jsonl').open('a') as log:
                log.write(json.dumps({'call':call,'exit':result['exit'],'error':output.get('error')})+'\\n')
            results.append(result)
        return results
    briefing_job.run_reads=reads
captured=io.StringIO()
if sys.argv[1:2]==['weather']:
    code,value=weather(sys.argv[1:])
    captured.write((value if isinstance(value,str) else json.dumps(value))+'\\n')
elif sys.argv[1:2]==['news']:
    captured.write(json.dumps(FAULT)+'\\n')
    code=1
else:
    try:
        with contextlib.redirect_stdout(captured):code=main()
    except SystemExit as error:
        code=error.code if isinstance(error.code,int) else 0 if error.code is None else 1
text=captured.getvalue()
try:response=json.loads(text)
except ValueError:response={}
if not isinstance(response,dict):response={}
with (runtime/'trial-commands.jsonl').open('a') as log:
    log.write(json.dumps({'call':entry['call'],'exit':code or 0,'error':response.get('error')})+'\\n')
print(text,end='')
raise SystemExit(code)
'''


class CheckpointBridge(TrialBridge):
    """Seed an interrupted preview before the ordinary, unchanged dispatch prompt."""
    def __init__(self, engine, seed, language):
        super().__init__(engine, agent='build')
        self.runtime, self.seed, self.language = str(engine.runtime), seed, language
        self.seeded = None

    def verify_scope(self):
        expected = {str(Path(self.runtime))+'/*':True,
                    str(Path(self.runtime).parent)+'/*':False,
                    str(ROOT)+'/*':False}
        checks = []
        for _ in range(10):
            try:
                agents = self.request('/api/agent?location%5Bdirectory%5D='+quote(self.directory,safe='')).get('data',[])
                agent = next((entry for entry in agents if entry.get('id') == 'build'), {})
            except OSError:
                agent = {}
            rules = agent.get('permissions', [])
            actual = {path:external_allowed(rules,path) for path in expected}
            checks.append(actual)
            save(Path(self.directory)/'permissions-preflight.json', {'expected':expected,'checks':checks})
            if agent.get('id') == 'build' and actual == expected:
                return
            time.sleep(.5)
        raise AssertionError('Isolated trial permission scope was not confirmed; no model request dispatched')

    def control(self, action, **parameters):
        if action == 'session.send' and self.seed and self.seeded is None:
            job = next(line.split(': ', 1)[1] for line in parameters['prompt'].splitlines()
                       if line.startswith(('Browser job: ', '浏览器任务: ')))
            session = parameters['sessionId']
            act(self.runtime, job, session, 'init', {})
            weather = ['weather', [['p', 'Weather is unavailable; check before travelling.' if self.language == 'en'
                                    else '天气数据暂不可用，出行前请另行确认。']]]
            act(self.runtime, job, session, 'publish', {'position':0, 'section':weather})
            self.seeded = {'weather':weather}
            save(Path(self.runtime)/'seeded-checkpoint.json', self.seeded)
        return super().control(action, **parameters)


def synthetic_weather(instant, later=None):
    """Brief text and JSON from the real weather code: past night rain, drizzle now easing within three hours, rain from 21:00.

    Only today's past night reaches 100%, so the daily maximum is a figure the forward read never reports,
    even when a late run's window reaches into tomorrow's night.
    A `later` day (tomorrow, for the evening) gets that day's card instead: dry until 21:00, then rain."""
    from unittest.mock import patch
    from goodmorning import weather as w
    local = instant.astimezone(ZoneInfo('Europe/London'))
    day = local.date()
    times = [f'{day + timedelta(days=h // 24)}T{h % 24:02d}:00' for h in range(48)]
    forecast = {'timezone':'Europe/London', 'hourly':{'time':times, 'temperature_2m':[9 + (h % 24) / 4 for h in range(48)],
                'precipitation_probability':[100 if h in (3, 4) else 70 + h % 24 if h % 24 >= 21
                                              else 60 if 0 <= h - local.hour < 3 and h < 24 else 5 for h in range(48)]},
                'current':{'time':local.strftime('%Y-%m-%dT%H:00'), 'temperature_2m':12, 'weather_code':51},
                'daily':{'time':[str(day), str(day + timedelta(days=1))], 'temperature_2m_min':[9, 9], 'temperature_2m_max':[14.8, 14.8],
                         'precipitation_probability_max':[100, 100], 'weather_code':[61, 61], 'rain_sum':[3, 3], 'showers_sum':[1, 1],
                         'snowfall_sum':[0, 0], 'sunrise':[f'{day}T07:36', f'{day + timedelta(days=1)}T07:38'],
                         'sunset':[f'{day}T17:53', f'{day + timedelta(days=1)}T17:50']}}
    air = {'timezone':'Europe/London', 'current':{'time':local.strftime('%Y-%m-%dT%H:00'), 'us_aqi':27},
           'hourly':{'time':times, 'us_aqi':[27] * 48}}
    with patch.object(w, 'http_get_json', side_effect=lambda url, **kw: air if 'air-quality' in url else forecast), \
         patch.object(w.time, 'time', return_value=instant.timestamp()):
        out = w.fetch_openmeteo('London', 51.51, -0.13)
        aqi = w.fetch_aqi_openmeteo(51.51, -0.13)
        out.update(latitude=51.51, longitude=-0.13, country='GB', cache_state='live', fetched_at=instant.isoformat(),
                   aqi=aqi, aqi_source='auto', warnings=[])
        if later:
            card = w.outlook(out, w.forecast_frame(out, None, day=later), later)
            out = {key:out[key] for key in ('city','latitude','longitude','country','timezone','provider','cache_state','fetched_at','warnings')}
            out.update(day=later, outlook=card)
        else:
            w.apply_frame(out, w.forecast_frame(out, aqi))
            out.pop('hourly'); aqi.pop('hourly')
    return {'brief':w.brief(out), 'json':out}


def protected_state(runtime):
    """Settings bytes and calendar events/history; a briefing may record which editions reported the calendar."""
    import sqlite3
    state = {name:hashlib.sha256((runtime/name).read_bytes()).hexdigest() for name in ('profile.md','browser-policy.json')}
    from contextlib import closing
    with closing(sqlite3.connect(f'file:{runtime/"calendar.sqlite"}?mode=ro', uri=True)) as calendar:
        state['calendar'] = hashlib.sha256(repr([calendar.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                                                 for table in ('events','history')]).encode()).hexdigest()
    return state


def seed_tasks(runtime, language, scenario, day):
    if scenario == 'morning-empty':
        return []
    tomorrow = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    titles = ['Send Atlas report', 'Send Boreal report', 'Buy groceries'] if language == 'en' else [
        '发送 Atlas 报告', '发送 Boreal 报告', '购买食品']
    specs = [(titles[0], tomorrow, 'Atlas'), (titles[1], tomorrow, 'Boreal'), (titles[2], day, '')]
    inbox = InboxStore(runtime, write=True)
    try:
        for index, (title, planned, project) in enumerate(specs):
            inbox.mutate('add', {'kind':'todo', 'raw':title, 'task':{
                'title':title, 'planned_date':planned, 'timezone':'Europe/London', 'project':project}},
                'ses_fixture', 'briefing-fixture-'+str(index), day+'T12:00:00+01:00')
    finally:
        inbox.close()
    return records(runtime)


def observe(app, bridge, job, folder, stage, language, selected):
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        with context(language, selected):
            status = app.status(job)
        if status['state'] in ('ready', 'waiting', 'stopped', 'uncertain'):
            break
        time.sleep(3)
    save(folder/(stage+'.status.json'), status)
    session = app.job(job).get('session')
    if session:
        info = bridge.session(session)
        save(folder/(stage+'.session.json'), {key:info.get(key) for key in ('id','agent','model','cost','outcome')})
        save(folder/(stage+'.messages.json'), bridge.control('session.messages', sessionId=session, limit=120))
        assert info.get('model') == session_payload(selected), 'Model/variant mismatch'
        assert info.get('agent') == 'build', 'Pinned agent mismatch'
    assert not status.get('permissions'), 'Unexpected permission; never auto-approved'
    assert status['state'] in ('ready', 'waiting', 'stopped', 'uncertain'), 'Timed out; preserve in-flight request'
    return status


def commands(runtime):
    path = runtime/'trial-commands.jsonl'
    entries = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    requests = [entry for entry in entries if 'argv' in entry]
    outcomes = {entry['call']:entry for entry in entries if 'exit' in entry}
    for request in requests:
        if 'call' in request:
            outcome = outcomes.get(request['call'], {})
            request['exit'] = outcome.get('exit')
            request['error'] = outcome.get('error')
    return requests


def job_action(argv):
    return next((arg for arg in argv[1:] if arg in ('prepare','init','publish','skip','finish')),None) if argv[:1] == ['job'] else None


def link_handoff(folder, stage, expected_url=None):
    """Structural heuristic only; manual review must reject factual recap/invitations."""
    messages = json.loads((folder/(stage+'.messages.json')).read_text())['messages']
    replies = [message['text'].strip() for message in messages if message['role'] == 'assistant']
    link = r'(?:https?://[^\s)]+|/(?:d/\d{4}-\d{2}-\d{2}/)?(?:gm|gn)\b)'
    if not replies:
        return False
    text = replies[-1]
    found = re.findall(r'\[[^\]\n]+\]\('+link+r'\)|'+link, text)
    lines = [line for line in text.splitlines() if line.strip()]
    return bool(len(found) == 1 and len(lines) <= 3 and len(text) <= 250
                and (len(lines) <= 2 or found[0] in lines[1])
                and (expected_url is None or expected_url in found[0] and 'http' not in found[0])
                and not any(line.lstrip().startswith(('-', '*', '#')) for line in lines))


def collection_order_issues(log, plan, position=0, reconcile=False, quiet=False):
    """Check provider attempts and delivered views against successful publications.

    Failed scoped reads return no view. Their blocked attempts remain recorded.
    Older logs without exit data require separate manual receipt review.
    """
    issues = []
    for entry in log:
        argv = entry['argv']
        if entry.get('exit',0) != 0 and argv and argv[0] in ('job','task'):
            continue  # No view data returned, and failed publication does not advance.
        if not argv or '--help' in argv or '-h' in argv:
            continue
        if argv[0] == 'job':
            payload = entry.get('input', {})
            action = job_action(argv)
            if action in ('publish','skip') and isinstance(payload.get('position'), int):
                if action == 'skip' or 'section' in payload:
                    position = max(position, payload['position'] + 1)
            continue
        tag = argv[0] if argv[0] in ('weather','news') else None
        if argv[0] == 'task' and '--briefing' in argv and '--section' in argv:
            tag = argv[argv.index('--section') + 1]
        if quiet and tag == 'today' and position < len(plan) and plan[position][0] == 'today':
            position += 1  # Code read Today and skipped it on a quiet evening; the log has no skip for it.
            continue
        if (tag == 'today' and entry.get('receipt') and 0 < position <= len(plan) and plan[position - 1][0] == 'today'):
            continue  # Publishing Today reread it to place the cards, after the publish call was logged.
        if tag == 'tasks' and position == 0 and reconcile:
            continue  # Targeted feedback reconciliation is reviewed separately.
        if tag and (position >= len(plan) or tag != plan[position][0]):
            issues.append('Collected '+tag+' before resolving position '+str(position))
    return issues


def trial_config(runtime):
    return {'skills':['.'], 'agents':{'build':{'permissions':[
        {'action':'external_directory','resource':'*','effect':'deny'},
        {'action':'external_directory','resource':str(runtime)+'/*','effect':'allow'},
        {'action':'webfetch','resource':'*','effect':'deny'},
        {'action':'websearch','resource':'*','effect':'deny'}]}}}


def external_allowed(rules, resource):
    effect = 'ask'
    for rule in rules:
        action = re.escape(rule['action']).replace(r'\*','.*').replace(r'\?','.')
        pattern = re.escape(rule['resource']).replace(r'\*','.*').replace(r'\?','.')
        if re.fullmatch(action,'external_directory') and re.fullmatch(pattern,resource):
            effect = rule['effect']
    return effect == 'allow'


def empty_schedule_block(runtime, day, kind, language):
    from goodmorning.records.task import main
    captured = io.StringIO()
    with redirect_stdout(captured):
        code = main(['--secretary-dir',str(runtime),'--briefing',kind,'--date',day,
                     '--section','schedule','--website-language',language])
    assert code == 0, 'Read-only schedule expectation could not be prepared'
    result = json.loads(captured.getvalue())
    return result['block'] if result.get('total') == 0 and not result['warnings'] else None


def section_timings(runtime, job, started=None):
    """Seconds per step from the job's timing log: provider reads, model turns, and code between them.

    A model turn runs from the receipt that handed it a step to the call that advanced it; calls the
    helper rejected stay in that turn. `start` is the first turn, from dispatch to prepare."""
    path = timings_path(runtime, job)
    events = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    rows, key = {}, 'start'
    def row(name):
        return rows.setdefault(name, {'read':0.0, 'model':0.0, 'code':0.0, 'calls':0})
    if started and events:
        row('start')['model'] += events[0]['at'] - started
    for event, after in zip(events, events[1:] + [None]):
        gap = after['at'] - event['at'] if after else 0.0
        step = event['step']
        if step in ('write', 'opening', 'closing'):
            key = event['section'] if step == 'write' else step
        if step == 'receive':
            row(key)['calls'] += 1
            # A rejected call gets no receipt, so the model is still on the same step.
            row(key)['model' if after and after['step'] == 'receive' else 'code'] += gap
        elif step == 'collect':
            row(event['section'])['read'] += gap
        elif step in ('write', 'opening', 'closing'):
            row(key)['model'] += gap
        else:  # Images after a publish, and the final save.
            row(key)['code'] += gap
    return {name:{part:round(value, 2) for part, value in values.items()} for name, values in rows.items()}


def print_timings(language, scenario, timings):
    print(language+' '+scenario+' timings (s): ' + '; '.join(
        f"{name} read {value['read']:.1f} model {value['model']:.1f} code {value['code']:.1f} calls {value['calls']}"
        for name, value in timings.items()), flush=True)


def seed_timing(runtime, language, day):
    """Today and tomorrow appointments and a saved idea, so Schedule and Reminders have rows to present."""
    tomorrow = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    names = (('Team stand-up', 'Dentist', 'Project review'), 'Try a weekly review on Fridays') if language == 'en' else (
        ('团队站会', '看牙医', '项目评审'), '试试每周五做一次周回顾')
    calendar = CalendarStore(str(runtime/'calendar.sqlite'))
    try:
        for subject, date, start, end in ((names[0][0], day, '09:30', '09:45'), (names[0][1], day, '15:00', '16:00'),
                                          (names[0][2], tomorrow, '11:00', '12:00')):
            calendar.add({'subject':subject, 'start':f'{date}T{start}:00+00:00', 'end':f'{date}T{end}:00+00:00'})
    finally:
        calendar.close()
    inbox = InboxStore(runtime, write=True)
    try:
        inbox.mutate('add', {'kind':'idea', 'raw':names[1]}, 'ses_fixture', 'timing-idea', day+'T07:00:00+00:00')
    finally:
        inbox.close()


# The note's undated or distant items must stay out; only tomorrow's dinner is tied to today (#227).
HEADLINE_MEMORY = {'en': ('mochi', 'marathon', 'vegetarian'), 'zh-CN': ('mochi', '马拉松', '吃素')}


def headline_case(runtime, language, instant):
    """A dentist appointment today, rain later and a note with one item dated tomorrow."""
    from goodmorning.records import memory
    day = instant.astimezone(ZoneInfo('Europe/London')).date()
    tomorrow = day + timedelta(days=1)
    calendar = CalendarStore(str(runtime/'calendar.sqlite'))
    try:
        calendar.add({'subject':'Dentist' if language == 'en' else '看牙医', 'location':'Elm Street Dental',
                      'start':datetime(day.year, day.month, day.day, 10, 30, tzinfo=ZoneInfo('Europe/London')).isoformat(),
                      'end':datetime(day.year, day.month, day.day, 11, 15, tzinfo=ZoneInfo('Europe/London')).isoformat()})
    finally:
        calendar.close()
    note = ({'life':'You have a dog, Mochi. You are vegetarian.',
             'lately':f'You are training for a marathon in March. Your friend Priya\'s birthday dinner is on {tomorrow.day} {tomorrow:%B}.'}
            if language == 'en' else
            {'life':'你养了一只叫 Mochi 的狗。你吃素。',
             'lately':f'你在为三月的马拉松做训练。{tomorrow.month} 月 {tomorrow.day} 日是朋友 Priya 的生日晚餐。'})
    memory.change(runtime, 0, note=note)


def check_headline(document, language, scenario, result):
    headline = document['greeting']
    result['headline'], result['opening'] = headline, document['opening']
    assert len(headline) <= HEADLINE_LIMIT[language] and '\n' not in headline, 'Headline is not one short line'
    if scenario == 'morning-headline':
        words = HEADLINE_MEMORY[language] + ('priya',)
        assert not [word for word in words if word in headline.casefold()], 'Memory reached the headline'
        text = json.dumps(document, ensure_ascii=False).casefold()
        assert not [word for word in HEADLINE_MEMORY[language] if word in text], 'A memory item not tied to today was mentioned'
        assert 'sam' not in headline.casefold(), 'The name went into the headline'
    result['checks'].append('Headline is one short line; memory stays out of it')


def run_case(output, template, language, scenario, instant):
    timing, folder = scenario.endswith('-timing'), output/scenario
    scenario = scenario.replace('-timing', '-weather')  # Timing cases are the weather cases plus a fuller agenda.
    folder.mkdir(mode=0o700)
    runtime = folder/'account'
    runtime.mkdir(mode=0o700)
    source = folder/'source'
    shutil.copytree(template, source)
    (source/'opencode.json').write_text(json.dumps(trial_config(runtime)))
    selected = for_language(language)
    tone = {'morning-empty':'default', 'morning-weather':'default', 'morning-headline':'playful', 'morning-resume':'formal',
            'evening-feedback':'playful', 'evening-ambiguous':'formal', 'evening-weather':'default'}[scenario]
    profile = ('city: London, GB\ntimezone: Europe/London\nnews_country: GB\n'
               'secretary_name: Nora\ncalendar_source: custom\n')
    if TONES[tone]:
        profile += 'secretary_tone: '+TONES[tone]+'\n'
    if scenario in ('morning-empty', 'morning-headline', 'evening-feedback'):
        profile += 'user_name: Sam\n'
    (runtime/'profile.md').write_text(profile)
    (runtime/'browser-policy.json').write_text(json.dumps({key:False for key in (
        'calendar_sync','publisher_images','news_acknowledgement')}))
    initialize(runtime)
    CalendarStore(str(runtime/'calendar.sqlite')).close()
    if scenario == 'morning-headline':
        headline_case(runtime, language, instant)
    if scenario in ('morning-weather', 'morning-headline', 'evening-weather'):
        tomorrow = (instant.astimezone(ZoneInfo('Europe/London')) + timedelta(days=1)).date().isoformat()
        reading = synthetic_weather(instant, tomorrow if scenario == 'evening-weather' else None)
        save(runtime/'trial-weather.json', reading)
        save(folder/'weather-reading.json', reading)
    bridge = CheckpointBridge(trial_engine.Engine(source, runtime).start(), scenario == 'morning-resume', language)
    app = BrowserApp(runtime, bridge, now=lambda:instant, preflight=True)
    day = app.today()
    if timing:
        seed_timing(runtime, language, day)
    baseline = seed_tasks(runtime, language, scenario, day)
    protected = protected_state(runtime)
    result = {'scenario':folder.name, 'language':language, 'tone':tone, 'model':session_payload(selected),
              'date':day, 'checks':[], 'review':'pending manual language/tone/grounding review'}
    save(folder/'baseline.json', {'tasks':baseline, 'protected':protected})
    kind = 'gm' if scenario.startswith('morning') else 'gn'
    try:
        bridge.verify_scope()
        # Intent is persistent before upstream effects. Never rerun an existing folder.
        save(folder/'start-intent.json', {'date':day, 'kind':kind})
        with context(language, selected):
            job = app.start(day, kind)['job']
        save(folder/'job.json', {'id':job})
        if kind == 'gn':
            with context(language, selected):
                status = app.status(job)
            assert status['state'] == 'waiting' and not bridge.sessions, 'Evening feedback did not precede dispatch'
            form = status['forms'][0]
            if scenario == 'evening-feedback':
                grocery = next(option['value'] for field in form['fields'] if field['key'] == 'completed'
                               for option in field['options'] if option['label'] == baseline[2]['title'])
                details = ('The Atlas report is blocked awaiting the dataset. Its agreed workday stays tomorrow; '
                           'no dates or rollover are changed.') if language == 'en' else (
                           'Atlas 报告被阻塞，正在等待数据集。约定工作日仍为明天，不更改日期，也不顺延。')
                answer = {'completed':[grocery], 'details':details}
            elif scenario == 'evening-weather':
                answer = {'completed':['none'], 'details':'No other updates'}
            else:
                answer = {'completed':['none'], 'details':'One of the reports is blocked, but I have not specified which one.'
                          if language == 'en' else '有一份报告被阻塞，但我还没有说明是哪一份。'}
            save(folder/'feedback-intent.json', {'form':form, 'answer':answer})
            with context(language, selected):
                app.reply(job, 'form', form['id'], {'answer':answer})
            result['checks'].append('Browser feedback saved before model dispatch')
        status = observe(app, bridge, job, folder, 'original', language, selected)
        result['timings'] = section_timings(runtime, job, app.job(job).get('running_at'))
        print_timings(language, folder.name, result['timings'])
        assert protected_state(runtime) == protected, 'Protected settings/calendar changed'
        result['checks'].append('Settings, calendar and integration policy unchanged')
        log = commands(runtime)
        assert not any(entry.get('exit',0) is None for entry in log), 'A helper outcome is unknown; inspect, do not infer success'
        result['blocked_out_of_turn_reads'] = sum(entry.get('error') == 'browser_section_not_ready' for entry in log)
        assert not any(entry['argv'][:1] == ['workflow'] for entry in log), 'Browser agent repeated local preparation'
        prepared = json.loads(context_path(runtime, job).read_text())
        reconcile = kind == 'gn'
        saved = app.source(day, kind)
        quiet = kind == 'gn' and saved.exists() and 'today' not in [s[0] for s in json.loads(saved.read_text())['sections']]
        order_issues = collection_order_issues(log, default_plan(prepared), 1 if bridge.seeded else 0, quiet=quiet,
                                              reconcile=reconcile)
        result['collection_order_issues'] = order_issues
        if scenario == 'evening-ambiguous':
            assert status['state'] == 'waiting' and status['forms'], 'Ambiguous report did not request clarification'
            choices=[option.get('label','')+' '+str(option.get('value','')) for form in status['forms']
                     for field in form['fields'] for option in field.get('options',[])]
            assert not any(baseline[2]['title'] in choice for choice in choices), 'Report attribution offered an unrelated grocery task'
            assert records(runtime) == baseline, 'Ambiguous attribution changed records before clarification'
            assert not app.source(day,kind).exists(), 'Waiting edition was saved'
            result['checks'].append('Ambiguous report asks before any record mutation or final save')
        else:
            assert status['state'] == 'ready', 'Edition did not finish; inspect preserved status/transcript'
            document = json.loads(app.source(day,kind).read_text())
            save(folder/'original.document.json', document)
            assert document['v'] == 2 and document['lang'] == language
            assert document['sections'] and not list((runtime/'daily').glob('*.html'))
            expected_schedule = empty_schedule_block(runtime, day, kind, language)
            if expected_schedule:
                schedule = next(section for section in document['sections'] if section[0] == 'schedule')
                assert expected_schedule in schedule[1], 'Schedule omitted or rewrote the code-owned window summary'
            result['checks'].append('Verified native v2 edition in pinned language; no HTML copy')
            if kind == 'gm':
                check_headline(document, language, scenario, result)
                assert records(runtime) == baseline, 'Morning presentation changed task records'
                assert any(section[0] == 'news' for section in document['sections'])
                if scenario in ('morning-weather', 'morning-headline'):
                    blocks = document['sections'][0][1]
                    weather = next(block for block in blocks if block[0] == 'weather')
                    assert len(weather) == 3 and weather[2] == reading['json']['frame'], 'Code did not attach the read frame'
                    cards = {row[0]:row for row in weather[1]}
                    assert {'temperature','precipitation','air'} <= set(cards), 'Weather cards missing'
                    from goodmorning.briefings.briefing_document import weather_values
                    from goodmorning.web import language as ui
                    values = weather_values(reading['json'], lambda words, **fill: ui.text(words, lang=language, **fill))
                    assert all(row[1] == values[kind] for kind, row in cards.items()), 'Card values did not come from the read'
                    assert not any(re.search(r'\d+ ?%|°', str(row[2])) for row in cards.values()), 'A detail repeated card figures'
                    rain = ' '.join(str(value) for value in cards['precipitation'][1:3])
                    assert '100%' not in rain, 'Precipitation repeated the whole-day 100% the read no longer reports'
                    warm = str(cards['temperature'][2]).casefold()
                    assert not any(word in warm for word in ('rain', 'drizzle', 'umbrella', 'shower', '雨', '伞')), \
                        'Temperature detail reported precipitation'
                    result['weather_cards'] = weather[1]
                    result['checks'].append('Weather published from the forward-looking read; frame attached by code')
                elif scenario == 'morning-empty':
                    assert [section[0] for section in document['sections']] == ['weather','news','schedule']
                    result['checks'].append('Required unavailable sections retained; empty optional positions skipped')
                    operations = [entry for entry in log if '--help' not in entry['argv'] and '-h' not in entry['argv']
                                  and not (entry['argv'][:1] == ['job'] and entry.get('exit',0) != 0)]
                    assert job_action(operations[0]['argv']) == 'prepare', 'First operation was not job prepare'
                    assert job_action(operations[1]['argv']) == 'init', 'Collection preceded preview init'
                    result['checks'].append('Prepare then immediate init before collection')
                else:
                    assert document['sections'][0] == bridge.seeded['weather']
                    assert not any(entry['argv'][:1] == ['weather'] for entry in log)
                    assert not any(job_action(entry['argv']) == 'init' for entry in log)
                    result['checks'].append('Existing checkpoint resumed without reinit, rewriting or refetching its section')
            elif scenario == 'evening-weather':
                assert records(runtime) == baseline, 'Evening without updates changed task records'
                assert [section[0] for section in document['sections']][:2] == ['weather','schedule'], 'A quiet evening kept a Today section'
                assert not any(job_action(entry['argv']) in ('publish','skip') and entry.get('input',{}).get('position') == 0
                               for entry in log), 'The model spent a turn on the quiet Today position'
                section = document['sections'][0]
                assert section[1] == [reading['json']['outlook']], 'The section is not exactly the code-filled card'
                assert section[3:] == [default_plan(prepared)[1][1]], 'Weather tomorrow lost its planned title'
                assert section[2:3] and section[2].strip() and '\n' not in section[2], 'No one-line closing note'
                assert not re.search(r'\d', section[2]), 'The note repeated numbers or times the card already shows'
                result['weather_note'] = section[2]
                result['checks'].append('Quiet evening: no Today section or turn; Weather tomorrow is the code-filled card with a one-line note')
            else:
                current = records(runtime)
                atlas = next(task for task in current if task['id'] == baseline[0]['id'])
                groceries = next(task for task in current if task['id'] == baseline[2]['id'])
                assert atlas['status'] == 'blocked' and atlas['planned_date'] == baseline[0]['planned_date']
                assert atlas['revision'] == baseline[0]['revision'] + 1, 'Clear blocker report was rewritten after reconciliation'
                assert groceries['status'] == 'done' and len(current) == len(baseline)
                assert not any(entry['argv'][:1] == ['news'] for entry in log)
                result['checks'].append('Exact selected completion and explicit blocker applied without changing future workday')
                assert not any(entry['argv'][:1] == ['task'] and '--show' in entry['argv'] for entry in log), 'Today looked up a revision the Tasks read gave'
                today = next(section for section in document['sections'] if section[0] == 'today')
                assert today[1][:1] and today[1][0][0] == 'actions', 'Code did not place the Today cards first'
                assert not any(json.dumps(entry.get('input'), ensure_ascii=False).count('"actions"') for entry in log
                               if job_action(entry['argv']) == 'publish' and entry.get('input', {}).get('position') == 0), \
                    'The model wrote the Today cards itself'
                result['checks'].append('Today: the model sent only its words; code placed the cards, with no revision lookup')
                before = (runtime/'inbox.sqlite').read_bytes()
                feedback = (runtime/'daily'/(day+'.md')).read_text().split('## feedback',1)[1]
                save(folder/'regenerate-intent.json', {'previous':job})
                with context(language, selected):
                    replacement = app.regenerate({'date':day,'kind':kind,'id':uuid.uuid4().hex,'previous':job})['job']
                save(folder/'replacement-job.json', {'id':replacement})
                replacement_status = observe(app, bridge, replacement, folder, 'replacement', language, selected)
                assert replacement_status['state'] == 'ready', 'Regeneration did not finish or re-asked feedback'
                assert (runtime/'inbox.sqlite').read_bytes() == before, 'Regeneration mutated task records'
                assert (runtime/'daily'/(day+'.md')).read_text().split('## feedback',1)[1] == feedback
                save(folder/'replacement.document.json', json.loads(app.source(day,kind).read_text()))
                if expected_schedule:
                    replacement_doc = json.loads(app.source(day,kind).read_text())
                    schedule = next(section for section in replacement_doc['sections'] if section[0] == 'schedule')
                    assert expected_schedule in schedule[1], 'Regeneration rewrote the code-owned schedule window'
                result['checks'].append('Regeneration reuses feedback; no repeated question, completion or task mutation')
                replacement_log = commands(runtime)[len(log):]
                replacement_context = json.loads(context_path(runtime, replacement).read_text())
                replacement_order_issues = collection_order_issues(replacement_log, default_plan(replacement_context))
                result['replacement_collection_order_issues'] = replacement_order_issues
                assert not replacement_order_issues, '; '.join(replacement_order_issues)
                assert link_handoff(folder, 'replacement', f'/d/{day}/{kind}'), 'Regeneration reply was not a verified briefing-link handoff'
            assert link_handoff(folder, 'original', f'/d/{day}/{kind}'), 'Completed reply was not a verified briefing-link handoff'
            result['checks'].append('Final reply is a short saved-briefing link handoff; content still needs manual review')
        assert not order_issues, '; '.join(order_issues)
        result['checks'].append('No future-section collection before submitting the current position')
        result['functional_complete'] = True
        print(language+' '+folder.name+': '+str(len(result['checks']))+' checks passed', flush=True)
    except Exception as error:
        result['failure'] = str(error)[:1500]
        result['functional_complete'] = False
        print(language+' '+folder.name+': INCOMPLETE — '+result['failure'], flush=True)
    finally:
        bridge.close()
        save(folder/'result.json', result)
    return result


FLEXIBLE = {
    'en': {
        'morning-vague': [('atlas report stuff etc', 'need to send it to Dana by friday', 'Atlas', 0),
                          ('Groceries', 'milk and eggs', '', 0),
                          ('Prepare Q3 slides for the Boreal review', '', 'Boreal', 0)],
        'evening-complex': [('Draft Boreal report', '', 'Boreal', 0), ('Send Atlas report', '', 'Atlas', 1),
                            ('Buy groceries', '', '', 0)],
        'details': ("Got about half of the Boreal draft done (intro and charts); the rest needs Priya's numbers. "
                    "The Atlas report is blocked until the dataset arrives. Also finally called the bank about the mortgage, sorted. "
                    "Oh, and can you push the Atlas report to Monday?"),
        'answer': 'Yes, please move the Atlas report to next Monday.',
        'monday': ('monday', 'mon '),
        'bank': ('bank', 'mortgage'),
    },
    'zh-CN': {
        'morning-vague': [('atlas 报告的事 等等', '周五前要发给 Dana', 'Atlas', 0), ('杂货', '牛奶和鸡蛋', '', 0),
                          ('准备 Boreal 评审用的第三季度幻灯片', '', 'Boreal', 0)],
        'evening-complex': [('起草 Boreal 报告', '', 'Boreal', 0), ('发送 Atlas 报告', '', 'Atlas', 1), ('购买食品', '', '', 0)],
        'details': ('Boreal 草稿完成了一半左右（引言和图表），剩下的要等 Priya 的数据。Atlas 报告在数据集到之前都卡着。'
                    '另外终于给银行打了电话问房贷的事，已经办妥。对了，能把 Atlas 报告挪到周一吗？'),
        'answer': '是的，请把 Atlas 报告挪到下周一。',
        'monday': ('周一', '星期一', 'monday'),
        'bank': ('银行', '房贷'),
    },
}


def seed_flexible(runtime, language, scenario, day):
    """Vague task copy or messy multi-part feedback: judgment cases, not fixed recipes."""
    inbox = InboxStore(runtime, write=True)
    try:
        for index, (title, detail, project, offset) in enumerate(FLEXIBLE[language][scenario]):
            planned = (datetime.fromisoformat(day) + timedelta(days=offset)).date().isoformat()
            task = {'title':title, 'planned_date':planned, 'timezone':'Europe/London', 'project':project}
            if detail:
                task['detail'] = detail
            inbox.mutate('add', {'kind':'todo', 'raw':title, 'task':task}, 'ses_fixture', scenario+'-'+str(index), day+'T07:00:00+01:00')
    finally:
        inbox.close()
    return records(runtime)


def answer_question(app, job, forms, language):
    """Answer only the Monday move this fixture requested; anything else needs manual review."""
    words = FLEXIBLE[language]
    for form in forms:
        values = {}
        for field in form['fields']:
            options = field.get('options') or []
            chosen = next((option['value'] for option in options
                           if any(key in (option.get('label','')+' '+str(option.get('value',''))).lower() for key in words['monday'])), None)
            if chosen is not None and not field.get('multiple'):
                values[field['key']] = chosen
            elif field['type'] == 'string' and (field.get('custom') or not options):
                values[field['key']] = words['answer']
            else:
                raise AssertionError('Unsupported synthetic question; inspect it instead of guessing approval')
        app.reply(job, 'form', form['id'], {'answer':values})


CASES = ('morning-empty', 'morning-resume', 'evening-feedback', 'evening-ambiguous')
FLEXIBLE_CASES = ('morning-vague', 'evening-complex')


def run_flexible_case(output, template, language, scenario, instant):
    folder = output/scenario
    folder.mkdir(mode=0o700)
    runtime = folder/'account'
    runtime.mkdir(mode=0o700)
    source = folder/'source'
    shutil.copytree(template, source)
    (source/'opencode.json').write_text(json.dumps(trial_config(runtime)))
    selected = for_language(language)
    (runtime/'profile.md').write_text('city: London, GB\ntimezone: Europe/London\nnews_country: GB\n'
                                      'secretary_name: Nora\ncalendar_source: custom\nsecretary_tone: '+TONES['playful']+'\n')
    (runtime/'browser-policy.json').write_text(json.dumps({key:False for key in (
        'calendar_sync','publisher_images','news_acknowledgement')}))
    initialize(runtime)
    CalendarStore(str(runtime/'calendar.sqlite')).close()
    bridge = CheckpointBridge(trial_engine.Engine(source, runtime).start(), False, language)
    app = BrowserApp(runtime, bridge, now=lambda:instant, preflight=True)
    day = app.today()
    kind = 'gm' if scenario == 'morning-vague' else 'gn'
    baseline = seed_flexible(runtime, language, scenario, day)
    result = {'scenario':scenario, 'language':language, 'tone':'playful', 'model':session_payload(selected),
              'date':day, 'checks':[], 'review':'pending manual judgment/language/tone review'}
    save(folder/'baseline.json', {'tasks':baseline})
    try:
        bridge.verify_scope()
        save(folder/'start-intent.json', {'date':day, 'kind':kind})
        with context(language, selected):
            job = app.start(day, kind)['job']
        save(folder/'job.json', {'id':job})
        if kind == 'gn':
            with context(language, selected):
                form = app.status(job)['forms'][0]
            done = [option['value'] for field in form['fields'] if field['key'] == 'completed'
                    for option in field['options'] if option['label'] == baseline[2]['title']]
            with context(language, selected):
                app.reply(job, 'form', form['id'], {'answer':{'completed':done, 'details':FLEXIBLE[language]['details']}})
        status = observe(app, bridge, job, folder, 'original', language, selected)
        stage = 'original'
        if status['state'] == 'waiting' and status.get('forms'):
            result['asked'] = [field.get('description') or field.get('title') for form in status['forms'] for field in form['fields']]
            save(folder/'question.json', status['forms'])
            with context(language, selected):
                answer_question(app, job, status['forms'], language)
            status, stage = observe(app, bridge, job, folder, 'followup', language, selected), 'followup'
        assert status['state'] == 'ready', 'Edition did not finish; inspect preserved status/transcript'
        document = json.loads(app.source(day, kind).read_text())
        save(folder/'original.document.json', document)
        current = {task['id']:task for task in records(runtime)}
        assert len(current) == len(baseline), 'Feedback or polish created or removed tasks'
        if kind == 'gm':
            vague, groceries, clear = baseline
            # A briefing rewords vague rows on the page only; saved records stay as they are.
            shown = {}
            def rows(node):
                if isinstance(node, list):
                    if len(node) > 5 and isinstance(node[0], str) and node[0].startswith('task_'):
                        shown.setdefault(node[0], node[5])
                    for child in node:
                        rows(child)
                elif isinstance(node, dict):
                    for child in node.values():
                        rows(child)
            rows(document)
            result['titles_after'] = [current[task['id']]['title'] for task in baseline]
            result['titles_shown'] = [shown.get(task['id']) for task in baseline]
            assert all(current[task['id']] == task for task in baseline), 'The briefing changed a saved task'
            result['polished_vague'] = sum(shown.get(task['id']) not in (None, task['title']) for task in (vague, groceries))
            assert shown.get(clear['id']) == clear['title'], 'A clear title was reworded'
            assert result['polished_vague'] == 2, 'A materially vague title was shown unpolished'
            result['checks'].append('Both vague titles reworded on the page; saved tasks and the clear title unchanged')
        else:
            boreal, atlas, groceries = baseline
            today = next(section for section in document['sections'] if section[0] == 'today')
            statuses = {row[0]:row[4] for block in today[1] if block[0] == 'actions' for row in block[1]}
            assert statuses.get(boreal['id']) == 'partial', 'Half-finished Boreal draft was not reported as partial'
            assert current[atlas['id']]['status'] == 'blocked', 'Atlas blocker was not recorded'
            assert current[groceries['id']]['status'] == 'done'
            text = json.dumps(document, ensure_ascii=False).lower()
            assert any(key in text for key in FLEXIBLE[language]['bank']), 'Extra accomplishment was dropped'
            moved = current[atlas['id']]['planned_date'] != atlas['planned_date']
            if moved:
                monday = datetime.fromisoformat(day).date() + timedelta(days=(7 - datetime.fromisoformat(day).weekday()) or 7)
                assert current[atlas['id']]['planned_date'] == monday.isoformat(), 'Atlas moved to a day other than Monday'
            assert moved or 'asked' in result, 'Requested Monday move was neither applied nor asked about'
            result['checks'].append('Partial, blocker and extra accomplishment reported; Monday request '
                                    + ('applied' if moved else 'asked about'))
        assert link_handoff(folder, stage, f'/d/{day}/{kind}'), 'Completed reply was not a verified briefing-link handoff'
        result['functional_complete'] = True
        print(language+' '+scenario+': '+str(len(result['checks']))+' checks passed', flush=True)
    except Exception as error:
        result['failure'] = str(error)[:1500]
        result['functional_complete'] = False
        print(language+' '+scenario+': INCOMPLETE — '+result['failure'], flush=True)
    finally:
        bridge.close()
        save(folder/'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    trial_engine.add_arguments(parser)
    parser.add_argument('--language', choices=('en','zh-CN'), required=True)
    parser.add_argument('--only', nargs='+', choices=CASES + FLEXIBLE_CASES + ('morning-weather', 'morning-headline', 'evening-weather', 'morning-timing', 'evening-timing'),
                        help='Run only these scenarios; the weather and timing cases run only when named')
    args = parser.parse_args()
    output = trial_engine.private_output(parser, args.output)
    with matrix_lock(output):
        output.mkdir(mode=0o700)
        source = output/'source'
        trial_engine.copy_release(source, args.source.resolve())
        (source/'opencode.json').write_text(json.dumps({'skills':['.'],'permissions':[
            {'action':'webfetch','resource':'*','effect':'deny'},
            {'action':'websearch','resource':'*','effect':'deny'}]}))
        (source/'scripts/goodmorning.py').write_text(TRIAL_CLI)
        instant = datetime.now(timezone.utc)
        results = [(run_flexible_case if scenario in FLEXIBLE_CASES else run_case)(output, source, args.language, scenario, instant)
                   for scenario in args.only or CASES + FLEXIBLE_CASES]
        save(output/'matrix.json', {'cases':results, 'limitations':[
            'Real native models and browser job/controller helpers; no public HTTPS/encrypted account test.',
            'Provider faults and prepublished checkpoint are synthetic; no real weather/news provider validation.',
            'One sample per scenario/model, not statistical reliability; prose needs manual review.']})
        if not all(result.get('functional_complete') for result in results):
            raise SystemExit(1)


if __name__ == '__main__':
    main()
