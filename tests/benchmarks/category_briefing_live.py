"""Paid live briefings over a synthetic week holding every item category.

Real models write a Wednesday morning and a Friday evening edition through the
real browser job helpers; weather/news providers are unavailable on purpose.
Checks: each edition shows its focus day only (plus deadlines and earlier open
work), the evening form asks the right questions, and the pages render on
desktop and mobile. Prose, tone and layout still need manual screenshot review.
"""
import argparse
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


def run(output, template, language, kind):
    zh = language == 'zh-CN'
    t = lambda en, cn: cn if zh else en
    name = 'wednesday-morning' if kind == 'gm' else 'friday-evening'
    folder = output / name
    folder.mkdir(mode=0o700)
    runtime = folder / 'account'
    source = folder / 'source'
    shutil.copytree(template, source)
    (source / 'opencode.json').write_text(json.dumps(trial_config(runtime)))
    for path in [p for p in source.rglob('*') if p.parent != source or p.is_dir()]:  # Like a deployed release: the agent cannot patch the code.
        path.chmod(path.stat().st_mode & ~0o222)
    seed(runtime, MONDAY, language)
    day = MONDAY + timedelta(days=2 if kind == 'gm' else 4)
    instant = datetime.combine(day, time(7, 30) if kind == 'gm' else time(20, 30), ZoneInfo(ZONE)).astimezone(timezone.utc)
    selected = for_language(language)
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
        tasks, schedule = rows(document, 'tasks'), rows(document, 'schedule')
        result['tasks'], result['schedule'] = tasks, schedule
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
            if title not in tasks:
                result['problems'].append('missing task: ' + title)
        for title in absent:
            if title in tasks:
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
        cases = [run(output, template, args.language, kind) for kind in ('gm', 'gn')]
        screenshots(output, cases)
        for result, *_ in cases:
            save(output / result['case'] / 'result.json', result)
        summary = [{k: r[k] for k in ('case', 'language', 'problems')} for r, *_ in cases]
        save(output / 'summary.json', summary)
        print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
