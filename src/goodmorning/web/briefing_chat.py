"""Account-local, durable conversations for the four website secretary modes."""
import hashlib
import html
import json
import re
import threading
import time

from goodmorning.runtime_files import atomic_text
from .briefing_resources import favicon_links
from . import language as ui
from .session_inventory import chat_session_title

MODES = {'initialize': 'Initialize', 'secretary': 'Secretary', 'todo': 'To-do', 'eureka': 'Eureka'}


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


class Chats:
    def __init__(self, runtime, chamber):
        self.runtime, self.chamber = runtime, chamber
        self.lock = threading.RLock()
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
            return [{'id': item['id'], 'mode': item['mode'], 'title': item['title']}
                    for item in reversed(list(self.items.values()))][:100]

    def start(self, body):
        if set(body) != {'id', 'mode', 'text'} or body['mode'] not in MODES:
            raise ValueError('Choose one of the four secretary modes')
        chat, text = identifier(body['id']), message(body['text'])
        if not text and body['mode'] not in ('initialize', 'secretary'):
            raise ValueError('Write the task or idea you want to save')
        with self.lock:
            if chat in self.items:
                item = self.items[chat]
                if item['mode'] != body['mode'] or item['turns'][0]['text'] != text:
                    raise ValueError('Request ID already belongs to another conversation')
                return {'chat': chat}
            if not self.chamber:
                raise ValueError('The secretary is not connected')
            if len(self.items) >= 500:
                raise ValueError('Conversation storage needs administrator archival')
            self.capacity(text)
            item = {'id': chat, 'mode': body['mode'], 'title': text[:64] or ui.text(MODES[body['mode']]),
                    'state': 'starting', 'turns': [{'id': chat, 'text': text,'language':ui.current()}],
                    'created': time.time()}
            self.items[chat] = item
            self.save()  # Save intent before any model request; never blindly replay.
            threading.Thread(target=self.dispatch, args=(item, text, True), daemon=True).start()
        return {'chat': chat}

    def send(self, chat, body):
        if set(body) != {'id', 'text'}:
            raise ValueError('Invalid message')
        request, text = identifier(body['id']), message(body['text'])
        if not text:
            raise ValueError('Write a reply first')
        with self.lock:
            self.get(chat)
            item = self.items[chat]
            old = next((turn for turn in item['turns'] if turn['id'] == request), None)
            if old:
                if old['text'] != text:
                    raise ValueError('Request ID already belongs to another message')
                return {'chat': chat}
            if self.status(chat)['state'] != 'idle':
                raise ValueError('Wait for the secretary or answer the pending question')
            if len(item['turns']) >= 200:
                raise ValueError('Start a new conversation to keep context bounded')
            self.capacity(text)
            item['turns'].append({'id': request, 'text': text,'language':ui.current()})
            item['state'] = 'starting'
            self.save()
            threading.Thread(target=self.dispatch, args=(item, text, False), daemon=True).start()
        return {'chat': chat}

    def dispatch(self, item, text, first):
        try:
            selected=item['turns'][-1]['language']
            if first:
                result = self.chamber.control('session.create', title=chat_session_title(
                    ui.text(MODES[item['mode']],lang=selected), item['title']))
                session = result['sessionId']
                if not re.fullmatch('ses[A-Za-z0-9_]+', session):
                    raise ValueError('Invalid session')
                with self.lock:
                    item['session'] = session
                    self.save()
            prompt = (f"/{item['mode']}\nBrowser chat: {item['id']}\nRuntime: {self.runtime}\n" if first else '')
            prompt += f"Website language: {selected}\n\n{text}"
            prompt=prompt.strip()
            with self.lock:
                item['turns'][-1]['prompt_hash'] = hashlib.sha256(prompt.encode()).hexdigest()
                self.save()
            result = self.chamber.control('session.send', sessionId=item['session'], prompt=prompt)
            if result.get('promptDispatched') is not True:
                raise ValueError('Message dispatch was not confirmed')
            with self.lock:
                item['state'] = 'running'
                self.save()
        except Exception:
            with self.lock:
                item['state'] = 'uncertain'
                self.save()

    def status(self, chat):
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
                transcript = self.chamber.control('session.messages', sessionId=item['session'], limit=100)
                messages = []
                originals = {turn.get('prompt_hash'): turn['text'] or ui.text('Start {mode}',lang=turn.get('language','en'),
                             mode=ui.text(MODES[item['mode']],lang=turn.get('language','en')).lower())
                              for turn in item['turns']}
                for entry in transcript['messages']:
                    if entry.get('role') not in ('user', 'assistant') or not isinstance(entry.get('text'), str):
                        continue
                    text = entry['text']
                    if entry['role'] == 'user':
                        text = originals.get(hashlib.sha256(text.encode()).hexdigest(), text)
                    messages.append({'id': entry['id'], 'role': entry['role'], 'text': text})
                result.update(messages=messages, forms=forms, permissions=permissions, history_limited=len(messages) >= 100)
                if item['state'] not in ('starting', 'uncertain'):
                    state = transcript['sessionStatus']['type']
                    last_prompt = item['turns'][-1].get('prompt_hash')
                    seen = any(entry.get('role') == 'user' and isinstance(entry.get('text'), str)
                               and hashlib.sha256(entry['text'].encode()).hexdigest() == last_prompt
                               for entry in transcript['messages'])
                    result['state'] = 'waiting' if forms or permissions else 'idle' if state == 'idle' and seen else 'running' if state in ('busy', 'idle') else 'uncertain'
            except Exception:
                result['state'] = 'unavailable'
        result['label'] = {'starting': 'Opening your conversation', 'running': 'Your secretary is working',
                           'waiting': 'Your secretary needs your answer', 'idle': 'Ready for your reply',
                           'uncertain': 'Delivery is uncertain. Ask the administrator to inspect this conversation before sending again.',
                           'unavailable': 'The secretary connection is unavailable. Your conversation is preserved.'}[result['state']]
        result['label']=ui.text(result['label'])
        return result

    def reply(self, chat, category, request, body):
        item = self.get(chat)
        if not item.get('session') or category not in ('form', 'permission') or not self.chamber:
            raise ValueError('Invalid reply target')
        forms, permissions = self.chamber.pending(item['session'])
        if not any(entry['id'] == request for entry in (forms if category == 'form' else permissions)):
            raise ValueError('This request is no longer pending in this conversation')
        if category == 'form':
            body = {'answer': body['answer']}
        else:
            if body.get('decision') not in ('once', 'reject'):
                raise ValueError('Only one-time approval or rejection is allowed')
            body = {'decision': body['decision']}
        self.chamber.request(f'/api/session/{item["session"]}/{category}/{request}/reply', body)
        return {'answered': True}


def page(csrf, ready, connected, secretary_name=None):
    config = html.escape(json.dumps({'csrf': csrf, 'defaultMode': 'secretary' if ready else 'initialize',
                                   'connected': connected, 'secretary_name': secretary_name}), quote=True)
    choices = ''.join(f'<button type="button" role="radio" aria-checked="false" data-mode="{mode}">{label}</button>'
                      for mode, label in MODES.items())
    heading = html.escape(secretary_name) + '.' if secretary_name else 'Your secretary.'
    title = (html.escape(secretary_name) + ' — GoodMorning') if secretary_name else 'Your secretary — GoodMorning'
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<title>' + title + '</title>' + favicon_links('secretary') + '<link rel="stylesheet" href="/briefing.css">'
            '<link rel="stylesheet" href="/chat.css"></head><body class="chat-page">'
            '<a class="skip-link" href="#conversation">Skip to conversation</a>'
            '<header class="masthead"><a class="wordmark" href="/chat">GoodMorning<span>A little space to think, plan, and begin.</span></a>'
            '<nav class="edition-switch" aria-label="Your desk"><a class="edition-link" href="/gm.html">Morning</a>'
            '<a class="edition-link" href="/gn.html">Evening</a><a class="edition-link selected" href="/chat" aria-current="page">Secretary</a></nav></header>'
            '<main class="chat-layout"><aside class="conversation-sidebar"><figure class="desk-figure"><img class="desk-illustration" src="/desk-secretary.png" alt="Pixel-art secretary desk under a warm office spotlight" width="440" height="440" fetchpriority="high" onerror="this.parentNode.hidden=true"></figure><p class="eyebrow">Your desk</p>'
            '<h1 id="secretary-heading">' + heading + '</h1><p>A place for your plans, bright ideas, and the details that make this yours.</p>'
            '<button id="new-conversation" type="button">New conversation</button>'
            '<details id="conversation-history"><summary>Previous conversations</summary><nav id="chat-history" aria-label="Previous conversations"></nav></details></aside>'
            '<section class="conversation-panel" id="conversation" aria-label="Secretary conversation">'
             '<div class="mode-switch" role="radiogroup" aria-label="Secretary mode">'+choices+'</div>'
             '<details id="mode-guide"><summary>Which mode should I use?</summary>'
             '<p>Use Secretary for discussion and planning, To-do for a task, Eureka for an idea, and Initialize for setup or preference review.</p></details>'
            '<p id="mode-description"></p><div id="chat-empty"><span class="desk-symbol" aria-hidden="true">✦</span>'
            '<h2 id="chat-welcome"></h2><p id="chat-hint"></p></div>'
            '<div id="chat-messages" role="log" aria-label="Conversation messages" aria-live="polite" aria-relevant="additions text"></div>'
             '<p id="chat-status" role="status"></p><p id="request-language-note" role="status"></p><div id="chat-questions"></div>'
            '<form id="chat-compose"><label for="chat-text" id="compose-label">Your message</label>'
            '<textarea id="chat-text" rows="3" maxlength="8000" placeholder="What’s on your mind?"></textarea>'
            '<div class="compose-footer"><span id="compose-note">Only your chosen mode. No commands needed.</span>'
             '<button type="submit" id="chat-send" disabled>Send message</button></div></form><p id="chat-error" role="alert"></p>'
            '<noscript>Enable JavaScript to talk with your secretary. Saved briefings remain readable.</noscript></section></main>'
            '<div id="chat-config" hidden data-config="'+config+'"></div>'
            '<script src="/questions.js" defer></script><script src="/chat.js" defer></script></body></html>')
