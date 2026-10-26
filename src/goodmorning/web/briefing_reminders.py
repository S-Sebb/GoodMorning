"""Reminders for a briefing not prepared yet, worded by the secretary in the saved tone.

The secretary writes a few lines per edition once for each tone, website language and saved
user name; `reminder-lines.json` in the runtime keeps them with the last writing attempt. Built-in lines
cover the time before they exist and any failed attempt. The gateway decides when to remind.
"""
import json
import re
import secrets
import threading
import time
from datetime import date

from goodmorning.runtime_files import atomic_text, profile_fields
from . import language as ui
from . import models as site_models
from .session_inventory import PREFIX

COUNT = 3
LIMITS = {'en': 100, 'zh-CN': 40}  # Characters in one line, short enough for a notification.
RETRY = 6 * 3600  # A failed attempt for the same wording waits this long before another.
NAMES = {'en': ('morning briefing', 'evening briefing'), 'zh-CN': ('早报', '晚报')}  # As the website calls them.
FALLBACK = {
    'en': {'gm': ["Good morning! Tap to prepare it and start the day with a clear plan ☀️",
                  "Rise and shine! A fresh look at your day is just a tap away 🌤️",
                  "Morning! Open it whenever you're ready, and let's look at today together 🌱"],
           'gn': ["Evening! Tap to prepare it and wind down with tomorrow in view 🌙",
                  "The day's nearly done. Let's tidy it up together before you rest ✨",
                  "Time to unwind! Open it to look back on today and get ready for tomorrow 🌙"]},
    'zh-CN': {'gm': ["早上好！点一下准备早报，带着清楚的计划开始这一天 ☀️",
                     "该起床啦！点一下，就能重新看看今天的样子 🌤️",
                     "早上好！什么时候准备好了就什么时候打开，我们一起看看今天 🌱"],
              'gn': ["晚上好！点一下准备晚报，看着明天的安排慢慢放松下来 🌙",
                     "一天快过完啦。在你休息之前，我们一起把它收拾好 ✨",
                     "该放松一下啦！打开看看今天，也顺便为明天做点准备 🌙"]},
}


class Unknown(Exception):
    """No attempt has this ID: its request never arrived."""


def line(lines, kind, day):
    """The day's line for one edition, so consecutive days differ."""
    options = lines[kind]
    return options[date.fromisoformat(day).toordinal() % len(options)]


def written(text, lang):
    """The secretary's reply as lines, or None when it is not exactly the requested JSON."""
    match = re.fullmatch(r'\s*(?:```(?:json)?\s*)?(\{.*\})\s*(?:```)?\s*', text, flags=re.S)
    try:
        value = json.loads(match[1]) if match else None
    except ValueError:
        return None
    if not isinstance(value, dict) or set(value) != {'gm', 'gn'}:
        return None
    lines = {}
    for kind in ('gm', 'gn'):
        options = value[kind]
        if not isinstance(options, list) or len(options) != COUNT:
            return None
        cleaned = [' '.join(item.split()) if isinstance(item, str) else '' for item in options]
        if any(not item or len(item) > LIMITS[lang] or re.search(r'[*_`#<>\[\]]', item) for item in cleaned):
            return None
        lines[kind] = cleaned
    return lines


class ReminderLines:
    def __init__(self, runtime, chamber):
        self.runtime, self.chamber = runtime, chamber
        self.path = runtime / 'reminder-lines.json'
        self.lock = threading.RLock()
        if self.path.is_symlink():
            raise ValueError('Unsafe reminder lines')
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {}
        attempt = self.state.get('attempt')
        if attempt and attempt['state'] == 'starting':
            attempt['state'] = 'uncertain'  # A restart cannot prove the dispatch failed.
            self.save()

    def save(self):
        if self.path.is_symlink():
            raise ValueError('Unsafe reminder lines')
        atomic_text(self.path, json.dumps(self.state, ensure_ascii=False) + '\n')

    def wording(self, lang):
        """What the lines must follow; a change asks the secretary for new ones."""
        fields = profile_fields(self.runtime)
        return {'language': lang, 'tone': fields.get('secretary_tone') or '', 'user_name': fields.get('user_name') or ''}

    def current(self, lang):
        """Lines for the website language, and whether the secretary should write new ones now."""
        wording = self.wording(lang)
        with self.lock:
            saved = self.state.get('lines')
            if saved and saved['wording'] == wording:
                return {'lines': saved['lines'], 'write': False}
            attempt = self.state.get('attempt')
            busy = attempt and attempt['wording'] == wording and (
                attempt['state'] in ('starting', 'running') or time.time() - attempt['created'] < RETRY)
            return {'lines': FALLBACK[lang], 'write': bool(self.chamber) and not busy}

    def prompt(self, wording):
        tone = {'value': wording['tone'] or 'warm and helpful', 'source': 'saved' if wording['tone'] else 'default'}
        prompt = (f"Write briefing reminder lines.\nWebsite language: {wording['language']}\n"
                  f"Secretary tone at request start: {json.dumps(tone, ensure_ascii=False)}\n")
        if wording['user_name']:
            prompt += f"Call the user: {json.dumps(wording['user_name'], ensure_ascii=False)}\n"
        limit, names = LIMITS[wording['language']], NAMES[wording['language']]
        return prompt + (
            "\nEach line is the body of a notification sent at the user's chosen time when today's morning (gm) or "
            "evening (gn) briefing has not been prepared yet. The title already says which briefing is not prepared; "
            "tapping opens it, and the secretary writes it once the user asks there, so never suggest the user writes, "
            f"fills in or sets it up. When a line names the briefing, call it {json.dumps(names[0], ensure_ascii=False)} "
            f"(gm) or {json.dumps(names[1], ensure_ascii=False)} (gn).\n"
            f"Write {COUNT} different lines for gm and {COUNT} for gn: one sentence each, at most {limit} characters, "
            "in the website language. Match the saved tone first; within it, sound comfortable, energetic and cute. "
            "Invite the user to open and prepare the briefing. Never say it is ready, being prepared or will be "
            "prepared automatically, never say how long preparing takes or that it is quick or easy, and never invent "
            "plans, weather, news, tasks, progress or feelings. If a name to call the user is given above, use it in at "
            "most one line; never call the user anything else, such as a nickname or pet name (\"sleepyhead\", \"cutie\"). "
            "No Markdown; one emoji per line at most.\n"
            "Use no tools and do not ask the user anything before replying. Reply with only this JSON: "
            '{"gm":["…","…","…"],"gn":["…","…","…"]}')

    def start(self, body):
        if set(body) != {'id'} or not isinstance(body['id'], str) or not re.fullmatch('[a-f0-9]{32}', body['id']):
            raise ValueError('Invalid reminder lines request')
        lang = ui.current()
        wording = self.wording(lang)
        with self.lock:
            attempt = self.state.get('attempt')
            if attempt and attempt['id'] == body['id']:
                return {'lines': attempt['id']}
            if not self.current(lang)['write']:
                raise ValueError('Reminder lines are already written or being written')
            attempt = {'id': body['id'], 'wording': wording, 'state': 'starting', 'created': time.time()}
            self.state['attempt'] = attempt
            self.save()  # Record intent before any model request; never blindly replay.
        threading.Thread(target=self.dispatch, args=(attempt,), daemon=True).start()
        return {'lines': attempt['id']}

    def dispatch(self, attempt):
        try:
            session = self.chamber.control('session.create', title=PREFIX + 'Briefing reminders')['sessionId']
            if not re.fullmatch('ses[A-Za-z0-9_]+', session):
                raise ValueError('Invalid session')
            with self.lock:
                attempt['session'] = session
                self.save()
            self.chamber.request(f'/api/session/{session}/agent', {'agent': 'secretary'})
            site_models.apply_to_session(self.chamber, session, site_models.CURRENT.get() or site_models.for_language(attempt['wording']['language']))
            if self.chamber.control('session.send', sessionId=session, prompt=self.prompt(attempt['wording'])).get('promptDispatched') is not True:
                raise ValueError('Prompt dispatch was not confirmed')
            state = 'running'
        except Exception:
            state = 'uncertain'
        with self.lock:
            attempt['state'] = state
            self.save()

    def status(self, identifier):
        """'running' until the secretary's reply is read: 'ready' once its lines are saved, else 'stopped'."""
        with self.lock:
            attempt = self.state.get('attempt')
            if not attempt or attempt['id'] != identifier:
                raise Unknown(identifier)
            if attempt['state'] != 'running':
                return {'state': {'starting': 'running', 'uncertain': 'stopped'}.get(attempt['state'], attempt['state'])}
            session = attempt['session']
        forms, permissions = self.chamber.pending(session)
        if not forms and not permissions:
            if self.chamber.control('session.status', sessionId=session)['sessionStatus']['type'] != 'idle':
                return {'state': 'running'}
            replies = [item['text'] for item in self.chamber.control('session.messages', sessionId=session, limit=10)['messages']
                       if item['role'] == 'assistant']
            lines = written(replies[-1], attempt['wording']['language']) if replies else None
        else:
            lines = None  # It asked instead of writing; leave the question unanswered.
        with self.lock:
            attempt['state'] = 'ready' if lines else 'stopped'
            if lines:
                self.state['lines'] = {'wording': attempt['wording'], 'lines': lines}
            self.save()
        return {'state': attempt['state']}
