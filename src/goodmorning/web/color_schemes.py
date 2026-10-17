"""Account-wide palettes, independent of edition and authored content."""
from contextvars import ContextVar
import html
import json
import re

from goodmorning.runtime_files import atomic_text

OPTIONS = {'day': {'classic': 'Classic', 'warm': 'Warm', 'morning-sky': 'Morning Sky',
                   'first-light': 'First Light', 'grass-block': 'Grass Block', 'cottage': 'Cottage'},
           'night': {'classic': 'Classic', 'starry': 'Starry', 'city-lights': 'City Lights',
                     'midnight-violet': 'Midnight Violet', 'grass-block': 'Grass Block', 'cottage': 'Cottage'}}
# These scenes always draw in pixel style, whatever the Pixel style switch says.
PIXEL_SCENES = {'grass-block', 'cottage'}
DEFAULT = {'day': 'morning-sky', 'night': 'starry', 'pixel': False}
CURRENT = ContextVar('website_color_schemes', default=DEFAULT)


def validate(value):
    """Pixel style is optional so older saved choices keep their scenes and stay smooth."""
    if not isinstance(value, dict) or set(value) - {'pixel'} != set(OPTIONS):
        raise ValueError('Choose one of the offered color schemes')
    if any(not isinstance(value[theme], str) or value[theme] not in choices for theme, choices in OPTIONS.items()):
        raise ValueError('Choose one of the offered color schemes')
    if not isinstance(value.get('pixel', False), bool):
        raise ValueError('Choose one of the offered color schemes')
    return {**{theme: value[theme] for theme in OPTIONS}, 'pixel': value.get('pixel', False)}


def pixel_on(selected, edition):
    """Whether a page in this edition draws in pixel style."""
    return selected['pixel'] or selected['night' if edition == 'gn' else 'day'] in PIXEL_SCENES


def current():
    return dict(CURRENT.get())


def saved(value):
    """Retired day palettes fall back without changing the saved night preference."""
    if isinstance(value, dict) and value.get('day') == 'sunlit-garden':
        value = {**value, 'day': DEFAULT['day']}
    return validate(value)


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
    controls = ('<form id="color-scheme-form" class="language-toolbar" action="/api/color-schemes" method="post"><h3 class="color-scheme-heading">Appearance</h3>'
                '<label class="pixel-style-switch"><span><span class="pixel-style-name">Pixel style</span>'
                '<small>Pixel frames and headings. Grass Block and Cottage are always pixel.</small></span>'
                '<input type="checkbox" id="pixel-style" name="pixel" value="on" role="switch"'+(' checked' if selected['pixel'] else '')+'></label>')
    # Picture cards are native radios, so they work with a keyboard and without JavaScript.
    for theme, choices in OPTIONS.items():
        controls += f'<fieldset class="scheme-picker" id="{theme}-color-scheme"><legend>{theme.title()} color scheme</legend>'
        controls += ''.join(f'<label class="scheme-card"><input type="radio" name="{theme}" value="{code}"'+(' checked' if code == selected[theme] else '')+'>'
                            f'<span class="scheme-swatch" data-swatch="{theme}-{code}" aria-hidden="true"><i></i><i></i><i></i></span>'
                            f'<span class="scheme-name" data-ui-text="{label}">'+ui.text(label)+'</span></label>'
                            for code, label in choices.items()) + '</fieldset>'
    return (controls + '<input type="hidden" name="csrf" value="'+html.escape(csrf or '', quote=True)+'">'
            '<input type="hidden" name="return_to" value="'+html.escape(return_to, quote=True)+'">'
            '<noscript><button type="submit">Apply</button></noscript><span id="color-scheme-feedback" role="status"></span></form>')


def page(source, csrf, return_to):
    selected = current()
    def attributes(match):
        tag = re.sub(r'\sdata-(?:day-scheme|night-scheme|pixel-style|pixel)="[^"]*"', '', match[0])
        edition = re.search(r'\sdata-edition="([^"]*)"', tag)
        pixel = ' data-pixel="on"' if pixel_on(selected, edition and edition[1]) else ''
        return (tag[:-1]+f' data-day-scheme="{selected["day"]}" data-night-scheme="{selected["night"]}"'
                f' data-pixel-style="{"on" if selected["pixel"] else "off"}"{pixel}>')
    source = re.sub(r'<html\b[^>]*>', attributes, source, count=1)
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
