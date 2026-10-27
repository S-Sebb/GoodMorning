"""A synthetic week with every item category, modelled on real usage patterns.

`seed(runtime, monday)` fills a fresh runtime. Run directly to print what each
morning briefing, evening briefing and Schedule-tab day shows (no model calls):

    PY tests/benchmarks/category_week.py --output /tmp/opencode/DIR
"""
import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from goodmorning.records.inbox_store import InboxStore, initialize
from goodmorning.records.custom_store import CustomStore
from goodmorning.calendar.calendar_store import CalendarStore

ZONE = 'Europe/London'
PROFILE = ('city: London, GB\ntimezone: Europe/London\nnews_country: GB\n'
           'secretary_name: Nora\ncalendar_source: custom\n')


def seed(runtime, monday, language='en'):
    """One week from Monday. Titles follow the website language."""
    zh = language == 'zh-CN'
    t = lambda en, cn: cn if zh else en
    day = lambda n: (monday + timedelta(days=n)).isoformat()
    runtime = Path(runtime)
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    (runtime / 'profile.md').write_text(PROFILE)
    (runtime / 'browser-policy.json').write_text(json.dumps({k: False for k in (
        'calendar_sync', 'publisher_images', 'news_acknowledgement')}))
    initialize(runtime)
    zone = ZoneInfo(ZONE)
    stamp = datetime.combine(monday - timedelta(days=3), time(12), zone).isoformat()
    calendar = CalendarStore(str(runtime / 'calendar.sqlite'))
    try:
        def timed(subject, n, hour, hours=1, location=''):
            start = datetime.combine(monday + timedelta(days=n), time(hour), zone)
            calendar.add({'subject': subject, 'start': start.isoformat(), 'end': (start + timedelta(hours=hours)).isoformat(),
                          'timezone': ZONE, **({'location': location} if location else {})})
        timed(t('Reinforcement Learning Lab', '强化学习实验课'), 0, 10, 2, 'RSM G08')
        timed(t('Spatial Transcriptomics Discussion', '空间转录组讨论会'), 3, 14, 1, 'Teams')
        timed(t('Spatial Transcriptomics Discussion', '空间转录组讨论会'), 10, 14, 1, 'Teams')
        timed(t('Programming 2', '编程二'), 4, 9, 2, 'RSM G08')
        calendar.add({'subject': t("Mum's birthday", '妈妈生日'), 'start': day(2), 'end': day(3), 'all_day': True,
                      'timezone': ZONE, 'repeat': {'yearly': True, 'start': day(2)}})
        start = datetime.combine(monday + timedelta(days=1), time(16), zone)
        calendar.import_events('outlook', [{'external_id': 'catchup', 'subject': t('Imperial-QMUL catch-up', '帝国理工-伦敦玛丽女王大学例会'),
                                            'start': start.isoformat(), 'end': (start + timedelta(hours=1)).isoformat(), 'timezone': ZONE}])
    finally:
        calendar.close()
    habits = CustomStore(runtime, write=True)
    try:
        habit = habits.add({'title': t('Strength training', '力量训练'), 'timezone': ZONE, 'policy': {
            'base': 'interval_days', 'interval_days': 2, 'start': day(0), 'anchor': 'fixed',
            'miss_policy': 'chase', 'nightly': 'due_only'}}, 'ses_fixture', 'habit', stamp)['id']
    finally:
        habits.close()
    inbox = InboxStore(runtime, write=True)
    ids = {}
    try:
        def add(key, title, kind='todo', **fields):
            payload = {'kind': kind, 'raw': title}
            if kind == 'todo':
                payload['task'] = {'title': title, **fields}
            elif kind == 'event_proposal':
                payload['draft'] = {'title': title, **fields}
            receipt = inbox.mutate('add', payload, 'ses_fixture', 'seed-' + key, stamp)
            ids[key] = receipt.get('task_id') or receipt.get('draft_id') or receipt['id']
        weekly = lambda wd: {'timezone': ZONE, 'repeat': {'weekdays': [wd], 'start': day(0)}}
        add('salary', t("Claim this week's GTA salary", '申领本周助教工资'), **weekly(4))
        add('hair', t('Remove hair', '脱毛'), **weekly(5))
        add('prep', t('Prepare the project-update presentation', '准备项目进展汇报'), project='ST-Morph', timezone=ZONE,
            repeat={'event_subject': t('Spatial Transcriptomics Discussion', '空间转录组讨论会'), 'offset_days': -1, 'start': day(0)})
        add('cells', t('Pass the HL60 cells', '传代 HL60 细胞'), project='HL60 rescue', planned_date=day(1))
        add('ranking', t('Calculate the new ranking before the rebalance', '调仓前计算新排名'), project='YuKuant', planned_date=day(2))
        add('council', t('Log the council tax student exemption', '登记市政税学生豁免'), due_date=day(4))
        add('warmer', t('Buy the hand warmer at Bailian ZX', '去百联ZX买暖娃'), defer_until=day(3), due_date=day(8))
        add('ointment', t('Buy the ointment', '买软膏'), follow_up='until-done', defer_until=day(0))
        for n, step in enumerate((t('Fix weak blur and motion-blur correction', '修复模糊和运动模糊校正'),
                                  t('Improve scanner-difference harmonization', '改进扫描仪差异的协调'),
                                  t('Add external test cases', '增加外部测试样例'),
                                  t('Draft the paper outline', '起草论文大纲'))):
            add('mr%d' % n, step, project='MRHarmon', due_date='2026-12-31', due_soft=True)
        for n, step in enumerate((t('Diagnose the slide-CV vs spatial-CV gap', '诊断切片交叉验证与空间交叉验证的差距'),
                                  t('Audit each MIR step for explainability', '审查 MIR 每一步的可解释性'),
                                  t('Re-evaluate levels above 0.7 confidence', '重新评估置信度高于 0.7 的层级'))):
            add('st%d' % n, step, project='ST-Morph', optional=True)
        add('challenge', t('Investigate organising an ISBI or MICCAI challenge', '研究组织 ISBI 或 MICCAI 挑战赛'), project='ST-Morph')
        add('plate', t('Transform the plasmid and plate the bacteria', '质粒转化并铺板'), project='HL60 rescue')
        add('sequence', t('Send the plates for sequencing', '取出菌板送测序'), project='HL60 rescue', after=ids['plate'])
        add('pipette', t('Confirm the pipette reimbursement was approved', '确认移液枪报销审批是否完成'))
        inbox.mutate('add', {'kind': 'todo', 'raw': 'Check the chair price', 'task': {
                     'title': t('Check the SIHOO M18 chair price', '看看 SIHOO M18 椅子的价格'), 'kind': 'nudge'}},
                     'ses_fixture', 'seed-chair', stamp)
        # Items saved with page wording, as the chat now records them.
        both = lambda en, zh: {'en': en, 'zh': zh}
        ids['worded-wed'] = inbox.mutate('add', {'kind': 'todo', 'raw': 'Return the library books', 'task': {
            'title': t('Return the library books', '去图书馆还书'), 'detail': t('Three books, due at the main library.', '三本书，还到总馆。'),
            'planned_date': day(2), 'display': both(
                {'morning': {'title': 'Return the three library books', 'detail': 'They go back to the main library.'}, 'schedule': 'Library books'},
                {'morning': {'title': '把三本书还到图书馆', 'detail': '还到总馆。'}, 'schedule': '还书'})}}, 'ses_fixture', 'seed-worded-wed', stamp)['task_id']
        ids['worded-sat'] = inbox.mutate('add', {'kind': 'todo', 'raw': 'Bake the birthday cake', 'task': {
            'title': t('Bake the birthday cake', '烤生日蛋糕'), 'planned_date': day(5), 'display': both(
                {'morning': {'title': 'Bake the birthday cake', 'detail': ''},
                 'evening': {'title': 'Birthday cake baking', 'detail': 'Take the butter out of the fridge tonight.'}, 'schedule': 'Birthday cake'},
                {'morning': {'title': '烤生日蛋糕', 'detail': ''},
                 'evening': {'title': '烤生日蛋糕', 'detail': '今晚先把黄油从冰箱拿出来。'}, 'schedule': '生日蛋糕'})}}, 'ses_fixture', 'seed-worded-sat', stamp)['task_id']
        # Items saved the way older captures did: the secretary's notes inside detail. Morning polish moves them to extra.
        legacy = (
            ('legacy-desk', t('Check the Lumo standing desk price', '看看 Lumo 升降桌的价格'), {'kind': 'nudge'}, t(
                'I check this myself when generating the morning briefing and report the current price and change. Latest user-observed '
                'price £289 on 2026-10-03. You buy it yourself if it is below £250. Shows every morning until you tell me to stop. I cannot buy it for you.',
                '我会在生成早报时自己去查并报告现价和变化。用户最近看到的价格是 2026-10-03 的 £289。低于 £250 时你自己下单。每天早上都会显示，直到你让我停。我没法替你购买。')),
            ('legacy-calibration', t('Re-run the spectrometer calibration', '重新做光谱仪校准'), {'project': 'Optics'}, t(
                '2026-10-03: first run done, sample B too dilute. 2026-10-04: re-prepared sample B. Next: re-run the calibration with sample B. '
                'History in projects/Optics.md and entry ib_0123456789abcdef.',
                '2026-10-03：第一次跑完，B 样品太稀。2026-10-04：重新配了 B 样品。下一步：用 B 样品重新校准。历史见 projects/Optics.md 和记录 ib_0123456789abcdef。')),
            ('legacy-helpdesk', t('Call the IT helpdesk about the receipt upload error', '打电话给 IT 服务台处理报销上传报错'), {'planned_date': day(2)}, t(
                'Reminder date: 2026-10-07 (tomorrow). Call extension 4471 to fix the "username already exists" error when uploading receipts.',
                '提醒日期：2026-10-07（明天）。拨打分机 4471，处理上传报销附件时提示"用户名已存在"的问题。')),
            ('legacy-confirm', t('Fix the photo export crash', '修复照片导出崩溃'), {}, t(
                'Keep open until the user confirms the fix after deployment. Follow-up saved: test exporting a 50-photo album.',
                '部署后等用户确认修好再关闭。已保存的后续：测试导出 50 张照片的相册。')),
            ('legacy-clean', t('Review the venue contract', '审阅场地合同'), {}, t(
                'Waiting for the client to send the floor plans.', '在等客户发平面图。')),
        )
        for key, title, fields, detail in legacy:
            ids[key] = inbox.mutate('add', {'kind': 'todo', 'raw': title, 'task': {'title': title, 'detail': detail, **fields}},
                                    'ses_fixture', 'seed-' + key, stamp)['task_id']
        # A detail that narrates how the reminder works, as a live capture once saved it: morning polish trims it.
        inbox.mutate('add', {'kind': 'todo', 'raw': 'Remind me to water the plants', 'task': {
                     'title': t('Water the balcony plants', '给阳台的植物浇水'), 'kind': 'nudge', 'detail': t(
                         'I remind you about this myself when generating the morning briefing. The basil needs the most water. '
                         'Shows every morning until you tell me to turn it off. I cannot water them for you.',
                         '我会在生成早报时亲自提醒你这件事。罗勒最需要多浇水。每天早上都会显示，直到你让我关掉。我没法替你浇水。')}},
                     'ses_fixture', 'seed-plants', stamp)
        # Errands: the secretary looks these up itself. One always reports; one's condition is never met.
        for key, title, detail, extra in (
                ('wage', t('Look up the UK National Living Wage on GOV.UK', '在 GOV.UK 查一下英国国家生活工资'),
                 t('Tell me the hourly rate for workers aged 21 and over only if it changed since your last check, with the old and new rate.',
                   '只有21岁及以上的时薪和你上次查的不一样时才告诉我，写出旧的和新的标准。'),
                 ''),
                ('pi', t('Check the Raspberry Pi 5 8GB price on raspberrypi.com', '在 raspberrypi.com 查树莓派5 8GB的价格'),
                 t('Tell me only if it is under £5.', '只有低于5英镑时才告诉我。'), ''),
                ('chair-errand', t('Check the black SIHOO M18 chair price on Amazon UK', '查亚马逊英国黑色 SIHOO M18 椅子的价格'),
                 t('Tell me only when it is below £120.', '只在低于120英镑时告诉我。'), '')):
            task = {'title': title, 'kind': 'errand', 'detail': detail, **({'extra': extra} if extra else {})}
            if key == 'chair-errand':  # Saved with its card heading, as the chat now records errands.
                task['display'] = {'en': {'morning': {'title': 'SIHOO M18 chair price (black, Amazon UK)', 'detail': ''}, 'schedule': 'Chair price'},
                                   'zh': {'morning': {'title': 'SIHOO M18 椅子价格（黑色，亚马逊英国）', 'detail': ''}, 'schedule': '椅子价格'}}
            ids[key] = inbox.mutate('add', {'kind': 'todo', 'raw': title, 'task': task}, 'ses_fixture', 'seed-' + key, stamp)['task_id']
        inbox.mutate('add', {'kind': 'todo', 'raw': 'Bring gym clothes', 'task': {'title': t('Bring gym clothes', '带运动衣服'),
                     'kind': 'nudge', 'timezone': ZONE, 'when': {'custom_rule_id': habit}}}, 'ses_fixture', 'seed-clothes', stamp)
        inbox.mutate('add', {'kind': 'todo', 'raw': 'Rebuy protein', 'task': {'title': t('Rebuy protein powder', '回购蛋白粉'),
                     'kind': 'reference', 'trigger': t('Protein powder runs out', '蛋白粉吃完'),
                     'detail': 'Myprotein Impact Whey, vanilla'}}, 'ses_fixture', 'seed-protein', stamp)
        inbox.mutate('add', {'kind': 'idea', 'raw': t('Maybe an image-based briefing', '也许可以做图片版简报')},
                     'ses_fixture', 'seed-idea', stamp)
        inbox.mutate('add', {'kind': 'event_proposal', 'raw': 'Archery class', 'draft': {
            'title': t('Archery class', '弓道课'), 'date': day(5), 'timezone': ZONE, 'confirmed_day': True,
            'location': t('Hongqiao Sports Park', '虹桥体育公园'),
            'repeat': {'weekdays': [5], 'start': day(5), 'until': day(19)}}}, 'ses_fixture', 'seed-archery', stamp)
        # Monday's morning edition remembers the wage errand's result; Wednesday compares with it.
        (runtime / 'daily').mkdir(exist_ok=True)
        from goodmorning.briefings import briefing_document as native
        (runtime / 'daily' / (day(0) + '.gm.json')).write_text(native.encode({'v': 2, 'greeting': 'Hello.', 'opening': 'Synthetic.',
            'sections': [['tasks', [['errands', [[ids['wage'], 1, t('Look up the UK National Living Wage on GOV.UK', '在 GOV.UK 查一下英国国家生活工资'),
                                                  '', [], t(day(0) + ': £12.21 per hour on the GOV.UK rates page', day(0) + '：GOV.UK 费率页显示每小时 £12.21')]]]]]]}))
    finally:
        inbox.close()
    return {'habit': habit, **ids}


def audit(runtime, monday):
    from goodmorning.records import routing
    from goodmorning.records.inbox_store import InboxStore
    from goodmorning.records.task_store import TaskStore
    from goodmorning.web.schedule import saved_week
    lines = []
    week = saved_week(Path(runtime), ZONE, datetime.combine(monday, time(9), ZoneInfo(ZONE)).astimezone(timezone.utc), 0)
    for n in range(7):
        today = (monday + timedelta(days=n)).isoformat()
        lines.append('=' * 20 + ' ' + today + ' ' + (monday + timedelta(days=n)).strftime('%a'))
        for kind in ('gm', 'gn'):
            view = routing.prepare(runtime, today, kind, limit=200)
            lines.append(f'  [{kind}] schedule: ' + '; '.join(
                f"{i.get('date') or i.get('start', '')[:10]} {i.get('subject')}{' TBC' if i.get('draft') else ''}" for i in view['schedule']['items']))
            for row in view['tasks']['items']:
                lines.append(f"  [{kind}] task {row['group']:<10} {row['category']:<8} {row['date'] or '-':<10} {row['title']}")
            for row in view['tasks'].get('errands', []):
                lines.append(f"  [{kind}] errand    {row['title']}")
            for row in view['attention']['items']:
                lines.append(f"  [{kind}] reminder  {row['title']}")
        inbox = InboxStore(runtime)
        try:
            feedback = routing.feedback_day(TaskStore(inbox), today)
        finally:
            inbox.close()
        lines.append('  [gn] evening checks: ' + '; '.join(
            f"{r['title']}{' (due)' if r.get('due_now') else ' (optional)' if r.get('actual') else ''}" for r in feedback))
        tab = week['days'][n]
        lines.append('  [tab] events: ' + '; '.join(e.get('subject') or e.get('title') for e in tab['events']))
        lines.append('  [tab] to-dos: ' + '; '.join(t['text'] + (f" <{t['marker']}>" if t.get('marker') else '') for t in tab['tasks']))
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--monday', default='2026-10-19')
    args = parser.parse_args()
    monday = date.fromisoformat(args.monday)
    runtime = args.output / 'account'
    if runtime.exists():
        raise SystemExit('Use a new output directory')
    seed(runtime, monday)
    print(audit(runtime, monday))


if __name__ == '__main__':
    main()
