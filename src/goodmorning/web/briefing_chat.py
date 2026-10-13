"""Account-local, durable conversations for the four website secretary modes."""
import hashlib
import html
import json
import re
import threading
import time
from urllib.parse import urlencode

from goodmorning.runtime_files import atomic_text
from .briefing_resources import favicon_links
from . import language as ui
from . import models as site_models
from .session_inventory import chat_session_title
from .chat_uploads import Uploads, attachment_ids, MAX_UPLOAD_BYTES
from .avatar_images import image_url

MODES = {'initialize': 'Initialize', 'secretary': 'Secretary', 'todo': 'To-do', 'eureka': 'Eureka'}

AVATARS = (('f1', 'desk-secretary.png', 'Classic'),
           ('f2', 'desk-secretary-f2.png', 'Female 2'),
           ('m1', 'desk-secretary-m1.png', 'Male 1'),
           ('m2', 'desk-secretary-m2.png', 'Male 2'))
AVATAR_IDS = tuple(entry[0] for entry in AVATARS)
AVATAR_FILES = {entry[0]: entry[1] for entry in AVATARS}


def avatar_widget(selected='f1', sources=None, class_name='desk-figure'):
    custom = (sources or {}).get('custom')
    sources = {entry: (sources or {}).get(entry, '/' + filename) for entry, filename, _ in AVATARS}
    if custom:
        sources['custom'] = custom
    ids = tuple(sources)
    selected = selected if selected in ids else 'f1'
    options = html.escape(json.dumps([{'id': entry, 'src': sources[entry]} for entry in ids]), quote=True)
    previews = ''.join(
        f'<button type="button" class="avatar-preview" role="option" data-avatar-choice="{entry}" aria-selected="{str(entry == selected).lower()}" aria-label="Avatar {index}">'
        f'<img src="{html.escape(sources[entry], quote=True)}" alt="" width="72" height="72" loading="lazy"><span>{index}</span></button>'
        for index, entry in enumerate(ids, 1))
    return (f'<figure class="{class_name} avatar-display" data-avatar="{selected}" data-avatar-options="{options}">'
            '<div class="avatar-frame">'
            f'<img class="avatar-image" src="{html.escape(sources[selected], quote=True)}" alt="Secretary avatar" width="220" height="220">'
            '<button class="avatar-toggle" type="button" data-avatar-toggle aria-label="Change avatar" title="Change avatar" aria-expanded="false" disabled>'
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            '<path d="m16 3 5 5-3 3v10H6V11L3 8l5-5a4 4 0 0 0 8 0Z"/></svg></button></div>'
            '<div class="avatar-menu" role="dialog" aria-label="Choose an avatar" hidden>'
            '<div class="avatar-carousel"><button class="avatar-step" type="button" data-avatar-prev aria-label="Previous avatar">‹</button>'
            '<div class="avatar-previews" role="listbox" aria-label="Secretary avatars">' + previews + '</div>'
            '<button class="avatar-step" type="button" data-avatar-next aria-label="Next avatar">›</button></div>'
            '<button type="button" class="avatar-upload" data-avatar-upload>Upload your own avatar</button>'
            '<input type="file" data-avatar-file accept="image/png,image/jpeg,image/webp" aria-label="Upload your own avatar" hidden>'
            '<p class="avatar-upload-note">PNG, JPEG or WebP. Up to 5 MB.</p>'
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
        return 'f1' if selected == 'custom' and not image_url(runtime) else selected
    except (ValueError, AttributeError, TypeError):
        return 'f1'


def write_avatar(runtime, value):
    from pathlib import Path
    avatar_id(value)
    if value == 'custom' and not image_url(runtime):
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
        raise ValueError('Choose a mode using the switch instead of typing commands')
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


def question_history(messages, questions, pending):
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
            if anchor in anchors or anchor is None and len(messages) < 100:
                additions.setdefault(anchor, []).append(exchange)
    result = list(additions.get(None, []))
    for entry in messages:
        result.append(entry)
        result.extend(additions.get(entry['id'], []))
    return result


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
                item['state'] = 'uncertain'
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
                        language = item['turns'][0].get('language', 'en')
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
                     'title': self.title_cache.get(item.get('session')) or ui.text(MODES[item['mode']]),
                     'title_pending': bool(item.get('native_title') and item.get('session') not in self.title_cache)}
                    for item in items]

    def remember_questions(self, chat, forms, messages):
        with self.lock:
            item = self.items[chat]
            questions = item.setdefault('questions', [])
            known = {entry['id'] for entry in questions}
            additions = [{'id': form['id'], 'form': form, 'after': messages[-1]['id'] if messages else None,
                          'language': item['turns'][-1].get('language', 'en')}
                         for form in forms if form['id'] not in known]
            if additions:
                self.capacity(additions)
                questions.extend(additions)
                self.save()
            return list(questions)

    def start(self, body):
        if set(body) not in ({'id', 'mode', 'text'}, {'id', 'mode', 'text', 'attachments'}) or body['mode'] not in MODES:
            raise ValueError('Choose one of the four secretary modes')
        chat, text = identifier(body['id']), message(body['text'])
        attachments = [self.uploads.get(value) for value in attachment_ids(body)]
        if not text and not attachments and body['mode'] not in ('initialize', 'secretary'):
            raise ValueError('Write the task or idea you want to save')
        with self.lock:
            if chat in self.items:
                item = self.items[chat]
                if item['mode'] != body['mode'] or item['turns'][0]['text'] != text or item['turns'][0].get('attachments', []) != attachments:
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
            state = self.status(chat)['state']
            if state == 'waiting':
                raise ValueError('Answer the pending question first')
            if state in ('uncertain', 'unavailable'):
                raise ValueError('Delivery is uncertain. Ask the administrator to inspect this conversation before sending again.')
            if state not in ('idle', 'running', 'starting'):
                raise ValueError('Wait for the secretary or answer the pending question')
            if len(item['turns']) >= 200:
                raise ValueError('Start a new conversation to keep context bounded')
            self.capacity({'text': text, 'attachments': attachments})
            item['turns'].append({'id': request, 'text': text, 'attachments': attachments,'language':ui.current(),'model':site_models.current()})
            item['state'] = 'starting'
            self.save()
            threading.Thread(target=self.dispatch, args=(item['id'], request, text, False), daemon=True).start()
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
                # A session keeps its original release location across server updates.
                # Move only this resumed conversation, without replacing its history.
                info = self.chamber.request(f'/api/session/{session}')['data']
                if info['location']['directory'] != self.chamber.directory:
                    self.chamber.request(f'/api/session/{session}/move',
                                         {'directory': self.chamber.directory})
                    info = self.chamber.request(f'/api/session/{session}')['data']
                    if info['location']['directory'] != self.chamber.directory:
                        raise ValueError('Conversation release update was not confirmed')
                    refresh = True
            site_models.apply_to_session(self.chamber, session, chosen)
            prompt = (f"/{mode}\nBrowser chat: {chat_id}\nRuntime: {runtime}\n" if first or refresh else '')
            if refresh:
                prompt += 'Workflow refresh: true\n'
            prompt += f"Website language: {selected}\n\n{text}"
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
                item['state'] = 'uncertain'
                self.save()

    def status(self, chat, *, include_messages=True):
        item = self.get(chat)
        try:
            from goodmorning.runtime_files import profile_fields, normalize_secretary_name
            secretary_name = normalize_secretary_name(profile_fields(self.runtime).get("secretary_name", "")) or None
        except (ValueError, OSError):
            secretary_name = None
        result = {'chat': chat, 'mode': item['mode'], 'state': item['state'], 'forms': [], 'permissions': [],'language':item['turns'][-1].get('language') if item['turns'] else None,
                  'secretary_name': secretary_name}
        if item.get('session') and self.chamber:
            try:
                forms, permissions = self.chamber.pending(item['session'])
                if include_messages:
                    transcript = self.chamber.control('session.messages', sessionId=item['session'], limit=100)
                else:
                    # Queue reconciliation must not depend on a renderable transcript.
                    # Confirm the latest user turn was accepted before releasing idle work.
                    status = self.chamber.control('session.status', sessionId=item['session'])
                    page = self.chamber.request(f'/api/session/{item["session"]}/message?type=user&limit=1&order=desc')
                    transcript = {**status, 'messages': [
                        {**entry, 'role': 'user'} for entry in page['data'] if entry.get('type') == 'user']}
                messages = []
                originals = {turn.get('prompt_hash'): turn
                               for turn in item['turns']}
                for entry in (transcript['messages'] if include_messages else []):
                    if entry.get('role') not in ('user', 'assistant') or not isinstance(entry.get('text'), str):
                        continue
                    text = entry['text']
                    attachments = []
                    if entry['role'] == 'user':
                        turn = originals.get(hashlib.sha256(text.encode()).hexdigest())
                        if turn:
                            attachments = [dict(attachment) for attachment in turn.get('attachments', [])]
                            for attachment in attachments:
                                if 'mime' in attachment:
                                    continue
                                try:
                                    mime = self.uploads.get(attachment['id']).get('mime')
                                except (ValueError, OSError):
                                    continue
                                if mime:
                                    attachment['mime'] = mime
                            text = turn['text'] or ('' if attachments else ui.text('Start {mode}',lang=turn.get('language','en'),
                                mode=ui.text(MODES[item['mode']],lang=turn.get('language','en')).lower()))
                    messages.append({'id': entry['id'], 'role': entry['role'], 'text': text, 'attachments': attachments})
                questions = self.remember_questions(chat, forms, messages) if include_messages else item.get('questions', [])
                answered = {entry['id'] for entry in questions if 'answer' in entry}
                forms = [form for form in forms if form['id'] not in answered]
                receipts = item.get('replied_inputs', [])
                forms = [form for form in forms if 'form:'+form['id'] not in receipts]
                permissions = [permission for permission in permissions if 'permission:'+permission['id'] not in receipts]
                result.update(forms=forms, permissions=permissions)
                if include_messages:
                    result.update(messages=question_history(messages, questions, {form['id'] for form in forms}),
                                  history_limited=len(messages) >= 100)
                if (forms or permissions) and item['state'] not in ('starting', 'uncertain'):
                    result['reservation_required'] = False
                if item['state'] not in ('starting', 'uncertain'):
                    state = transcript['sessionStatus']['type']
                    last_prompt = item['turns'][-1].get('prompt_hash')
                    seen = any(entry.get('role') == 'user' and isinstance(entry.get('text'), str)
                               and hashlib.sha256(entry['text'].strip().encode()).hexdigest() == last_prompt
                               for entry in transcript['messages'])
                    result['state'] = 'waiting' if forms or permissions else 'idle' if state == 'idle' and seen else 'running' if state in ('busy', 'idle') else 'uncertain'
            except Exception:
                result['state'] = 'unavailable'
        with self.lock:
            if self.title_states.get(chat) != result['state'] and result['state'] in ('idle', 'waiting'):
                self.titles_checked = float('-inf')
            self.title_states[chat] = result['state']
        result['label'] = {'starting': 'Opening your conversation', 'running': 'Your secretary is working',
                           'waiting': 'Your secretary needs your answer', 'idle': 'Ready for your reply',
                           'uncertain': 'Delivery is uncertain. Ask the administrator to inspect this conversation before sending again.',
                           'unavailable': 'The secretary connection is unavailable. Your conversation is preserved.'}[result['state']]
        result['label']=ui.text(result['label'])
        return result

    def reply(self, chat, category, request, body):
        with self.lock:
            item = self.get(chat)
            if not item.get('session') or category not in ('form', 'permission') or not self.chamber:
                raise ValueError('Invalid reply target')
            if category+':'+request in item.get('replied_inputs', []):
                return {'answered': True}
            forms, permissions = self.chamber.pending(item['session'])
            if not any(entry['id'] == request for entry in (forms if category == 'form' else permissions)):
                raise ValueError('This request is no longer pending in this conversation')
            if category == 'form':
                if not isinstance(body.get('answer'), dict):
                    raise ValueError('Invalid answer')
                body = {'answer': body['answer']}
                transcript = self.chamber.control('session.messages', sessionId=item['session'], limit=100)['messages']
                questions = self.remember_questions(chat, forms, transcript)
                question = next(entry for entry in questions if entry['id'] == request)
                self.capacity(body)
            else:
                if body.get('decision') not in ('once', 'reject'):
                    raise ValueError('Only one-time approval or rejection is allowed')
                body = {'decision': body['decision']}
            self.chamber.request(f'/api/session/{item["session"]}/{category}/{request}/reply', body)
            item.setdefault('replied_inputs', []).append(category+':'+request)
            if category == 'form':
                question.update(answer=body['answer'], answer_after=transcript[-1]['id'] if transcript else None)
            self.save()
        return {'answered': True}


def page(csrf, ready, connected, secretary_name=None, avatar='f1', avatar_urls=None, timezone='UTC', theme='gm'):
    if avatar not in AVATAR_IDS and not (avatar == 'custom' and (avatar_urls or {}).get('custom')):
        avatar = 'f1'
    sources = dict(avatar_urls) if avatar_urls else {}
    for entry, filename in AVATAR_FILES.items():
        sources.setdefault(entry, '/' + filename)
    config = html.escape(json.dumps({'csrf': csrf, 'defaultMode': 'secretary' if ready else 'initialize',
                                    'maxUploadBytes': MAX_UPLOAD_BYTES,
                                    'timezone': timezone,
                                   'connected': connected, 'secretary_name': secretary_name,
                                   'avatar': avatar, 'avatars': [{'id': entry, 'src': source} for entry, source in sources.items()]}), quote=True)
    choices = ''.join(f'<button type="button" role="radio" aria-checked="false" data-mode="{mode}">{label}</button>'
                      for mode, label in MODES.items())
    heading = html.escape(secretary_name) if secretary_name else 'Your secretary'
    conversation_name = html.escape(secretary_name) if secretary_name else ui.text('Your secretary')
    title = (html.escape(secretary_name) + ' — GoodMorning') if secretary_name else 'Your secretary — GoodMorning'
    return ('<!doctype html><html lang="en" data-edition="' + ('gn' if theme == 'gn' else 'gm') + '"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<title>' + title + '</title>' + favicon_links('secretary') + '<link rel="stylesheet" href="/briefing.css">'
            '<link rel="stylesheet" href="/chat.css"><link rel="stylesheet" href="/avatar.css"></head><body class="chat-page">'
            '<a class="skip-link" href="#conversation">Skip to conversation</a>'
            '<header class="masthead"><a class="wordmark" href="/chat">GoodMorning<span>A little space to think, plan, and begin.</span></a>'
            '<nav class="edition-switch" aria-label="Your desk"><a class="edition-link" href="/gm.html">Morning</a>'
            '<a class="edition-link" href="/gn.html">Evening</a><a class="edition-link selected" href="/chat" aria-current="page">Secretary</a></nav></header>'
            '<main class="chat-layout"><aside class="conversation-sidebar">'
            + avatar_widget(avatar, sources) +
            '<p class="eyebrow">Your desk</p>'
            '<h1 id="secretary-heading">' + heading + '</h1><p>A place for your plans, bright ideas, and the details that make this yours.</p>'
             '<details id="conversation-history" open><summary>Previous conversations</summary><nav id="chat-history" aria-label="Previous conversations"></nav></details>'
             '<button id="new-conversation" type="button">New conversation</button></aside>'
             '<section class="conversation-panel" id="conversation" aria-label="Secretary conversation">'
             '<h2 id="conversation-name" class="chat-visually-hidden" data-content>'+conversation_name+'</h2>'
             '<div class="mode-controls"><div class="mode-switch" role="radiogroup" aria-label="Secretary mode">'+choices+'</div>'
             '<button id="mode-help" type="button" aria-label="Which mode should I use?" title="Which mode should I use?" aria-controls="mode-guide" aria-expanded="false"><span aria-hidden="true">?</span></button></div>'
             '<div id="mode-guide" hidden>'
             '<p><strong>Initialize</strong> — Set up your secretary for the first time, or review your location, timezone, name and preferences. Existing records and saved work stay intact.</p>'
             '<p><strong>Secretary</strong> — Talk through plans, review your schedule and saved records, clarify priorities, or update preferences. Ask follow-up questions in your own words; changes that need your approval will be confirmed first.</p>'
             '<p><strong>To-do</strong> — Capture a task and add details such as a project, deadline or priority when useful. Saving a task records it; it does not automatically start the work.</p>'
             '<p><strong>Eureka</strong> — Save an idea, observation or question before it slips away, then develop it through follow-up discussion. Capturing an idea does not automatically research or execute it.</p>'
             '<p>When in doubt, try it—it can do a lot more than you think!</p>'
             '<p>Write naturally; no commands are needed. Enter sends your message; Shift+Enter adds a new line. Use the paperclip, paste images, or drag files into the composer to attach them. Click an image preview to enlarge it.</p></div>'
             '<div id="chat-scroll" role="region" aria-label="Conversation" tabindex="0">'
             '<div id="chat-empty"><span class="desk-symbol" aria-hidden="true">✦</span>'
            '<h2 id="chat-welcome"></h2><p id="chat-hint"></p></div>'
            '<div id="chat-messages" role="log" aria-label="Conversation messages" aria-live="polite" aria-relevant="additions text"></div>'
             '<div id="chat-questions"></div><p id="chat-status" role="status"></p><p id="request-language-note" role="status"></p></div>'
             '<div class="chat-scroll-tools"><button type="button" id="chat-latest" hidden>Jump to latest</button></div>'
            '<form id="chat-compose"><label for="chat-text" id="compose-label" class="chat-visually-hidden">Your message</label>'
             '<div class="chat-input-row"><button type="button" id="chat-attach" aria-label="Attach files" aria-describedby="upload-note" title="Attach files" disabled>'
             '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true"><path d="m8 12 6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l9-9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></button>'
             '<textarea id="chat-text" rows="1" maxlength="8000" placeholder="Your message…" enterkeyhint="send"></textarea>'
            '<button type="submit" id="chat-send" disabled><span class="chat-send-label chat-visually-hidden">Send message</span>'
            '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true"><path d="m4 5 16 7-16 7 3-7-3-7Zm3 7h13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></button></div>'
            '<input id="chat-files" type="file" multiple hidden><div id="chat-attachments" aria-live="polite"></div>'
             '<span id="upload-note" class="chat-visually-hidden">Up to 50 MB per file. You can also paste images or drag files into this box.</span>'
             '</form><p id="chat-error" role="alert"></p>'
            '<noscript>Enable JavaScript to talk with your secretary. Saved briefings remain readable.</noscript></section></main>'
            '<div id="chat-config" hidden data-config="'+config+'"></div>'
            '<script src="/questions.js" defer></script><script src="/avatar.js" defer></script>'
            '<script src="/marked.js" defer></script><script src="/markdown.js" defer></script><script src="/chat.js" defer></script></body></html>')
