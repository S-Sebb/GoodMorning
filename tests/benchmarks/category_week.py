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
        'live_project_access', 'calendar_sync', 'publisher_images', 'news_acknowledgement')}))
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
        calendar.stage('outlook', [{'external_id': 'catchup', 'subject': t('Imperial-QMUL catch-up', '帝国理工-伦敦玛丽女王大学例会'),
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
