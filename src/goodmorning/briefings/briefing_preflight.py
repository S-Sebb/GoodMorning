"""Browser-owned decisions and exact user feedback, before any model dispatch."""
import json
from pathlib import Path

from .briefing_job import context_path
from .briefing_stream import bounded_json
from goodmorning.records.daily import amend, one_line, read_record, record_path
from goodmorning.runtime_files import atomic_text, runtime_lock
from goodmorning.records.workflow import prepare
from goodmorning.web import language as ui


def write(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, separators=(',',':'))+'\n')


def initialize(runtime, job, previous=None):
    selected=job.get('language',ui.current())
    context = prepare(runtime, job['kind'], job['date'], Path(runtime)/'cache', task_limit=200, website_language=selected,
                      replacement='replacement' in job)
    context['website_language']=selected
    policy_path = Path(runtime)/'browser-policy.json'
    policy = bounded_json(policy_path,2000) if policy_path.exists() else {}
    if not isinstance(policy,dict) or set(policy)-{'live_project_access','calendar_sync','publisher_images','news_acknowledgement'} or any(type(v) is not bool for v in policy.values()):
        raise ValueError('Invalid browser integration policy')
    context['integration_policy'] = policy
    if not context.get('ready') or context.get('duplicate'):
        raise ValueError('Configured profile and a new edition are required')
    if context.get('document_version') != 2 and context['daily'].get('next_offset') is not None:
        raise ValueError('Daily list exceeds the browser feedback limit; review it before generation')
    if (Path(runtime)/'inbox.sqlite').exists():
        from goodmorning.records.inbox_store import InboxStore
        from goodmorning.records.task_store import TaskStore
        from goodmorning.records.routing import planned_day
        inbox = InboxStore(runtime)
        try:
            if inbox.version == 1:
                raise ValueError('migration_required: review and explicitly upgrade task storage before a new edition')
            if inbox.version == 2:
                rows = planned_day(TaskStore(inbox), job['date'])
                if len(rows) > 200:
                    raise ValueError('Planned occurrences exceed the feedback limit; review before generation')
                context['feedback_tasks'] = [{'id': r['occurrence_id'], 'task_id': r['id'], 'revision': r['revision'],
                                             'text': r['title'], 'done': r['status'] == 'done'} for r in rows]
        finally:
            inbox.close()
    fields = []
    if 'replacement' in job:
        context['regenerating'] = True
    if previous and previous.get('past_missing_choice') == 'continue_today':
        context.update(missed=[], missed_total=0, past_missing_choice='continue_today')
    if previous and previous.get('feedback', {}).get('saved') is True:
        context['feedback'] = previous['feedback']
    if context['missed_total']:
        fields.append({'key':'continue','title':'Past missing editions','type':'string','required':True,
                       'description':'Past missing editions stay read-only. Continue with today’s briefing?',
                       'options':[{'value':'today','label':'Continue today'},{'value':'stop','label':'Stop for now'}]})
    if job['kind'] == 'gn' and not context.get('feedback'):
        tasks = [t for t in context.get('feedback_tasks', context['daily']['tasks']) if not t['done']]
        fields.extend([
            {'key':'completed','title':'What did you fully complete?','type':'multiselect','required':True,
             'minItems':1,'description':'Choose completed tasks, or “None yet.” Partial work stays open.',
             'options':[{'value':'none','label':'None yet'}]+[{'value':t['id'],'label':t['text']} for t in tasks]},
            {'key':'details','title':'Partial, blocked, changed or extra work','type':'string','required':True,
             'custom':True,'options':[{'value':'No other updates','label':'No other updates'}],
             'description':'Give actual details, or choose “No other updates.”'}])
    context['awaiting'] = bool(fields)
    for field in fields:
        for key in ('title','description'):
            if key in field:field[key]=ui.text(field[key],lang=selected)
        for option in field.get('options',[]):
            if option['value'] in ('today','stop','none','No other updates'):option['label']=ui.text(option['label'],lang=selected)
    revision = '_'+str(job['preflight_revision']) if job.get('preflight_revision') else ''
    context['form'] = {'id':'preflight_'+job['id']+revision,'title':ui.text('Before your briefing',lang=selected),'fields':fields} if fields else None
    write(context_path(runtime, job['id']), context)
    return context


def answer(runtime, job, value):
    target = context_path(runtime, job['id'])
    context = bounded_json(target, 300_000)
    if not context.get('awaiting'):
        if context.get('browser_answer') == value:
            return context
        raise ValueError('This browser decision is no longer pending')
    keys = {f['key'] for f in context['form']['fields']}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError('Answer exactly the pending browser fields')
    if 'continue' in keys and value['continue'] not in ('today','stop'):
        raise ValueError('Invalid missed-edition choice')
    if value.get('continue') == 'stop':
        context.update(awaiting=False,cancelled=True,browser_answer=value)
        write(target, context)
        return context
    if job['kind'] == 'gn' and 'completed' in keys:
        chosen, details = value['completed'], value['details']
        known = {t['id']:t for t in context.get('feedback_tasks', context['daily']['tasks']) if not t['done']}
        if not isinstance(chosen,list) or not chosen or any(not isinstance(x,str) for x in chosen) or len(set(chosen)) != len(chosen):
            raise ValueError('Select completed tasks or explicitly select None yet')
        if 'none' in chosen and chosen != ['none'] or set(chosen)-set(known)-{'none'}:
            raise ValueError('Choose only listed task IDs; None yet cannot be combined with completions')
        if not isinstance(details,str) or len(details)>1800:
            raise ValueError('Progress details exceed their limit')
        details = one_line(details)
        complete = [] if chosen == ['none'] else chosen
        feedback = ['Completed: '+known[x]['text'] for x in complete] or ['No listed tasks were fully completed.']
        feedback.append('Other updates: '+details)
        # Store the exact explicit input before applying it, making uncertain retries recoverable.
        previous = context.get('browser_answer')
        if previous is not None and previous != value:
            raise ValueError('A pending feedback save must be reconciled before replacing its input')
        amendment = {'complete':[] if 'feedback_tasks' in context else complete,'confirmed_completion':True,'append':{'feedback':feedback}}
        with runtime_lock(runtime, '.state.lock'):
            current = read_record(record_path(runtime, job['date']))[1]
            expected = context['daily']['sha256']
            if current == expected:
                receipt = amend(runtime, job['date'], expected, amendment, locked=True, dry_run=True)
                context.update(browser_answer=value, feedback_result_sha256=receipt['sha256'])
                write(target, context)
                if 'feedback_tasks' in context:
                    from goodmorning.records.inbox_store import InboxStore, stamp
                    from goodmorning.records.task_store import TaskStore
                    inbox = InboxStore(runtime, write=True)
                    try:
                        # Preflight precedes agent-session creation. Audit the browser job itself.
                        TaskStore(inbox).complete_day([known[x] for x in complete], job['date'],
                            'browser:' + job['id'], 'browser-feedback:' + job['id'], stamp(runtime), details)
                    finally:
                        inbox.close()
                receipt = amend(runtime, job['date'], expected, amendment, locked=True)
            elif previous == value and current == context.get('feedback_result_sha256'):
                receipt = {'sha256':current}  # Previous atomic amendment committed before its receipt.
            else:
                raise ValueError('The daily plan changed; reconcile feedback before continuing')
        context['feedback'] = {'completed':[known[x]['text'] for x in complete],'details':details,'saved':True}
        context['daily']['sha256'] = receipt['sha256']
        for task in context.get('feedback_tasks', context['daily']['tasks']):
            if task['id'] in complete:
                task['done'] = True
    context.update(awaiting=False,browser_answer=value)
    # The choice is resolved in code; do not invite another missed-run question.
    context['missed'] = []
    context['missed_total'] = 0
    context['past_missing_choice'] = 'continue_today'
    write(target, context)
    return context
