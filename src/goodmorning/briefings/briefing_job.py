"""Code-owned browser workflow context and incremental authoring commands."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import date as Date
import io
import json
import os
import re
from pathlib import Path
import shlex
import sqlite3
import sys

from . import briefing_document as native
from . import briefing_guides
from .briefing_stream import DEFAULT_PLANS, LEGACY_PLANS, bounded_json, load, paths, publish, require_final
from goodmorning.records import letters
from goodmorning.runtime_files import atomic_text, runtime_lock, secretary_path
from goodmorning.web import language as ui


def context_path(runtime, identifier):
    if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{32}', identifier):
        raise ValueError('Invalid job')
    directory = Path(runtime).expanduser().resolve() / 'browser-jobs'
    target = directory / (identifier + '.context.json')
    if directory.is_symlink() or target.is_symlink() or target.resolve() != target:
        raise ValueError('Unsafe browser context path')
    return target


def owned(runtime, identifier, session):
    directory, target, job = paths(runtime, identifier)
    if not session or session != job.get('session'):
        raise ValueError('This browser job belongs to a different session')
    if job['state'] == 'complete':
        raise ValueError('This browser job is complete; stop without fetching or rewriting it')
    context = bounded_json(context_path(runtime, identifier), 300_000)
    if (context['date'], context['workflow']) != (job['date'], job['kind']):
        raise ValueError('Browser context does not match its job')
    if context.get('awaiting'):
        raise ValueError('Browser feedback is still required')
    if context.get('cancelled'):
        raise ValueError('This browser job was cancelled; stop')
    return directory, target, job, context


def session_job(runtime, session):
    """Bind active browser actors even when a model omits the read recipe's flag."""
    registry = Path(runtime)/'browser-jobs/jobs.json'
    if not session or not registry.exists():
        return None
    jobs = bounded_json(registry, 2_000_000)
    identifiers = {job['id'] for job in jobs.values() if job.get('session') == session
                   and job.get('state') in ('starting','running','uncertain')
                   and context_path(runtime, job['id']).exists()
                   and bounded_json(context_path(runtime, job['id']), 300_000).get('document_version') == 2}
    if len(identifiers) > 1:
        raise ValueError('browser_job_ambiguous: inspect this actor\'s owning job before reading')
    return next(iter(identifiers), None)


def require_section(runtime, identifier, session, kind, date, section):
    _, target, job, context = owned(runtime, identifier, session)
    if (kind, date) != (job['kind'], job['date']) or not section:
        raise ValueError('browser_section_scope: use the owning job\'s edition, pinned date and explicit section')
    checkpoint = load(target)
    if not checkpoint:
        raise ValueError('browser_section_not_ready: initialize the preview before section reads')
    position = len(checkpoint['outcomes'])
    if position == len(checkpoint['plan']):
        raise ValueError('browser_sections_resolved: finish the job; no further section reads')
    expected = checkpoint['plan'][position][0]
    reconcile = kind == 'gn' and position == 0 and section == 'tasks' and not context.get('regenerating')
    if section != expected and not reconcile:
        raise ValueError(f'browser_section_not_ready: publish {expected} before reading {section}; this is not a provider failure')
    return context.get('website_language','en')


def default_plan(context):
    plan = deepcopy((DEFAULT_PLANS if context.get('document_version') == 2 else LEGACY_PLANS)[context['workflow']])
    selected=context.get('website_language','en')
    for item in plan:
        item[1]=ui.text(item[1],lang=selected)
        if item[0] == 'news':
            item[1] = ui.text('News — as of {time}', lang=selected, time=context['news']['as_of'][11:16])
    if context['workflow'] == 'gn' and context.get('document_version') == 2 and context.get('anime', {}).get('enabled'):
        plan.append(['anime', ui.text(native.TITLES['anime'], lang=selected)])
    if context['workflow'] == 'gn' and context.get('document_version') == 2 and context.get('games', {}).get('enabled'):
        plan.append(['games', ui.text(native.TITLES['games'], lang=selected)])
    if context['workflow'] == 'gn' and context.get('document_version') == 2 and context.get('stocks', {}).get('enabled'):
        plan.append(['stocks', ui.text(native.TITLES['stocks'], lang=selected)])
    if (context['workflow'] == 'gn' and context.get('document_version') == 2 and context.get('weekly_letter', {}).get('enabled')
            and Date.fromisoformat(context['date']).weekday() == 6):
        plan.append(['letter', ui.text(native.TITLES['letter'], lang=selected)])
    return plan


def next_step(runtime, identifier, session, context, checkpoint):
    """One compact recipe; no speculative flags or whole-briefing fetching."""
    command = ['python', 'scripts/goodmorning.py', 'job', '--secretary-dir', str(runtime), '--job', identifier, '--session', session]
    if not checkpoint:
        if context.get('document_version') == 2:
            return {'action':'init', 'command':shlex.join(command + ['init']), 'input':{'greeting':'…','opening':'…'}}
        instruction = 'Initialize now, before any provider or additional record reads. Use the supplied default plan unchanged; do not reorder, add or remove sections. Translate plan titles only if needed for the pinned language, preserving order.'
        if context.get('regenerating'):
            instruction += (' This is an explicitly authorized replacement, not a duplicate run. Reuse saved feedback and current records; '
                            'do not replay daily, inbox, project or calendar mutations, or renew earlier execution consent. '
                             'The final helper owns snapshot replacement; v2 never schedules tasks from it.')
        return {'action':'init', 'command':shlex.join(command + ['init']),
                'input':{'greeting':'…','opening':'…','plan':default_plan(context)},
                'instruction':instruction}
    position = len(checkpoint['outcomes'])
    if position == len(checkpoint['plan']):
        return {'action':'finish', 'command':shlex.join(command + ['finish']), 'input':{}}
    tag, title = checkpoint['plan'][position]
    reads = []
    selected = context['paths']
    if tag == 'weather':
        reads.append(shlex.join(['python','scripts/goodmorning.py','weather','--secretary-dir',str(runtime),
                                '--city',context['city'],'--cache-dir',selected['cache']]
                                + (['--day',context['tomorrow']] if context['workflow'] == 'gn' else [])))
    elif tag == 'news':
        for country in context['news']['countries']:
            read = ['python','scripts/goodmorning.py','news','--country',country,
                    '--timezone',context['timezone'],'--cache-dir',selected['cache'],
                    '--latest','--as-of',context['news']['as_of'],'--format','json','--view','sections']
            if context['news'].get('sources'):
                read += ['--sources',context['news']['sources']]
            reads.append(shlex.join(read))
    elif context.get('document_version', 1) == 1 and tag in ('schedule', 'tomorrow') and selected.get('calendar_db'):
        reads.append(shlex.join(['python','scripts/goodmorning.py','calendar','--secretary-dir',str(runtime),
            '--db',selected['calendar_db'],'--from',context['tomorrow'] if tag == 'tomorrow' else context['date'],
            '--days','1' if tag == 'tomorrow' else '3','--timezone',context['timezone'],'--json','--details']))
    elif tag == 'anime':
        reads.append(shlex.join(['python','scripts/goodmorning.py','anime','--secretary-dir',str(runtime),'--date',context['date'],
                                 '--timezone',context['timezone'],'--website-language',context.get('website_language','en'),
                                 '--cache-dir',selected['cache']]))
    elif tag in ('games', 'stocks'):
        reads.append(shlex.join(['python','scripts/goodmorning.py',tag,'--secretary-dir',str(runtime),'--date',context['date'],
                                 '--timezone',context['timezone'],'--website-language',context.get('website_language','en'),
                                 '--cache-dir',selected['cache']]))
    elif tag == 'letter':
        reads.append(shlex.join(['python','scripts/goodmorning.py','letter','--secretary-dir',str(runtime),'--week',letters.week_of(context['date']),
                                 '--website-language',context.get('website_language','en')]))
    elif context.get('document_version') == 2 and tag in ('schedule', 'tasks', 'attention', 'today'):
        read_command = ['python', 'scripts/goodmorning.py', 'task', '--secretary-dir', str(runtime),
                                '--briefing', context['workflow'], '--date', context['date'],
                                '--browser-job', identifier, '--session', session,
                                '--section', tag,
                                '--website-language', context.get('website_language', 'en')]
        reads.append(shlex.join(read_command))
        if tag == 'today' and not context.get('regenerating') and context.get('feedback',{}).get('details') not in ('No other updates','No updates today',None):
            candidates = read_command.copy()
            candidates[candidates.index('--section') + 1] = 'tasks'
            reads.insert(0, shlex.join(candidates))
    instruction = ('Use saved context first. Run only this section\'s read recipes and required pages/review, '
                   'then publish it before collecting any later section. Do not batch future sections\' reads.')
    if context.get('document_version', 1) == 1 and tag in ('schedule', 'tomorrow'):
        instruction += (' Legacy preview: review active inbox/project constraints; preserve flexible rows '
                        '[date,status,title,detail], TBC appointments and existing history; no automatic rollover. '
                        'No timed appointments does not mean a free day.')
    action = {'action':'publish','command':shlex.join(command + ['publish']), 'position':position,
              'section':[tag,title], 'read':reads}
    if tag == 'letter':
        action['input'] = ({'position':position} if letters.load(runtime, letters.week_of(context['date']))
                           else {'position':position, 'letter':{'opening':'…', 'signoff':'…'}})
    elif context.get('document_version') == 2:
        action['input'] = {'position':position, 'section':[tag,'BLOCKS','NOTE',title]}
    else:
        action['instruction'] = instruction
    return action


def activity_path(runtime, identifier):
    return context_path(runtime, identifier).with_name(identifier + '.activity.json')


def note(runtime, identifier, step, **values):
    """Record the step code is on, for the waiting page. Only code writes it, so it never overstates progress."""
    atomic_text(activity_path(runtime, identifier), json.dumps({'step':step, **values}, separators=(',',':')))


def weather_frame_path(runtime, identifier):
    return context_path(runtime, identifier).with_name(identifier + '.weather.json')


def save_weather_frame(runtime, identifier, command, results):
    """Keep the hourly frame (or the evening's card) the weather read used; publishing attaches it, so they never come from the model."""
    path = weather_frame_path(runtime, identifier)
    frame = None
    if results and results[0]['exit'] == 0:
        output = run_reads([command + ' --json'])[0]['output']
        frame = (output.get('outlook') or output.get('frame')) if isinstance(output, dict) else None
    if frame:
        atomic_text(path, json.dumps(frame, separators=(',', ':')))
    else:
        path.unlink(missing_ok=True)


def with_weather_frame(runtime, identifier, section):
    """The section as saved: its first weather block carries the read's frame, or code fills the evening's ["outlook"] card."""
    try:
        frame = json.loads(weather_frame_path(runtime, identifier).read_text())
    except (OSError, ValueError):
        return section
    blocks = section[1] if isinstance(section, list) and len(section) > 1 and isinstance(section[1], list) else []
    for index, block in enumerate(blocks):
        if block == ['outlook'] and isinstance(frame, list):
            section = deepcopy(section)
            section[1][index] = frame
            break
        if isinstance(block, list) and block[:1] == ['weather'] and len(block) == 2 and isinstance(frame, dict):
            section = deepcopy(section)
            section[1][index] = [*block, frame]
            break
    return section


def letter_section(runtime, job, context, payload):
    """The briefing's notice for this week's letter, saving the letter first so the notice never promises a missing one."""
    if set(payload) - {'position', 'letter'}:
        raise ValueError('Publish the weekly letter as {"position":N,"letter":{"opening":"…","signoff":"…"}}, or {"position":N} as its guide says')
    week = letters.week_of(job['date'])
    letter = letters.load(runtime, week)
    if letter is None:
        try:
            letters.facts(runtime, week, context.get('website_language', 'en'))
        except (ValueError, OSError, KeyError, sqlite3.Error):
            return ['letter', [['letter', week, None]]]  # Records could not be read: no letter this week.
        if 'letter' not in payload:
            raise ValueError('This week\'s records were read: write the letter as {"position":N,"letter":{"opening":"…","signoff":"…"}}')
        letter = letters.save(runtime, week, payload['letter'], context.get('website_language', 'en'))
    return ['letter', [['letter', week, letters.counts(letter)]]]


def read_count(runtime, job, tag, results):
    """Items the section's reads returned, when their shape says so plainly."""
    if tag in ('anime', 'games', 'stocks'):
        from importlib import import_module
        return len(import_module('goodmorning.' + tag).saved_rows(runtime, job['date']))
    outputs = [result['output'] for result in results if result['exit'] == 0 and isinstance(result['output'], dict)]
    if tag == 'news':
        stories = [len(value.get('selected', [])) for output in outputs
                   for value in output.get('sections', {}).values() if isinstance(value, dict)]
        return sum(stories) if stories else None
    if tag in ('schedule', 'tasks', 'attention', 'today') and outputs and isinstance(outputs[-1].get('total'), int):
        return outputs[-1]['total']
    return None


def run_reads(commands):
    """Run a section's read recipes for the agent, exactly as written, so each costs no model turn."""
    from goodmorning.cli import main as cli
    results = []
    for command in commands:
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            try:
                code = cli(shlex.split(command)[2:])
            except SystemExit as error:
                code = error.code if isinstance(error.code, int) else 1
        try:
            value = json.loads(output.getvalue())
        except ValueError:
            value = (output.getvalue().strip() or errors.getvalue().strip())[-4000:]
        results.append({'command':command, 'exit':code or 0, 'output':value})
    return results


def news_path(runtime, identifier):
    return context_path(runtime, identifier).with_name(identifier + '.news.json')


def shown_news(runtime, date):
    """Links the previous morning briefing showed; a rolling window would otherwise repeat them."""
    from goodmorning.news.news import canonical_url
    for source in sorted((Path(runtime)/'daily').glob('????-??-??.gm.json'), reverse=True):
        if source.name[:10] < date:
            try:
                document = native.validate(bounded_json(source, native.MAX_BYTES))
            except (ValueError, OSError):
                return set()  # An unreadable edition only allows repeats.
            return {canonical_url(url) for section in document['sections'] for block in section[1]
                    if block[0] == 'news' for row in block[2] for _, url in row[2]}
    return set()


def fresh_news(runtime, identifier, job, context, results):
    """Drop stories the previous morning showed, then record the categories left with picks for news_gaps."""
    from goodmorning.news.news import canonical_url
    shown, filled = shown_news(runtime, job['date']), set()
    for result, country in zip(results, context['news']['countries']):
        sections = result['output'].get('sections') if result['exit'] == 0 and isinstance(result['output'], dict) else None
        for name, value in (sections or {}).items():
            for key in ('selected', 'more'):
                value[key] = [story for story in value[key] if not shown & {canonical_url(link['url']) for link in story['links']}]
            if value['selected']:
                filled.add(country if name == 'national' else name)
    atomic_text(news_path(runtime, identifier), json.dumps(sorted(filled)))


def news_gaps(runtime, identifier, context, section):
    """Categories this job's news read filled but the section leaves out."""
    path = news_path(runtime, identifier)
    if not path.exists():
        return []
    filled = set(json.loads(path.read_text()))
    present = set()
    for block in section[1] if isinstance(section, list) and len(section) > 1 and isinstance(section[1], list) else []:
        if not (isinstance(block, list) and len(block) >= 3 and block[0] == 'news' and isinstance(block[1], str)):
            continue
        if len(block) > 3 and isinstance(block[3], str) and block[3]:
            present.add(block[3].upper())
        elif re.search(r'(?<![a-z])ai(?![a-z])|人工智能', block[1].casefold()):
            present.add('ai')
        else:
            present.add('major')
    return [name for name in ('ai', 'major', *context['news']['countries']) if name in filled and name not in present]


def image_previews(runtime, job, context, checkpoint):
    if context.get('integration_policy', {}).get('publisher_images') is not True:
        # No fetch without consent. Name the disabled state so a future
        # all-placeholder briefing is offered as a choice, never silent.
        urls = native.news_urls(checkpoint['document'])
        if not urls:
            return None
        return {'cached': 0, 'unavailable': len(urls), 'disabled': True,
                'next': 'Publisher previews are disabled by policy; keep honest placeholders and offer the choice separately.'}
    from .briefing_images import cache_previews
    from goodmorning.news.news_cache import feed_images
    urls = native.news_urls(checkpoint['document'])
    if not urls:
        return None
    try:
        hints = feed_images(context['paths']['cache'], urls) if context.get('paths', {}).get('cache') else {}
    except (ValueError, sqlite3.Error):
        hints = {}  # The archive only adds a fallback; previews still work without it.
    try:
        entries = cache_previews(urls, Path(runtime)/'browser-images'/job['date'], Path(runtime)/'browser-images/objects', hints)
        return {'cached':sum(entry['status'] == 'cached' for entry in entries.values()),
                'unavailable':sum(entry['status'] == 'unavailable' for entry in entries.values())}
    except (ValueError, OSError, ImportError, sqlite3.Error):
        return {'unavailable':True, 'next':'Keep honest placeholders; preserve the image cache and inspect it separately.'}


def read_rows(runtime, job, tag, section):
    """Episode, deal and holding rows are code-owned: each must be a row their read returned, unchanged."""
    if tag == 'anime':
        from goodmorning.anime import saved_rows
        kind, label = 'episodes', 'Episode'
    elif tag == 'games':
        from goodmorning.games import saved_rows
        kind, label = 'deals', 'Deal'
    else:
        from goodmorning.stocks import saved_block, saved_rows
        kind, label = 'holdings', 'Holding'
    returned = saved_rows(runtime, job['date'])
    for value in section[1] if len(section) > 1 and isinstance(section[1], list) else []:
        if isinstance(value, list) and value[:1] == [kind] and len(value) > 1 and isinstance(value[1], list):
            if any(row not in returned for row in value[1]):
                raise ValueError(f'{label} rows must be copied unchanged from the {tag} read; copy its block and publish again')
            # Closed-market facts and the market overview travel after the rows and must survive the copy too.
            if tag == 'stocks' and value[2:] != (saved_block(runtime, job['date']) or [])[2:]:
                raise ValueError('Copy the stocks block whole, including the closed-market and market overview items after its rows, and publish again')


def cover_previews(runtime, job, checkpoint):
    """Turning the section on asked for covers, so they are cached like publisher previews."""
    from .briefing_images import cache_previews
    urls = native.cover_urls(checkpoint['document'])
    if not urls:
        return None
    try:
        entries = cache_previews(urls, Path(runtime)/'browser-images'/job['date'], Path(runtime)/'browser-images/objects', direct=True)
    except (ValueError, OSError, ImportError, sqlite3.Error):
        return {'unavailable': True}
    return {'cached': sum(entry['status'] == 'cached' for entry in entries.values()),
            'unavailable': sum(entry['status'] == 'unavailable' for entry in entries.values())}


def writing_rule(context, next_action):
    """Compact, localized source-meaning reminders at the point of authoring."""
    chinese = context.get('website_language') == 'zh-CN'
    action = next_action['action']
    tag = next_action.get('section', [''])[0]
    if action == 'init':
        return ('开场只说明即将回顾的内容，不要在获取数据前说已经整理完毕。' if chinese else
                'Opening describes what will be reviewed; do not claim collection is already complete.')
    if action == 'finish':
        return ('结尾可省略；没有待办、完成记录或实际反馈可回顾时，不写结尾。否则只回应已核实的结果。空日程只能说明没有已保存的约定，不能说“日程清空”、日子清闲、可以随意安排或时间充裕。不要承诺来源恢复后自动更新，不推断空闲、就绪或未来完成。' if chinese else
                'Closing is optional; omit it when there are no tasks, completions or actual feedback to reflect. Otherwise use verified results only. An empty calendar means no saved appointments, not a clear schedule, quiet/free day or time to spare. Do not promise automatic updates after recovery, readiness or future completion.')
    if tag == 'tasks':
        return ('动作行的日期是约定工作日，不是截止日期；只有明确的 due_date/due_at 才是期限。不要建议把明天的工作提前到今天。open 仅表示尚未完成，不能据此说已就绪或没有阻碍；也不能保证一个阻碍消失后即可完成。不要猜测哪项更轻松或需要多久。已确认的受阻原因保持原意，不得改写成“暂未推进”或“没有进展”；措辞整理不得改变其原意。' if chinese else
                'Action-row dates are agreed workdays, not deadlines; only explicit due_date/due_at establish a deadline. Do not suggest moving tomorrow\'s work into today. Open means unfinished; it does not establish readiness or absence of blockers. Resolving one blocker does not guarantee readiness/completion. Do not invent comparative ease or duration. A confirmed blocker reason keeps its exact meaning: never reword it as no progress, and any wording polish must preserve that meaning; blocked does not mean no progress.')
    if tag == 'today':
        return ('只回顾该报告日明确反馈的结果。报告受阻不等于完全没做过工作；不要增加明天的建议，也不要断言数据到位后即可推进或完成。' if chinese else
                'Report only outcomes explicitly supplied for the reporting day. A blocker does not prove no work was done. Do not add tomorrow\'s advice or assert readiness/completion after a dependency arrives.')
    if tag == 'schedule':
        if context.get('workflow') == 'gm':
            return ('复制返回的代码生成块；晨间日程覆盖今天，以及读取结果中返回的更晚日期卡片（用户要求提前提醒的事项，称为“即将到来”）；不要自行加入其他未来约定；空日程使用返回的今日段落，不自行改写日期、星期或扩大范围。没有已保存的约定不能证明空闲、没有准备工作或没有冲突。用保存的语气加一句简短注记，用通俗说法总结当天（空：仅说明当天没有已保存的约定，不说空闲；非空：数量和最早时间加最有用的准备），不要出现窗口、三天一览、TBC、timed 焦点、代码块等内部说法，不要重复每张卡片。' if chinese else
                    'Copy returned code-owned blocks. The morning schedule covers today plus any later cards the read returns (advance notices the user asked for; call them coming up); do not add other upcoming appointments. Use the returned empty-schedule paragraph without recalculating dates/weekdays or widening the range. No saved appointments does not establish free time, absence of preparation or absence of conflicts. Add a short note in the saved tone summarizing the day in plain words (empty: no appointments saved; non-empty: count and earliest time plus most useful preparation); do not mention windows, glances, TBC, timed focus, or code blocks; do not repeat every card.')
        return ('复制返回的代码生成块；晚间日程覆盖明天，以及读取结果中返回的更晚日期卡片（用户要求提前提醒的事项，称为“即将到来”）；不要自行加入其他更远日期的约定；空日程使用返回的明日段落，不自行改写日期、星期或扩大范围。没有已保存的约定不能证明空闲、没有准备工作或没有冲突。用保存的语气加一句简短注记，用通俗说法总结当天（空：仅说明当天没有已保存的约定，不说空闲；非空：数量和最早时间加最有用的准备），不要出现窗口、三天一览、TBC、timed 焦点、代码块等内部说法，不要重复每张卡片。' if chinese else
                'Copy returned code-owned blocks. The evening schedule covers tomorrow plus any later cards the read returns (advance notices the user asked for; call them coming up); do not add other later appointments. Use the returned empty-schedule paragraph without recalculating dates/weekdays or widening the range. No saved appointments does not establish free time, absence of preparation or absence of conflicts. Add a short note in the saved tone summarizing the day in plain words (empty: no appointments saved; non-empty: count and earliest time plus most useful preparation); do not mention windows, glances, TBC, timed focus, or code blocks; do not repeat every card.')
    if tag == 'letter':
        return ('开头和结尾只能提到读取结果里有的事：完成的事项、习惯、灵感和下周的安排。不要提到没完成的事、中断的习惯或空着的部分；不要编造进展、感受、空闲时间或精力，也不要承诺之后会做什么。' if chinese else
                'The opening and sign-off may mention only what the read returned: finished items, habits, ideas and next week\'s plans. Never mention unfinished work, broken or missing streaks or empty parts; never invent progress, feelings, free time or energy, or promise anything later.')
    if tag == 'stocks':
        return ('只写读取结果里有的股票和涨跌；不预测走势、不给买卖建议，也不承诺之后提醒。' if chinese else
                'Mention only stocks and moves the read returned. No forecasts, no buy or sell advice, no promise of later alerts.')
    if tag == 'games':
        return ('只写读取结果里有的游戏和价格；不评价游戏、不猜之后会不会更便宜，也不劝买或承诺之后提醒。' if chinese else
                'Mention only games and prices the read returned. No reviews, no guessing whether prices will drop further, no urging to buy, no promise of later reminders.')
    if tag == 'anime':
        return ('只写读取结果里有的剧集；不剧透、不猜剧情、不说在哪里看，也不承诺之后补上或提醒。' if chinese else
                'Mention only episodes the read returned. No spoilers or guessed plot, no where-to-watch, no promise of later updates or reminders.')
    if tag in ('weather','news'):
        return ('来源不可用时，只说明本次无法获取相应日期的数据，不补写预测或报道，也不推断没有新闻、预警或风险。没有安排自动重试或后续更新；不能说“恢复后我再整理”“稍后补上”。只说明当前失败，不编造失败原因或恢复入口。' if chinese else
                'If the source is unavailable, report only that this edition could not obtain the requested dated data. Do not invent forecasts/stories or infer no news, warnings or risks. No automatic retry or later update is scheduled; do not promise to fill it in after recovery. Do not invent a failure cause or recovery route.')
    return None


def act(runtime, identifier, session, action, payload=None):
    directory, target, job, context = owned(runtime, identifier, session)
    with runtime_lock(directory, identifier + '.workflow.lock'):
        directory, target, job, context = owned(runtime, identifier, session)
        checkpoint = load(target)
        if 'replacement' in job:
            from .briefing_replacement import check
            check(runtime, job, checkpoint['document'] if checkpoint else None)
        if not checkpoint and 'replacement' not in job and native.source_path(runtime, job['date'], job['kind']).exists():
            raise ValueError('A saved edition already exists; stop and inspect its owning run, without fetching or rewriting')
        reply_context = {'language':context.get('website_language','en'),
                         'tone':context.get('profile',{}).get('secretary_tone') or 'warm and helpful'}
        if context.get('profile',{}).get('user_name'):
            reply_context['user_name'] = context['profile']['user_name']
        reply_context['instruction'] = ('所有可见文字，包括进度和提问，均用简体中文并遵循保存的语气；不要描述读取契约或检查格式。' if reply_context['language'] == 'zh-CN' else
                                        'All visible text, including progress and questions, uses English and the saved tone; do not narrate reading contracts or format checks.')
        def receipt(value):
            checkpoint = load(target)
            next_action = next_step(runtime, identifier, session, context, checkpoint)
            if context.get('document_version') == 2:
                next_action['guide'] = briefing_guides.guide(context, next_action, checkpoint['plan'] if checkpoint else default_plan(context),
                                                             runtime=runtime, job=identifier, session=session)
                position, tag = next_action.get('position'), next_action.get('section', [None])[0]
                if next_action.get('read'):
                    reads, next_action['results'] = next_action.pop('read'), []
                    for done, command in enumerate(reads):
                        note(runtime, identifier, 'collect', position=position, section=tag, done=done, total=len(reads))
                        next_action['results'] += run_reads([command])
                    if tag == 'weather':
                        save_weather_frame(runtime, identifier, reads[0], next_action['results'])
                    if tag == 'news':
                        fresh_news(runtime, identifier, job, context, next_action['results'])
                if next_action['action'] == 'publish':
                    note(runtime, identifier, 'write', position=position, section=tag,
                         count=read_count(runtime, job, tag, next_action.get('results', [])))
                else:
                    note(runtime, identifier, 'opening' if next_action['action'] == 'init' else 'closing')
            rule = writing_rule(context, next_action)
            if rule:
                next_action['writing'] = rule
            return {**value, 'reply_context':reply_context, 'next':next_action}
        if action == 'prepare':
            # Preparation is saved once by the server, not reread by the agent.
            prepared = {k:v for k,v in context.items() if k not in ('form','browser_answer','awaiting')}
            if context.get('feedback'):
                prepared['feedback'] = {**context['feedback'], 'date':context['date']}
                prepared['feedback_task_scope'] = 'feedback_tasks are completion choices only, not all attribution candidates. Reports may concern future or undated actions; read the permitted Tasks lookup before offering named report choices.'
            if context.get('document_version') == 2:
                # Sources are reread per section. Do not invite reuse of stale/legacy plans.
                prepared.pop('items', None)
                prepared['daily'] = {k:v for k,v in context['daily'].items() if k not in ('tasks','tasks_total','next_offset')}
                prepared['inbox'] = {'total': context.get('inbox', {}).get('total', 0)}
                if job['kind'] == 'gm':
                    prepared.pop('feedback_tasks', None)
            if context.get('document_version') == 2:
                prepared['contract'] = briefing_guides.contract(context)
            return receipt({**prepared, 'job': identifier, 'session': session,
                    'next_position': len(checkpoint['outcomes']) if checkpoint else 0})
        if action == 'init':
            if not isinstance(payload, dict) or not {'greeting','opening'} <= payload.keys() or set(payload) - {'greeting', 'opening', 'lang', 'plan'}:
                raise ValueError('Initialize with greeting, opening, optional lang and plan')
            selected=context.get('website_language','en')
            if 'lang' in payload and payload['lang']!=selected:raise ValueError('Use this job’s pinned website language')
            document = {'v': context.get('document_version', 1), 'greeting': payload['greeting'], 'opening': payload['opening'], 'sections': [],'lang':selected}
            expected = default_plan(context)
            if context.get('document_version') == 2 and checkpoint is None:
                if 'plan' in payload and payload['plan'] != expected:
                    raise ValueError('Briefing plan order is fixed; use the default plan unchanged (gm Weather, News, Schedule, Tasks, Reminders; gn Today, Weather tomorrow, Schedule, Tasks, Reminders, then New episodes, Game sales and Stocks when on, and the Weekly letter on Sundays)')
                plan = expected
            else:
                plan = payload.get('plan', expected)
            if checkpoint:
                if checkpoint['plan'] != plan or {k:v for k,v in checkpoint['document'].items() if k not in ('sections','closing')} != {k:v for k,v in document.items() if k != 'sections'}:
                    raise ValueError('An existing preview cannot be reinitialized differently')
                return receipt({'resolved':len(checkpoint['outcomes']), 'planned':len(plan), 'saved':False})
            return receipt(publish(runtime, identifier, document, plan))
        if not checkpoint:
            raise ValueError('Initialize the preview first')
        document = deepcopy(checkpoint['document'])
        position = len(checkpoint['outcomes'])
        if action in ('publish', 'skip'):
            if (action == 'publish' and isinstance(payload, dict) and type(payload.get('position')) is int
                    and 0 <= payload['position'] <= min(position, len(checkpoint['plan']) - 1) and checkpoint['plan'][payload['position']][0] == 'letter'):
                payload = {'position':payload['position'], 'section':letter_section(runtime, job, context, payload)}
            if not isinstance(payload, dict) or set(payload) != ({'position','section'} if action == 'publish' else {'position'}):
                raise ValueError('Supply the section position and, for publish, one section')
            requested = payload['position']
            if type(requested) is not int or requested < 0:
                raise ValueError('Invalid section position')
            section = payload.get('section')
            if isinstance(section, list) and section[:1] == ['news'] and 2 <= len(section) < 4 and requested < len(checkpoint['plan']):
                # An omitted news title renders as yesterday's date for older editions, so new ones keep their as-of title.
                payload['section'] = section + [''] * (3 - len(section)) + [checkpoint['plan'][requested][1]]
            if requested < position:
                outcome = checkpoint['outcomes'][requested]
                sections = iter(document['sections'])
                previous = [next(sections) if value == 'ready' else None for value in checkpoint['outcomes']]
                if (action == 'skip' and outcome == 'skipped') or (action == 'publish' and outcome == 'ready' and previous[requested] in (
                        payload['section'], with_weather_frame(runtime, identifier, payload['section']))):
                    return receipt({'resolved':position,'planned':len(checkpoint['plan']),'saved':False,'reused':True})
                raise ValueError('Published sections cannot change')
            if requested != position or position == len(checkpoint['plan']):
                raise ValueError('Publish only the next unresolved section')
            if action == 'skip':
                if checkpoint['plan'][position][0] in ('weather','news','schedule','today','tomorrow','anime','games','stocks','letter'):
                    raise ValueError('Publish material unavailability; do not skip a required section')
                return receipt(publish(runtime, identifier, skip=True, position=position))
            if checkpoint['plan'][position][0] == 'news' and isinstance(payload['section'], list) and payload['section'][:1] == ['news']:
                missing = news_gaps(runtime, identifier, context, payload['section'])
                if missing:
                    labels = ', '.join({'ai':'AI', 'major':'World'}.get(name, 'National ' + name) for name in missing)
                    raise ValueError('News leaves out ' + labels + ', which the news read filled. Add one news block for each '
                                     '(a national block ends with its country code), using the read\'s selected or more stories; '
                                     'then publish again.')
            if checkpoint['plan'][position][0] in ('anime', 'games', 'stocks') and isinstance(payload['section'], list):
                read_rows(runtime, job, checkpoint['plan'][position][0], payload['section'])
            section = payload['section']
            if checkpoint['plan'][position][0] == 'weather':
                section = with_weather_frame(runtime, identifier, section)
            document['sections'].append(section)
            result = publish(runtime, identifier, document, position=position)
            pictures = (native.news_urls(document) if payload['section'][0] == 'news' and context.get('integration_policy', {}).get('publisher_images') is True
                        else native.cover_urls(document) if payload['section'][0] in ('anime', 'games') else [])
            if pictures:
                note(runtime, identifier, 'images', position=position + 1, total=len(pictures),
                     pictures='stories' if payload['section'][0] == 'news' else 'covers')
            if payload['section'][0] == 'news':
                images = image_previews(runtime, job, context, load(target))
                if images is not None:
                    result['images'] = images
            if payload['section'][0] in ('anime', 'games'):
                covers = cover_previews(runtime, job, load(target))
                if covers is not None:
                    result['images'] = covers
            return receipt(result)
        if action == 'finish':
            if not isinstance(payload, dict) or set(payload) - {'closing'}:
                raise ValueError('Finish accepts only an optional closing')
            if 'closing' in payload:
                document['closing'] = payload['closing']
            note(runtime, identifier, 'save')
            source = native.source_path(runtime, job['date'], job['kind'])
            if source.exists() and 'replacement' not in job:
                if native.parse(source.read_text()) != document:
                    raise ValueError('An existing saved edition does not match this job; preserve it')
            else:
                # An interrupted replacement may already have committed this exact document.
                try:
                    matches = source.exists() and native.parse(source.read_text()) == document
                except (ValueError, UnicodeError):
                    matches = False
                if not matches:
                    publish(runtime, identifier, document, position=position)
            require_final(runtime, identifier, job['date'], job['kind'], session, document)
            # Code assembles the cumulative draft; the model never re-emits its prefix.
            draft = directory / (identifier + '.draft.json')
            atomic_text(draft, native.encode(document))
            from goodmorning.records.state import main as save
            output = io.StringIO()
            with redirect_stdout(output):
                code = save(['--secretary-dir',str(runtime),'--today',job['date'],'--mark-'+job['kind'],
                             '--session',session,'--browser-job',identifier,
                             '--answer-file',str(draft),'--json'])
            if code:
                raise ValueError('Final save was not confirmed: '+output.getvalue().strip())
            draft.unlink()  # Only this confirmed job's temporary cumulative input.
            weather_frame_path(runtime, identifier).unlink(missing_ok=True)
            return {'saved':True,'date':job['date'],'kind':job['kind'],
                    'url':f"/d/{job['date']}/{job['kind']}.html",
                    'reply_context':reply_context,
                    'next':('保存已经核实，正文已在网页中。现在只交付链接：用保存的语气写简短的交付标签并附上这个相对链接。'
                            '不要再回顾任务、完成情况、受阻事项、日程或服务失败，不追加邀请。不要查找主机、继续读取、改写记录或确认新闻。'
                            if reply_context['language'] == 'zh-CN' else
                            'Save is verified; the page already contains the briefing. Hand over the relative link with a brief delivery label in the saved tone. '
                            'Do not repeat tasks, completions, blockers, schedules or provider failures, or append an invitation. '
                            'No host lookup, further reads, record rewriting or news acknowledgement.')}
        raise ValueError('Unknown browser workflow action')


def decode_input(raw):
    def pairs(entries):
        value = {}
        for key, item in entries:
            if key in value:
                raise ValueError('Duplicate JSON object key; serialize one object with json.dumps')
            value[key] = item
        return value
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: native.fail('input','non-finite numbers are not allowed'))
    except json.JSONDecodeError as error:
        raise ValueError(f'Invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}. Serialize with json.dumps; do not hand-escape text.') from None
    except (UnicodeError, RecursionError):
        raise ValueError('Input must be bounded UTF-8 JSON') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secretary-dir')
    parser.add_argument('--job', required=True)
    parser.add_argument('--session', default=os.environ.get('OPENCODE_SESSION_ID'))
    parser.add_argument('action', choices=('prepare','init','publish','skip','finish'))
    args = parser.parse_args()
    try:
        payload = None
        if args.action != 'prepare':
            raw = sys.stdin.buffer.read(native.MAX_BYTES + 1)
            if len(raw) > native.MAX_BYTES:
                raise ValueError('Authoring input exceeds its size limit')
            payload = decode_input(raw)
        print(json.dumps(act(secretary_path(args.secretary_dir), args.job, args.session, args.action, payload), ensure_ascii=False, separators=(',',':')))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'error':'browser_workflow_unavailable','next':str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
