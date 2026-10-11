"""Render synthetic native briefings without a model, network or personal data."""
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from goodmorning.briefings.briefing_document import encode


def render(kind, document):
    if kind in ('gm', 'gn'):
        return encode(document)
    template = (ROOT / 'templates' / f'{kind}.reply.template.md').read_text()
    return re.search(r'```markdown\n(.*?)\n```', template, re.S)[1].format_map(document).strip() + '\n'


def fixtures():
    report = {'date': '2026-10-08', 'timezone': 'UTC', 'country': 'US',
              'counts': {'ai': 1, 'major': 1, 'national': 1},
              'notes': ['World feed: stale cached response'],
              'stories': [{'date': '2026-10-08', 'section': section, 'title': title,
                           'summary': summary, 'outlets': 1,
                           'links': [{'source': 'Example', 'url': f'https://example.invalid/{section}'}]}
                          for section, title, summary in (
                              ('ai', 'AI research tool released', 'Researchers released a tool for reproducible AI research.'),
                              ('major', 'World research agreement announced', 'Research agencies announced a joint agreement.'),
                              ('national', 'National research funding announced', 'A national programme announced new research funding.'))]}
    report['stories'][0]['date_basis'] = 'submitted'
    report['stories'][0]['summary'] += ' This is a submission date, not publication.'
    agenda = ['agenda', [['2026-10-10', '10:00–11:00', 'Demo review', 'Room A', 'bring slides']]]
    news = [['news', label, [[story['title'], story['summary'], [['Example', story['links'][0]['url']]]]]]
            for story, label in zip(report['stories'], ['AI', 'World', 'National — US'])]
    morning = {'v': 1, 'greeting': 'Good morning, you', 'opening': 'Start with the outline.', 'sections': [
        ['weather', [['weather', [['temperature', '12–18°C', 'Weather STALE: last updated at 07:00 UTC; refresh failed.'],
                                  ['precipitation', None, "Rain likely. I'd keep the umbrella handy."],
                                  ['air', 'AQI 27', 'Good air.']]]], 'Light layers should be comfortable.'],
        ['news', news, 'World news coverage is incomplete (stale cached source).'],
        ['schedule', [['p', 'Timezone: UTC'], agenda]],
        ['must-do', [['tasks', [['open', 'Demo: draft outline', "High priority; estimate 30 minutes. I'd start with the main questions; we can polish the wording afterward."]]]]],
        ['nice-to-do', [['tasks', [['open', 'Demo: optional reading', 'About 20 minutes, if useful.']]]]],
        ['reminders', [['p', 'One idea needs clarification; revisit it at /gn.']]]],
        'closing': "If you'd like, we can start with the outline's main question. I'm happy to help you untangle that part."}
    night = {'v': 1, 'greeting': 'Good evening, you', 'opening': 'Tomorrow has a useful foundation.', 'sections': [
        ['today', [['p', 'Demo outline completed—a useful foundation for tomorrow’s review.']]],
        ['still-open', [['tasks', [['open', 'Demo: optional reading', 'Read one paper tomorrow if useful.']]]]],
        ['tomorrow', [['p', 'Timezone: UTC'], agenda]],
        ['reminders', [['p', 'One idea still needs clarification; we can pick it up at /gm.']]]],
        'closing': 'Good night, you—we can pick up the optional reading when it suits your plan.'}
    return report, morning, night


def experiment():
    _, morning, night = fixtures()
    print(json.dumps({kind: {'bytes': len(render(kind, doc).encode()), 'characters': len(render(kind, doc))}
                      for kind, doc in [('gm', morning), ('gn', night)]}))


if __name__ == '__main__':
    experiment()
