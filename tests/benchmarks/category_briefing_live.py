"""Paid live briefings over a synthetic week holding every item category.

Real models write a Wednesday morning and a Friday evening edition through the
real browser job helpers; weather/news providers are unavailable on purpose.
Checks: each edition shows its focus day only (plus deadlines and earlier open
work), the evening form asks the right questions, and the pages render on
desktop and mobile. Prose, tone and layout still need manual screenshot review.
"""
import argparse
import re
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
from benchmarks.briefing_tone_live import TRIAL_CLI, CheckpointBridge, trial_config, observe
from benchmarks.category_week import seed, ZONE
from benchmarks.task_tone_live import context, matrix_lock, save
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web.models import for_language

MONDAY = date(2026, 10, 5)  # A past week: completions are stamped with the real clock.


def rows(document, section):
    """Titles of action/event rows in one section of a saved edition."""
    titles = []
    for entry in document['sections']:
        if entry[0] == section:
            for block in entry[1]:
                if block[0] == 'actions':
                    titles += [row[5] for row in block[1]]
                elif block[0] == 'events':
                    titles += [row[4] for row in block[1]]
    return titles


def saved_titles(runtime, document):
    """Saved titles of the Tasks rows a page shows, so reworded page titles still identify their items."""
    from benchmarks.category_live import tasks as saved_tasks
    from goodmorning.records.custom_store import CustomStore
    titles = {r['id']: r['title'] for r in saved_tasks(runtime)[0]}
    habits = CustomStore(runtime, write=False)
    try:
        titles.update({rule['id']: rule['title'] for rule in habits.all()})
    finally:
        habits.close()
    return [titles.get(row[0], row[5]) for entry in document['sections'] if entry[0] == 'tasks'
            for block in entry[1] if block[0] == 'actions' for row in block[1]]


def legacy_checks(runtime, document, seeded, problems):
    """Older items with notes inside detail: the record stays as saved; the page shows only what the user needs."""
    from benchmarks.category_live import tasks as saved_tasks
    rows = {r['id']: r for r in saved_tasks(runtime)[0]}
    shown = {row[0]: row[6] for entry in document['sections'] if entry[0] == 'tasks'
             for block in entry[1] if block[0] == 'actions' for row in block[1]}
    notes = r'every morning|briefing|I check|cannot buy|Keep open|Reminder date|tomorrow|ib_|projects/|每天早上|早报|我会|没法|提醒日期|明天|部署后|ib_|projects/'
    for key, facts in (('legacy-desk', ('250',)), ('legacy-calibration', ()), ('legacy-helpdesk', ('4471',)),
                       ('legacy-confirm', ()), ('legacy-clean', None)):
        row, display = rows[seeded[key]], shown.get(seeded[key])
        if row['revision'] != 1:
            problems.append(f'{key}: the briefing rewrote the saved record')
        if display is None:
            problems.append(f'{key}: not shown')
        elif facts is None:
            if row['detail'] not in display:
                problems.append(f'{key}: clean detail changed on the page: {display}')
        else:
            if re.search(notes, display, re.I):
                problems.append(f'{key}: page still shows the secretary\'s notes: {display}')
            for fact in facts:
                if fact not in display:
                    problems.append(f'{key}: page dropped {fact}: {display}')


def run(output, template, language, kind, selected=None):
    zh = language == 'zh-CN'
    t = lambda en, cn: cn if zh else en
    name = 'wednesday-morning' if kind == 'gm' else 'friday-evening'
    folder = output / name
    folder.mkdir(mode=0o700)
    runtime = folder / 'account'
    source = folder / 'source'
    shutil.copytree(template, source)
    config = trial_config(runtime)
    rules = config['agents']['build']['permissions']
    rules[:] = [r for r in rules if r['action'] not in ('webfetch', 'websearch')]  # Errands need the web, as in production.
    (source / 'opencode.json').write_text(json.dumps(config))
    for path in [p for p in source.rglob('*') if p.parent != source or p.is_dir()]:  # Like a deployed release: the agent cannot patch the code.
        path.chmod(path.stat().st_mode & ~0o222)
    seeded = seed(runtime, MONDAY, language)
    day = MONDAY + timedelta(days=2 if kind == 'gm' else 4)
    instant = datetime.combine(day, time(7, 30) if kind == 'gm' else time(20, 30), ZoneInfo(ZONE)).astimezone(timezone.utc)
    selected = selected or for_language(language)
    bridge = CheckpointBridge(source, runtime, False, language)
    app = BrowserApp(runtime, bridge, now=lambda: instant, preflight=True)
    result = {'case': name, 'language': language, 'date': day.isoformat(), 'checks': [], 'problems': []}
    try:
        bridge.verify_scope()
        with context(language, selected):
            job = app.start(day.isoformat(), kind)['job']
        if kind == 'gn':
            with context(language, selected):
                form = app.status(job)['forms'][0]
            save(folder / 'form.json', form)
            labels = {o['label']: o['value'] for f in form['fields'] for o in f.get('options', []) if isinstance(o, dict)}
            keys = {f['key'] for f in form['fields']}
            pick = lambda title: next(v for label, v in labels.items() if label.startswith(title))
            answer = {'completed': [pick(t("Claim this week's GTA salary", '申领本周助教工资')),
                                    pick(t('Log the council tax student exemption', '登记市政税学生豁免'))],
                      'details': t('Bought nothing yet; the ointment is still on my list.', '软膏还没买，明天再去。')}
            if 'completed_longterm' in keys:
                answer['completed_longterm'] = []
            for field in form['fields']:
                if field['key'].startswith('progress_'):
                    answer[field['key']] = (t('Tried two deblurring kernels; the second looks better.', '试了两个去模糊卷积核，第二个效果更好。')
                                            if field['project'] == 'MRHarmon' else '')
            result['form_fields'] = sorted(keys)
            result['form_today'] = [o['label'] for f in form['fields'] if f['key'] == 'completed' for o in f['options']]
            result['form_future'] = [o['label'] for f in form['fields'] if f['key'] == 'completed_longterm' for o in f['options']]
            save(folder / 'answer.json', answer)
            with context(language, selected):
                app.reply(job, 'form', form['id'], {'answer': answer})
        status = observe(app, bridge, job, folder, 'original', language, selected)
        assert status['state'] == 'ready', 'Edition did not finish; inspect the preserved transcript'
        document = json.loads(app.source(day.isoformat(), kind).read_text())
        save(folder / 'document.json', document)
        tasks, schedule = saved_titles(runtime, document), rows(document, 'schedule')  # Page titles may be reworded; match items by ID.
        result['tasks'], result['schedule'] = tasks, schedule
        errands = {row[0]: row for entry in document['sections'] if entry[0] == 'tasks'
                   for block in entry[1] if block[0] == 'errands' for row in block[1]}
        result['errands'] = list(errands.values())
        wage, pi = seeded['wage'], seeded['pi']
        if kind == 'gm':
            chair_title = seeded['chair-errand']
            for title in (wage, pi, chair_title):
                if title not in errands or day.isoformat() not in errands[title][5]:
                    result['problems'].append('errand without a dated note for the next morning: ' + title)
            if wage in errands and not ('12.21' in errands[wage][3] and '12.71' in errands[wage][3]
                                        and any('gov.uk' in u for _, u in errands[wage][4])):
                result['problems'].append('rate change against last result not shown with old/new rate and GOV.UK: '
                                          + json.dumps(errands[wage], ensure_ascii=False))
            chair = errands.get(chair_title)
            heading = t('SIHOO M18 chair price (black, Amazon UK)', 'SIHOO M18 椅子价格（黑色，亚马逊英国）')
            if chair and chair[2] != heading:
                result['problems'].append('errand card heading is not the saved wording: ' + chair[2])
            if chair and not chair[3] and not re.search(r'£\s?\d', chair[5]):
                result['problems'].append('chair check hidden without a price read: ' + json.dumps(chair, ensure_ascii=False))
        elif errands:
            result['problems'].append('errands shown in the evening')
        shown = {row[0]: row for entry in document['sections'] if entry[0] == 'tasks'
                 for block in entry[1] if block[0] == 'actions' for row in block[1]}
        key, place = ('worded-wed', 'morning') if kind == 'gm' else ('worded-sat', 'evening')
        from benchmarks.category_live import tasks as saved_tasks
        saved = next(r for r in saved_tasks(runtime)[0] if r['id'] == seeded[key])['display']['zh' if zh else 'en'][place]
        if key in seeded and [saved['title'], saved['detail']] != [shown.get(seeded[key], [''] * 7)[5], shown.get(seeded[key], [''] * 7)[6]]:
            result['problems'].append(f'{key}: saved {place} wording not shown as saved: {shown.get(seeded[key])}')
        if kind == 'gm':
            legacy_checks(runtime, document, seeded, result['problems'])
            plants = next((row for entry in document['sections'] if entry[0] == 'tasks' for block in entry[1]
                           if block[0] == 'actions' for row in block[1] if t('plants', '植物') in row[5]), None)
            result['plants'] = plants
            if not plants or len(plants[6]) > 120 or any(w in plants[6] for w in (t('every morning', '每天早上'), t('briefing', '早报'))):
                result['problems'].append('narrating heads-up detail not trimmed: ' + json.dumps(plants, ensure_ascii=False))
        if kind == 'gm':
            expected_tasks = [t('Strength training', '力量训练'), t('Prepare the project-update presentation', '准备项目进展汇报'),
                              t('Calculate the new ranking before the rebalance', '调仓前计算新排名'), t('Bring gym clothes', '带运动衣服'),
                              t('Buy the ointment', '买软膏'), t('Log the council tax student exemption', '登记市政税学生豁免')]
            absent = [t('Remove hair', '脱毛'), t("Claim this week's GTA salary", '申领本周助教工资'),
                      t('Buy the hand warmer at Bailian ZX', '去百联ZX买暖娃'), t('Send the plates for sequencing', '取出菌板送测序'),
                      t('Rebuy protein powder', '回购蛋白粉')]
            expected_schedule = [t("Mum's birthday", '妈妈生日')]
        else:
            expected_tasks = [t('Remove hair', '脱毛')]
            absent = [t('Bring gym clothes', '带运动衣服'), t('Check the SIHOO M18 chair price', '看看 SIHOO M18 椅子的价格'),
                      t('Prepare the project-update presentation', '准备项目进展汇报'), t('Rebuy protein powder', '回购蛋白粉')]
            expected_schedule = [t('Archery class', '弓道课')]
            assert any(label.startswith(t('Log the council tax', '登记市政税')) for label in result['form_today']), 'Due deadline not checked tonight'
            assert not any(t('Bring gym clothes', '带运动衣服') in label for label in result['form_today'] + result['form_future']), 'Nudge asked at night'
            from benchmarks.category_live import tasks as saved_tasks
            ointment = next(r for r in saved_tasks(runtime)[0] if r['title'] == t('Buy the ointment', '买软膏'))
            if ointment['status'] in ('blocked', 'partial'):
                result['problems'].append('"will go tomorrow" saved as ' + ointment['status'])
        for title in expected_tasks:
            if not any(title.casefold() in shown.casefold() for shown in tasks):  # Fallback wording may add a verb.
                result['problems'].append('missing task: ' + title)
        for title in absent:
            if any(title.casefold() in shown.casefold() for shown in tasks):
                result['problems'].append('shown out of its day: ' + title)
        if schedule != expected_schedule:
            result['problems'].append(f'schedule {schedule} != {expected_schedule}')
        result['checks'].append('Edition saved; rows compared with the focus-day rules')
    except Exception as error:
        result['problems'].append(type(error).__name__ + ': ' + str(error)[:800])
    save(folder / 'result.json', result)
    return result, runtime, instant, kind


def screenshots(output, cases):
    from playwright.sync_api import sync_playwright
    from support import start_server, returning_viewer
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for result, runtime, instant, kind in cases:
            if not (runtime / 'daily' / (result['date'] + '.' + kind + '.json')).exists():
                continue
            (runtime / 'website-language.json').write_text(json.dumps({'language': result['language']}))
            returning_viewer(runtime)
            server = start_server(BrowserApp(runtime, None, preflight=True, now=lambda instant=instant: instant))
            try:
                for width, height, label in ((1440, 1000, 'desktop'), (390, 844, 'mobile')):
                    page = browser.new_page(viewport={'width': width, 'height': height})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/{kind}.html')
                    page.wait_for_timeout(800)
                    page.screenshot(path=str(output / f"{result['language']}-{result['case']}-{label}.png"), full_page=True)
                    if errors or page.evaluate('document.documentElement.scrollWidth > innerWidth'):
                        result['problems'].append(f'{label}: page errors {errors} or horizontal overflow')
                    page.close()
            finally:
                server.shutdown()
                server.server_close()
        browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--language', choices=('en', 'zh-CN'), required=True)
    from goodmorning.web.models import MODELS
    parser.add_argument('--model', choices=tuple(MODELS), help='Defaults to the production model for the language')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to('/tmp/opencode'):
        parser.error('Synthetic output must stay beneath /tmp/opencode')
    with matrix_lock(output):
        output.mkdir(mode=0o700)
        template = output / 'source'
        template.mkdir()
        for name in ('src', 'scripts', 'docs', 'templates', 'assets', 'skill-source'):
            shutil.copytree(ROOT / name, template / name, ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('AGENTS.md', 'AGENT-PROMPT-GUIDE.md', 'SERVER-USER-GUIDE.md', 'SERVER-DATA-GUIDE.md'):
            shutil.copyfile(ROOT / name, template / name)
        shutil.copyfile(ROOT / 'skill-source/goodmorning.md', template / 'goodmorning.md')
        (template / 'scripts/goodmorning.py').write_text(TRIAL_CLI)
        cases = [run(output, template, args.language, kind, args.model) for kind in ('gm', 'gn')]
        screenshots(output, cases)
        for result, *_ in cases:
            save(output / result['case'] / 'result.json', result)
        summary = [{k: r[k] for k in ('case', 'language', 'problems')} for r, *_ in cases]
        save(output / 'summary.json', summary)
        print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
