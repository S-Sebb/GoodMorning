"""English/Chinese interface text. User-authored content is never translated here."""
from contextvars import ContextVar
from datetime import date as Date
import html
from html.parser import HTMLParser
import json
import re

from goodmorning.paths import WEB_ASSETS
from .models import MODELS, current as current_model
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


def day_label(day, *, full=False):
    value=Date.fromisoformat(day)
    label = ((f'{value.year}年' if full else '')+f'{value.month}月{value.day}日 '+['周一','周二','周三','周四','周五','周六','周日'][value.weekday()]
             if current()=='zh-CN' else value.strftime('%a %d %b'))
    if full and current()=='en':label=value.strftime('%A, %d %B %Y')
    attribute='data-ui-full-date' if full else 'data-ui-date'
    locale=f' lang="{current()}"' if full else ''
    return f'<span{locale} {attribute}="{day}">{label}</span>'


def agenda_day(day, reference=None):
    try:
        value=Date.fromisoformat(day)
        if value.isoformat()!=day:raise ValueError
    except ValueError:
        return html.escape(day)
    relative=({0:'Today',1:'Tomorrow'}.get((value-Date.fromisoformat(reference)).days) if reference else None)
    return (ui(relative)+' — ' if relative else '')+day_label(day,full=True)


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


def page(source,csrf,return_to='/'):
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
    current_label='简体中文' if current()=='zh-CN' else 'English'
    prefs=('<details class="menu" id="prefs-menu"><summary><span aria-hidden="true">⚙</span> '
           '<span class="menu-label">Settings</span><span id="prefs-current" class="settings-language" data-content>'+current_label+'</span></summary>'
           '<div class="menu-panel"><div class="settings-menu-header"><div><h2>Settings</h2><p>Make this space yours.</p></div>'
           '<button class="settings-close" type="button" aria-label="Close settings"><svg viewBox="0 0 20 20" width="16" height="16" fill="none" aria-hidden="true"><path d="m6 6 8 8m0-8-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></button></div>'
           '<form id="language-form" class="language-toolbar" action="/api/language" method="post">'
           '<label for="website-language">Website language</label><select id="website-language" name="language">'
           +''.join(f'<option value="{code}" lang="{code}"'+(' selected' if code==current() else '')+' data-content>'+label+'</option>'
                    for code,label in (('en','English'),('zh-CN','简体中文')))+
           '</select><input type="hidden" name="csrf" value="'+html.escape(csrf or '',quote=True)+'">'
           '<input type="hidden" name="return_to" value="'+html.escape(return_to,quote=True)+'">'
           '<noscript><button type="submit">Apply</button></noscript><span id="language-feedback" role="status"></span></form>'
           '<form id="model-form" class="language-toolbar" action="/api/model" method="post">'
           '<label for="website-model">Model</label><select id="website-model" name="model">'
           +''.join(f'<option value="{code}"'+(' selected' if code==current_model() else '')+' data-content>'+html.escape(entry['label'])+'</option>'
                    for code,entry in MODELS.items())+
           '</select><input type="hidden" name="csrf" value="'+html.escape(csrf or '',quote=True)+'">'
           '<input type="hidden" name="return_to" value="'+html.escape(return_to,quote=True)+'">'
           '<noscript><button type="submit">Apply</button></noscript><span id="model-feedback" role="status"></span></form>'
           '</div></details>')
    account_menu=('<details class="menu" id="account-menu"><summary><span class="menu-label">Account</span></summary>'
                  '<div class="menu-panel">'+account+'</div></details>') if account else ''
    controls=('<div class="toolbar-row">'+prefs+account_menu+'<span id="update-slot"></span></div>')
    source=re.sub(r'<html\b[^>]*\blang="[^"]*"',lambda match:re.sub(r'lang="[^"]*"','lang="'+current()+'"',match[0]),source,count=1)
    if 'id="language-form"' not in source:
        source=re.sub(r'(<body\b[^>]*>)',lambda match:match[0]+controls,source,count=1)
    elif account and 'id="account-menu"' not in source:
        source=source.replace('<span id="update-slot">',account_menu+'<span id="update-slot">',1)
    marker='<div id="language-config" hidden data-config="'+config+'"></div>'
    if 'id="language-config"' in source:
        source=re.sub(r'<div id="language-config"[^>]*></div>',lambda _:marker,source,count=1)
        source=re.sub(r'(<input type="hidden" name="csrf" value=")[^"]*(")',lambda match:match[1]+html.escape(csrf or '',quote=True)+match[2],source)
        source=re.sub(r'(<input type="hidden" name="return_to" value=")[^"]*(")',lambda match:match[1]+html.escape(return_to,quote=True)+match[2],source)
    else:
        source=source.replace('</head>','<script src="/language.js" defer></script><script src="/model.js" defer></script></head>')
        source=source.replace('</body>',marker+'</body>')
    source=color_schemes.page(source,csrf,return_to)
    parser=InterfaceHTML();parser.feed(source);parser.close()
    return ''.join(parser.parts)
