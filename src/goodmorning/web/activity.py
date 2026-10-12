"""Minimal activity metadata, without transcripts, mutations or inferred completion."""
import html
import json
from goodmorning.briefings.briefing_stream import bounded_json
from goodmorning.briefings.briefing_job import context_path


ACTIVITY_PATH = r'/api/activity/(chat|job)/([a-f0-9]{32})'


def snapshot(app, kind, identifier):
    item = app.chats.get(identifier) if kind == 'chat' else app.job(identifier)
    mode = item['mode'] if kind == 'chat' else item['kind']
    def summary(state):
        return {'mode': mode, 'state': state, **({'date': item['date']} if kind == 'job' else {})}
    if item['state'] == 'complete':
        return summary('idle')
    if kind == 'job' and not item.get('session'):
        path = context_path(app.runtime, identifier)
        context = bounded_json(path, 300_000) if path.exists() else {}
        state = 'idle' if context.get('cancelled') else 'waiting' if context.get('awaiting') else 'working'
        return summary(state)
    if item['state'] == 'uncertain':
        return summary('uncertain')
    if not item.get('session'):
        return summary('working')
    try:
        forms, permissions = app.chamber.pending(item['session'])
        state = app.chamber.control('session.status', sessionId=item['session'])['sessionStatus']['type']
        state = 'waiting' if forms or permissions else 'working' if item['state'] == 'starting' or state == 'busy' else 'idle' if state == 'idle' else 'uncertain'
    except Exception:
        state = 'unavailable'
    return summary(state)


def panel(source, hosts):
    if 'id="account-activity"' in source:
        return source
    origins = html.escape(json.dumps(['https://' + host for host in hosts]), quote=True)
    markup = ('<aside id="account-activity" hidden aria-live="polite" aria-label="Ongoing activity" data-origins="' + origins + '">'
              '<strong id="activity-heading">Ongoing activity</strong><div id="activity-items"></div></aside>')
    source = source.replace('</header>', '</header>' + markup, 1)
    return source.replace('</head>', '<link rel="stylesheet" href="/activity.css"><script src="/activity.js" defer></script></head>')
