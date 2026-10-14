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
        from goodmorning.records.routing import feedback_day, planned_day
        inbox = InboxStore(runtime)
        try:
            if inbox.version == 1:
                raise ValueError('migration_required: review and explicitly upgrade task storage before a new edition')
            if inbox.version == 2:
                rows = (feedback_day if job['kind'] == 'gn' else planned_day)(TaskStore(inbox), job['date'])
                if len(rows) > 200:
                    raise ValueError('Review tasks exceed the feedback limit; review before generation')
                context['feedback_tasks'] = [{'id': r['occurrence_id'], 'task_id': r['id'], 'revision': r['revision'],
                                             'text': r['title'], 'project': r['project'], 'done': r['status'] == 'done',
                                             **({'actual': True} if r.get('actual') else {})} for r in rows]
                try:
                    from goodmorning.records.custom_store import CustomStore
                    custom_store = CustomStore(runtime, write=False)
                    try:
                        for s in custom_store.briefing(job['date'], 'gn' if job['kind'] == 'gn' else 'gm'):
                            if job['kind'] != 'gn' and not s['due']:
                                continue
                            context['feedback_tasks'].append({
                                'id': s['occurrence_id'], 'task_id': s['id'], 'revision': s['revision'],
                                'text': s['title'], 'project': '', 'done': False, 'custom': True,
                                'custom_reason': s['reason'], 'weekly_count': s['weekly_count'],
                            })
                    finally:
                        custom_store.close()
                except (ValueError, OSError):
                    pass
        finally:
            inbox.close()
    fields = []
    if 'replacement' in job:
        context['regenerating'] = True
    # Browser generation is today-only. Archive gaps never require a blocking decision.
    context.update(missed=[], missed_total=0, past_missing_choice='continue_today')
    if previous and previous.get('feedback', {}).get('saved') is True:
        context['feedback'] = previous['feedback']
    if job['kind'] == 'gn' and not context.get('feedback'):
        tasks = [t for t in context.get('feedback_tasks', context['daily']['tasks']) if not t['done']]
        # Keep project order stable, with unassigned work after every named project.
        tasks.sort(key=lambda t: not bool(t.get('project')))
        if tasks:
            fields.extend([
                {'key':'completed','title':'What did you finish today?','type':'multiselect','required':True,
                 'minItems':1,'description':'Tick anything you fully finished. If something is still in progress, leave it unticked—you can tell me about it below.',
                 'options':[{'value':'none','label':'None of these today.'}]+[
                     {'value':t['id'],'label':t['text'],'group':t.get('project') or ui.text('Other tasks',lang=selected)} for t in tasks]},
                {'key':'details','title':'Anything else you’d like to share?','type':'string','required':True,
                 'custom':True,'customFirst':True,'placeholder':'Share any progress or updates…',
                 'options':[{'value':'No other updates','label':'Nothing else to add.'}],
                 'description':'Partial progress, something that got in the way, a change of plan, or extra work you got done.'}])
        else:
            fields.append({'key':'details','title':'How did today go?','type':'string','required':True,
                           'custom':True,'customFirst':True,'placeholder':'Share any progress or updates…',
                           'options':[{'value':'No updates today','label':'Nothing extra to add today.'}],
                           'description':'There aren’t any saved tasks to tick off for this review. You can still share what you worked on or any progress you made.'})
    context['awaiting'] = bool(fields)
    for field in fields:
        for key in ('title','description','placeholder'):
            if key in field:field[key]=ui.text(field[key],lang=selected)
        for option in field.get('options',[]):
            if option['value'] in ('today','stop','none','No other updates','No updates today'):option['label']=ui.text(option['label'],lang=selected)
    revision = '_'+str(job['preflight_revision']) if job.get('preflight_revision') else ''
    context['form'] = {'id':'preflight_'+job['id']+revision,
                       'title':ui.text('Let’s look back on today' if job['kind']=='gn' else 'Before your briefing',lang=selected),
                       'fields':fields} if fields else None
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
    if job['kind'] == 'gn' and 'details' in keys:
        chosen, details = value.get('completed', ['none']), value['details']
        known = {t['id']:t for t in context.get('feedback_tasks', context['daily']['tasks']) if not t['done']}
        if not isinstance(chosen,list) or not chosen or any(not isinstance(x,str) for x in chosen) or len(set(chosen)) != len(chosen):
            raise ValueError('Select completed tasks or choose “None of these today.”')
        if 'none' in chosen and chosen != ['none'] or set(chosen)-set(known)-{'none'}:
            raise ValueError('Choose listed tasks or “None of these today.”, not both')
        if not isinstance(details,str) or len(details)>1800:
            raise ValueError('Progress details exceed their limit')
        if not details.strip():
            raise ValueError('Give actual details or choose the no-updates option')
        details = one_line(details)
        complete = [] if chosen == ['none'] else chosen
        feedback = ['Completed: '+known[x]['text'] for x in complete] or (['No listed tasks were fully completed.'] if 'completed' in keys else [])
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
                    task_choices = [known[x] for x in complete if not known[x].get('custom')]
                    custom_choices = [known[x] for x in complete if known[x].get('custom')]
                    if task_choices:
                        inbox = InboxStore(runtime, write=True)
                        try:
                            # Preflight precedes agent-session creation. Audit the browser job itself.
                            TaskStore(inbox).complete_day(task_choices, job['date'],
                                'browser:' + job['id'], 'browser-feedback:' + job['id'], stamp(runtime), details)
                        finally:
                            inbox.close()
                    for entry in custom_choices:
                        from goodmorning.records.custom_store import CustomStore
                        custom_store = CustomStore(runtime, write=True)
                        try:
                            custom_store.report(entry['task_id'], entry['revision'],
                                {'status': 'done', 'confirmed_completion': True, 'detail': ''},
                                'browser:' + job['id'], 'browser-feedback:' + job['id'] + ':custom:' + entry['task_id'],
                                stamp(runtime), job['date'])
                        finally:
                            custom_store.close()
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
