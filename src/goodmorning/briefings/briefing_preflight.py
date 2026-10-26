"""Browser-owned decisions and exact user feedback, before any model dispatch."""
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

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
    from goodmorning.calendar.calendar_ics import refresh
    feed = refresh(runtime, job['date'], job['kind'])
    context = prepare(runtime, job['kind'], job['date'], Path(runtime)/'cache', task_limit=200, website_language=selected,
                      replacement='replacement' in job)
    context['website_language']=selected
    if 'news' in context:
        # One cutoff per job, so its title and every country's read agree; a regeneration is a new job and collects afresh.
        context['news']['as_of'] = dt.datetime.fromtimestamp(job['created'], ZoneInfo(context['timezone'])).isoformat(timespec='seconds')
    if feed is not None:
        context['calendar_feed'] = feed
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
                                             'category': r['category'],
                                             **({'actual': True} if r.get('actual') else {}),
                                             **({'due_now': r['due_date']} if r.get('due_now') else {})} for r in rows]
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
                if job['kind'] == 'gn':
                    from goodmorning.records.routing import stale_tasks
                    context['tidy'] = stale_tasks(TaskStore(inbox), job['date'])
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
        # A stale task is asked about once, in the tidy-up, whose "I already did it" also completes it.
        tidied = {t['id'] for t in context.get('tidy', [])}
        open_tasks = [t for t in context.get('feedback_tasks', context['daily']['tasks']) if not t['done'] and t.get('task_id') not in tidied]
        # Split night checks: due-today vs longer-term early wins. Today comes
        # from planned occurrences (no synthetic flag); longer-term comes from
        # still-open morning tasks reported early (synthetic today flag).
        # Split night checks: due-today vs future early wins. Today holds planned
        # occurrences for the date plus overdue morning work; future holds
        # undated background and upcoming dated work. Labels are display-only
        # and never persisted in task records (size guard).
        morning_date_lists = {}
        try:
            from goodmorning.briefings.briefing_stream import bounded_json as _bounded
            from goodmorning.briefings.briefing_document import validate as _validate
            from pathlib import Path as _Path
            _morning = _Path(runtime) / 'daily' / (job['date'] + '.gm.json')
            if _morning.exists():
                _doc = _validate(_bounded(_morning, 150_000))
                for _section in _doc['sections']:
                    if _section[0] != 'tasks':
                        continue
                    for _block in _section[1]:
                        if _block[0] != 'actions':
                            continue
                        for _row in _block[1]:
                            # [id, revision, occurrence_id, date, status, title, detail]
                            if len(_row) >= 4:
                                morning_date_lists.setdefault(_row[0], set()).add(_row[3] or '')
        except Exception:
            morning_date_lists = {}
        for _tid, _dates in list(morning_date_lists.items()):
            _dates.discard('')
            morning_date_lists[_tid] = sorted(_dates)
        def _orig_dates(_task_id):
            return morning_date_lists.get(_task_id, [])
        today_tasks = []
        longterm_tasks = []
        for _t in open_tasks:
            if not _t.get('actual') or _t.get('due_now'):
                # Planned work and hard deadlines that have arrived are tonight's checks.
                _t['_section'] = 'today'
                today_tasks.append(_t)
                continue
            _dates = _orig_dates(_t['task_id'])
            _dated = [d for d in _dates if d]
            if _dated and min(_dated) < job['date']:
                # Overdue still-open work belongs with today, not future.
                _t['_section'] = 'today'
                today_tasks.append(_t)
            else:
                _t['_section'] = 'future'
                longterm_tasks.append(_t)
        _token = ui.CURRENT.set(selected)
        try:
            from goodmorning.web.language import day_text as _day_text
            # Dates travel as option descriptions so the check-in never parses titles.
            _notes = {}
            for _t in today_tasks:
                if _t.get('due_now'):
                    _notes[_t['id']] = ui.text('Due: {date}', date=_day_text(_t['due_now']), lang=selected)
                elif _t.get('actual'):
                    # Overdue: show original workday, not today.
                    _dates = [d for d in _orig_dates(_t['task_id']) if d]
                    if _dates:
                        _notes[_t['id']] = _day_text(min(_dates))
            for _t in longterm_tasks:
                _dates = [d for d in _orig_dates(_t['task_id']) if d]
                if _dates:
                    _notes[_t['id']] = ', '.join(_day_text(d) for d in _dates)
        finally:
            ui.CURRENT.reset(_token)
        # Keep project order stable, with unassigned work after every named project.
        today_tasks.sort(key=lambda t: not bool(t.get('project')))
        longterm_tasks.sort(key=lambda t: not bool(t.get('project')))
        # Drop display-only helpers before persisting task records (size guard).
        for _t in today_tasks + longterm_tasks:
            _t.pop('_label', None)
        if today_tasks or longterm_tasks:
            if today_tasks:
                fields.append(
                    {'key':'completed','title':'What did you finish today?','type':'multiselect','required':True,
                     'minItems':1,'description':'Tick anything you fully finished. If something is still in progress, leave it unticked—you can tell me about it below.',
                     'options':[{'value':'none','label':'None of these today.'}]+[
                         {'value':t['id'],'label':t['text'],'group':t.get('project') or ui.text('Other tasks',lang=selected),
                          **({'description':_notes[t['id']]} if t['id'] in _notes else {})} for t in today_tasks]})
            if longterm_tasks:
                fields.append(
                    {'key':'completed_longterm','title':'Future tasks (optional)','type':'multiselect','required':False,
                     'description':'Only tick if fully done early.',
                     'options':[
                         {'value':t['id'],'label':t['text'],'group':t.get('project') or ui.text('Other tasks',lang=selected),
                          **({'description':_notes[t['id']]} if t['id'] in _notes else {})} for t in longterm_tasks]})
            fields.extend(tidy_fields(context, job['date'], selected))
            fields.append(
                {'key':'details','title':'Anything else you’d like to share?','type':'string','required':True,
                 'custom':True,'customFirst':True,'placeholder':'Share any progress or updates…',
                 'options':[{'value':'No other updates','label':'Nothing else to add.'}],
                 'description':'Partial progress, something that got in the way, a change of plan, or extra work you got done.'})
        else:
            fields.extend(tidy_fields(context, job['date'], selected))
            fields.append({'key':'details','title':'How did today go?','type':'string','required':True,
                           'custom':True,'customFirst':True,'placeholder':'Share any progress or updates…',
                           'options':[{'value':'No updates today','label':'Nothing extra to add today.'}],
                           'description':'There aren’t any saved tasks to tick off for this review. You can still share what you worked on or any progress you made.'})
    context['awaiting'] = bool(fields)
    for field in fields:
        if field.get('tidy'):
            continue  # Already worded; its title is the task's own.
        for key in ('title','description','placeholder'):
            if key in field:
                field[key]=ui.text(field[key],lang=selected)
        for option in field.get('options',[]):
            if option['value'] in ('today','stop','none','No other updates','No updates today'):option['label']=ui.text(option['label'],lang=selected)
    revision = '_'+str(job['preflight_revision']) if job.get('preflight_revision') else ''
    context['form'] = {'id':'preflight_'+job['id']+revision,
                       'title':ui.text('Let’s look back on today' if job['kind']=='gn' else 'Before your briefing',lang=selected),
                       'fields':fields, **({'checkin':True} if job['kind']=='gn' else {})} if fields else None
    write(context_path(runtime, job['id']), context)
    return context


TIDY_NOTES = {'still-open': 'Planned for {date}', 'deadline': 'Was due {date}', 'other': 'Open since {date}'}


def tidy_fields(context, day, lang):
    """One optional choice per stale task; leaving it unanswered changes nothing."""
    token = ui.CURRENT.set(lang)
    try:
        hidden = ui.day_text((dt.date.fromisoformat(day) + dt.timedelta(days=7)).isoformat(), reference=day)
        choices = [('keep', 'Keep it on my list', ui.text('It stays as it is; I won’t ask about it again for a month.')),
                   ('snooze', 'Hide it for a week', ui.text('It’s off your morning list until {date}.', date=hidden)),
                   ('done', 'I already did it', ui.text('Marked as done today.')),
                   ('drop', 'Let it go', ui.text('Taken off your list. It’s kept in your history, not deleted.')),
                   ('later', 'Decide later', ui.text('Nothing changes for now.'))]
        return [{'key': 'tidy_' + item['id'], 'title': item['title'], 'type': 'string', 'required': False, 'tidy': True,
                 'description': ui.text(TIDY_NOTES[item['group']], date=ui.day_text(item['date'], reference=day)),
                 'options': [{'value': value, 'label': ui.text(label), 'description': hint} for value, label, hint in choices]}
                for item in context.get('tidy', [])]
    finally:
        ui.CURRENT.reset(token)


def answer(runtime, job, value):
    target = context_path(runtime, job['id'])
    context = bounded_json(target, 300_000)
    form_keys = {f['key'] for f in (context.get('form') or {}).get('fields', [])}
    # The optional future-tasks check may be omitted; treat it as empty.
    if isinstance(value, dict) and 'completed_longterm' in form_keys and 'completed_longterm' not in value:
        value = {**value, 'completed_longterm': []}
    tidy_keys = {'tidy_' + item['id'] for item in context.get('tidy', [])} & form_keys
    if isinstance(value, dict):
        value = {**{key: '' for key in tidy_keys}, **value}  # Unanswered tidy-up items stay as they are.
        if any(value[key] not in ('', 'keep', 'snooze', 'done', 'drop', 'later') for key in tidy_keys):
            raise ValueError('Choose one of the tidy-up answers or leave it blank.')
    if not context.get('awaiting'):
        if context.get('browser_answer') == value:
            return context
        raise ValueError('This browser decision is no longer pending')
    keys = form_keys
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError('Answer exactly the pending browser fields')
    if 'continue' in keys and value['continue'] not in ('today','stop'):
        raise ValueError('Invalid missed-edition choice')
    if value.get('continue') == 'stop':
        context.update(awaiting=False,cancelled=True,browser_answer=value)
        write(target, context)
        return context
    if job['kind'] == 'gn' and 'details' in keys:
        details = value['details']
        known = {t['id']:t for t in context.get('feedback_tasks', context['daily']['tasks']) if not t['done']}
        def _is_future(_t):
            if '_section' in _t:
                return _t['_section'] == 'future' and not _t.get('custom')
            return bool(_t.get('actual')) and not _t.get('custom')
        def _is_today(_t):
            if '_section' in _t:
                return _t['_section'] == 'today' and not _t.get('custom')
            return not _t.get('actual') and not _t.get('custom')
        known_today = {tid for tid, t in known.items() if _is_today(t)}
        known_longterm = {tid for tid, t in known.items() if _is_future(t)}
        known_custom = {tid for tid, t in known.items() if t.get('custom')}
        # Today check is required when present; future tasks are optional.
        # Older single-list answers may mix both sets in `completed`; split them.
        if 'completed' in keys:
            chosen = value.get('completed', ['none'])
            if not isinstance(chosen,list) or not chosen or any(not isinstance(x,str) for x in chosen) or len(set(chosen)) != len(chosen):
                raise ValueError('Select completed tasks or choose “None of these today.”')
            if 'none' in chosen and chosen != ['none']:
                raise ValueError('Choose listed tasks or “None of these today.”, not both')
            _mixed_long = [x for x in chosen if x in known_longterm]
            _chosen_today = [x for x in chosen if x != 'none' and x not in known_longterm]
            if set(_chosen_today)-known_today-{'none'}-known_custom:
                raise ValueError('Choose listed tasks or “None of these today.”, not both')
            chosen = _chosen_today if 'none' not in chosen else chosen
            if _mixed_long:
                # Fold legacy mixed selections into the optional future list.
                chosen_long_legacy = _mixed_long
            else:
                chosen_long_legacy = []
        else:
            chosen = []
            chosen_long_legacy = []
        if 'completed_longterm' in keys:
            chosen_long = value.get('completed_longterm', [])
            if not isinstance(chosen_long,list) or any(not isinstance(x,str) for x in chosen_long) or len(set(chosen_long)) != len(chosen_long):
                raise ValueError('Select future tasks or leave them unticked.')
            chosen_long = chosen_long + chosen_long_legacy
            if len(set(chosen_long)) != len(chosen_long):
                raise ValueError('Choose listed future tasks only, once each.')
            if set(chosen_long)-known_longterm or set(chosen_long) & set(chosen if chosen != ['none'] else []):
                raise ValueError('Choose listed future tasks only, once each.')
        else:
            chosen_long = chosen_long_legacy
        if not isinstance(details,str) or len(details)>1800:
            raise ValueError('Progress details exceed their limit')
        if not details.strip():
            raise ValueError('Give actual details or choose the no-updates option')
        details = one_line(details)
        progress = []
        # Only forms prepared before project progress notes were removed still ask them.
        for field in context['form']['fields']:
            if field['key'].startswith('progress_'):
                note = value[field['key']]
                if not isinstance(note, str) or len(note) > 600:
                    raise ValueError('Progress details exceed their limit')
                if note.strip():
                    progress.append('Progress on '+field['project']+': '+one_line(note))
        today_complete = [] if chosen == ['none'] else chosen
        complete = today_complete + chosen_long
        offered = [item for item in context.get('tidy', []) if 'tidy_' + item['id'] in keys]
        tidy = {item['id']: value['tidy_' + item['id']] for item in offered}
        finished = [known[x]['text'] for x in complete] + [item['title'] for item in offered if tidy[item['id']] == 'done']
        feedback = ['Completed: '+title for title in finished] or (['No listed tasks were fully completed.'] if 'completed' in keys or 'completed_longterm' in keys else [])
        feedback.extend(progress)
        hidden = (dt.date.fromisoformat(job['date']) + dt.timedelta(days=7)).isoformat()
        feedback.extend(('Hidden from the morning list until ' + hidden + ': ' if tidy[item['id']] == 'snooze' else 'Let go (cancelled): ')
                        + item['title'] for item in offered if tidy[item['id']] in ('snooze', 'drop'))
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
                    if offered:
                        inbox = InboxStore(runtime, write=True)
                        try:
                            TaskStore(inbox).tidy(offered, tidy, job['date'], 'browser:' + job['id'],
                                                  'browser-tidy:' + job['id'], stamp(runtime))
                        finally:
                            inbox.close()
                receipt = amend(runtime, job['date'], expected, amendment, locked=True)
            elif previous == value and current == context.get('feedback_result_sha256'):
                receipt = {'sha256':current}  # Previous atomic amendment committed before its receipt.
            else:
                raise ValueError('The daily plan changed; reconcile feedback before continuing')
        context['feedback'] = {'completed':finished,'details':details,'saved':True,
                               **({'progress':progress} if progress else {})}
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
