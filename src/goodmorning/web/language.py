"""English/Chinese interface text. User-authored content is never translated here."""
from contextvars import ContextVar
from datetime import date as Date
import html
from html.parser import HTMLParser
import json
import re

from goodmorning.paths import WEB_ASSETS
from . import color_schemes

LANGUAGES = {'en':'English', 'zh-CN':'Simplified Chinese'}
CURRENT = ContextVar('website_language', default='en')
CATALOG = json.loads((WEB_ASSETS/'translations.json').read_text())
PATTERNS = [(source, re.compile('^'+re.sub(r'\\\{([a-z]+)\\\}', r'(?P<\1>.+?)', re.escape(source))+'$'))
            for source in CATALOG if '{' in source]


def language(value):
    if not isinstance(value,str) or value not in LANGUAGES:
        raise ValueError('Choose English or Simplified Chinese')
    return value


def current():
    return CURRENT.get()


def reply_language(value):
    return LANGUAGES[language(value)]


def text(source, *, lang=None, **values):
    selected = language(lang) if lang is not None else current()
    translated = CATALOG.get(source,source) if selected=='zh-CN' else source
    if values:
        return translated.format(**values)
    if selected=='zh-CN' and source not in CATALOG:
        for key,pattern in PATTERNS:
            match=pattern.fullmatch(source)
            if match:return CATALOG[key].format(**match.groupdict())
    return translated


def ui(source, **values):
    original=source.format(**values) if values else source
    return '<bdi lang="'+current()+'" data-ui-text="'+html.escape(original,quote=True)+'">'+html.escape(text(source,**values))+'</bdi>'


def day_text(day, *, full=False, reference=None):
    """Month-first dates; the year appears only when it differs from the reference day's."""
    value=Date.fromisoformat(day)
    year=bool(reference) and value.year!=Date.fromisoformat(reference[:10]).year
    if current()=='zh-CN':
        return (f'{value.year}年' if year else '')+f'{value.month}月{value.day}日 '+['周一','周二','周三','周四','周五','周六','周日'][value.weekday()]
    label=f'{value:%A}, {value:%B} {value.day}' if full else short_day(value)
    return label+(f', {value.year}' if year else '')


def short_day(value):
    """English dates read month first everywhere: Tue, Oct 13."""
    return f'{value:%a}, {value:%b} {value.day}'


def human_dates(text, reference=None):
    """Show stored ISO dates (and date-times) the way the rest of the page writes dates."""
    def replace(match):
        try:
            label=day_text(match[1],reference=reference)
        except ValueError:
            return match[0]
        return label+(' '+match[2] if match[2] else '')
    return re.sub(r'(?<![\d-])(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2})(?::\d{2})?(?:[+-]\d{2}:?\d{2}|Z)?)?(?![\d:-])',replace,text or '')


def day_label(day, *, full=False, reference=None):
    label=day_text(day,full=full,reference=reference)
    attribute='data-ui-full-date' if full else 'data-ui-date'
    locale=f' lang="{current()}"' if full else ''
    year=' data-ui-year' if reference and day[:4]!=reference[:4] else ''
    return f'<span{locale} {attribute}="{day}"{year}>{label}</span>'


def agenda_day(day, reference=None):
    try:
        value=Date.fromisoformat(day)
        if value.isoformat()!=day:raise ValueError
    except ValueError:
        return html.escape(day)
    relative=({0:'Today',1:'Tomorrow'}.get((value-Date.fromisoformat(reference)).days) if reference else None)
    return (ui(relative)+' — ' if relative else '')+day_label(day,full=True,reference=reference)


class InterfaceHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts=[];self.stack=[]

    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        blocked=(self.stack[-1][1] if self.stack else False) or 'data-content' in values or tag in ('script','style','pre','code')
        raw=self.get_starttag_text()
        if not blocked:
            for key in ('aria-label','title','placeholder','alt'):
                value=values.get(key)
                if value and (value in CATALOG or any(pattern.fullmatch(value) for _,pattern in PATTERNS)):
                    raw=re.sub(r'\b'+key+r'=("[^"]*"|\x27[^\x27]*\x27)',key+'="'+html.escape(text(value),quote=True)+'"',raw,count=1)
                    if 'data-ui-'+key not in values:
                        raw=raw[:-1]+' data-ui-'+key+'="'+html.escape(value,quote=True)+'">'
        self.parts.append(raw)
        if tag not in ('area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'):
            self.stack.append((tag,blocked or 'data-ui-text' in values or 'data-ui-date' in values))

    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if self.stack and self.stack[-1][0]==tag:self.stack.pop()

    def handle_endtag(self,tag):
        self.parts.append('</'+tag+'>')
        if self.stack and self.stack[-1][0]==tag:self.stack.pop()

    def handle_data(self,data):
        value=data.strip()
        known=value in CATALOG or any(pattern.fullmatch(value) for _,pattern in PATTERNS)
        if not (self.stack and self.stack[-1][1]) and known:
            # Title is text-only; do not insert markup inside it.
            if self.stack and self.stack[-1][0]=='title':
                if 'data-ui-title' not in self.parts[-1]:
                    self.parts[-1]=self.parts[-1][:-1]+' data-ui-title="'+html.escape(value,quote=True)+'">'
                output=html.escape(text(value))
            else:output=ui(value)
            self.parts.append(data[:len(data)-len(data.lstrip())]+output+data[len(data.rstrip()):])
        else:self.parts.append(data)

    def handle_entityref(self,name):self.parts.append('&'+name+';')
    def handle_charref(self,name):self.parts.append('&#'+name+';')
    def handle_decl(self,decl):self.parts.append('<!'+decl+'>')
    def handle_comment(self,data):self.parts.append('<!--'+data+'-->')


def page(source,csrf,return_to='/',avatars=False):
    from .release import VERSION
    # Load the shared response reader before every deferred page script.
    if '/network.js' not in source:
        source=re.sub(r'(<head\b[^>]*>)',r'\1<script src="/network.js" defer></script>',source,count=1)
    if 'id="site-release"' not in source:
        source=source.replace('</head>','<link rel="stylesheet" href="/update.css"><script src="/update.js" defer></script></head>')
        notice='<div id="site-release" hidden data-version="'+VERSION+'"></div>'
        source=source.replace('</body>',notice+'</body>')
    else:
        # A proxied backend may have embedded its own fingerprint; the served
        # document must match this process's /api/release source of truth.
        source=re.sub(r'id="site-release"[^>]*data-version="[a-f0-9]{64}"','id="site-release" hidden data-version="'+VERSION+'"',source,count=1)
        if '/update.js' not in source:
            source=source.replace('</head>','<link rel="stylesheet" href="/update.css"><script src="/update.js" defer></script></head>')
    config=html.escape(json.dumps({'language':current(),'csrf':csrf}),quote=True)
    # Top-right utility cluster: two compact menus plus the update pill's fixed
    # slot. Native details/summary keeps every control usable without
    # JavaScript; each panel is an absolutely positioned dropdown.
    account=''
    match=re.search(r'<nav class="account-tools".*?</nav>',source,flags=re.S)
    if match:
        account=match[0]
        source=source[:match.start()]+source[match.end():]
    close=('<button class="settings-close" type="button" aria-label="Close menu"><svg viewBox="0 0 20 20" width="16" height="16" fill="none" aria-hidden="true">'
           '<path d="m6 6 8 8m0-8-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></button>')
    language_form=('<form id="language-form" class="language-toolbar" action="/api/language" method="post">'
           '<label for="website-language">Website language</label><select id="website-language" name="language">'
           +''.join(f'<option value="{code}" lang="{code}"'+(' selected' if code==current() else '')+' data-content>'+label+'</option>'
                    for code,label in (('en','English'),('zh-CN','简体中文')))+
           '</select><input type="hidden" name="csrf" value="'+html.escape(csrf or '',quote=True)+'">'
           '<input type="hidden" name="return_to" value="'+html.escape(return_to,quote=True)+'">'
           '<noscript><button type="submit">Apply</button></noscript><span id="language-feedback" role="status"></span></form>')
    appearance='<form id="color-scheme-form"></form>'  # Filled by color_schemes.page.
    # The linked app reveals this for its own widgets; see app.js.
    widgets=('<form id="widget-theme-form" class="language-toolbar" hidden>'
           '<label for="widget-theme">Widget theme</label><select id="widget-theme" name="theme">'
           +''.join(f'<option value="{code}">{label}</option>' for code,label in (
               ('clock','Day and night by the clock'),('phone',"Follow the phone’s dark mode"),
               ('day','Always the day scheme'),('night','Always the night scheme')))+
           '</select><p class="notification-note">For this phone’s home screen widgets. The clock switches at 06:00 and 18:00, like the website.</p>'
           '<span id="widget-theme-feedback" role="status"></span></form>')
    # Hosted pages reveal this where the device can show notifications; see app.js.
    notifications=('<form id="notification-form" class="language-toolbar notification-settings" hidden>'
           '<h3 class="color-scheme-heading notification-heading">Notifications</h3><p id="notification-status"></p>'
           '<button type="button" id="notification-device" hidden></button>'
           '<div id="notification-choices" hidden><fieldset id="notification-kinds"><legend>Notify me when</legend>'
           +''.join(f'<label><input type="checkbox" name="{name}"> {label}</label>' for name,label in (
               ('briefing','A briefing is ready'),('waiting','My secretary needs my answer'),
               ('chat','A chat reply is finished'),('events','An event is about to start')))+
           '</fieldset><label for="notification-lead">Remind me before events</label><select id="notification-lead" name="lead">'
           +''.join(f'<option value="{minutes}">{minutes} minutes</option>' for minutes in (5,10,15,30,60))+
           '</select><fieldset id="briefing-reminders"><legend>Remind me to prepare a briefing</legend>'
           +''.join(f'<div class="briefing-reminder"><label><input type="checkbox" name="{kind}"> {label}</label>'
                    f'<input type="time" name="{kind}_time" aria-label="{label} reminder time" required></div>'
                    for kind,label in (('gm','Morning briefing'),('gn','Evening briefing')))+
           '<p class="notification-note">Sent at that time only if the briefing isn’t prepared yet.</p></fieldset>'
           '<p class="notification-note">These choices apply to this device only.</p></div>'
           '<span id="notification-feedback" role="status"></span></form>')
    phones=('<form id="app-link-form" class="language-toolbar app-link-settings" hidden>'
           '<h3 class="color-scheme-heading app-link-heading">Linked phones</h3>'
           '<p class="notification-note">Linked phones show your schedule, briefings and secretary chat in Android home screen widgets. '
           'In the GoodMorning app, open Link this phone, then enter the code it shows.</p>'
           '<label for="app-link-code">Code from the app</label>'
           '<input id="app-link-code" name="code" autocomplete="off" autocapitalize="characters" spellcheck="false" inputmode="text" placeholder="ABCD-2345" required>'
           '<button type="submit">Link phone</button><ul id="app-links"></ul>'
           '<span id="app-link-feedback" role="status"></span></form>'
           '<section id="notification-devices" class="language-toolbar notification-settings" hidden>'
           '<h3 class="color-scheme-heading notification-heading">Devices with notifications</h3>'
           '<p class="notification-note">Each device chooses its own notifications in its Settings. Turn one off here if you no longer use it.</p>'
           '<ul id="notification-device-list"></ul><span id="notification-devices-feedback" role="status"></span></section>')
    # avatar.js fills in the choices and reveals the picker once the account's avatars load.
    avatar=('<section id="avatar-settings" class="language-toolbar" aria-labelledby="avatar-settings-heading" hidden>'
           '<h3 id="avatar-settings-heading" class="color-scheme-heading">Secretary avatar</h3>'
           '<div class="avatar-previews" role="listbox" aria-label="Secretary avatars"></div>'
           '<p class="avatar-upload-heading">Upload your own avatar</p><div class="avatar-uploads">'
           +''.join(f'<button type="button" class="avatar-upload" data-avatar-upload="{kind}" aria-label="{label}">{text}</button>'
                    for kind,text,label in (('day','Scene · day','Upload day scene'),('night','Scene · night','Upload night scene'),
                                            ('profile','Profile','Upload profile picture')))+
           '</div><input type="file" data-avatar-file accept="image/png,image/jpeg,image/webp" aria-label="Upload your own avatar" hidden>'
           '<p class="notification-note">PNG, JPEG or WebP, up to 5 MB. Missing images are filled in from the ones you upload.</p>'
           '<span class="avatar-feedback" role="status"></span></section>') if avatars or account else ''
    about=('<a id="about-me-link" href="/about-me"><span class="color-scheme-heading about-me-heading">About me</span>'
           '<span class="notification-note">What your secretary knows about you</span></a>')
    # Settings holds what belongs to this device; Account what follows the signed-in owner everywhere.
    # Without an account (sign-in page, local viewer) language stays with this device too.
    prefs=('<details class="menu" id="prefs-menu"><summary><span aria-hidden="true">⚙</span> '
           '<span class="menu-label">Settings</span></summary>'
           '<div class="menu-panel"><div class="settings-menu-header"><div><h2>Settings</h2><p>'
           +('Choices for this device only.' if account else 'Make this space yours.')+'</p></div>'+close+'</div>'
           +(appearance+widgets+notifications if account else language_form+appearance+avatar)+'</div></details>')
    account_menu=('<details class="menu" id="account-menu"><summary><span class="menu-label">Account</span></summary>'
                  '<div class="menu-panel"><div class="settings-menu-header account-menu-header"><div><h2>Account</h2>'
                  '<p>These follow you on every device you sign in on.</p></div>'+close+'</div>'
                  +about+avatar+language_form+phones+account+'</div></details>') if account else ''
    controls=('<div class="toolbar-row">'+prefs+account_menu+'<span id="update-slot"></span></div>')
    if avatar and '/avatar.js' not in source:
        source=source.replace('</head>','<link rel="stylesheet" href="/avatar.css"><script src="/avatar.js" defer></script></head>',1)
    if 'id="language-form"' not in source:
        source=re.sub(r'(<body\b[^>]*>)',lambda match:match[0]+controls,source,count=1)
    elif account and 'id="account-menu"' not in source:
        # A proxied backend page brings device-only menus; signed in, they are rebuilt with Account.
        source=re.sub(r'<div class="toolbar-row">.*?<span id="update-slot"></span></div>',lambda _:controls,source,count=1,flags=re.S)
    marker='<div id="language-config" hidden data-config="'+config+'"></div>'
    if 'id="language-config"' in source:
        source=re.sub(r'<div id="language-config"[^>]*></div>',lambda _:marker,source,count=1)
        source=re.sub(r'(<input type="hidden" name="csrf" value=")[^"]*(")',lambda match:match[1]+html.escape(csrf or '',quote=True)+match[2],source)
        source=re.sub(r'(<input type="hidden" name="return_to" value=")[^"]*(")',lambda match:match[1]+html.escape(return_to,quote=True)+match[2],source)
    else:
        source=source.replace('</head>','<script src="/language.js" defer></script></head>')
        source=source.replace('</body>',marker+'</body>')
    return translate(color_schemes.page(source,csrf,return_to))


def translate(source):
    """Interface text in the current language; saved content (data-content) stays as written."""
    source=re.sub(r'<html\b[^>]*\blang="[^"]*"',lambda match:re.sub(r'lang="[^"]*"','lang="'+current()+'"',match[0]),source,count=1)
    parser=InterfaceHTML();parser.feed(source);parser.close()
    return ''.join(parser.parts)
