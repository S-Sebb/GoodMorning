"""The Letters tab: every saved weekly letter, newest first, as a memory book to look back on. Read-only."""
from datetime import date as Date, datetime, timedelta, timezone
import html
from zoneinfo import ZoneInfo

from goodmorning.briefings.briefing_document import letter_counts
from goodmorning.records import letters
from . import language as ui
from . import quick_chat
from .briefing_resources import favicon_links
from .chat_theme import clock_theme


def week_label(week, today):
    end = (Date.fromisoformat(week) + timedelta(days=6)).isoformat()
    return ui.day_label(week, reference=today) + ' – ' + ui.day_label(end, reference=today)


def words(value, lang):
    return f'<p lang="{html.escape(lang, quote=True)}" data-content>{html.escape(value)}</p>'


def shelf(runtime, today):
    saved = letters.weeks(runtime)
    items = ''.join(f'<li><a href="/letters/{week}"><span class="letters-week">{week_label(week, today)}</span>'
                    f'{letter_counts(letters.counts(letters.load(runtime, week)))}</a></li>' for week in saved)
    if not letters.enabled(runtime):
        note = '<p class="letters-note">' + ui.ui('Weekly letters are turned off. Ask your secretary to turn them back on.') + '</p>'
    elif not saved:
        note = '<p class="letters-note">' + ui.ui('No letters yet. Your first one is written when you prepare Sunday’s evening briefing.') + '</p>'
    else:
        note = ''
    return ('<section class="letters-shelf"><h1>' + ui.ui('Weekly letters') + '</h1>'
            '<p class="letters-intro">' + ui.ui('A letter about each week, written with Sunday’s evening briefing and kept here to look back on.') + '</p>'
            + note + ('<ol class="letters-list">' + items + '</ol>' if items else '') + '</section>')


def reading(letter, today):
    lang, parts = letter['lang'], []
    total = letters.counts(letter)[0]
    if letter['finished']:
        named = len(letter['finished']) > 1  # A lone projectless group needs no heading.
        groups = ''.join(('<h3 data-content>' + html.escape(project) + '</h3>' if project else '<h3>' + ui.ui('Other tasks') + '</h3>' if named else '')
                         + '<ul>' + ''.join('<li><span data-content>' + html.escape(title) + '</span>'
                                            + (f' <span class="letter-times">×{count}</span>' if count > 1 else '') + '</li>' for title, count in items) + '</ul>'
                         for project, items in letter['finished'])
        parts.append('<section><h2>' + ui.ui('What you finished') + f' <span class="letter-total">{total}</span></h2>' + groups + '</section>')
    if letter['habits']:
        rows = ''.join('<li><span data-content>' + html.escape(title) + '</span> <span class="letter-detail">'
                       + ui.ui('1 time this week' if times == 1 else '{count} times this week', count=times)
                       + (' · ' + ui.ui('{count} weeks in a row', count=run) if run > 1 else '') + '</span></li>'
                       for title, times, run in letter['habits'])
        parts.append('<section><h2>' + ui.ui('Habits') + '</h2><ul>' + rows + '</ul></section>')
    if letter['ideas']:
        parts.append('<section><h2>' + ui.ui('Ideas you saved') + f' <span class="letter-total">{len(letter["ideas"])}</span></h2><ul>'
                     + ''.join('<li data-content>' + html.escape(idea) + '</li>' for idea in letter['ideas']) + '</ul></section>')
    upcoming = letter['next']
    rows = [(day, '<span class="letter-when">' + ui.ui('TBC' if clock is None else 'All day') + '</span>' if not clock
             else f'<span class="letter-when">{clock}</span>', html.escape(title)) for day, clock, title in upcoming['events']]
    rows += [(day, '<span class="letter-when">' + ui.ui('Due') + '</span>', html.escape(title)) for day, title in upcoming['deadlines']]
    if rows or upcoming['planned'] or not upcoming['complete']:
        listing = ''.join(f'<li><span class="letter-day">{ui.day_label(day, reference=today)}</span> {when} <span data-content>{title}</span></li>'
                          for day, when, title in sorted(rows, key=lambda row: row[0]))
        planned = ('<p class="letter-detail">' + ui.ui('1 task planned across the week' if upcoming['planned'] == 1 else '{count} tasks planned across the week',
                                                      count=upcoming['planned']) + '</p>') if upcoming['planned'] else ''
        gap = '' if upcoming['complete'] else '<p class="letter-detail">' + ui.ui('Some of next week’s plans couldn’t be read when this letter was written.') + '</p>'
        parts.append('<section><h2>' + ui.ui('Coming up next week') + '</h2>' + (f'<ul>{listing}</ul>' if listing else '') + planned + gap + '</section>')
    return ('<article class="weekly-letter"><a class="letters-back" href="/letters">' + ui.ui('All letters') + '</a>'
            '<p class="eyebrow">' + ui.ui('Weekly letter') + '</p><h1>' + week_label(letter['week'], today) + '</h1>'
            '<div class="letter-opening">' + words(letter['opening'], lang) + '</div>' + ''.join(parts)
            + '<div class="letter-signoff">' + words(letter['signoff'], lang) + '</div></article>')


def page(app, week=None):
    zone = app.profile().get('timezone')
    now = app.now() if app.now else datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(zone or 'UTC')).date().isoformat()
    if week:
        letter = letters.load(app.runtime, week)
        if letter is None:
            raise ValueError('No letter for that week')
        content, title = reading(letter, today), 'Weekly letter'
    else:
        content, title = shelf(app.runtime, today), 'Weekly letters'
    source = ('<!doctype html><html lang="en" data-edition="' + clock_theme(zone, now)['theme'] + '"><head><meta charset="utf-8">'
              '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>' + title + ' — GoodMorning</title>'
              + favicon_links('secretary') + '<link rel="stylesheet" href="/briefing.css"><link rel="stylesheet" href="/scroll-rails.css"><script src="/scroll-rails.js" defer></script>'
              '</head><body class="letters-page">'
              '<header class="masthead"><a class="wordmark" href="/gm.html">GoodMorning<span>A personal secretary just for you</span></a>'
              '<nav class="edition-switch" aria-label="Your desk"><a class="edition-link" href="/gm.html">Morning</a><a class="edition-link" href="/gn.html">Evening</a>'
              '<a class="edition-link" href="/schedule">Schedule</a><a class="edition-link selected" href="/letters" aria-current="page">Letters</a>'
              '<a class="edition-link" href="/chat">Secretary</a></nav></header><main>' + content + '</main></body></html>')
    return app.resources.rewrite(ui.page(quick_chat.widget(source, app.csrf), app.csrf, '/letters/' + week if week else '/letters')).encode()
