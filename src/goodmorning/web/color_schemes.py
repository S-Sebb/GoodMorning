"""Account-wide palettes, independent of edition and authored content."""
from contextvars import ContextVar
import html
import json
import re

from goodmorning.runtime_files import atomic_text

OPTIONS = {'day': {'classic': 'Classic', 'warm': 'Warm'}, 'night': {'classic': 'Classic', 'starry': 'Starry'}}
DEFAULT = {'day': 'classic', 'night': 'starry'}
CURRENT = ContextVar('website_color_schemes', default=DEFAULT)


def validate(value):
    if not isinstance(value, dict) or set(value) != set(OPTIONS):
        raise ValueError('Choose one of the offered color schemes')
    if any(not isinstance(value[theme], str) or value[theme] not in choices for theme, choices in OPTIONS.items()):
        raise ValueError('Choose one of the offered color schemes')
    return {theme: value[theme] for theme in OPTIONS}


def current():
    return dict(CURRENT.get())


def read(runtime):
    path = runtime / 'website-color-schemes.json'
    if path.is_symlink():
        raise ValueError('Unsafe website color scheme file')
    return validate(json.loads(path.read_text())) if path.is_file() else dict(DEFAULT)


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
    for theme, choices in OPTIONS.items():
        controls += f'<div class="color-scheme-field"><label for="{theme}-color-scheme">{theme.title()} color scheme</label><select id="{theme}-color-scheme" name="{theme}">'
        controls += ''.join(f'<option value="{code}" data-ui-text="{label}"'+(' selected' if code == selected[theme] else '')+'>'+ui.text(label)+'</option>'
                            for code, label in choices.items()) + '</select></div>'
    return (controls + '<input type="hidden" name="csrf" value="'+html.escape(csrf or '', quote=True)+'">'
            '<input type="hidden" name="return_to" value="'+html.escape(return_to, quote=True)+'">'
            '<noscript><button type="submit">Apply</button></noscript><span id="color-scheme-feedback" role="status"></span></form>')


def page(source, csrf, return_to):
    selected = current()
    def attributes(match):
        tag = re.sub(r'\sdata-(?:day|night)-scheme="[^"]*"', '', match[0])
        return tag[:-1]+f' data-day-scheme="{selected["day"]}" data-night-scheme="{selected["night"]}">'
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
        source = source.replace('</head>', '<link rel="stylesheet" href="/color-schemes.css"><script src="/color-schemes.js" defer></script></head>')
    return source
