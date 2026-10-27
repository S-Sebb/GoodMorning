"""Code-led website setup: storage consent, the step order, validation and saving each step.

Initialize chats run one step at a time. Code owns which step comes next, which profile lines
it may change, every value's rules and the save; the secretary words each question and turns
free-text answers into values, quoting the user's own words. Chats (`web.briefing_chat`) post
the consent question, a step's question when the secretary did not ask it, and the closing
note; the secretary uses `setup next|ask|answer` (`setup_check.main`) for everything else.
"""
from contextlib import contextmanager, redirect_stdout
import io
import json
from pathlib import Path
import re
import shlex
import shutil
import time
from zoneinfo import ZoneInfo

from . import setup_guides, weather
from .calendar import public_holidays
from .paths import ROOT
from .records.celebrations import birthday
from .runtime_files import (atomic_text, calendar_path, normalize_profile_text, normalize_secretary_name, profile_fields,
                            runtime_lock, set_profile_fields)
from .setup_check import profile_status, verify
from .web import language as ui

STEPS = ('secretary_name', 'user_name', 'birthday', 'location', 'rhythm', 'about', 'news', 'holidays')
FIELDS = {'secretary_name': ('secretary_name',), 'user_name': ('user_name',), 'birthday': ('birthday',),
          'location': ('city', 'region', 'timezone'),
          'rhythm': ('work_days', 'work_hours', 'sleep_time', 'secretary_tone'),
          'about': ('occupations', 'expertise_fields', 'special_needs', 'industry', 'project_scope', 'knowledge_area'),
          'news': ('news_country', 'news_additional_countries'), 'holidays': ('holiday_countries',)}
STEP_OF = {field: step for step, fields in FIELDS.items() for field in fields}
# Asked in the step's form; the rest of a step's lines are saved only when the user states them.
ASKED = {**FIELDS, 'location': ('city',), 'about': ('occupations', 'expertise_fields', 'special_needs')}
REQUIRED = {'location': ('city', 'region', 'timezone'), 'news': ('news_country',)}
# Worked out from the user's city rather than quoted.
DERIVED = ('region', 'timezone')
NEWS = ('US', 'GB', 'CN', 'CA', 'AU')  # Bundled outlets; others are set up later in a Secretary chat.
COUNTRIES = {'US': 'United States', 'GB': 'United Kingdom', 'CN': 'China', 'CA': 'Canada', 'AU': 'Australia'}
# Code-applied choices; anything else is the user's own words for the secretary to interpret.
KEEP, SKIP, KEEP_ALL = 'keep', 'skip', 'keep_all'
CONSENT = 'setup-consent.json'
CHECK_FIELDS = ('city', 'timezone', 'news_country', 'news_additional_countries')
LABELS = {'secretary_name': ('Your secretary’s name', 'A name for me',
                             'Up to 30 characters. Skip it and I’ll just be “your secretary”.'),
          'user_name': ('Your name', 'What I should call you',
                        'Any name or form of address, up to 30 characters. Skip it and I won’t use a name.'),
          'birthday': ('Birthday', 'MM-DD',
                       'Month and day only, like 03-14. On that day your morning briefing opens with a birthday card.'),
          'city': ('City and country', 'City, country',
                   'For example “Edinburgh, UK”. I use it for your weather and to work out your timezone.'),
          'work_days': ('Work days', 'For example, Monday to Friday', ''),
          'work_hours': ('Work hours', 'For example, 9:00–17:30', ''),
          'sleep_time': ('Bedtime', 'For example, 23:00', ''),
          'secretary_tone': ('How I should talk with you', 'For example, warm and helpful, formal or playful', ''),
          'occupations': ('Your roles', 'For example, nurse, student or parent', ''),
          'expertise_fields': ('Fields you know well', 'For example, biology or accounting', ''),
          'special_needs': ('Anything I should keep in mind', 'For example, I prefer short replies', ''),
          'news_country': ('Main country', '', 'National news comes from this country’s outlets.'),
          'news_additional_countries': ('Other countries (optional)', '', ''),
          'holiday_countries': ('Public holidays', '',
                                'They show on your Schedule and briefings on their day, and for China the make-up '
                                'workdays too. Pick as many as you like.')}
TITLES = {'secretary_name': 'What would you like to call me?', 'user_name': 'What should I call you?',
          'birthday': 'When’s your birthday?', 'location': 'Where are you based?',
          'rhythm': 'What does your usual week look like?',
          'about': 'Is there anything about you that would help me help you?',
          'news': 'Which countries’ news should your morning briefing cover?',
          'holidays': 'Which public holidays should I show?'}
NOTES = {'rhythm': 'All optional. It helps me plan around your day and talk the way you like.',
         'about': 'All optional. It helps me pick relevant news and explain things at the right depth.'}


class SetupError(ValueError):
    """`code: next step` for the secretary; nothing was saved."""


def chat_id(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise SetupError('setup_chat: this conversation is not an Initialize chat')
    return value


@contextmanager
def speaking(lang):
    """Builds questions and receipts in the chat's language, whatever page asked."""
    token = ui.CURRENT.set(ui.language(lang))
    try:
        yield
    finally:
        ui.CURRENT.reset(token)


def directory(runtime):
    folder = Path(runtime) / 'browser-chats' / 'setup'
    if folder.parent.is_symlink() or folder.is_symlink():
        raise ValueError('Unsafe setup storage')
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder


def path(runtime, chat):
    target = directory(runtime) / (chat_id(chat) + '.json')
    if target.is_symlink():
        raise ValueError('Unsafe setup storage')
    return target


def load(runtime, chat):
    target = path(runtime, chat)
    return json.loads(target.read_text(encoding='utf-8')) if target.exists() else None


def store(runtime, chat, state):
    atomic_text(path(runtime, chat), json.dumps(state, ensure_ascii=False) + '\n')


def locked(runtime, chat):
    return runtime_lock(directory(runtime), chat_id(chat) + '.lock')


def consented(runtime):
    """Storage consent is a condition of using GoodMorning. A saved profile predates the consent
    record and was created only after the user agreed, so it counts as consent for the base scope."""
    return (Path(runtime) / 'profile.md').is_file() or (Path(runtime) / CONSENT).is_file()


def agree(runtime, chat):
    """Records consent and creates only missing base storage; never overwrites a record."""
    runtime = Path(runtime)
    with runtime_lock(runtime, '.setup.lock'):
        for name in ('projects', 'daily'):
            (runtime / name).mkdir(mode=0o700, exist_ok=True)
        profile = runtime / 'profile.md'
        if not profile.exists():
            shutil.copyfile(ROOT / 'templates/profile.template.md', profile)
        from .records.inbox_store import initialize
        from .calendar.calendar_store import CalendarStore
        initialize(runtime)
        CalendarStore(str(calendar_path(runtime))).close()
        if not (runtime / CONSENT).exists():
            atomic_text(runtime / CONSENT, json.dumps({'version': 1, 'scope': 'base', 'chat': chat,
                                                       'at': time.time()}) + '\n')


def begin(runtime, chat):
    """This chat's setup state, created on its first request; an existing one is kept."""
    with locked(runtime, chat):
        state = load(runtime, chat)
        if state is None:
            ready = profile_status(runtime, profile_fields(runtime), 'en')['profile_ready']
            state = {'version': 1, 'mode': 'review' if ready else 'new', 'done': [], 'changed': [], 'revision': 0,
                     'asked': None, 'pending': None, 'shown': {}, 'fallbacks': [], 'phase': 'steps', 'created': time.time()}
            store(runtime, chat, state)
        return state


def current(state):
    return next((step for step in STEPS if step not in state['done']), None)


def news_options():
    return [{'value': code, 'label': ui.text(COUNTRIES[code])} for code in NEWS]


def holiday_options(fields):
    """Every region grouped by country, with the user's news countries first."""
    first = [fields.get('news_country', ''), *split(fields.get('news_additional_countries', ''))]
    order = sorted(public_holidays.REGIONS, key=lambda code: (first.index(code[:2]) if code[:2] in first else 9,
                                                              NEWS.index(code[:2])))
    lang = ui.current()
    return [{'value': code, 'label': public_holidays.choice(code, lang),
             'group': public_holidays.named(public_holidays.REGIONS[code]['country'], lang)} for code in order] + [
        {'value': 'none', 'label': ui.text('No public holidays')}]


def split(value):
    return [code.strip().upper() for code in re.split(r'[,;\s]+', value or '') if code.strip()]


def field(key, fields, optional, keep_all=False):
    saved = fields.get(key, '')
    if key == 'city' and saved and fields.get('timezone'):
        saved += ' · ' + fields['timezone']
    label, placeholder, description = LABELS[key]
    entry = {'key': key, 'title': ui.text(label), 'type': 'string', 'required': True}
    if description:
        entry['description'] = ui.text(description)
    if key == 'news_country':
        return {**entry, 'options': news_options(), **({'default': saved} if saved in NEWS else {})}
    if key == 'news_additional_countries':
        return {**entry, 'type': 'multiselect', 'required': False, 'options': news_options(),
                'default': [code for code in split(saved) if code in NEWS]}
    if key == 'holiday_countries':
        chosen = ['none'] if saved == 'none' else split(saved)
        return {**entry, 'type': 'multiselect', 'minItems': 1, 'options': holiday_options(fields),
                'default': [code for code in chosen if code == 'none' or code in public_holidays.REGIONS]}
    options = ([{'value': KEEP, 'label': ui.text('Keep “{value}”', value=saved)}] if saved
               else [{'value': SKIP, 'label': ui.text('Skip for now')}] if optional else [])
    if keep_all:
        options.append({'value': KEEP_ALL, 'label': ui.text('Keep everything as it is')})
    if options:
        entry.update(options=options, custom=True, customFirst=True, default=options[0]['value'])
    if placeholder:
        entry['placeholder'] = ui.text(placeholder)
    return entry


def form(runtime, state, step, title=None):
    """The step's question: code owns its fields, options and limits; the secretary may word the title."""
    fields = profile_fields(runtime)
    first = state['mode'] == 'review' and not state['done'] and step == STEPS[0]
    entries = [field(key, fields, step not in REQUIRED, keep_all=first and index == 0)
               for index, key in enumerate(ASKED[step])]
    if step in NOTES:
        entries[0]['description'] = ui.text(NOTES[step])
    state['revision'] += 1
    return {'id': f'setup_{step}_{state["revision"]}', 'title': title or ui.text(TITLES[step]), 'setup': step,
            'fields': entries}


def consent_form():
    return {'id': f'setup_consent_{time.time_ns()}', 'title': ui.text('Before we begin: how GoodMorning keeps your information'),
            'setup': 'consent', 'fields': [{
                'key': 'consent', 'title': ui.text('Do you agree?'), 'type': 'string', 'required': True,
                'description': ui.text(setup_guides.CONSENT),
                'options': [{'value': 'agree', 'label': ui.text('I agree')},
                            {'value': 'decline', 'label': ui.text('I don’t agree')}]}]}


def posted(runtime, chat, question):
    """Remember what the step's question showed, so a change made elsewhere since then is not overwritten."""
    with locked(runtime, chat):
        state = load(runtime, chat)
        step = question.get('setup')
        if state is None or step not in FIELDS:
            return
        fields = profile_fields(runtime)
        state['shown'] = {key: fields.get(key, '') for key in FIELDS[step]}
        state['asked'] = {'step': step, 'form': question['id']}
        state['pending'] = None
        store(runtime, chat, state)


def fallback(runtime, chat, record=True):
    """The current step's question in code wording, for a turn that ended without asking it
    (`record`), or to open a blank Initialize chat without a model run."""
    with locked(runtime, chat):
        state = load(runtime, chat)
        step = state and current(state)
        if not step:
            return None
        question = form(runtime, state, step)
        if record:
            state['fallbacks'].append(step)
        store(runtime, chat, state)
        return question


def pending(runtime, chat):
    state = load(runtime, chat)
    return state and state.get('pending')


# Values ------------------------------------------------------------------------------------------

def clean(key, value, saved):
    """One profile value as it is saved; raises SetupError with the rule."""
    if isinstance(value, list) and key in ('news_additional_countries', 'holiday_countries'):
        value = ', '.join(str(entry) for entry in value if entry != 'none' or len(value) == 1)
    if not isinstance(value, str):
        raise SetupError(f'invalid_value: {key} is text')
    value = value.strip()
    try:
        if key in ('secretary_name', 'user_name'):
            return normalize_secretary_name(value, key)
        if key == 'birthday':
            return birthday(value)
        if key == 'region':
            if value not in ('global', 'mainland-china'):
                raise ValueError('region is global or mainland-china')
            return value
        if key == 'timezone':
            if '/' not in value:
                raise ValueError('timezone is an IANA zone such as Europe/London')
            ZoneInfo(value)
            return value
        if key == 'news_country':
            if value.upper() not in NEWS:
                raise ValueError('news_country is one of ' + ', '.join(NEWS)
                                 + '; other countries are set up later in a Secretary chat, so save nothing for them')
            return value.upper()
        if key == 'news_additional_countries':
            codes = split(value)
            if any(code not in NEWS for code in codes):
                raise ValueError('news_additional_countries uses only ' + ', '.join(NEWS))
            return ', '.join(dict.fromkeys(code for code in codes if code != saved.get('news_country', '').upper()))
        if key == 'holiday_countries':
            return ', '.join(public_holidays.regions(value)) or 'none'
        text = normalize_profile_text(value, key)
        if key == 'city' and not text:
            raise ValueError('city is required')
        return text
    except (ValueError, KeyError) as error:
        raise SetupError(f'invalid_value: {error}; ask again with clarify or a plain question') from None


def normalized(text):
    return re.sub(r'[\s"“”‘’\'.,!?;:，。！？；：、（）()]+', '', str(text)).casefold()


def user_words(runtime, chat):
    """What this chat's user wrote or picked: their messages and question answers, never the secretary's."""
    registry = Path(runtime) / 'browser-chats' / 'chats.json'
    item = json.loads(registry.read_text(encoding='utf-8')).get(chat, {}) if registry.exists() else {}
    words = [turn.get('text', '') for turn in item.get('turns', []) if not turn.get('answer')]
    for question in item.get('questions', []):
        for value in question.get('answer', {}).values():
            words.extend(value if isinstance(value, list) else [value])
    return [normalized(word) for word in words if isinstance(word, str) and word.strip()]


def quoted(words, quote):
    """A quote is a whole message or answer, however short, or a meaningful part of one: at least two CJK or
    three other characters, so a stray "a" or "是" never stands in for the user's words."""
    quote = normalized(quote) if isinstance(quote, str) else ''
    if not quote or len(quote) > 500:
        return False
    meaningful = len(quote) >= 3 or len(re.findall(r'[\u3400-\u9fff\uf900-\ufaff]', quote)) >= 2
    return quote in words or meaningful and any(quote in word for word in words)


def save(runtime, state, step, values):
    """Validate a step's values against the saved profile, then write only real changes."""
    fields = profile_fields(runtime)
    changes = {}
    for key, value in values.items():
        if key not in STEP_OF:
            raise SetupError(f'invalid_field: {key} is not a setup value')
        cleaned = clean(key, value, {**fields, **values})
        if cleaned != fields.get(key, ''):
            changes[key] = cleaned
    shown = state.get('shown') or {}
    moved = [key for key in changes if key in shown and fields.get(key, '') != shown[key]]
    if moved:
        raise SetupError('changed_elsewhere: ' + ', '.join(moved) + ' changed on another page since this question; '
                         'ask again with `ask` so the user sees the current value')
    merged = {**fields, **changes}
    missing = [key for key in REQUIRED.get(step, ()) if not merged.get(key)]
    if missing:
        raise SetupError('required: ' + ', '.join(missing) + ' is needed for this step; ask for it')
    if 'city' in changes:
        place(changes['city'])
    if changes:
        set_profile_fields(runtime, changes)
        state['changed'] = list(dict.fromkeys(state['changed'] + list(changes)))
    return changes


def place(city):
    """A new city must name one place for the weather service; an unreachable service leaves it to the final check."""
    try:
        weather.openmeteo_geocode(city, 10)
    except weather.PlaceError as error:
        raise SetupError(f'city_unresolved: the weather service cannot place "{city}" ({error}). Save it as "City, '
                         'Province or State, CC" with the two-letter country code (Hangzhou, Zhejiang, CN); if you cannot '
                         'tell which place the user means, run `ask` for this step with `clarify`') from None
    except weather.WeatherError:
        pass


def finish_step(state, step, keep_all=False):
    if keep_all:
        state['done'] = list(STEPS)
    elif step not in state['done']:
        state['done'].append(step)
    state['asked'], state['pending'], state['shown'] = None, None, {}


def apply_form(runtime, chat, question, answer):
    """Applies a code question's answer when it holds only choices; returns False when free text needs
    the secretary. Choices are keep, skip, keep everything, or picked countries and holiday regions."""
    step = question['form'].get('setup')
    with locked(runtime, chat):
        state = load(runtime, chat)
        if state is None or step != current(state):
            return False
        values, keep_all = {}, False
        for entry in question['form']['fields']:
            value = answer.get(entry['key'])
            choices = {option['value'] for option in entry.get('options', [])}
            if value == KEEP_ALL:
                keep_all = True
            elif entry['key'] in ('news_country', 'news_additional_countries', 'holiday_countries'):
                values[entry['key']] = value if value is not None else []
            elif value in (KEEP, SKIP, None) and value in choices | {None}:
                continue
            else:
                return False
        if keep_all and state['mode'] != 'review':
            return False
        try:
            save(runtime, state, step, values)
        except SetupError:
            return False
        finish_step(state, step, keep_all)
        store(runtime, chat, state)
        return True


# The secretary's commands -------------------------------------------------------------------------

def owner(runtime, session):
    """The Initialize chat this native session belongs to."""
    registry = Path(runtime) / 'browser-chats' / 'chats.json'
    items = json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else {}
    chats = [item for item in items.values() if session and item.get('session') == session]
    if len(chats) != 1 or load(runtime, chats[0]['id']) is None:
        raise SetupError('setup_not_active: this session has no setup; follow docs/workflows/secretary.md')
    return chats[0]


def language(item):
    turns = item.get('turns') or [{}]
    return ui.language(turns[-1].get('language', 'en'))


def commands(runtime, session):
    base = ['python', 'scripts/goodmorning.py', 'setup', '--secretary-dir', str(runtime), '--session', session]
    return {action: shlex.join(base + [action] + (['--input-stdin'] if action != 'next' else []))
            for action in ('next', 'ask', 'answer')}


def finalize(runtime, state):
    """After the last step: check weather and news when the place or news changed (always for a new
    setup), then rebuild the state index. Runs once; failed checks stay pending, never retried."""
    fields = profile_fields(runtime)
    checks = {}
    if state['mode'] == 'new' or any(key in state['changed'] for key in CHECK_FIELDS):
        countries = profile_status(runtime, fields, 'en')['countries']
        checks = {name: {'status': row['status'], **({'reason': row['reason']} if 'reason' in row else {})}
                  for name, row in verify(Path(runtime), fields, countries, ('weather', 'news'), 20).items()}
    from .records import state as index
    output = io.StringIO()
    with redirect_stdout(output):
        rebuilt = index.main(['--secretary-dir', str(runtime), '--rebuild', '--json']) == 0
    state.update(phase='done', checks=checks, rebuilt=rebuilt)


def receipt(runtime, chat, session, lang, *, contract=False):
    """The rules and commands for the current step only, in the website language."""
    with speaking(lang):
        with locked(runtime, chat):
            state = load(runtime, chat)
            if state is None:
                raise SetupError('setup_not_active: this session has no setup')
            step = current(state)
            if step is None and state['phase'] != 'done':
                finalize(runtime, state)
            finished = step is None and not state.get('summarized')
            state['summarized'] = step is None
            store(runtime, chat, state)
        fields = profile_fields(runtime)
        words = setup_guides.text(lang)
        reply = {'language': lang, 'tone': fields.get('secretary_tone') or 'warm and helpful'}
        if fields.get('user_name'):
            reply['user_name'] = fields['user_name']
        result = {'setup': {'mode': state['mode'], 'step': step, 'position': len(state['done']) + 1 if step else None,
                            'steps': len(STEPS)}, 'reply_context': reply}
        if contract:
            result['contract'] = words['contract']
        actions = commands(runtime, session)
        if step:
            guide = words[step] + (' ' + words['review'] if state['mode'] == 'review' else '')
            if state['mode'] == 'review' and not state['done'] and step == STEPS[0]:
                guide += ' ' + words['keep_all']
            asked = ASKED[step] + tuple(key for key in DERIVED if key in FIELDS[step])
            result['saved'] = {key: fields.get(key, '') for key in FIELDS[step]}
            result['next'] = {'action': 'answer_or_ask', 'guide': guide,
                              'answer': {'command': actions['answer'], 'input': {
                                  'step': step, 'values': {key: '…' for key in asked},
                                  'quotes': {key: '…' for key in ASKED[step]}}},
                              'ask': {'command': actions['ask'], 'input': {'step': step, 'title': '…'}}}
        elif finished:
            result['next'] = {'action': 'finish', 'guide': words['finish'],
                              'saved': {key: fields.get(key, '') for key in state['changed']},
                              'checks': state.get('checks') or None}
        else:
            result['next'] = {'action': 'done', 'guide': words['done']}
        return result


def hint(runtime, chat):
    """The more-features note, once, after setup is done."""
    with locked(runtime, chat):
        state = load(runtime, chat)
        if not state or state['phase'] != 'done' or state.get('hinted'):
            return None
        state['hinted'] = True
        store(runtime, chat, state)
        return ui.text(setup_guides.MORE)


def ask(runtime, chat, payload):
    with locked(runtime, chat):
        state = load(runtime, chat)
        step = current(state)
        if not isinstance(payload, dict) or set(payload) - {'step', 'title', 'clarify'} or payload.get('step') != step:
            raise SetupError(f'wrong_step: ask only the current step ({step}) with {{"step","title"}}')
        title = payload.get('title')
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 300 or any(ord(c) < 32 for c in title):
            raise SetupError('invalid_title: one line of up to 300 characters, the question in your words')
        question = form(runtime, state, step, title.strip())
        clarify = payload.get('clarify')
        if clarify is not None and step in ('news', 'holidays'):
            raise SetupError('invalid_clarify: this step already lists its choices')
        if clarify is not None:
            if (not isinstance(clarify, list) or not 2 <= len(clarify) <= 8
                    or any(not isinstance(entry, str) or not 1 <= len(entry.strip()) <= 120 for entry in clarify)):
                raise SetupError('invalid_clarify: 2-8 candidate answers, each a short line')
            first = question['fields'][0]
            question['fields'][0] = {**first, 'options': [{'value': entry.strip(), 'label': entry.strip()} for entry in clarify],
                                     'custom': True, 'customFirst': False, 'default': None}
        state['pending'] = question
        store(runtime, chat, state)
        return question


def answer(runtime, chat, payload):
    words = user_words(runtime, chat)
    with locked(runtime, chat):
        state = load(runtime, chat)
        step = current(state)
        if not isinstance(payload, dict) or set(payload) - {'step', 'values', 'quotes', 'quote', 'keep_all'}:
            raise SetupError('invalid_input: send {"step","values","quotes"} or {"step","values":{},"quote"}')
        if step is None or payload.get('step') != step:
            raise SetupError(f'wrong_step: the current step is {step}; answer only it, then ask the step the receipt names')
        values, quotes = payload.get('values') or {}, payload.get('quotes') or {}
        if not isinstance(values, dict) or not isinstance(quotes, dict):
            raise SetupError('invalid_input: values and quotes are objects')
        later = STEPS[STEPS.index(step):]
        for key in values:
            if STEP_OF.get(key) not in later:
                raise SetupError(f'invalid_field: {key} belongs to no remaining step')
            if key in DERIVED and ('city' in values or key in quotes and quoted(words, quotes[key])):
                continue
            if not quoted(words, quotes.get(key)):
                raise SetupError(f'unquoted: {key} needs `quotes.{key}` with the user\'s own words from this chat: their '
                                 'whole message or answer, or a part of at least 3 characters (2 Chinese); never fill a '
                                 'value the user did not give')
            if key in ('secretary_name', 'user_name') and normalized(values[key]) not in normalized(quotes[key]):
                raise SetupError(f'unquoted: {key} is saved exactly as the user spelled it, so its quote contains it')
        if not values and not quoted(words, payload.get('quote')):
            raise SetupError('unquoted: keeping or skipping needs `quote` with the user\'s own words: their whole message '
                             'or answer, or a part of at least 3 characters (2 Chinese)')
        keep_all = payload.get('keep_all') is True
        if keep_all and (state['mode'] != 'review' or values):
            raise SetupError('invalid_keep_all: only a review keeps everything, with no values')
        changes = save(runtime, state, step, values)
        finish_step(state, step, keep_all)
        store(runtime, chat, state)
    return changes


def command(runtime, session, action, raw):
    """`setup next|ask|answer` for the secretary; prints one JSON receipt."""
    try:
        item = owner(runtime, session)
        chat = item['id']
        lang = language(item)
        if action == 'next':
            result = receipt(runtime, chat, session, lang, contract=True)
        else:
            try:
                payload = json.loads(raw or '')
            except json.JSONDecodeError as error:
                raise SetupError(f'invalid_input: malformed JSON ({error.msg}); nothing was saved') from None
            if action == 'ask':
                with speaking(lang):
                    ask(runtime, chat, payload)
                result = {'asked': True, 'next': setup_guides.text(lang)['asked']}
            else:
                result = {'changed': answer(runtime, chat, payload), **receipt(runtime, chat, session, lang)}
        print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
        return 0
    except SetupError as error:
        code, _, detail = str(error).partition(': ')
        print(json.dumps({'error': code, 'next': detail or code}, ensure_ascii=False))
        return 1
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'error': 'setup_unavailable', 'next': 'Preserve records; say setup could not continue right now. '
                          + type(error).__name__}))
        return 1
