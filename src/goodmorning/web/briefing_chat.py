"""Account-local, durable conversations for website setup and secretary chats."""
import hashlib
import html
import json
import re
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode

from goodmorning.runtime_files import atomic_text
from .briefing_resources import favicon_links
from . import language as ui
from . import models as site_models
from .session_inventory import chat_session_title
from .chat_uploads import Uploads, attachment_ids, MAX_UPLOAD_BYTES
from .avatar_images import image_urls

MODES = {'initialize': 'Initialize', 'secretary': 'Secretary', 'todo': 'To-do', 'eureka': 'Eureka'}
# Secretary now saves to-dos and ideas itself; older To-do/Eureka chats stay readable and replyable.
NEW_MODES = ('initialize', 'secretary')
OUTREACH_TITLE = 'A note from your secretary'
# An engine stores an accepted prompt at once; wait this long before calling an unseen one not sent.
DELIVERY_GRACE = 120

AVATARS = (('f1', 'desk-secretary.png', 'Classic'),
           ('f2', 'desk-secretary-f2.png', 'Female 2'),
           ('m1', 'desk-secretary-m1.png', 'Male 1'),
           ('m2', 'desk-secretary-m2.png', 'Male 2'))
AVATAR_IDS = tuple(entry[0] for entry in AVATARS)
# Each built-in avatar has a lamp-lit night scene, a daylight scene, a gently animated copy of each scene
# and a round profile picture.
AVATAR_FILES = {entry: {'night': filename, 'day': filename.replace('.png', '-day.png'),
                        'nightAnimated': filename.replace('.png', '-animated.png'),
                        'dayAnimated': filename.replace('.png', '-day-animated.png'),
                        'profile': filename.replace('.png', '-profile.png')} for entry, filename, _ in AVATARS}


def avatar_variant(theme):
    return 'night' if theme == 'gn' else 'day'


def avatar_widget(selected='f1', sources=None, class_name='desk-figure', theme='gm'):
    custom = (sources or {}).get('custom')
    sources = {entry: (sources or {}).get(entry) or {variant: '/' + name for variant, name in files.items()}
               for entry, files in AVATAR_FILES.items()}
    if custom:
        sources['custom'] = custom
    ids = tuple(sources)
    selected = selected if selected in ids else 'f1'
    variant = avatar_variant(theme)
    options = html.escape(json.dumps([{'id': entry, **sources[entry]} for entry in ids]), quote=True)
    previews = ''.join(
        f'<button type="button" class="avatar-preview" role="option" data-avatar-choice="{entry}" aria-selected="{str(entry == selected).lower()}" aria-label="Avatar {index}">'
        f'<img src="{html.escape(sources[entry][variant], quote=True)}" alt="" width="72" height="72" loading="lazy"><span>{index}</span></button>'
        for index, entry in enumerate(ids, 1))
    uploads = ''.join(f'<button type="button" class="avatar-upload" data-avatar-upload="{kind}" aria-label="{label}">{text}</button>'
                      for kind, text, label in (('day', 'Scene · day', 'Upload day scene'),
                                                ('night', 'Scene · night', 'Upload night scene'),
                                                ('profile', 'Profile', 'Upload profile picture')))
    profile = sources[selected]['profile'] or ''
    animated = sources[selected].get(variant + 'Animated')
    return (f'<figure class="{class_name} avatar-display" data-avatar="{selected}" data-profile="{html.escape(profile, quote=True)}" data-avatar-options="{options}">'
            '<div class="avatar-frame">'
            # Only the main portrait moves, and never for readers who ask for reduced motion.
            '<picture>' + (f'<source media="(prefers-reduced-motion: no-preference)" srcset="{html.escape(animated, quote=True)}">' if animated else '') +
            f'<img class="avatar-image" src="{html.escape(sources[selected][variant], quote=True)}" alt="Secretary avatar" width="220" height="220"></picture>'
            f'<img class="avatar-profile" src="{html.escape(profile or sources[selected][variant], quote=True)}" alt="" width="44" height="44">'
            '<button class="avatar-toggle" type="button" data-avatar-toggle aria-label="Change avatar" title="Change avatar" aria-expanded="false" disabled>'
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            '<path d="m16 3 5 5-3 3v10H6V11L3 8l5-5a4 4 0 0 0 8 0Z"/></svg></button></div>'
            '<div class="avatar-menu" role="dialog" aria-label="Choose an avatar" hidden>'
            '<div class="avatar-carousel"><button class="avatar-step" type="button" data-avatar-prev aria-label="Previous avatar">‹</button>'
            '<div class="avatar-previews" role="listbox" aria-label="Secretary avatars">' + previews + '</div>'
            '<button class="avatar-step" type="button" data-avatar-next aria-label="Next avatar">›</button></div>'
            '<p class="avatar-upload-heading">Upload your own avatar</p>'
            '<div class="avatar-uploads">' + uploads + '</div>'
            '<input type="file" data-avatar-file accept="image/png,image/jpeg,image/webp" aria-label="Upload your own avatar" hidden>'
            '<p class="avatar-upload-note">PNG, JPEG or WebP, up to 5 MB. Missing images are filled in from the ones you upload.</p>'
            '<p class="avatar-feedback" role="status">Avatar ' + str(ids.index(selected) + 1) + ' of ' + str(len(ids)) + '</p></div></figure>')


def avatar_id(value):
    if value not in (*AVATAR_IDS, 'custom'):
        raise ValueError('Unknown secretary avatar')
    return value


def read_avatar(runtime):
    from pathlib import Path
    path = Path(runtime) / 'website-avatar.json'
    if path.is_symlink():
        raise ValueError('Unsafe avatar storage')
    try:
        raw = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return 'f1'
    except OSError:
        return 'f1'
    try:
        selected = avatar_id(json.loads(raw).get('avatar'))
        return 'f1' if selected == 'custom' and not image_urls(runtime) else selected
    except (ValueError, AttributeError, TypeError):
        return 'f1'


def write_avatar(runtime, value):
    from pathlib import Path
    avatar_id(value)
    if value == 'custom' and not image_urls(runtime):
        raise ValueError('Upload a secretary avatar first')
    path = Path(runtime) / 'website-avatar.json'
    if path.is_symlink():
        raise ValueError('Unsafe avatar storage')
    atomic_text(path, json.dumps({'avatar': value}) + '\n')
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise ValueError('Invalid conversation request')
    return value


def message(value):
    if not isinstance(value, str) or len(value) > 8000 or '\x00' in value:
        raise ValueError('Use a message of up to 8,000 characters')
    if re.match(r'^\s*/[a-zA-Z]', value):
        raise ValueError('Write in your own words; no commands are needed')
    return value.strip()


def question_text(form, language):
    parts = [form.get('title') or ui.text('A question for you', lang=language)]
    for field in form['fields']:
        if field.get('hidden'):
            continue
        parts.append(field.get('title') or ui.text('Your answer', lang=language))
        if field.get('description'):
            parts.append(field['description'])
        for option in field.get('options', []):
            parts.append('• ' + option['label'] + (': ' + option['description'] if option.get('description') else ''))
    return '\n'.join(parts)


def answer_text(form, answer, language):
    parts = []
    for field in form['fields']:
        if field['key'] not in answer:
            continue
        value = answer[field['key']]
        options = {option['value']: option['label'] for option in field.get('options', [])}
        values = value if isinstance(value, list) else [value]
        labels = [ui.text('Yes' if entry else 'No', lang=language) if isinstance(entry, bool)
                  else str(options.get(entry, entry)) for entry in values]
        parts.append((field.get('title') or ui.text('Your answer', lang=language)) + ': ' + (', '.join(labels) or '—'))
    return '\n'.join(parts) or '—'


def model_answer(form, answer):
    """The engine's own wording for a question tool result, so a later answer reads as one."""
    parts = []
    for field in form['fields']:
        value = answer.get(field['key'])
        values = [] if value is None else value if isinstance(value, list) else [value]
        text = ', '.join(('Yes' if entry else 'No') if isinstance(entry, bool) else str(entry) for entry in values)
        parts.append(json.dumps(field.get('description') or field.get('title') or field['key'], ensure_ascii=False)
                     + '=' + json.dumps(text or 'Unanswered', ensure_ascii=False))
    return ('User has answered your questions: ' + ', '.join(parts)
            + ". You can now continue with the user's answers in mind.")


def valid_answer(form, answer):
    fields = {field['key'] for field in form['fields']}
    if (not isinstance(answer, dict) or not answer or set(answer) - fields
            or any(not isinstance(value, (str, bool, int, float)) and not (isinstance(value, list) and all(isinstance(entry, str) for entry in value))
                   for value in answer.values())
            or len(json.dumps(answer, ensure_ascii=False)) > 8000):
        raise ValueError('Invalid answer')
    return answer


def parked_forms(questions):
    """Saved questions still waiting for the user."""
    return [entry['form'] for entry in questions if entry.get('parked') and 'answer' not in entry and 'skipped' not in entry]


def close_question(chamber, session, form):
    """Closes an engine question whose copy is already saved. Returns False only when someone answered it
    in the engine first (for example in OpenChamber), and None when it is still open; the next read retries."""
    try:
        chamber.request(f'/api/session/{session}/form/{form}', method='DELETE')
        return True
    except HTTPError:
        try:
            state = chamber.request(f'/api/session/{session}/form/{form}')['data']['state']['status']
        except HTTPError as error:
            return True if error.code == 404 else None
        except Exception:
            return None
        return None if state == 'pending' else state != 'answered'
    except Exception:
        return None


def question_tool(entry):
    return entry['form'].get('metadata', {}).get('tool', {}).get('id')


def expired_questions(messages, questions, language):
    """Fill in questions the engine closed. A saved question appears where it was asked once it is
    answered or skipped; while it waits, only its form shows. An older unsaved question shows as expired:
    the form when this page saw it, otherwise a plain note. Also returns the saved questions shown here."""
    saved = {question_tool(entry): entry for entry in questions}
    result, shown = [], set()
    for entry in messages:
        tools = entry.pop('_tools', None)
        if tools is None:
            result.append(entry)
            continue
        known = [saved[tool] for tool in tools if tool in saved]
        parked = [question for question in known if question.get('parked')]
        if parked:
            shown.update(question['id'] for question in parked)
            result.extend({'id': 'question:' + question['id'], 'role': 'assistant',
                           'kind': 'question' if 'answer' in question else 'skipped', 'language': question['language'],
                           'text': question_text(question['form'], question['language'])}
                          for question in parked if 'answer' in question or 'skipped' in question)
            continue
        if any('answer' in question for question in known):
            continue
        shown.update(question['id'] for question in known)
        entry['language'] = known[0]['language'] if known else language
        entry['text'] = '\n\n'.join(question_text(question['form'], question['language']) for question in known) or ui.text(
            'Your secretary asked you something here.', lang=entry['language'])
        result.append(entry)
    return result, shown


def question_history(messages, questions, pending, complete):
    """Insert account-local form exchanges at their original transcript positions."""
    anchors = {entry['id'] for entry in messages}
    additions = {}
    for entry in questions:
        language = entry['language']
        exchanges = []
        if 'answer' in entry or entry['id'] not in pending:
            exchanges.append((entry['after'], {'id': 'question:' + entry['id'], 'role': 'assistant',
                'kind': 'question', 'language': language, 'text': question_text(entry['form'], language)}))
        if 'answer' in entry:
            exchanges.append((entry['answer_after'], {'id': 'answer:' + entry['id'], 'role': 'user',
                'kind': 'answer', 'language': language, 'text': answer_text(entry['form'], entry['answer'], language)}))
        for anchor, exchange in exchanges:
            # Do not move old exchanges into the newer, bounded transcript window.
            if anchor in anchors or anchor is None and complete:
                additions.setdefault(anchor, []).append(exchange)
    result = list(additions.get(None, []))
    for entry in messages:
        result.append(entry)
        result.extend(additions.get(entry['id'], []))
    return result


def chat_language(item, latest=False):
    """A secretary-opened conversation speaks its opening's language until the user replies."""
    if item['turns']:
        return item['turns'][-1 if latest else 0].get('language', 'en')
    return item.get('opening', {}).get('language', 'en' if not latest else None)


def opening_message(opening):
    return {'id': opening['id'], 'role': 'assistant', 'text': opening['text'], 'attachments': [],
            'kind': 'outreach', 'language': opening['language']}


class Chats:
    def __init__(self, runtime, chamber):
        self.runtime, self.chamber = runtime, chamber
        self.uploads = Uploads(runtime)
        self.lock = threading.RLock()
        self.title_cache = {}
        self.title_states = {}
        self.titles_checked = float('-inf')
        self.directory = runtime / 'browser-chats'
        self.path = self.directory / 'chats.json'
        if self.directory.is_symlink() or self.path.is_symlink():
            raise ValueError('Unsafe conversation storage')
        self.directory.mkdir(mode=0o700, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size > 8_000_000:
            raise ValueError('Conversation registry exceeds its limit')
        self.items = json.loads(self.path.read_text()) if self.path.exists() else {}
        for item in self.items.values():
            if item['state'] == 'starting':
                item.update(state='uncertain', uncertain_since=time.time())
        if self.items:
            self.save()

    def save(self):
        if self.directory.is_symlink() or self.path.is_symlink():
            raise ValueError('Unsafe conversation storage')
        raw = json.dumps(self.items, ensure_ascii=False) + '\n'
        if len(raw.encode()) > 8_000_000:
            raise ValueError('Conversation registry exceeds its limit')
        atomic_text(self.path, raw)

    def capacity(self, text):
        # Leave room for dispatch metadata; never grow beyond the restart read limit.
        size = len(json.dumps(self.items, ensure_ascii=False).encode())
        if size + len(json.dumps(text, ensure_ascii=False).encode()) + 1024 > 7_500_000:
            raise ValueError('Conversation storage needs administrator archival')

    def get(self, chat):
        identifier(chat)
        with self.lock:
            if chat not in self.items:
                raise ValueError('Unknown conversation')
            return dict(self.items[chat])

    def listing(self):
        with self.lock:
            items = [dict(item) for item in reversed(list(self.items.values()))][:100]
            sessions = {item['session']: item for item in items if item.get('session')}
            self.title_cache = {session:title for session,title in self.title_cache.items() if session in sessions}
            pending = any(item.get('native_title') and session not in self.title_cache for session,item in sessions.items())
            refresh = self.chamber and sessions and time.monotonic() - self.titles_checked >= (3 if pending else 30)
            if refresh:
                self.titles_checked = time.monotonic()
        if refresh:
            cursor = None
            missing = set(sessions)
            try:
                for _ in range(5):
                    query = {'limit': 100, **({'cursor': cursor} if cursor else {'order': 'desc'})}
                    page = self.chamber.request('/api/session?' + urlencode(query))
                    for entry in page['data']:
                        session, title = entry.get('id'), entry.get('title')
                        if session not in sessions:
                            continue
                        missing.discard(session)
                        if not isinstance(title, str) or not title.strip():
                            continue
                        item = sessions[session]
                        language = chat_language(item)
                        label = ui.text(MODES[item['mode']], lang=language)
                        # A seeded raw-message title is not an AI summary.
                        if (title == chat_session_title(label, item['title']) or title == chat_session_title(label, '')
                            or title == label or re.fullmatch(r'New session - \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z', title)):
                            continue
                        title = ' '.join(title.removeprefix('GoodMorning · ').split())[:160]
                        with self.lock:
                            self.title_cache[session] = title
                    next_cursor = page.get('cursor', {}).get('next')
                    if not missing or not next_cursor or next_cursor == cursor:
                        break
                    cursor = next_cursor
            except Exception:
                pass  # Title lookup must not hide preserved conversations during an outage.
        with self.lock:
            return [{'id': item['id'], 'mode': item['mode'],
                     'title': ((item['title'] or ui.text(OUTREACH_TITLE)) if 'opening' in item else
                               self.title_cache.get(item.get('session')) or ui.text(MODES[item['mode']])),
                     'title_pending': bool(item.get('native_title') and item.get('session') not in self.title_cache),
                     **({'unread': True} if item.get('unread') else {}),
                     **({'created': item['created']} if isinstance(item.get('created'), (int, float)) else {})}
                    for item in items]

    def park(self, chat, session, forms):
        """Saves each open engine question, then closes it there. The engine holds a waiting question
        only in memory; the saved copy outlives restarts, and the answer later continues as a new turn."""
        if not forms:
            return
        with self.lock:
            item = self.items[chat]
            questions = item.setdefault('questions', [])
            known = {entry['id']: entry for entry in questions}
            additions = [{'id': form['id'], 'form': form, 'after': None, 'language': chat_language(item, latest=True)}
                         for form in forms if form['id'] not in known]
            if additions:
                self.capacity(additions)
                questions.extend(additions)
            for entry in questions:
                if entry['id'] in {form['id'] for form in forms}:
                    entry['parked'] = True
            self.save()  # Saved before closing, so a crash in between loses nothing.
        for form in forms:
            if close_question(self.chamber, session, form['id']) is False:
                with self.lock:
                    next(entry for entry in self.items[chat]['questions'] if entry['id'] == form['id']).pop('parked', None)
                    self.save()

    def start(self, body):
        if set(body) not in ({'id', 'mode', 'text'}, {'id', 'mode', 'text', 'attachments'}) or body['mode'] not in NEW_MODES:
            raise ValueError('Start a Secretary conversation')
        chat, text = identifier(body['id']), message(body['text'])
        attachments = [self.uploads.get(value) for value in attachment_ids(body)]
        with self.lock:
            if chat in self.items:
                item = self.items[chat]
                if not item['turns'] or item['mode'] != body['mode'] or item['turns'][0]['text'] != text or item['turns'][0].get('attachments', []) != attachments:
                    raise ValueError('Request ID already belongs to another conversation')
                return {'chat': chat}
            if not self.chamber:
                raise ValueError('The secretary is not connected')
            if len(self.items) >= 500:
                raise ValueError('Conversation storage needs administrator archival')
            self.capacity({'text': text, 'attachments': attachments})
            item = {'id': chat, 'mode': body['mode'], 'title': ui.text(MODES[body['mode']]),
                    'native_title': True,
                    'state': 'starting', 'turns': [{'id': chat, 'text': text, 'attachments': attachments,'language':ui.current(),'model':site_models.current()}],
                    'created': time.time()}
            self.items[chat] = item
            self.save()  # Save intent before any model request; never blindly replay.
            threading.Thread(target=self.dispatch, args=(chat, chat, text, True), daemon=True).start()
        return {'chat': chat}

    def outreach(self, body):
        """The administrator's exact words, delivered in the secretary's voice; no model runs until the user replies."""
        if set(body) - {'title'} != {'id', 'text'}:
            raise ValueError('Send an id and the message text')
        chat, text = identifier(body['id']), message(body['text'])
        title = ' '.join(str(body.get('title') or '').split())[:160]  # Empty: the default follows the account language.
        if not text:
            raise ValueError('Write the message first')
        with self.lock:
            if chat in self.items:
                item = self.items[chat]
                if item.get('opening', {}).get('text') != text:
                    raise ValueError('Request ID already belongs to another conversation')
                return {'chat': chat}
            if len(self.items) >= 500:
                raise ValueError('Conversation storage needs administrator archival')
            self.capacity({'text': text, 'title': title})
            now = time.time()
            self.items[chat] = {'id': chat, 'mode': 'secretary', 'title': title, 'state': 'idle', 'turns': [],
                                'opening': {'id': 'opening-' + chat, 'text': text, 'language': ui.current(), 'created': now},
                                'unread': True, 'created': now}
            self.save()
        return {'chat': chat}

    def seen(self, chat):
        with self.lock:
            self.get(chat)
            if self.items[chat].pop('unread', None):
                self.save()
        return {'seen': True}

    def send(self, chat, body):
        if set(body) not in ({'id', 'text'}, {'id', 'text', 'attachments'}):
            raise ValueError('Invalid message')
        request, text = identifier(body['id']), message(body['text'])
        attachments = [self.uploads.get(value) for value in attachment_ids(body)]
        if not text and not attachments:
            raise ValueError('Write a reply first')
        with self.lock:
            self.get(chat)
            item = self.items[chat]
            old = next((turn for turn in item['turns'] if turn['id'] == request), None)
            if old:
                if old['text'] != text or old.get('attachments', []) != attachments:
                    raise ValueError('Request ID already belongs to another message')
                return {'chat': chat}
            status = self.status(chat)
            state = status['state']
            if state == 'waiting':
                if status['permissions']:
                    raise ValueError('Answer the pending question first')
                state = 'idle'  # A new message skips the saved questions; the engine already closed them.
            if state == 'uncertain':
                raise ValueError('Checking whether your last message reached your secretary. Try again in a moment.')
            if state == 'unavailable':
                raise ValueError('The secretary connection is unavailable. Your conversation is preserved. Try again in a moment.')
            if state not in ('idle', 'running', 'starting'):
                raise ValueError('Wait for the secretary or answer the pending question')
            if len(item['turns']) >= 200:
                raise ValueError('Start a new conversation to keep context bounded')
            self.capacity({'text': text, 'attachments': attachments})
            # A secretary-opened conversation has no session until the user's first reply. After a
            # first message that never reached the engine, the next one opens the conversation
            # again. A first message still being opened ('starting') is awaited instead.
            first = item['state'] == 'idle' and all(turn.get('undelivered') for turn in item['turns'])
            item['turns'].append({'id': request, 'text': text, 'attachments': attachments,'language':ui.current(),'model':site_models.current(), 'created': time.time()})
            for entry in item.get('questions', []):
                if entry.get('parked') and 'answer' not in entry:
                    entry.setdefault('skipped', request)
            item['state'] = 'starting'
            item.pop('unread', None)
            self.save()
            threading.Thread(target=self.dispatch, args=(item['id'], request, text, first), daemon=True).start()
        return {'chat': chat}

    def dispatch(self, chat_id, turn_id, text, first):
        try:
            refresh = False
            with self.lock:
                item = self.items.get(chat_id)
                if item is None:
                    return
                turn = next((entry for entry in item['turns'] if entry['id'] == turn_id), None)
                if turn is None:
                    return
                selected = turn.get('language', 'en')
                chosen = turn.get('model', site_models.DEFAULT)
                attachments = list(turn.get('attachments', []))
                mode = item['mode']
                runtime = self.runtime
                opening = item.get('opening') if first else None
            if first:
                # A custom title disables the engine's built-in AI title generation.
                result = self.chamber.control('session.create')
                session = result['sessionId']
                if not re.fullmatch('ses[A-Za-z0-9_]+', session):
                    raise ValueError('Invalid session')
                with self.lock:
                    item = self.items.get(chat_id)
                    if item is None:
                        return
                    item['session'] = session
                    self.save()
            else:
                # A follow-up sent while the first dispatch is still opening
                # has no session yet. Wait briefly rather than failing the
                # interrupt; the opening dispatch creates it.
                session = None
                for _ in range(100):
                    with self.lock:
                        item = self.items.get(chat_id)
                        if item is None:
                            return
                        session = item.get('session')
                    if session:
                        break
                    time.sleep(0.1)
                if not session:
                    raise ValueError('Wait for the secretary or answer the pending question')
                refresh = self.chamber.relocate(session)
            # The secretary agent (.opencode/agents) is denied reading source code and tests.
            # OpenChamber keeps an agent given to session.create only when that create also
            # sends a prompt, and the attachment path names none, so set it before every turn.
            self.chamber.request(f'/api/session/{session}/agent', {'agent': 'secretary'})
            site_models.apply_to_session(self.chamber, session, chosen)
            # Older To-do/Eureka chats continue under the Secretary workflow.
            prompt = (f"/{mode if mode in NEW_MODES else 'secretary'}\nBrowser chat: {chat_id}\nRuntime: {runtime}\n" if first or refresh else '')
            if refresh:
                prompt += 'Workflow refresh: true\n'
            prompt += (f"Native session ID: {session}\n"
                       "Use this ID for --session and calendar --actor; browser chat/message IDs are not session IDs.\n")
            from goodmorning.runtime_files import profile_fields
            fields=profile_fields(runtime)
            tone=fields.get('secretary_tone')
            tone_context={'value':tone or 'warm and helpful','source':'saved' if tone else 'default'}
            prompt += (f"Website language: {selected}\n"
                       f"Secretary tone at request start: {json.dumps(tone_context,ensure_ascii=False)}\n")
            if fields.get('user_name'):
                prompt += f"Call the user: {json.dumps(fields['user_name'],ensure_ascii=False)}\n"
            if opening:
                prompt += f"Secretary opening: {json.dumps(opening['text'],ensure_ascii=False)}\n"
            prompt += f"\n{text}"
            if attachments:
                # Distinguish file-only turns with identical text when matching
                # acknowledged messages and restoring their attachment labels.
                prompt += f"\n\nBrowser message: {turn_id}"
            prompt=prompt.strip()
            with self.lock:
                item = self.items.get(chat_id)
                if item is None:
                    return
                turn = next((entry for entry in item['turns'] if entry['id'] == turn_id), None)
                if turn is None:
                    return
                turn['prompt_hash'] = hashlib.sha256(prompt.encode()).hexdigest()
                self.save()
            if attachments:
                # OpenChamber's composer uses this native V2 prompt API. Control's
                # text-only session.send drops files, so it cannot carry attachments.
                result = self.chamber.request(f'/api/session/{session}/prompt',
                    {'text': prompt, 'files': self.uploads.files([entry['id'] for entry in attachments])})
                receipt = result.get('data', {})
                if not isinstance(receipt.get('id'), str) or not receipt['id']:
                    raise ValueError('Message dispatch was not confirmed')
            else:
                result = self.chamber.control('session.send', sessionId=session, prompt=prompt)
                if result.get('promptDispatched') is not True:
                    raise ValueError('Message dispatch was not confirmed')
            with self.lock:
                item = self.items.get(chat_id)
                if item is None:
                    return
                item['state'] = 'running'
                self.save()
        except Exception:
            with self.lock:
                item = self.items.get(chat_id)
                if item is None:
                    return
                # A stale dispatch must not mark a newer interrupt as uncertain.
                if item['turns'] and item['turns'][-1]['id'] != turn_id:
                    self.save()
                    return
                item.update(state='uncertain', uncertain_since=time.time())
                self.save()

    def settle(self, chat):
        """Resolve uncertain delivery from the engine's own transcript, never by replaying it.
        An acknowledged prompt continues; one the engine never received is marked not sent,
        and an answer that never arrived reopens its saved question."""
        with self.lock:
            item = self.items[chat]
            turn = item['turns'][-1] if item['turns'] else None
            session = item.get('session')
            prompt = turn and turn.get('prompt_hash')
            # Identical prompts (two plain "Yes" replies) each need their own acknowledgment.
            needed = sum(entry.get('prompt_hash') == prompt and not entry.get('undelivered') for entry in item['turns'])
            waited = time.time() - item.get('uncertain_since', 0)
        # The prompt hash is saved before sending and the session before the prompt is built.
        delivered = False
        if session and prompt:
            if not self.chamber:
                return
            page = self.chamber.request(f'/api/session/{session}/message?type=user&limit=200&order=desc')
            delivered = sum(entry.get('type') == 'user' and isinstance(entry.get('text'), str)
                            and hashlib.sha256(entry['text'].strip().encode()).hexdigest() == prompt
                            for entry in page['data']) >= needed
            if not delivered:
                status = self.chamber.control('session.status', sessionId=session)['sessionStatus']['type']
                if status != 'idle' or waited < DELIVERY_GRACE:
                    return
        with self.lock:
            item = self.items[chat]
            if item['state'] != 'uncertain' or (item['turns'][-1] if item['turns'] else None) is not turn:
                return
            item.pop('uncertain_since', None)
            if delivered:
                item['state'] = 'running'
            else:
                item['state'] = 'idle'
                question = next((entry for entry in item.get('questions', []) if turn and entry['id'] == turn.get('answer')), None)
                if question:
                    item['turns'].remove(turn)
                    question.pop('answer')
                    question['unsent'] = True
                elif turn:
                    turn['undelivered'] = True
            self.save()

    def status(self, chat, *, include_messages=True, limit=100):
        if not isinstance(limit, int) or not 100 <= limit <= 1000:
            raise ValueError('Invalid history request')
        if self.get(chat)['state'] == 'uncertain':
            try:
                self.settle(chat)
            except Exception:
                pass  # Still uncertain; the next status read checks again.
        item = self.get(chat)
        sent = [turn for turn in item['turns'] if not turn.get('undelivered')]
        try:
            from goodmorning.runtime_files import profile_fields, normalize_secretary_name
            secretary_name = normalize_secretary_name(profile_fields(self.runtime).get("secretary_name", "")) or None
        except (ValueError, OSError):
            secretary_name = None
        result = {'chat': chat, 'mode': item['mode'], 'state': item['state'], 'forms': [], 'permissions': [],'language':chat_language(item, latest=True),
                  'secretary_name': secretary_name, **({'unread': True} if item.get('unread') else {})}
        opening = [opening_message(item['opening'])] if 'opening' in item else []
        undelivered = item['turns'][-1] if item['turns'] and item['turns'][-1].get('undelivered') else None
        if undelivered and include_messages:
            undelivered = {'id': 'undelivered:' + undelivered['id'], 'role': 'user', 'kind': 'undelivered',
                           'text': self.turn_text(item, undelivered), 'attachments': self.turn_attachments(undelivered),
                           'turn': undelivered['id']}
        if not item.get('session') and include_messages:
            result['messages'] = opening + ([undelivered] if undelivered else [])
        expired = False
        if item.get('session') and self.chamber:
            try:
                forms, permissions = self.chamber.pending(item['session'])
                self.park(chat, item['session'], forms)
                with self.lock:
                    questions = [dict(entry) for entry in self.items[chat].get('questions', [])]
                if include_messages:
                    transcript = self.chamber.control('session.messages', sessionId=item['session'], limit=limit)
                else:
                    # Queue reconciliation must not depend on a renderable transcript.
                    # Confirm the latest user turn was accepted before releasing idle work.
                    status = self.chamber.control('session.status', sessionId=item['session'])
                    page = self.chamber.request(f'/api/session/{item["session"]}/message?type=user&limit=1&order=desc')
                    transcript = {**status, 'messages': [
                        {**entry, 'role': 'user'} for entry in page['data'] if entry.get('type') == 'user']}
                messages = []
                originals, matched_turns = {}, {}
                for turn in sent:
                    originals.setdefault(turn.get('prompt_hash'), []).append(turn)
                # Match from the newest end of the bounded window. Repeated text
                # (for example, two "Yes" replies) still belongs to distinct turns.
                for entry in reversed(transcript['messages'] if include_messages else []):
                    if entry.get('role') == 'user' and isinstance(entry.get('text'), str):
                        candidates = originals.get(hashlib.sha256(entry['text'].encode()).hexdigest())
                        if candidates:
                            matched_turns[entry['id']] = candidates.pop()
                for entry in (transcript['messages'] if include_messages else []):
                    if entry.get('role') not in ('user', 'assistant') or not isinstance(entry.get('text'), str):
                        continue
                    text = entry['text']
                    attachments = []
                    turn = None
                    if entry['role'] == 'user':
                        turn = matched_turns.get(entry['id'])
                        if turn:
                            attachments = self.turn_attachments(turn)
                            text = self.turn_text(item, turn)
                    visible = {'id': entry['id'], 'role': entry['role'], 'text': text, 'attachments': attachments}
                    question = next((saved for saved in questions if saved['id'] == turn.get('answer')), None) if turn else None
                    if question:
                        visible.update(kind='answer', language=question['language'],
                                       text=answer_text(question['form'], question['answer'], question['language']))
                    if turn:
                        visible['_turn'] = turn['id']
                    if entry.get('kind') == 'expired':
                        visible.update(kind='expired', _tools=entry['tools'])
                    messages.append(visible)
                messages, shown = expired_questions(messages, questions, result['language'])
                forms = parked_forms(questions)
                receipts = item.get('replied_inputs', [])
                permissions = [permission for permission in permissions if 'permission:'+permission['id'] not in receipts]
                result.update(forms=forms, permissions=permissions)
                if include_messages:
                    from .chat_actions import read_changes, action_history
                    with self.lock:
                        aliases = {item['id'], *(turn['id'] for turn in item['turns'])}
                        expected_aliases = len(aliases)
                        for other in self.items.values():
                            if other['id'] != item['id']:
                                aliases.difference_update((other['id'], *(turn['id'] for turn in other['turns'])))
                    changes, unavailable = read_changes(self.runtime, item['session'], aliases=aliases)
                    unavailable = unavailable or len(aliases) != expected_aliases
                    # Saved questions show at their own place in the transcript, and their answers as turns.
                    history = question_history(messages, [entry for entry in questions if entry['id'] not in shown and not entry.get('parked')],
                                               {form['id'] for form in forms}, not transcript['more'])
                    result.update(messages=opening + action_history(history, changes, sent, item['created'])
                                  + ([undelivered] if undelivered else []),
                                  action_history_unavailable=unavailable,
                                  history_limited=transcript['more'])
                if (forms or permissions) and item['state'] not in ('starting', 'uncertain'):
                    result['reservation_required'] = False
                expired = include_messages and bool(messages) and messages[-1].get('kind') == 'expired'
                if item['state'] not in ('starting', 'uncertain'):
                    state = transcript['sessionStatus']['type']
                    # A chat whose only message was never sent has no turn to wait for.
                    last_prompt = sent[-1].get('prompt_hash') if sent else None
                    seen = not sent or any(entry.get('role') == 'user' and isinstance(entry.get('text'), str)
                               and hashlib.sha256(entry['text'].strip().encode()).hexdigest() == last_prompt
                               for entry in transcript['messages'])
                    result['state'] = 'waiting' if forms or permissions else 'idle' if state == 'idle' and seen else 'running' if state in ('busy', 'idle', 'retry') else 'uncertain'
            except Exception:
                result['state'] = 'unavailable'
        with self.lock:
            if self.title_states.get(chat) != result['state'] and result['state'] in ('idle', 'waiting'):
                self.titles_checked = float('-inf')
            self.title_states[chat] = result['state']
        result['label'] = {'starting': 'Opening your conversation', 'running': 'Your secretary is working',
                           'waiting': 'Your answer didn’t reach your secretary. Please answer again.' if any(
                               entry.get('unsent') and 'answer' not in entry and 'skipped' not in entry for entry in item.get('questions', [])) else 'Your secretary needs your answer',
                           'idle': 'Your secretary’s question expired. Send a message to continue.' if expired
                                   else 'Your last message wasn’t sent. Send it again or write a new one.' if undelivered else 'Ready for your reply',
                           'uncertain': 'Checking whether your last message reached your secretary…',
                           'unavailable': 'The secretary connection is unavailable. Your conversation is preserved.'}[result['state']]
        result['label']=ui.text(result['label'])
        return result

    def turn_text(self, item, turn):
        language = turn.get('language', 'en')
        return turn['text'] or ('' if turn.get('attachments') else ui.text(
            'Start {mode}', lang=language, mode=ui.text(MODES[item['mode']], lang=language).lower()))

    def turn_attachments(self, turn):
        attachments = [dict(attachment) for attachment in turn.get('attachments', [])]
        for attachment in attachments:
            try:
                mime = self.uploads.get(attachment['id']).get('mime')
            except ValueError:
                # Expired after 30 days; the chat keeps its name and size.
                attachment.pop('mime', None)
                attachment['removed'] = True
                continue
            except OSError:
                continue
            if mime:
                attachment['mime'] = mime
        return attachments

    def reply(self, chat, category, request, body):
        with self.lock:
            item = self.get(chat)
            if not item.get('session') or category not in ('form', 'permission') or not self.chamber:
                raise ValueError('Invalid reply target')
            if category+':'+request in item.get('replied_inputs', []):
                return {'answered': True}
            forms, permissions = self.chamber.pending(item['session'])
            if category == 'form':
                return self.answer(chat, item['session'], forms, request, body)
            if not any(entry['id'] == request for entry in permissions):
                raise ValueError('This request is no longer pending in this conversation')
            if body.get('decision') not in ('once', 'reject'):
                raise ValueError('Only one-time approval or rejection is allowed')
            self.chamber.request(f'/api/session/{item["session"]}/permission/{request}/reply', {'decision': body['decision']})
            self.items[chat].setdefault('replied_inputs', []).append('permission:'+request)
            self.save()
        return {'answered': True}

    def answer(self, chat, session, forms, request, body):
        """Delivers an answer to a saved question as a new turn of the same session. The answer and its
        turn are saved together before dispatch, so a retried or second answer never sends twice."""
        self.park(chat, session, forms)  # An answer can arrive before any read saved the question.
        with self.lock:
            item = self.items[chat]
            question = next((entry for entry in item.get('questions', []) if entry['id'] == request and entry.get('parked')), None)
            if question is None or 'skipped' in question:
                raise ValueError('This request is no longer pending in this conversation')
            if 'answer' in question:
                return {'answered': True}
            if item['state'] in ('starting', 'uncertain'):
                raise ValueError('Wait for the secretary or answer the pending question')
            answer = valid_answer(question['form'], body.get('answer'))
            if len(item['turns']) >= 200:
                raise ValueError('Start a new conversation to keep context bounded')
            text = model_answer(question['form'], answer)
            self.capacity({'answer': answer, 'text': text})
            turn = hashlib.sha256(('answer:' + chat + ':' + request).encode()).hexdigest()[:32]
            item['turns'].append({'id': turn, 'text': text, 'answer': request, 'attachments': [], 'language': ui.current(),
                                  'model': site_models.current(), 'created': time.time()})
            question['answer'] = answer
            question.pop('unsent', None)
            item['state'] = 'starting'
            self.save()
            threading.Thread(target=self.dispatch, args=(chat, turn, text, False), daemon=True).start()
        return {'answered': True}


def page(csrf, ready, connected, secretary_name=None, avatar='f1', avatar_urls=None, timezone='UTC', theme='gm'):
    if avatar not in AVATAR_IDS and not (avatar == 'custom' and (avatar_urls or {}).get('custom')):
        avatar = 'f1'
    sources = dict(avatar_urls) if avatar_urls else {}
    for entry, files in AVATAR_FILES.items():
        sources.setdefault(entry, {variant: '/' + name for variant, name in files.items()})
    config = html.escape(json.dumps({'csrf': csrf, 'workspaceScope': hashlib.sha256(('chat-workspace:' + csrf).encode()).hexdigest(),
                                    'defaultMode': 'secretary' if ready else 'initialize',
                                    'maxUploadBytes': MAX_UPLOAD_BYTES,
                                    'timezone': timezone,
                                   'connected': connected, 'secretary_name': secretary_name,
                                   'avatar': avatar, 'avatars': [{'id': entry, **source} for entry, source in sources.items()]}), quote=True)
    heading = html.escape(secretary_name) if secretary_name else 'Your secretary'
    conversation_name = html.escape(secretary_name) if secretary_name else ui.text('Your secretary')
    title = (html.escape(secretary_name) + ' — GoodMorning') if secretary_name else 'Your secretary — GoodMorning'
    return ('<!doctype html><html lang="en" data-edition="' + ('gn' if theme == 'gn' else 'gm') + '"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<title>' + title + '</title>' + favicon_links('secretary') + '<link rel="stylesheet" href="/briefing.css">'
            '<link rel="stylesheet" href="/chat.css"><link rel="stylesheet" href="/avatar.css">'
            '<link rel="stylesheet" href="/scroll-rails.css"><script src="/scroll-rails.js" defer></script></head><body class="chat-page">'
            '<a class="skip-link" href="#conversation">Skip to conversation</a>'
            '<header class="masthead"><a class="wordmark" href="/chat">GoodMorning<span>A personal secretary just for you</span></a>'
            '<nav class="edition-switch" aria-label="Your desk"><a class="edition-link" href="/gm.html">Morning</a>'
            '<a class="edition-link" href="/gn.html">Evening</a><a class="edition-link" href="/schedule">Schedule</a><a class="edition-link" href="/letters">Letters</a><a class="edition-link selected" href="/chat" aria-current="page">Secretary</a></nav></header>'
            '<main class="chat-layout"><aside class="conversation-sidebar">'
            '<div class="secretary-identity">' + avatar_widget(avatar, sources, theme=theme) +
            '<p class="eyebrow">Your desk</p>'
            '<h1 id="secretary-heading">' + heading + '</h1><p>A place for your plans, bright ideas, and the details that make this yours.</p>'
             '</div><section id="conversation-history" aria-labelledby="history-heading">'
             '<header class="history-header"><p class="eyebrow">Your conversations</p><h2 id="history-heading">History conversations</h2></header>'
             '<nav id="chat-history" aria-label="History conversations"></nav>'
             '<p id="history-notice" role="status">Loading conversations…</p><button id="history-retry" type="button" hidden>Try again</button></section></aside>'
             '<section class="conversation-panel" id="conversation" aria-label="Secretary conversation">'
              '<h2 id="conversation-name" class="chat-visually-hidden" data-content>'+conversation_name+'</h2>'
              '<header class="chat-topic-header"><div><p class="eyebrow" id="chat-topic-mode"></p><h2 id="chat-topic">New conversation</h2></div>'
              '<button id="new-conversation" type="button"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg><span>New conversation</span></button></header>'
              '<p class="chat-topic-hint">Continue this topic, or start a new conversation for something different.</p>'
              '<p id="chat-resume-notice" role="status" hidden><span>A fresh space after 15 minutes away.</span> <a id="chat-resume" href="/chat">Resume previous conversation</a></p>'
             '<div class="chat-help-row"><button id="chat-help" type="button" aria-controls="chat-guide" aria-expanded="false">'
             '<span class="chat-help-mark" aria-hidden="true">?</span><span>What can I ask?</span></button></div>'
             '<div id="chat-guide" hidden>'
              '<p data-guide="initialize"' + (' hidden' if ready else '') + '><strong>Initialize</strong> — Set up your secretary for the first time, or review your location, timezone, name and preferences. Existing records and saved work stay intact.</p>'
              '<div data-guide="secretary"' + ('' if ready else ' hidden') + '><p>Everything happens in this one conversation. Just say what you need.</p><ul>'
               '<li><strong>Save a to-do or an idea</strong> <em>“Call the dentist on Friday”</em> <span>Your secretary tells you whether it was saved as a to-do or an idea.</span></li>'
               '<li><strong>Plan and review</strong> <em>“What’s due this week?”</em></li>'
               '<li><strong>Have something checked for you</strong> <em>“Tell me when the train tickets drop under £40”</em></li>'
               '<li><strong>Change your preferences</strong> <em>“I moved to Leeds”</em></li></ul>'
              '<p>When it’s unclear whether you want something saved or done, your secretary asks first. Saving never starts the work, and changes that need your approval are confirmed first.</p></div>'
              '<p>Returning from another website tab resumes your conversation. After 15 minutes away, settled conversations open as a fresh draft; your history is preserved.</p>'
              '<p>Write naturally; no commands are needed. Enter sends your message; Shift+Enter adds a new line. Use the paperclip, paste images, or drag files into the composer to attach them. Click an image preview to enlarge it. Attached files are kept for 30 days, then removed; the chat keeps their names.</p></div>'
             '<div id="chat-scroll" role="region" aria-label="Conversation" tabindex="0">'
             '<div id="chat-empty"><span class="desk-symbol" aria-hidden="true">✦</span>'
            '<h2 id="chat-welcome"></h2><p id="chat-hint"></p>'
            '<div id="chat-starters"' + ('' if ready else ' hidden') + ' aria-label="Conversation starters">'
             '<button type="button" data-starter>Remind me to…</button><button type="button" data-starter>I had an idea…</button>'
             '<button type="button" data-starter>What’s on this week?</button></div></div>'
            '<div id="chat-earlier" hidden><button type="button" id="chat-earlier-button">Show earlier messages</button>'
            '<p id="chat-earlier-note" hidden>Your earliest messages are too far back to show here.</p></div>'
            '<div id="chat-messages" role="log" aria-label="Conversation messages" aria-live="polite" aria-relevant="additions text"></div>'
              '<p id="chat-action-notice" role="status" hidden data-ui-text="Saved changes are temporarily unavailable. Your conversation is preserved."></p>'
              '<div id="chat-questions"></div><p id="chat-status" role="status"></p><p id="request-language-note" role="status"></p></div>'
             '<div class="chat-scroll-tools"><button type="button" id="chat-latest" hidden>Jump to latest</button></div>'
            '<form id="chat-compose"><label for="chat-text" id="compose-label" class="chat-visually-hidden">Your message</label>'
             '<div class="chat-input-row"><button type="button" id="chat-attach" aria-label="Attach files" aria-describedby="upload-note" title="Attach files" disabled>'
             '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true"><path d="m8 12 6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l9-9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></button>'
             '<textarea id="chat-text" rows="1" maxlength="8000" placeholder="Your message…" enterkeyhint="send"></textarea>'
            '<button type="submit" id="chat-send" disabled><span class="chat-send-label chat-visually-hidden">Send message</span>'
            '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true"><path d="m4 5 16 7-16 7 3-7-3-7Zm3 7h13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></button></div>'
            '<input id="chat-files" type="file" multiple hidden><div id="chat-attachments" aria-live="polite"></div>'
             '<span id="upload-note" class="chat-visually-hidden">Up to 50 MB per file. You can also paste images or drag files into this box. Attached files are kept for 30 days, then removed; the chat keeps their names.</span>'
             '</form><p id="chat-error" role="alert"></p>'
            '<noscript>Enable JavaScript to talk with your secretary. Saved briefings remain readable.</noscript></section></main>'
            '<div id="chat-config" hidden data-config="'+config+'"></div>'
            '<script src="/questions.js" defer></script><script src="/avatar.js" defer></script>'
            '<script src="/marked.js" defer></script><script src="/markdown.js" defer></script><script src="/chat.js" defer></script></body></html>')
