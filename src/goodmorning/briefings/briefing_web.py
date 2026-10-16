"""Render validated browser-native editions and cache authorized publisher images."""
import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
from datetime import date as Date

from .briefing_layout import celestial, icon
from .briefing_images import cache_previews, cached_previews
from . import briefing_document as native
from goodmorning.news.news_cache import feed_images
from goodmorning.paths import WEB_ASSETS
from goodmorning.runtime_files import cache_path
from goodmorning.web.briefing_resources import ICON_TYPES, favicon_links
from goodmorning.web import language as ui

ASSETS = WEB_ASSETS
KINDS = {"gm": "Morning", "gn": "Evening"}


class PreviewText(HTMLParser):
    """Extract an inert excerpt from the rendered section."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def excerpt(self, content):
        self.feed(content)
        text = " ".join(" ".join(self.parts).split())
        return text if len(text) <= 180 else text[:180].rsplit(" ", 1)[0] + "…"


def visible_text(source):
    """Hide bookkeeping tokens without changing saved data or link targets."""
    return re.sub(r'(?<![\w/])(?:ib_[0-9a-f]{16,64}|ses_[A-Za-z0-9]+|(?:task|todo)_[0-9a-f]{16,64})(?!\w)', '', source)


def display_heading(title, translate=False):
    """Section heading with a subtle date badge instead of a raw ISO suffix."""
    base, iso = native.split_dated_title(title.strip())
    if not iso:
        return ui.ui(title.strip()) if translate else native.escaped(title.strip())
    human = native.humanize_iso_date(iso)
    badge = (f' <span class="section-date" data-date="{html.escape(iso, quote=True)}">'
             f'<span aria-hidden="true">· {html.escape(human)}</span>'
             f'<span class="visually-hidden"> ({html.escape(iso)})</span></span>')
    if translate:
        return ui.ui(base) + badge
    return html.escape(base) + badge


def navigation(number, title, body, kind, ui_title=False):
    label = html.escape(title.strip())
    attributes=f' data-ui-section-title="{label}" data-ui-section-number="{number:02d}"' if ui_title else ''
    accessible=html.escape(ui.text(title.strip())) if ui_title else label
    base, iso = native.split_dated_title(title.strip())
    if iso:
        human = native.humanize_iso_date(iso)
        badge = (f' <span class="preview-date" data-date="{html.escape(iso, quote=True)}">'
                 f'· {html.escape(human)}</span>')
        if ui_title:
            visible = ui.ui(base) + badge
        else:
            visible = html.escape(base) + badge
    else:
        visible=ui.ui(title.strip()) if ui_title else label
    preview = html.escape(PreviewText().excerpt(body))
    return f'<div class="scroll-segment"><a class="scroll-chunk" href="#section-{number}"{attributes} aria-label="{number:02d}: {accessible}" aria-describedby="preview-{number}"><span class="chunk-bar" aria-hidden="true"></span><span class="chunk-number" aria-hidden="true">{number:02d}</span></a><span class="nav-preview" id="preview-{number}" role="tooltip"><span class="preview-eyebrow">{ui.ui("SECTION {number} / "+KINDS[kind].upper()+" EDITION",number=f"{number:02d}")}</span><span class="preview-title" data-content>{visible}</span><span class="preview-excerpt" data-content>{ui.ui(PreviewText().excerpt(body)) if ui_title else preview}</span><span class="preview-footer"><span class="preview-lines" aria-hidden="true"></span><span class="pointer-hint">{ui.ui("Jump to section ↗")}</span><span class="touch-hint">{ui.ui("Tap again to jump ↗")}</span></span></span></div>'


def section_markup(number, heading, content, layout, pending=False):
    symbol = {'weather': 'sun', 'news': 'news', 'schedule': 'calendar',
              'must-do': 'check', 'nice-to-do': 'list', 'reminders': 'bell', 'tomorrow': 'calendar',
              'today': 'sun', 'still-open': 'list', 'tasks': 'check', 'attention': 'bell'}.get(layout, 'list')
    busy = ' data-pending="true" aria-busy="true"' if pending else ''
    return f'<section id="section-{number}" class="briefing-section {layout}"{busy}><header><span class="section-number">{number:02d}</span><h2>{heading}</h2><span class="section-symbol">{icon(symbol)}</span></header><div class="section-body">{content}</div></section>'


def loading_body(layout):
    return f'<div class="section-loading loading-{layout}"><div class="section-loader" aria-hidden="true"><span></span><span></span><span></span></div><p class="section-loading-label">{ui.ui("Waiting its turn")}</p><div class="skeleton-lines" aria-hidden="true"><i></i><i></i><i></i></div></div>'


def preview_shell(plan, kind, ui_titles=False):
    sections = ''.join(section_markup(n, display_heading(title, translate=ui_titles), loading_body(tag), tag, pending=True)
                       for n, (tag, title) in enumerate(plan, 1))
    nav = ''.join(navigation(n, title, '<p>Waiting its turn</p>', kind,ui_title=ui_titles) for n, (_, title) in enumerate(plan, 1))
    return sections, nav


def edition(document, date, kind, available, images=None, preview_plan=None, ui_intro=False):
    native.validate(document, partial=preview_plan is not None)
    nav, sections = [], []
    for number, section in enumerate(document['sections'], 1):
        title = visible_text(native.section_title(section, date,document.get('lang','en')))
        content = ''.join(native.render_block(value, images or {}, date) for value in section[1])
        if len(section) >= 3 and section[2]:
            content += '<p class="section-takeaway">' + native.escaped(section[2]) + '</p>'
        nav.append(navigation(number, title, content, kind))
        sections.append(section_markup(number, display_heading(title), content, section[0]))
    if preview_plan is not None:
        panels, chunks = preview_shell(preview_plan, kind,ui_titles=ui_intro)
        sections, nav = [panels], [chunks]
    switches = []
    for other, label in KINDS.items():
        if other in available:
            selected = ' selected' if other == kind else ''
            current = ' aria-current="page"' if other == kind else ''
            switches.append(f'<a class="edition-link{selected}" href="{other}.html"{current}>{label}</a>')
        else:
            switches.append(f'<span class="edition-unavailable" aria-label="{label} briefing not available yet"><span>{label}</span><small>Not yet</small></span>')
    template = (ASSETS / "edition.html").read_text(encoding="utf-8")
    values = {"KIND": kind, "DATE": date, "EDITION": KINDS[kind], "ARTICLELABEL":ui.text(KINDS[kind]+' briefing'), "SWITCHES": ''.join(switches),
              "NAV": ''.join(nav), "SECTIONS": ''.join(sections), "INTRO": '',
              "HASH": hashlib.sha256(json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:12],
              "TITLE": ui.ui(document['greeting']) if ui_intro else native.escaped(document['greeting']), "SUBTITLE": ui.ui(document['opening']) if ui_intro else native.escaped(document['opening']),
              "LANG": ui.current() if ui_intro else document.get('lang', 'en'),
              "CLOSING": '<p class="briefing-closing">' + native.escaped(document['closing']) + '</p>' if document.get('closing') else '',
              "SOURCE": kind + '.json', "SOURCELABEL": 'View saved data',
              "CELESTIAL": celestial(kind), "ICONS": favicon_links(kind, '')}
    output=re.sub(r"\{\{([A-Z]+)\}\}", lambda match: values[match[1]], template)
    return output.replace('data-content lang=','data-ui-language lang=') if ui_intro else output


def build(runtime, date, fetch_images=False, include_assets=True, kind=None):
    if Date.fromisoformat(date).isoformat() != date:
        raise ValueError("Use an ISO YYYY-MM-DD date")
    if kind is not None and kind not in KINDS:
        raise ValueError('Unknown edition kind')
    sources = {}
    for selected in ([kind] if kind else KINDS):
        path = native.source_path(runtime, date, selected)
        if path.is_file():
            sources[selected] = path.read_bytes()
    if not sources:
        raise ValueError("No saved morning or evening briefing for this date")
    documents = {kind: native.parse(source.decode('utf-8')) for kind, source in sources.items()}
    urls = list(dict.fromkeys(url for document in documents.values() for url in native.news_urls(document)))[:32]
    cache = runtime / 'browser-images' / date
    if fetch_images and urls:
        try:
            hints = feed_images(str(cache_path()), urls)
        except (ValueError, sqlite3.Error):
            hints = {}  # The archive only adds a fallback; previews still work without it.
        cache_previews(urls, cache, runtime / 'browser-images' / 'objects', hints)
    images, image_files = cached_previews(cache, urls, responsive=not include_assets)
    files = dict(image_files)
    for kind, document in documents.items():
        files[f'{kind}.html'] = edition(document, date, kind, documents, images).encode()
        files[kind + '.json'] = sources[kind]
    if include_assets:
        for name in ('briefing.css', 'briefing.js', 'fonts/lora-italic.woff2', 'fonts/OFL.txt', *ICON_TYPES):
            files[name] = (ASSETS / name).read_bytes()
    files['index.html'] = files['gm.html' if 'gm' in documents else 'gn.html']
    return files


def main():
    parser = argparse.ArgumentParser(description='Cache publisher previews for saved native editions; never export webpages.')
    parser.add_argument('--secretary-dir', type=Path, required=True)
    parser.add_argument('--date', required=True)
    parser.add_argument('--fetch-images', action='store_true', required=True, help='Explicitly authorize public publisher-image requests')
    args = parser.parse_args()
    files = build(args.secretary_dir.expanduser().resolve(), args.date, fetch_images=True, include_assets=False)
    print(json.dumps({'date': args.date, 'publisher_images': sum(name.startswith('media/') for name in files), 'exported': False}), flush=True)


if __name__ == '__main__':
    main()
