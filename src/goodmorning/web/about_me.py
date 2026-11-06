"""About me: what the secretary knows about the user, read from the profile on every request.

Each entry of SECTIONS renders one section from the current profile fields, so a
later feature adds its own section (or a row in an existing one) without a copy
of the data. Simple text fields and the evening extras' switches save through
`set_profile_fields`; anything that needs a provider or feed check stays in chat.
"""
from collections import Counter
from datetime import date as Date, datetime, timezone
import html
import json
import re
import sqlite3

from goodmorning import anime, games, stocks
from goodmorning.briefings.briefing_day import briefing_day
from goodmorning.briefings.briefing_layout import icon
from goodmorning.calendar import public_holidays
from goodmorning.records import celebrations, letters, memory as memories
from goodmorning.records.inbox_store import InboxStore
from goodmorning.setup_flow import GENDERS
from goodmorning.runtime_files import (PROFILE_TEXT_MAX as LONG, SECRETARY_NAME_MAX as SHORT, calendar_config,
                                       normalize_secretary_name, profile_fields, set_profile_fields)
from . import language as ui
from . import quick_chat
from .briefing_resources import favicon_links
from .chat_theme import clock_theme

# Edited on the page: key -> label, character limit.
TEXT = {'secretary_name': ('Your secretary’s name', SHORT), 'user_name': ('What {name} calls you', SHORT),
        'work_days': ('Work days', LONG), 'work_hours': ('Work hours', LONG), 'sleep_time': ('Bedtime', LONG),
        'secretary_tone': ('Tone', LONG), 'special_needs': ('Things to keep in mind', LONG),
        'occupations': ('Roles', LONG), 'expertise_fields': ('Expertise', LONG), 'industry': ('Industry', LONG),
        'project_scope': ('Project areas', LONG), 'knowledge_area': ('Knowledge area', LONG)}
# Lines that name the secretary, and how each reads before a name is saved.
UNNAMED = {'{name}’s notes about you': 'Your secretary’s notes about you',
           'What {name} calls you': 'What your secretary calls you',
           'How {name} talks with you': 'How your secretary talks with you',
           '{name} doesn’t know yet': 'Your secretary doesn’t know yet',
           'Ask {name}': 'Ask your secretary',
           'Nothing yet. Chat with {name} and this note will grow from there.':
               'Nothing yet. Chat with your secretary and this note will grow from there.',
           'What {name} has learned from your chats, check-ins and plans.':
               'What your secretary has learned from your chats, check-ins and plans.',
           'Tell {name} about it, or save a to-do for it. Rename or finish a project the same way.':
               'Tell your secretary about it, or save a to-do for it. Rename or finish a project the same way.'}
SOURCES = {'anilist': 'AniList', 'bangumi': 'Bangumi', 'myanimelist': 'MyAnimeList'}
# The user-facing reason for each rule `set_profile_fields` enforces.
REASONS = {'use 1-30 characters': 'Use up to 30 characters.', 'use at most 300 characters': 'Use up to 300 characters.',
           'no control characters or newlines': 'Keep it on one line.',
           'include at least one letter or number': 'Include at least one letter or number.'}


class Invalid(ValueError):
    """A value the user can fix; the message is interface text."""


def saved_name(fields, key='secretary_name'):
    try:
        return normalize_secretary_name(fields.get(key, ''), key)
    except ValueError:
        return ''


def say(fields, text):
    """Interface text with the secretary's saved name, or "your secretary" before there is one."""
    name = saved_name(fields)
    return ui.ui(text, name=name) if name else ui.ui(UNNAMED[text])


def desk_link(fields, selected=False):
    """The page bar's About me link; its icon follows the saved gender, neutral until one is picked."""
    person = fields.get('gender') if fields.get('gender') in ('woman', 'man') else 'neutral'
    return (f'<a class="edition-link{" selected" if selected else ""}" href="/about-me" data-person="{person}"'
            + (' aria-current="page"' if selected else '') + '>About me</a>')


def portrait(app):
    """The secretary's chosen picture, as on the weekly letters."""
    avatar = app.avatar_sources().get(app.avatar()) or {}
    return avatar.get('profile') or avatar.get('day') or ''


def chat(app, fields, starter):
    picture = portrait(app)
    name = saved_name(fields)
    label = f'Ask {name} to change this' if name else 'Ask your secretary to change this'
    return ('<a class="about-chat" href="/chat" data-quick-ask-prefill data-quick-ask="'
            + html.escape(starter, quote=True) + f'" aria-label="{html.escape(label, quote=True)}">'
            + (f'<img src="{html.escape(picture, quote=True)}" alt="" width="24" height="24">' if picture else '')
            + say(fields, 'Ask {name}') + '</a>')


def value(fields, text):
    return (f'<span class="about-value" data-content>{html.escape(text)}</span>' if text
            else '<span class="about-empty">' + say(fields, '{name} doesn’t know yet') + '</span>')


def row(label, content, action='', key=None, below=''):
    """One labelled line; `label` is already rendered interface text, `below` a full-width part under it."""
    field, label_id = (f' data-field="{key}"', f' id="about-label-{key}"') if key else ('', '')
    return (f'<div class="about-row"{field}><dt{label_id}>{label}</dt><dd class="about-content">{content}</dd>'
            f'<dd class="about-action">{action}</dd>{below}</div>')


def edit_button(attributes=''):
    """The pencil that turns a row into an editor; the script shows it once the page can save."""
    return f'<button class="about-edit" type="button" aria-label="Edit" title="Edit"{attributes} hidden>' + icon('pencil') + '</button>'


def text_row(fields, key):
    label, limit = TEXT[key]
    return row(say(fields, label) if label in UNNAMED else ui.ui(label), value(fields, fields.get(key, '')),
               edit_button(f' data-limit="{limit}"'), key)


def section(identifier, title, rows, why='', note='', attributes=''):
    """A card; its title, why line and note are already rendered. The stylesheet gives each identifier its desk icon."""
    return (f'<section class="about-section" id="about-{identifier}"{attributes}><h2>{title}</h2>'
            + (f'<p class="about-why">{why}</p>' if why else '') + '<dl>' + ''.join(rows) + '</dl>'
            + (f'<p class="about-note">{note}</p>' if note else '') + '</section>')


def count(singular, plural, number):
    return ui.ui(singular if number == 1 else plural, count=number)


def birthday(fields):
    """The user's birthday as a month and day; the script picks it from month and day lists."""
    saved = fields.get('birthday', '')
    try:
        known = celebrations.birthday(saved)
    except ValueError:
        known = ''  # Shown as saved, so the user can fix it.
    if known:
        month, day = map(int, known.split('-'))
        shown = f'{month}月{day}日' if ui.current() == 'zh-CN' else f'{Date(2000, month, 1):%B} {day}'
        content = f'<span class="about-value" data-birthday="{known}">{shown}</span>'
    else:
        content = value(fields, saved)
    return row(ui.ui('Birthday'), content, edit_button(), 'birthday')


def gender(fields):
    saved = fields.get('gender', '')
    content = (f'<span class="about-value" data-gender="{saved}">' + ui.ui(GENDERS[saved]) + '</span>' if saved in GENDERS
               else value(fields, saved))
    return row(ui.ui('Gender'), content + '<small class="about-hint">' + ui.ui('Only sets your About me icon.') + '</small>', edit_button(), 'gender')


def names(app, fields):
    return section('names', ui.ui('What you call each other'),
                   [text_row(fields, 'secretary_name'), text_row(fields, 'user_name'), birthday(fields), gender(fields)])


def day(app, fields):
    return section('day', ui.ui('Your day'),
                   [row(ui.ui('City'), value(fields, fields.get('city', '')), chat(app, fields, 'I’d like to change my city.')),
                    row(ui.ui('Time zone'), value(fields, fields.get('timezone', '')), chat(app, fields, 'I’d like to change my time zone.')),
                    *(text_row(fields, key) for key in ('work_days', 'work_hours', 'sleep_time'))])


def talk(app, fields):
    return section('talk', say(fields, 'How {name} talks with you'), [text_row(fields, 'secretary_tone'), text_row(fields, 'special_needs')])


def work(app, fields):
    return section('work', ui.ui('What you do'), [text_row(fields, key) for key in
                                                  ('occupations', 'expertise_fields', 'industry', 'project_scope', 'knowledge_area')])


def news(app, fields):
    codes = [fields.get('news_country', ''), *re.split(r'[\s,;]+', fields.get('news_additional_countries', ''))]
    codes = list(dict.fromkeys(code.upper() for code in codes if re.fullmatch(r'[A-Za-z]{2}', code)))
    content = (f'<span class="about-value" data-countries="{",".join(codes)}">{", ".join(codes)}</span>' if codes else value(fields, ''))
    return section('news', ui.ui('News you follow'),
                   [row(ui.ui('National news'), content, chat(app, fields, 'I’d like to change which countries’ news I get.'))])


def extras_state(runtime, fields):
    """Each evening extra's details and whether it can be switched on, or None while it was never set up."""
    state = {}
    try:
        chosen = anime.settings(runtime)
        listed = bool(chosen['account'])
        if listed or chosen['titles']:
            shows = len(chosen['titles'])
            state['anime_updates'] = [SOURCES[chosen['source']], (count('Your watching list and 1 more show', 'Your watching list and {count} more shows', shows)
                                      if listed and shows else ui.ui('Your watching list') if listed else count('1 show', '{count} shows', shows))]
    except anime.AnimeError:
        pass
    try:
        chosen = games.settings(runtime)
        listed = bool(chosen['account'])
        if listed or chosen['titles']:
            titles = len(chosen['titles'])
            state['game_sales'] = [f'<span data-region="{chosen["country"]}">' + ui.ui('{region} store', region=chosen['country']) + '</span>',
                                   ui.ui('{percent}% off or more', percent=chosen['threshold']),
                                   count('Your wishlist and 1 more game', 'Your wishlist and {count} more games', titles)
                                   if listed and titles else ui.ui('Your wishlist') if listed else count('1 game', '{count} games', titles)]
    except games.GameError:
        pass
    try:
        state['stock_report'] = holdings_table(stocks.holdings(fields.get('stock_holdings', '')), stocks.saved_names(runtime))
    except stocks.StockError:
        pass
    state['weekly_letter'] = [ui.ui('Written with Sunday’s evening briefing')]
    return state


SHOWN_HOLDINGS = 5


def holdings_table(held, names):
    """Name over code, shares and cost per holding; rows past the first few wait behind Show all."""
    rows = []
    for position, (symbol, (shares, cost, _)) in enumerate(held.items()):
        code = f'<span class="about-code">{html.escape(symbol[2:])}</span>'
        name = names.get(symbol)
        holding = f'<span data-content>{html.escape(name)}</span>{code}' if name else code
        price = (('$' if symbol.startswith('us') else '¥') + f'{cost:,.2f}') if cost else ''
        rows.append(f'<tr{" hidden" if position >= SHOWN_HOLDINGS else ""}><th scope="row">{holding}</th>'
                    f'<td>{shares:,}</td><td>{price}</td></tr>')
    more = len(held) - SHOWN_HOLDINGS
    toggle = ('<button class="about-more" type="button" aria-expanded="false"><span class="about-all">' + ui.ui('Show all ({count})', count=len(held))
              + '</span><span class="about-fewer">' + ui.ui('Show fewer') + '</span></button>' if more > 0 else '')
    return ('<dd class="about-holdings"><table><thead><tr><th scope="col">' + ui.ui('Holding') + '</th><th scope="col">'
            + ui.ui('Shares') + '</th><th scope="col">' + ui.ui('Cost') + f'</th></tr></thead><tbody>{"".join(rows)}</tbody></table>{toggle}</dd>')


def switch(key, on):
    return (f'<button class="about-switch" type="button" role="switch" aria-checked="{"true" if on else "false"}" '
            f'data-switch="{key}" aria-labelledby="about-label-{key}" hidden></button>')


def extras(app, fields):
    state = extras_state(app.runtime, fields)
    on = {key: fields.get(key, '').casefold() == 'true' for key in ('anime_updates', 'game_sales', 'stock_report')}
    on['weekly_letter'] = letters.enabled(app.runtime)
    rows = []
    for key, label, starter in (('anime_updates', 'New episodes', 'I’d like to change my new-episode updates.'),
                                ('game_sales', 'Game sales', 'I’d like to change my game-sale updates.'),
                                ('stock_report', 'Stocks', 'I’d like to update my stocks.'),
                                ('weekly_letter', 'Weekly letter', None)):
        details = state.get(key)
        # Stocks get their own table under the row; the other extras fit on one line.
        table = details if key == 'stock_report' else ''
        content = (switch(key, on[key]) + ('' if table else '<span class="about-details">' + ' · '.join(details) + '</span>')) if details else value(fields, '')
        rows.append(row(ui.ui(label), content, chat(app, fields, starter) if starter else '', key, table))
    return section('extras', ui.ui('Evening extras'), rows, note=ui.ui('Switching one off keeps its settings.'))


def holiday_regions():
    """Every region the picker offers, with its country and region names in both website languages."""
    return [{'code': code, 'country': [region['country'], public_holidays.named(region['country'], 'zh-CN')],
             **({} if region['label'] == region['country'] else {'region': [region['label'], public_holidays.named(region['label'], 'zh-CN')]})}
            for code, region in public_holidays.REGIONS.items()]


def holidays(fields):
    """The followed holiday regions; the script names them in the website language and offers the picker."""
    saved = fields.get('holiday_countries', '')
    try:
        codes = public_holidays.regions(saved)
    except ValueError:
        codes, saved = [], ''  # Unreadable: shown as unknown, and the picker replaces it.
    if codes:
        content = (f'<span class="about-value" data-holidays="{",".join(codes)}">'
                   + html.escape(', '.join(public_holidays.choice(code, ui.current()) for code in codes)) + '</span>')
    else:
        content = '<span class="about-value">' + ui.ui('No public holidays') + '</span>' if saved else value(fields, '')
    regions = html.escape(json.dumps(holiday_regions(), ensure_ascii=False, separators=(',', ':')), quote=True)
    return row(ui.ui('Public holidays'), content,
               edit_button(f' data-holiday-regions="{regions}"'),
               'holiday_countries')


def calendar(app, fields):
    linked = bool(calendar_config(app.runtime).get('ics_url'))
    content = '<span class="about-value">' + ui.ui('Connected') + '</span>' if linked else value(fields, '')
    return section('calendar', ui.ui('Your calendar'), [row(ui.ui('Linked calendar'), content, chat(app, fields, 'I’d like to change my linked calendar.')),
                                                        holidays(fields)])


PARTS = {'life': 'Your life', 'likes': 'How you like things', 'lately': 'Lately'}


def note_row(key, label, text):
    content = (f'<span class="about-value" data-content>{html.escape(text)}</span>' if text else
               '<span class="about-empty">' + ui.ui('Nothing yet') + '</span>')
    return (f'<div class="about-row" data-field="{key}" data-empty="Nothing yet"><dt id="about-label-{key}">' + ui.ui(label)
            + f'</dt><dd class="about-content">{content}</dd><dd class="about-action">'
            + edit_button(f' data-limit="{memories.LENGTH}" data-multiline') + '</dd></div>')


def open_todos(runtime):
    """Open to-dos per project, matched the way memory matches project names."""
    try:
        inbox = InboxStore(runtime)
    except (sqlite3.Error, ValueError):
        return Counter()  # No to-dos saved yet.
    try:
        if inbox.version != 2:
            return Counter()
        return Counter(memories.key(label) for (label,) in inbox.db.execute(
            "SELECT json_extract(data,'$.project') FROM tasks WHERE json_extract(data,'$.status') IN ('open','partial','blocked') "
            "AND COALESCE(json_extract(data,'$.kind'),'')=''") if label)
    finally:
        inbox.close()


def project_row(number, entry, todos, today):
    """One project's entry, with its open to-dos and when it last changed; it is edited here, renamed or started in chat."""
    text, label = entry['note'], f'about-label-project-{number}'
    content = (f'<span class="about-value" data-content>{html.escape(text)}</span>' if text else
               '<span class="about-empty">' + ui.ui('Nothing yet') + '</span>')
    details = ([count('1 open to-do', '{count} open to-dos', todos)] if todos else []) + (
        [ui.ui('Updated {date}', date=ui.day_text(entry['updated'], reference=today))] if entry.get('updated') else [])
    return (f'<div class="about-row about-project" data-field="{html.escape("project:" + entry["name"], quote=True)}" data-empty="Nothing yet">'
            f'<dt id="{label}">' + ui.ui('Project: {name}', name=entry['name']) + f'</dt><dd class="about-content">{content}'
            + ('<small class="about-hint">' + ' · '.join(details) + '</small>' if details else '') + '</dd><dd class="about-action">'
            + edit_button(f' data-limit="{memories.PROJECT}" data-multiline')
            + '<button class="about-forget" type="button" hidden>' + ui.ui('Forget') + '</button></dd></div>')


def remembered(app, fields):
    """The note the secretary keeps about the user, part by part; each part can be edited, or all of it forgotten."""
    data = memories.load(app.runtime)
    today = briefing_day(fields.get('timezone', ''))
    status = ('<span class="about-value">' + ui.ui('Last updated {date}', date=ui.day_text(data['updated'], reference=today)) + '</span>'
              if (any(data['note'].values()) or data['projects']) and 'updated' in data else
              '<span class="about-empty">' + say(fields, 'Nothing yet. Chat with {name} and this note will grow from there.') + '</span>')
    todos = open_todos(app.runtime) if data['projects'] else Counter()
    rows = [row(ui.ui('Remember things about me'), switch('memory', data['enabled']), key='memory'),
            *(note_row('memory:' + part, label, data['note'][part]) for part, label in PARTS.items()),
            *(project_row(number, entry, todos[memories.key(entry['name'])], today) for number, entry in enumerate(data['projects'])),
            row(ui.ui('New project'), '<span class="about-value">' + say(
                fields, 'Tell {name} about it, or save a to-do for it. Rename or finish a project the same way.') + '</span>',
                chat(app, fields, 'I’d like to tell you about a project.')),
            row(ui.ui('The whole note'), status,
                '<button class="about-forget-all" type="button" hidden>' + ui.ui('Forget everything') + '</button>', 'forget')]
    return section('memory', ui.ui('What I remember about you'), rows, say(fields, 'What {name} has learned from your chats, check-ins and plans.'),
                   ui.ui('Only used to make chats, briefings and letters personal, never as a setting or a permission. '
                         'When switched off, nothing is learned or used. Forgotten text is deleted for good.'),
                   f' data-revision="{data["revision"]}"')


def remember(app, key, text, revision):
    """Switch memory on or off, forget the whole note or one project, or rewrite one part or project entry.

    `revision` is the note the page showed, so an edit open while the secretary changed the note never overwrites it."""
    data = memories.load(app.runtime)
    try:
        if key == 'memory':
            if text not in ('true', 'false'):
                raise ValueError('Invalid switch')
            saved = memories.change(app.runtime, revision, enabled=text == 'true')
        elif key == 'forget':
            if text == 'all':
                saved = memories.change(app.runtime, revision, note={**dict.fromkeys(memories.PARTS, ''),
                                                                     **({'projects': dict.fromkeys(entry['name'] for entry in data['projects'])}
                                                                        if data['projects'] else {})})
            elif text.startswith('project:') and memories.find(data['projects'], text.removeprefix('project:')):
                saved = memories.change(app.runtime, revision, note={'projects': {text.removeprefix('project:'): None}})
            else:
                raise ValueError('Invalid change')
        elif key.removeprefix('memory:') in memories.PARTS:
            saved = memories.change(app.runtime, revision, note={key.removeprefix('memory:'): text})
            text = memories.load(app.runtime)['note'][key.removeprefix('memory:')]
        elif key.startswith('project:') and memories.find(data['projects'], key.removeprefix('project:')):
            # Only an existing entry: projects start in chat or with their first to-do.
            saved = memories.change(app.runtime, revision, note={'projects': {key.removeprefix('project:'): text}})
            text = memories.find(memories.load(app.runtime)['projects'], key.removeprefix('project:'))['note']
        else:
            raise ValueError('This can only be changed in chat')
    except ValueError as error:
        reason = {'memory_off': 'Turn memory on to edit it.',
                  'revision_conflict': 'Your secretary just changed this. Refresh the page to see the latest.',
                  'memory_too_long': f'The whole note fits {memories.LENGTH:,} characters. Shorten it a little.',
                  'project_too_long': f'A project fits {memories.PROJECT} characters. Shorten it a little.',
                  'invalid_input': 'Use plain text.'}.get(str(error).split(':', 1)[0])
        if reason:
            raise Invalid(reason) from None
        raise
    return {'field': key, 'value': text, 'revision': saved['revision']}


SECTIONS = [names, day, talk, work, remembered, news, extras, calendar]


def save(app, body):
    """One field per request: a text field's new value, or an evening extra switched on or off."""
    if not isinstance(body, dict) or set(body) - {'revision'} != {'field', 'value'} or not isinstance(body['value'], str):
        raise ValueError('Invalid About me change')
    key, text = body['field'], body['value']
    if not (app.runtime / 'profile.md').is_file():
        raise ValueError('No profile to change yet')
    if key in ('memory', 'forget') or key.startswith(('memory:', 'project:')):
        revision = body.get('revision', memories.load(app.runtime)['revision'])
        if type(revision) is not int:
            raise ValueError('Invalid About me change')
        return remember(app, key, text, revision)
    if key in ('anime_updates', 'game_sales', 'stock_report', 'weekly_letter'):
        if text not in ('true', 'false'):
            raise ValueError('Invalid switch')
        if text == 'true' and key not in extras_state(app.runtime, profile_fields(app.runtime)):
            raise Invalid('Ask your secretary to set this up first.')
    elif key == 'birthday':
        try:
            text = celebrations.birthday(text)
        except ValueError:
            raise Invalid('Pick a real month and day.') from None
    elif key == 'gender':
        if text not in GENDERS:
            raise ValueError('Invalid gender')
    elif key == 'holiday_countries':
        text = ', '.join(public_holidays.regions(text)) or 'none'  # Nothing chosen saves "none", as declining in chat does.
    elif key not in TEXT:
        raise ValueError('This can only be changed in chat')
    try:
        saved = set_profile_fields(app.runtime, {key: text})[key]
    except ValueError as error:
        reason = next((message for rule, message in REASONS.items() if rule in str(error)), None)
        if reason:
            raise Invalid(reason) from None
        raise
    return {'field': key, 'value': saved}


def page(app):
    fields = profile_fields(app.runtime)
    zone = fields.get('timezone')
    theme = clock_theme(zone, app.now() if app.now else datetime.now(timezone.utc))['theme']
    content = ''.join(build(app, fields) for build in SECTIONS)
    picture, user, name = portrait(app), saved_name(fields, 'user_name'), saved_name(fields)
    ready = (app.runtime / 'profile.md').is_file()
    if not ready:
        greeting = ui.ui('Hi! I don’t know much about you yet. Once we finish setting up in chat, what I remember will show up here.')
    elif user:
        greeting = ui.ui('Hi {user}! Change anything here, or just tell me.', user=user)
    else:
        greeting = ui.ui('Hi! Change anything here, or just tell me.')
    intro = ((f'<img class="about-portrait" src="{html.escape(picture, quote=True)}" alt="" width="84" height="84">' if picture else '')
             + '<div><h1>' + say(fields, '{name}’s notes about you') + f'</h1><p class="about-greeting">{greeting}</p></div>')
    source = ('<!doctype html><html lang="en" data-edition="' + theme + '"><head><meta charset="utf-8">'
              '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>About me — GoodMorning</title>'
              + favicon_links() + '<link rel="stylesheet" href="/briefing.css"><link rel="stylesheet" href="/about-me.css">'
              '</head><body class="about-page">'
              '<header class="masthead"><a class="wordmark" href="/gm">GoodMorning</a>'
              '<nav class="edition-switch" aria-label="Your desk"><a class="edition-link" href="/gm">Morning</a><a class="edition-link" href="/gn">Evening</a>'
              '<a class="edition-link" href="/schedule">Schedule</a><a class="edition-link" href="/letters">Letters</a>'
              '<a class="edition-link" href="/chat">Secretary</a>' + desk_link(fields, True) + '</nav></header>'
              '<main class="about-me"' + ('' if ready else ' data-readonly')
              + (f' data-secretary="{html.escape(name, quote=True)}"' if name else '') + '><header class="about-intro">' + intro + '</header>'
              # After language.js, which the shared page shell adds to the head.
              + content + '</main><script src="/about-me.js" defer></script></body></html>')
    return app.resources.rewrite(ui.page(quick_chat.widget(source, app.csrf), app.csrf, '/about-me', avatars=True)).encode()
