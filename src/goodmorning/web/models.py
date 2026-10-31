"""Website models, pinned per briefing job and chat turn."""
from contextvars import ContextVar

MODELS = {
    'deepseek-flash': {'providerID': 'opencode-go', 'id': 'deepseek-v4.1-flash', 'variant': 'high',
                       'label': 'DeepSeek V4.1 Flash · High'},
}
DEFAULT = 'deepseek-flash'
# Jobs and chat turns pinned before a model was retired run on its replacement.
RETIRED = {'muse-spark': 'deepseek-flash'}
CURRENT = ContextVar('website_model', default=None)  # Explicit synthetic-trial override only.


def for_language(value):
    from .language import language
    language(value)  # Rejects unsupported languages; every website language uses DEFAULT.
    return DEFAULT


def model(value):
    if not isinstance(value, str) or value not in MODELS:
        raise ValueError('Choose one of the offered website models')
    return value


def current():
    from .language import current as current_language
    return CURRENT.get() or for_language(current_language())


def session_payload(value):
    """The OpenCode session model body for a website model choice."""
    entry = MODELS[model(value)]
    return {'providerID': entry['providerID'], 'id': entry['id'], 'variant': entry['variant']}


def apply_to_session(chamber, session, value):
    """Point an existing session at the chosen model before sending."""
    chamber.request(f'/api/session/{session}/model', {'model': session_payload(RETIRED.get(value, value))})
