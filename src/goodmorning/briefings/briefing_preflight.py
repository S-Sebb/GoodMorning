"""Browser-owned decisions and exact user feedback, before any model dispatch."""
import json
from pathlib import Path

from .briefing_job import context_path
from .briefing_stream import bounded_json
from goodmorning.records.daily import amend, one_line, read_record, record_path
from goodmorning.runtime_files import atomic_text, runtime_lock
from goodmorning.records.workflow import prepare


def write(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, separators=(',',':'))+'\n')


def initialize(runtime, job):
    context = prepare(runtime, job['kind'], job['date'], Path(runtime)/'cache', task_limit=200)
    policy_path = Path(runtime)/'browser-policy.json'
    policy = bounded_json(policy_path,2000) if policy_path.exists() else {}
    if not isinstance(policy,dict) or set(policy)-{'live_project_access','calendar_sync','publisher_images','news_acknowledgement'} or any(type(v) is not bool for v in policy.values()):
        raise ValueError('Invalid browser integration policy')
    context['integration_policy'] = policy
    if not context.get('ready') or context.get('duplicate'):
        raise ValueError('Configured profile and a new edition are required')
    if context['daily'].get('next_offset') is not None:
        raise ValueError('Daily list exceeds the browser feedback limit; review it before generation')
    fields = []
    if context['missed_total']:
        fields.append({'key':'continue','title':'Past missing editions','type':'string','required':True,
                       'description':'Past missing editions stay read-only. Continue with today’s briefing?',
                       'options':[{'value':'today','label':'Continue today'},{'value':'stop','label':'Stop for now'}]})
    if job['kind'] == 'gn':
        tasks = [t for t in context['daily']['tasks'] if not t['done']]
        fields.extend([
            {'key':'completed','title':'What did you fully complete?','type':'multiselect','required':True,
             'minItems':1,'description':'Choose completed tasks, or “None yet.” Partial work stays open.',
             'options':[{'value':'none','label':'None yet'}]+[{'value':t['id'],'label':t['text']} for t in tasks]},
            {'key':'details','title':'Partial, blocked, changed or extra work','type':'string','required':True,
             'custom':True,'options':[{'value':'No other updates','label':'No other updates'}],
             'description':'Give actual details, or choose “No other updates.”'}])
    context['awaiting'] = bool(fields)
    revision = '_'+str(job['preflight_revision']) if job.get('preflight_revision') else ''
    context['form'] = {'id':'preflight_'+job['id']+revision,'title':'Before your briefing','fields':fields} if fields else None
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
    if job['kind'] == 'gn':
        chosen, details = value['completed'], value['details']
        known = {t['id']:t for t in context['daily']['tasks'] if not t['done']}
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
        amendment = {'complete':complete,'confirmed_completion':True,'append':{'feedback':feedback}}
        with runtime_lock(runtime, '.state.lock'):
            current = read_record(record_path(runtime, job['date']))[1]
            expected = context['daily']['sha256']
            if current == expected:
                receipt = amend(runtime, job['date'], expected, amendment, locked=True, dry_run=True)
                context.update(browser_answer=value, feedback_result_sha256=receipt['sha256'])
                write(target, context)
                receipt = amend(runtime, job['date'], expected, amendment, locked=True)
            elif previous == value and current == context.get('feedback_result_sha256'):
                receipt = {'sha256':current}  # Previous atomic amendment committed before its receipt.
            else:
                raise ValueError('The daily plan changed; reconcile feedback before continuing')
        context['feedback'] = {'completed':[known[x]['text'] for x in complete],'details':details,'saved':True}
        context['daily']['sha256'] = receipt['sha256']
        for task in context['daily']['tasks']:
            if task['id'] in complete:
                task['done'] = True
    context.update(awaiting=False,browser_answer=value)
    # The choice is resolved in code; do not invite another missed-run question.
    context['missed'] = []
    context['missed_total'] = 0
    context['past_missing_choice'] = 'continue_today'
    write(target, context)
    return context
