"""Minimal activity metadata, without transcripts, mutations or inferred completion."""
import html
import json
from goodmorning.briefings.briefing_stream import bounded_json
from goodmorning.briefings.briefing_job import context_path


ACTIVITY_PATH = r'/api/activity/(chat|job)/([a-f0-9]{32})'

DESK_SVG = '''<svg viewBox="0 0 88 76" fill="none" aria-hidden="true">
<path d="M11 58h66M20 58v9m48-9v9" stroke="var(--ink, #233c36)" stroke-opacity=".45" stroke-width="2" stroke-linecap="round"/>
<rect x="23" y="14" width="40" height="40" rx="5" fill="var(--surface, #fffefa)" stroke="currentColor" stroke-opacity=".65" stroke-width="1.6"/>
<path d="M31 24h21" stroke="currentColor" stroke-opacity=".28" stroke-width="2" stroke-linecap="round"/>
<g class="activity-paper-lines" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M31 32h22"/><path d="M31 39h17"/><path d="M31 46h20"/></g>
<g class="activity-pencil"><path d="m54 34 12-17 4 3-12 17-6 3 2-6Z" fill="var(--warm, #d8b471)" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="m54 34 4 3" stroke="currentColor" stroke-width="1.2"/></g>
<rect x="9" y="45" width="9" height="10" rx="2" fill="var(--warm, #d8b471)" fill-opacity=".45"/><path d="M18 47h2a3 3 0 0 1 0 6h-2" stroke="currentColor" stroke-opacity=".55" stroke-width="1.3"/>
<path class="activity-steam" d="M13 40q-2-2 0-4t0-4" stroke="currentColor" stroke-opacity=".4" stroke-width="1.2" stroke-linecap="round"/>
</svg>'''


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
        receipts = item.get('replied_inputs', [])
        forms = [form for form in forms if 'form:'+form['id'] not in receipts]
        permissions = [permission for permission in permissions if 'permission:'+permission['id'] not in receipts]
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
              '<div id="activity-window"><div class="activity-window-header"><strong id="activity-heading">Your secretary</strong>'
              '<button id="activity-minimize" type="button" aria-label="Minimize activity" title="Minimize activity">'
              '<svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path d="M5 10h10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>'
              '</button></div><div id="activity-items"></div></div>'
              '<button id="activity-restore" type="button" hidden aria-label="Expand ongoing activity" aria-expanded="false" aria-controls="activity-window">'
              '<span class="activity-chip-light" aria-hidden="true"></span><span id="activity-summary"></span><span aria-hidden="true">↗</span></button>'
              '<template id="activity-desk-art">' + DESK_SVG + '</template></aside>')
    source = source.replace('</header>', '</header>' + markup, 1)
    return source.replace('</head>', '<link rel="stylesheet" href="/activity.css"><script src="/activity.js" defer></script></head>')
