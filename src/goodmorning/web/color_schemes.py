"""Website palettes, independent of edition and authored content. On the hosted site each device keeps
its own choice; a device that has not chosen yet uses the one its account saved before choices moved
to devices. A local install keeps one choice in its runtime."""
from contextvars import ContextVar
import html
import json
import re

from goodmorning.runtime_files import atomic_text

# Styles shape the components (frames, buttons, fonts); color schemes only set colors and scenery.
OPTIONS = {'style': {'soft': 'Soft', 'pixel': 'Pixel'},
           'day': {'classic': 'Classic', 'warm': 'Warm', 'morning-sky': 'Morning Sky',
                   'first-light': 'First Light', 'grass-block': 'Grass Block', 'picnic': 'Picnic'},
           'night': {'classic': 'Classic', 'starry': 'Starry', 'city-lights': 'City Lights',
                     'midnight-violet': 'Midnight Violet', 'grass-block': 'Grass Block', 'picnic': 'Picnic'}}
DEFAULT = {'style': 'soft', 'day': 'morning-sky', 'night': 'starry'}
LEGENDS = {'style': 'Style', 'day': 'Day color scheme', 'night': 'Night color scheme'}
CURRENT = ContextVar('website_color_schemes', default=DEFAULT)


def validate(value):
    """Style is optional so choices saved before styles existed keep their scenes and stay soft."""
    if isinstance(value, dict) and 'style' not in value:
        value = {**value, 'style': DEFAULT['style']}
    if not isinstance(value, dict) or set(value) != set(OPTIONS):
        raise ValueError('Choose one of the offered color schemes')
    if any(not isinstance(value[theme], str) or value[theme] not in choices for theme, choices in OPTIONS.items()):
        raise ValueError('Choose one of the offered color schemes')
    return {theme: value[theme] for theme in OPTIONS}



def current():
    return dict(CURRENT.get())


def saved(value):
    """Retired day palettes fall back without changing the saved night preference."""
    if isinstance(value, dict) and value.get('day') == 'sunlit-garden':
        value = {**value, 'day': DEFAULT['day']}
    return validate(value)


def cookie(value):
    """This device's choice, as the GoodMorningAppearance cookie holds it."""
    value = validate(value)
    return '.'.join(value[key] for key in OPTIONS)


def from_cookie(raw):
    parts = raw.split('.')
    if len(parts) != len(OPTIONS):
        raise ValueError('Invalid color scheme cookie')
    return saved(dict(zip(OPTIONS, parts)))


def read(runtime):
    path = runtime / 'website-color-schemes.json'
    if path.is_symlink():
        raise ValueError('Unsafe website color scheme file')
    return saved(json.loads(path.read_text())) if path.is_file() else dict(DEFAULT)


def write(runtime, value):
    value = validate(value)
    path = runtime / 'website-color-schemes.json'
    if path.is_symlink():
        raise ValueError('Unsafe website color scheme file')
    atomic_text(path, json.dumps(value) + '\n')
    return value


def form(csrf, return_to):
    from . import language as ui
    selected = current()
    controls = '<form id="color-scheme-form" class="language-toolbar" action="/api/color-schemes" method="post"><h3 class="color-scheme-heading">Appearance</h3>'
    # Picture cards are native radios, so they work with a keyboard and without JavaScript.
    for theme, choices in OPTIONS.items():
        picker = 'website-style' if theme == 'style' else theme + '-color-scheme'
        controls += f'<fieldset class="scheme-picker" id="{picker}"><legend>{LEGENDS[theme]}</legend>'
        controls += ''.join(f'<label class="scheme-card"><input type="radio" name="{theme}" value="{code}"'+(' checked' if code == selected[theme] else '')+'>'
                            f'<span class="scheme-swatch" data-swatch="{theme}-{code}" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>'
                            f'<span class="scheme-name" data-ui-text="{label}">'+ui.text(label)+'</span></label>'
                            for code, label in choices.items()) + '</fieldset>'
    return (controls + '<input type="hidden" name="csrf" value="'+html.escape(csrf or '', quote=True)+'">'
            '<input type="hidden" name="return_to" value="'+html.escape(return_to, quote=True)+'">'
            '<noscript><button type="submit">Apply</button></noscript><span id="color-scheme-feedback" role="status"></span></form>')


def mark(source):
    """This device's choice on the page's <html> element, where the stylesheets read it."""
    selected = current()
    def attributes(match):
        tag = re.sub(r'\sdata-(?:style|day-scheme|night-scheme)="[^"]*"', '', match[0])
        return tag[:-1]+f' data-style="{selected["style"]}" data-day-scheme="{selected["day"]}" data-night-scheme="{selected["night"]}">'
    return re.sub(r'<html\b[^>]*>', attributes, source, count=1)


def page(source, csrf, return_to):
    selected = current()
    source = mark(source)
    if 'id="color-scheme-form"' not in source:
        source = source.replace('</form></div></details>', '</form>'+form(csrf, return_to)+'</div></details>', 1)
    else:
        source = re.sub(r'<form id="color-scheme-form"[^>]*>.*?</form>', lambda _: form(csrf, return_to), source, count=1, flags=re.S)
    config = html.escape(json.dumps({'schemes': selected, 'csrf': csrf}), quote=True)
    marker = '<div id="color-scheme-config" hidden data-config="'+config+'"></div>'
    if 'id="color-scheme-config"' in source:
        source = re.sub(r'<div id="color-scheme-config"[^>]*></div>', lambda _: marker, source, count=1)
    else:
        source = source.replace('</body>', marker+'</body>')
    if '/color-schemes.css' not in source:
        source = source.replace('</head>', '<link rel="stylesheet" href="/color-schemes.css"><link rel="stylesheet" href="/pixel.css">'
                                '<script src="/color-schemes.js" defer></script></head>')
    return source
