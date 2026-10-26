"""About me: what the secretary knows about the user, read from the profile on every request.

Each entry of SECTIONS renders one section from the current profile fields, so a
later feature adds its own section (or a row in an existing one) without a copy
of the data. Simple text fields and the evening extras' switches save through
`set_profile_fields`; anything that needs a provider or feed check stays in chat.
"""
from datetime import datetime, timezone
import html
import re

from goodmorning import anime, games, stocks
from goodmorning.records import letters
from goodmorning.runtime_files import (PROFILE_TEXT_MAX as LONG, SECRETARY_NAME_MAX as SHORT, calendar_config,
                                       profile_fields, set_profile_fields)
from . import language as ui
from . import quick_chat
from .briefing_resources import favicon_links
from .chat_theme import clock_theme

# Edited on the page: key -> label, character limit.
TEXT = {'secretary_name': ('Your secretary’s name', SHORT), 'user_name': ('What your secretary calls you', SHORT),
        'work_days': ('Work days', LONG), 'work_hours': ('Work hours', LONG), 'sleep_time': ('Bedtime', LONG),
        'secretary_tone': ('Tone', LONG), 'special_needs': ('Things to keep in mind', LONG),
        'occupations': ('Roles', LONG), 'expertise_fields': ('Expertise', LONG), 'industry': ('Industry', LONG),
        'project_scope': ('Projects', LONG), 'knowledge_area': ('Knowledge area', LONG)}
SOURCES = {'anilist': 'AniList', 'bangumi': 'Bangumi', 'myanimelist': 'MyAnimeList'}
# The user-facing reason for each rule `set_profile_fields` enforces.
REASONS = {'use 1-30 characters': 'Use up to 30 characters.', 'use at most 300 characters': 'Use up to 300 characters.',
           'no control characters or newlines': 'Keep it on one line.',
           'include at least one letter or number': 'Include at least one letter or number.'}


class Invalid(ValueError):
    """A value the user can fix; the message is interface text."""


def chat(starter):
    return ('<a class="about-chat" href="/chat" data-quick-ask="' + html.escape(starter, quote=True) + '">'
            + ui.ui('Change in chat') + '</a>')


def value(text):
    return f'<span class="about-value" data-content>{html.escape(text)}</span>' if text else '<span class="about-empty">' + ui.ui('Not set yet') + '</span>'


def row(label, content, action='', key=None):
    field, label_id = (f' data-field="{key}"', f' id="about-label-{key}"') if key else ('', '')
    return (f'<div class="about-row"{field}><dt{label_id}>' + ui.ui(label) + f'</dt><dd class="about-content">{content}</dd>'
            f'<dd class="about-action">{action}</dd></div>')


def text_row(fields, key):
    label, limit = TEXT[key]
    return row(label, value(fields.get(key, '')),
               f'<button class="about-edit" type="button" data-limit="{limit}" hidden>' + ui.ui('Edit') + '</button>', key)


def section(identifier, title, rows, note=''):
    return (f'<section class="about-section" id="about-{identifier}"><h2>' + ui.ui(title) + '</h2><dl>' + ''.join(rows) + '</dl>'
            + ('<p class="about-note">' + ui.ui(note) + '</p>' if note else '') + '</section>')


def count(singular, plural, number):
    return ui.ui(singular if number == 1 else plural, count=number)


def names(app, fields):
    return section('names', 'Names', [text_row(fields, 'secretary_name'), text_row(fields, 'user_name')])


def day(app, fields):
    return section('day', 'Your day', [row('City', value(fields.get('city', '')), chat('I’d like to change my city.')),
                                       row('Time zone', value(fields.get('timezone', '')), chat('I’d like to change my time zone.')),
                                       *(text_row(fields, key) for key in ('work_days', 'work_hours', 'sleep_time'))])


def talk(app, fields):
    return section('talk', 'How your secretary talks with you', [text_row(fields, 'secretary_tone'), text_row(fields, 'special_needs')])


def work(app, fields):
    return section('work', 'Work and interests', [text_row(fields, key) for key in
                                                  ('occupations', 'expertise_fields', 'industry', 'project_scope', 'knowledge_area')])


def news(app, fields):
    codes = [fields.get('news_country', ''), *re.split(r'[\s,;]+', fields.get('news_additional_countries', ''))]
    codes = list(dict.fromkeys(code.upper() for code in codes if re.fullmatch(r'[A-Za-z]{2}', code)))
    content = (f'<span class="about-value" data-countries="{",".join(codes)}">{", ".join(codes)}</span>' if codes else value(''))
    return section('news', 'News', [row('National news', content, chat('I’d like to change which countries’ news I get.'))])


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
        held = stocks.holdings(fields.get('stock_holdings', ''))
        state['stock_report'] = ['<br>'.join(
            f'<span data-content>{html.escape(symbol)}</span> · ' + count('1 share', '{count} shares', shares)
            + (' · ' + ui.ui('cost {price}', price=('$' if symbol.startswith('us') else '¥') + f'{cost:,.2f}') if cost else '')
            for symbol, (shares, cost, _) in held.items())]
    except stocks.StockError:
        pass
    state['weekly_letter'] = [ui.ui('Written with Sunday’s evening briefing')]
    return state


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
        content = (switch(key, on[key]) + '<span class="about-details">' + ' · '.join(details) + '</span>') if details else value('')
        rows.append(row(label, content, chat(starter) if starter else '', key))
    return section('extras', 'Evening briefing extras', rows,
                   'Switching one off keeps its settings, so you can turn it back on later. To turn one on for the first time, ask in chat.')


def calendar(app, fields):
    linked = bool(calendar_config(app.runtime).get('ics_url'))
    content = '<span class="about-value">' + ui.ui('Connected') + '</span>' if linked else value('')
    return section('calendar', 'Calendar', [row('Linked calendar', content, chat('I’d like to change my linked calendar.'))])


def project_names(runtime):
    """Names from the profile's Project roots lines (`- Name | path | ...`); paths and scopes stay private."""
    try:
        text = (runtime / 'profile.md').read_text(encoding='utf-8')
    except FileNotFoundError:
        return []
    block = re.search(r'^## Project roots[ \t]*$(.*?)(?=^## |\Z)', text, re.M | re.S)
    return [match[1].strip() for match in re.finditer(r'^- ([^|\r\n]+)\|', block[1], re.M)] if block else []


def projects(app, fields):
    found = project_names(app.runtime)
    return section('projects', 'Projects', [row('Linked projects', value(', '.join(found)), chat('I’d like to change my projects.'))])


SECTIONS = [names, day, talk, work, news, extras, calendar, projects]


def save(app, body):
    """One field per request: a text field's new value, or an evening extra switched on or off."""
    if not isinstance(body, dict) or set(body) != {'field', 'value'} or not isinstance(body['value'], str):
        raise ValueError('Invalid About me change')
    key, text = body['field'], body['value']
    if not (app.runtime / 'profile.md').is_file():
        raise ValueError('No profile to change yet')
    if key in ('anime_updates', 'game_sales', 'stock_report', 'weekly_letter'):
        if text not in ('true', 'false'):
            raise ValueError('Invalid switch')
        if text == 'true' and key not in extras_state(app.runtime, profile_fields(app.runtime)):
            raise Invalid('Ask in chat to set this up first.')
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
    source = ('<!doctype html><html lang="en" data-edition="' + theme + '"><head><meta charset="utf-8">'
              '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>About me — GoodMorning</title>'
              + favicon_links('secretary') + '<link rel="stylesheet" href="/briefing.css"><link rel="stylesheet" href="/about-me.css">'
              '</head><body class="about-page">'
              '<header class="masthead"><a class="wordmark" href="/gm.html">GoodMorning<span>A personal secretary just for you</span></a>'
              '<nav class="edition-switch" aria-label="Your desk"><a class="edition-link" href="/gm.html">Morning</a><a class="edition-link" href="/gn.html">Evening</a>'
              '<a class="edition-link" href="/schedule">Schedule</a><a class="edition-link" href="/letters">Letters</a>'
              '<a class="edition-link" href="/chat">Secretary</a></nav></header>'
              '<main class="about-me"' + ('' if (app.runtime / 'profile.md').is_file() else ' data-readonly') + '><header class="about-intro"><h1>About me</h1>'
              '<p>What your secretary knows about you. It uses this to plan your days and write your briefings.</p></header>'
              # After language.js, which the shared page shell adds to the head.
              + content + '</main><script src="/about-me.js" defer></script></body></html>')
    return app.resources.rewrite(ui.page(quick_chat.widget(source, app.csrf), app.csrf, '/about-me')).encode()
