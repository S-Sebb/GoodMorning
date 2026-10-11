"""English/Chinese interface text. User-authored content is never translated here."""
from contextvars import ContextVar
from datetime import date as Date
import html
from html.parser import HTMLParser
import json
import re

from goodmorning.paths import WEB_ASSETS

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
    if 'id="site-release"' not in source:
        source=source.replace('</head>','<link rel="stylesheet" href="/update.css"><script src="/update.js" defer></script></head>')
        notice=('<div id="site-release" hidden data-version="'+VERSION+'"></div>'
                '<aside id="site-update" class="site-update" hidden aria-label="Website update">'
                '<p role="status" aria-live="polite">A website update is available.</p>'
                '<button id="update-refresh" type="button">Refresh</button>'
                '<button id="update-later" type="button">Later</button>'
                '<p id="update-feedback" role="status"></p></aside>')
        source=source.replace('</body>',notice+'</body>')
    config=html.escape(json.dumps({'language':current(),'csrf':csrf}),quote=True)
    controls=('<form id="language-form" class="language-toolbar" action="/api/language" method="post">'
              '<label for="website-language">Website language</label><select id="website-language" name="language">'
              +''.join(f'<option value="{code}" lang="{code}"'+(' selected' if code==current() else '')+' data-content>'+label+'</option>'
                       for code,label in (('en','English'),('zh-CN','简体中文')))+
              '</select><input type="hidden" name="csrf" value="'+html.escape(csrf or '',quote=True)+'">'
              '<input type="hidden" name="return_to" value="'+html.escape(return_to,quote=True)+'">'
              '<noscript><button type="submit">Apply</button></noscript><span id="language-feedback" role="status"></span></form>')
    source=re.sub(r'<html\b[^>]*\blang="[^"]*"',lambda match:re.sub(r'lang="[^"]*"','lang="'+current()+'"',match[0]),source,count=1)
    if 'id="language-form"' not in source:
        source=re.sub(r'(<body\b[^>]*>)',lambda match:match[0]+controls,source,count=1)
    marker='<div id="language-config" hidden data-config="'+config+'"></div>'
    if 'id="language-config"' in source:
        source=re.sub(r'<div id="language-config"[^>]*></div>',lambda _:marker,source,count=1)
        source=re.sub(r'(<input type="hidden" name="csrf" value=")[^"]*(")',lambda match:match[1]+html.escape(csrf or '',quote=True)+match[2],source,count=1)
        source=re.sub(r'(<input type="hidden" name="return_to" value=")[^"]*(")',lambda match:match[1]+html.escape(return_to,quote=True)+match[2],source,count=1)
    else:
        source=source.replace('</head>','<script src="/language.js" defer></script></head>')
        source=source.replace('</body>',marker+'</body>')
    parser=InterfaceHTML();parser.feed(source);parser.close()
    return ''.join(parser.parts)
