"""The Letters tab: the newest weekly letter, with a wheel of past weeks to look back on. Read-only."""
from datetime import date as Date, datetime, timedelta, timezone
import html
import sqlite3

from goodmorning.briefings.briefing_day import briefing_day
from goodmorning.records import letters
from goodmorning.runtime_files import normalize_secretary_name, profile_fields
from . import language as ui
from . import quick_chat
from .briefing_chat import avatar_variant
from .briefing_resources import favicon_links
from .chat_theme import clock_theme

WEEKDAYS = {'en': ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'), 'zh-CN': ('周一', '周二', '周三', '周四', '周五', '周六', '周日')}


def week_range(week, today):
    """Oct 19 – 25, or 10月19日 – 25日; the year only when it is not this year's."""
    start = Date.fromisoformat(week)
    end, year = start + timedelta(days=6), start.year != Date.fromisoformat(today).year
    if ui.current() == 'zh-CN':
        return (f'{start.year}年' if year else '') + f'{start.month}月{start.day}日 – ' + (
            f'{end.day}日' if end.month == start.month else f'{end.month}月{end.day}日')
    return f'{start:%b} {start.day} – ' + (str(end.day) if end.month == start.month else f'{end:%b} {end.day}') + (
        f', {start.year}' if year else '')


def words(value, lang):
    return f'<p lang="{html.escape(lang, quote=True)}" data-content>{html.escape(value)}</p>'


def wheel(saved, week, today):
    items = ''.join(f'<li><a href="/letters/{each}"' + (' aria-current="page"' if each == week else '') + '>'
                    f'<span class="wheel-range">{week_range(each, today)}</span>'
                    + ('<span class="wheel-note">' + ui.ui('Latest') + '</span>' if index == 0 else '') + '</a></li>'
                    for index, each in enumerate(saved))
    return '<nav class="letter-wheel" aria-label="' + html.escape(ui.text('Your letters'), quote=True) + '"><ol>' + items + '</ol></nav>'


def heading(icon, title, count=None):
    badge = f' <span class="letter-total">{count}</span>' if count else ''
    return f'<h2><span class="letter-sticker letter-sticker-{icon}" aria-hidden="true"></span>' + ui.ui(title) + badge + '</h2>'


def tile(day):
    value = Date.fromisoformat(day)
    return (f'<span class="letter-date" aria-hidden="true"><small>{WEEKDAYS[ui.current()][value.weekday()]}</small>{value.day}</span>'
            f'<span class="visually-hidden">{ui.day_text(day)}</span>')


def reading(letter, number, today, signature):
    lang, parts = letter['lang'], []
    if letter['finished']:
        named = len(letter['finished']) > 1  # A lone projectless group needs no heading.
        groups = ''.join((f'<p class="letter-project" data-content>{html.escape(project)}</p>' if project
                          else '<p class="letter-project">' + ui.ui('Other tasks') + '</p>' if named else '')
                         + '<ul class="letter-done">' + ''.join('<li><span data-content>' + html.escape(title) + '</span>'
                                                                + (f' <span class="letter-times">×{count}</span>' if count > 1 else '') + '</li>'
                                                                for title, count in items) + '</ul>'
                         for project, items in letter['finished'])
        parts.append('<section>' + heading('done', 'What you finished', letters.counts(letter)[0]) + groups + '</section>')
    if letter['habits']:
        rows = ''.join('<li><span class="letter-habit" data-content>' + html.escape(title) + '</span><span class="letter-detail">'
                       + ui.ui('1 time this week' if times == 1 else '{count} times this week', count=times) + '</span>'
                       + (('<span class="letter-streak"><span class="letter-dots" aria-hidden="true">' + '<i></i>' * min(run, 8) + '</span>'
                           + ui.ui('{count} weeks in a row', count=run) + '</span>') if run > 1 else '') + '</li>'
                       for title, times, run in letter['habits'])
        parts.append('<section>' + heading('habit', 'Habits') + '<ul class="letter-habits">' + rows + '</ul></section>')
    if letter['ideas']:
        parts.append('<section>' + heading('idea', 'Ideas you saved', len(letter['ideas'])) + '<ul class="letter-ideas">'
                     + ''.join('<li data-content>' + html.escape(idea) + '</li>' for idea in letter['ideas']) + '</ul></section>')
    upcoming = letter['next']
    rows = [(day, '<span class="letter-when">' + ui.ui('TBC' if clock is None else 'All day') + '</span>' if not clock
             else f'<span class="letter-when">{clock}</span>', html.escape(title)) for day, clock, title in upcoming['events']]
    rows += [(day, '<span class="letter-when is-due">' + ui.ui('Due') + '</span>', html.escape(title)) for day, title in upcoming['deadlines']]
    if rows or upcoming['planned'] or not upcoming['complete']:
        listing = ''.join(f'<li>{tile(day)}<span class="letter-plan">{when}<span data-content>{title}</span></span></li>'
                          for day, when, title in sorted(rows, key=lambda row: row[0]))
        planned = ('<p class="letter-detail">' + ui.ui('1 task planned across the week' if upcoming['planned'] == 1 else '{count} tasks planned across the week',
                                                      count=upcoming['planned']) + '</p>') if upcoming['planned'] else ''
        gap = '' if upcoming['complete'] else '<p class="letter-detail">' + ui.ui('Some of next week’s plans couldn’t be read when this letter was written.') + '</p>'
        parts.append('<section>' + heading('next', 'Coming up next week') + (f'<ul class="letter-next">{listing}</ul>' if listing else '')
                     + planned + gap + '</section>')
    name, portrait = signature
    return ('<article class="weekly-letter">'
            '<p class="letter-stamp" aria-hidden="true"><span>' + ui.ui('No. {count}', count=number) + '</span></p>'
            '<p class="letter-kicker">' + ui.ui('Weekly letter') + '</p><h1>' + week_range(letter['week'], today) + '</h1>'
            '<div class="letter-opening">' + words(letter['opening'], lang) + '</div>' + ''.join(parts)
            + '<div class="letter-signoff">' + words(letter['signoff'], lang)
            + f'<p class="letter-from"><img src="{html.escape(portrait, quote=True)}" alt="" width="44" height="44">'
            + (f'<span data-content>— {html.escape(name)}</span>' if name else '<span>— ' + ui.ui('Your secretary') + '</span>')
            + '</p></div></article>')


def page(app, week=None):
    zone = app.profile().get('timezone')
    now = app.now() if app.now else datetime.now(timezone.utc)
    today = briefing_day(zone or 'UTC', now)
    theme = clock_theme(zone, now)['theme']
    try:
        letters.catch_up(app.runtime, today, ui.current())
    except (ValueError, OSError, KeyError, sqlite3.Error):
        pass  # Saved letters still open; the next visit or briefing retries.
    saved = letters.weeks(app.runtime)
    week = week or (saved[0] if saved else None)
    if week and week not in saved:
        raise ValueError('No letter for that week')
    note = '' if letters.enabled(app.runtime) else (
        '<p class="letters-note">' + ui.ui('Weekly letters are turned off. Ask your secretary to turn them back on.') + '</p>')
    if week:
        avatar = app.avatar_sources().get(app.avatar()) or {}
        signature = (normalize_secretary_name(profile_fields(app.runtime).get('secretary_name', '')),
                     avatar.get('profile') or avatar.get(avatar_variant(theme)) or '')
        letter = reading(letters.load(app.runtime, week), len(saved) - saved.index(week), today, signature)
        content, title = note + '<div class="letters-desk">' + wheel(saved, week, today) + letter + '</div>', 'Weekly letter'
    else:
        content, title = ('<section class="letters-empty"><h1>' + ui.ui('Weekly letters') + '</h1>' + (note or (
            '<p>' + ui.ui('No letters yet. Your first one is written when you prepare Sunday’s evening briefing.') + '</p>'))
            + '<p class="letters-intro">' + ui.ui('A letter about each week, written with Sunday’s evening briefing and kept here to look back on.')
            + '</p></section>'), 'Weekly letters'
    source = ('<!doctype html><html lang="en" data-edition="' + theme + '"><head><meta charset="utf-8">'
              '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>' + title + ' — GoodMorning</title>'
              + favicon_links('secretary') + '<link rel="stylesheet" href="/briefing.css"><link rel="stylesheet" href="/scroll-rails.css">'
              '<script src="/scroll-rails.js" defer></script><script src="/letters.js" defer></script></head><body class="letters-page">'
              '<header class="masthead"><a class="wordmark" href="/gm">GoodMorning<span>A personal secretary just for you</span></a>'
              '<nav class="edition-switch" aria-label="Your desk"><a class="edition-link" href="/gm">Morning</a><a class="edition-link" href="/gn">Evening</a>'
              '<a class="edition-link" href="/schedule">Schedule</a><a class="edition-link selected" href="/letters" aria-current="page">Letters</a>'
              '<a class="edition-link" href="/chat">Secretary</a></nav></header><main>' + content + '</main></body></html>')
    return app.resources.rewrite(ui.page(quick_chat.widget(source, app.csrf), app.csrf, ('/letters/' + week if week else '/letters'), avatars=True)).encode()
