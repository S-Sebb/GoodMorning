"""User-selected website model. Sits beside the website language setting.

Two options for now. The choice is stored per account (like the website
language), pinned per briefing job and per chat turn, and applied to the
owning OpenChamber session right after creation, before any prompt is sent.
Unset accounts use DEFAULT, which matches the engine default.
"""
from contextvars import ContextVar

MODELS = {
    'muse-spark': {'providerID': 'opencode-go', 'id': 'muse-spark-1.3-contributor', 'variant': 'xhigh',
                   'label': 'Muse Spark 1.3 · XHigh'},
    'deepseek-flash': {'providerID': 'opencode-go', 'id': 'deepseek-v4.1-flash', 'variant': 'high',
                       'label': 'DeepSeek V4.1 Flash · High'},
}
DEFAULT = 'muse-spark'
CURRENT = ContextVar('website_model', default=DEFAULT)


def model(value):
    if not isinstance(value, str) or value not in MODELS:
        raise ValueError('Choose one of the offered website models')
    return value


def current():
    return CURRENT.get()


def session_payload(value):
    """The OpenChamber session model body for a website model choice."""
    entry = MODELS[model(value)]
    return {'providerID': entry['providerID'], 'id': entry['id'], 'variant': entry['variant']}


def apply_to_session(chamber, session, value):
    """Point an existing session at the chosen model before sending."""
    chamber.request(f'/api/session/{session}/model', {'model': session_payload(value)})
