"""Decorative icons and publisher previews for typed native components."""
import html
import re


ICONS = {
    "thermometer": '<path d="M14 14.8V5a3 3 0 0 0-6 0v9.8a5 5 0 1 0 6 0Z"/><path d="M11 7v10"/><circle cx="11" cy="18" r="1.7"/>',
    "snow": '<path d="M12 2v20M3.3 7l17.4 10M3.3 17 20.7 7M9 4l3 3 3-3M9 20l3-3 3 3M4 10l4-1-1-4M20 14l-4 1 1 4M4 14l4 1-1 4M20 10l-4-1 1-4"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.4 1.4M17.6 17.6 19 19M5 19l1.4-1.4M17.6 6.4 19 5"/>',
    "rain": '<path d="M6 16a4 4 0 1 1 1-7.9A6 6 0 0 1 19 10a3 3 0 0 1 0 6H6ZM8 19l-1 3m6-3-1 3m6-3-1 3"/>',
    "cloud": '<path d="M6 18a4 4 0 1 1 1-7.9A6 6 0 0 1 19 12a3 3 0 0 1 0 6H6Z"/>',
    "leaf": '<path d="M20 3C9 2 3 7 4 14c1 7 12 7 15-1 1-3 1-6 1-10Z"/><path d="M3 22 15 10"/>',
    "warning": '<path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5m0 3v1"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 10h18M7 14h3m4 0h3M7 17h3"/>',
    "pin": '<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "list": '<path d="M9 6h12M9 12h12M9 18h12M3 6h1m-1 6h1m-1 6h1"/>',
    "bell": '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM9 21h6"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18M5 7h14M5 17h14"/>',
    "chip": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4"/>',
    "news": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 8h4v4H7ZM14 8h3m-3 4h3M7 16h10"/>',
}


def icon(name):
    return '<svg class="data-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + ICONS.get(name, ICONS["list"]) + '</svg>'


def celestial(kind):
    """Decorative edition artwork, not a moon-phase or weather claim."""
    if kind == 'gm':
        drawing = ('<defs><linearGradient id="sun-light" x1="0" y1="0" x2="0" y2="1">'
                   '<stop stop-color="#fff0bf"/><stop offset=".55" stop-color="#f0cb83"/>'
                   '<stop offset="1" stop-color="#dfa45f"/></linearGradient></defs>'
                   '<circle cx="100" cy="68" r="32" fill="url(#sun-light)"/>'
                   '<g stroke="#c79a52" stroke-width="1.3" stroke-linecap="round" opacity=".8">'
                   '<path d="M100 15v9m0 88v9M47 68h9m88 0h9M73.5 22.1l4.5 7.8m44 76.2 4.5 7.8'
                   'M54.1 41.5l7.8 4.5m76.2 44 7.8 4.5M54.1 94.5l7.8-4.5m76.2-44 7.8-4.5'
                   'M73.5 113.9l4.5-7.8m44-76.2 4.5-7.8"/></g>')
    else:
        drawing = '<defs><linearGradient id="moon-light" x2="0" y2="1"><stop stop-color="#f4f0df"/><stop offset="1" stop-color="#bccbdc"/></linearGradient></defs><path d="M111 26a44 44 0 1 0 43 60 37 37 0 0 1-43-60Z" fill="url(#moon-light)"/><g stroke="#d8bd8b" stroke-width="1.3" stroke-linecap="round"><path d="M148 25v10m-5-5h10M57 35v6m-3-3h6"/></g><circle cx="154" cy="57" r="1.5" fill="#d8bd8b"/>'
    return '<svg class="celestial-art" viewBox="0 0 200 145" aria-hidden="true" focusable="false"><path d="M26 112a80 80 0 0 1 148 0" fill="none" stroke="currentColor" stroke-width=".8" opacity=".3"/>' + drawing + '</svg>'


def country_flag(code):
    from goodmorning.web import language as ui
    names = {'CN': 'China', 'GB': 'United Kingdom', 'US': 'United States', 'CA': 'Canada', 'AU': 'Australia'}
    code = 'GB' if code == 'UK' else code
    jack = '<rect width="30" height="20" fill="#21437a"/><path d="m0 0 30 20M30 0 0 20" stroke="white" stroke-width="5"/><path d="m0 0 30 20M30 0 0 20" stroke="#ca3047" stroke-width="2"/><path d="M15 0v20M0 10h30" stroke="white" stroke-width="7"/><path d="M15 0v20M0 10h30" stroke="#ca3047" stroke-width="4"/>'
    star = '<path d="m0-1 .224.691h.727l-.588.427.225.691L0 .382l-.588.427.225-.691-.588-.427h.727Z"/>'
    if code == 'CN':
        drawing = '<rect width="30" height="20" fill="#de3544"/><g fill="#ffe28b"><g transform="translate(5 5) scale(3)">' + star + '</g>'
        for x, y, rotation in ((10, 2, -32), (12, 4, -68), (12, 7, -104), (10, 9, -142)):
            drawing += f'<g transform="translate({x} {y}) rotate({rotation})">{star}</g>'
        drawing += '</g>'
    elif code == 'GB':
        drawing = jack
    elif code == 'US':
        drawing = '<rect width="30" height="20" fill="white"/>' + ''.join(f'<rect y="{row * 20 / 13:.3f}" width="30" height="{20 / 13:.3f}" fill="#c84450"/>' for row in range(0, 13, 2)) + '<rect width="12" height="10.77" fill="#294a7c"/>'
        drawing += ''.join(f'<circle cx="{1 + column * 2 + (row % 2):.2f}" cy="{.9 + row * 1.15:.2f}" r=".3" fill="white"/>' for row in range(9) for column in range(6 if row % 2 == 0 else 5))
    elif code == 'CA':
        drawing = '<rect width="30" height="20" fill="white"/><path d="M0 0h7v20H0ZM23 0h7v20h-7Z" fill="#d73b4d"/><path d="m15 3 1.3 4 2-1-.7 4 3-1-1 2 2 1-5.7 3 .4 2H15v2h-1v-2h-1.3l.4-2L7.5 12l2-1-1-2 3 1-.7-4 2 1Z" fill="#d73b4d"/>'
    elif code == 'AU':
        drawing = '<rect width="30" height="20" fill="#21437a"/><g transform="scale(.5)">' + jack + '</g><g fill="white">'
        for x, y, size in ((7, 15, 2), (23, 4, 1.6), (26, 10, 1.6), (22, 16, 1.6), (18, 9, 1.6), (24, 12, .8)):
            drawing += f'<g transform="translate({x} {y}) scale({size})">{star}</g>'
        drawing += '</g>'
    else:
        return f'<span class="country-code">{html.escape(code)}</span>'
    return f'<svg class="country-flag" viewBox="0 0 30 20" role="img" data-ui-aria-label="{names[code]}" aria-label="{ui.text(names[code])}" focusable="false">{drawing}</svg>'


def category_icon(category):
    country = re.search(r'\bNational\s*(?:[—–:-]\s*)?([A-Z]{2})\s*$', category)
    return country_flag(country[1]) if country else icon('chip' if category.casefold() == 'ai' else 'globe')


def news_visual(url, source_label, images):
    """A publisher preview, or nothing: imageless stories render as text-only cards."""
    from goodmorning.web import language as ui
    cached = images.get(url)
    if not cached:
        return ''
    responsive = ''
    if cached.get('small_src'):
        desktop_width = max(108, round(120 * cached['width'] / cached['height']))
        mobile_floor = round(136 * cached['width'] / cached['height'])
        responsive = f' srcset="{html.escape(cached["small_src"], quote=True)} {cached["small_width"]}w, /{html.escape(cached["src"].lstrip("/"), quote=True)} {cached["width"]}w" sizes="(max-width: 700px) max(calc(100vw - 196px), {mobile_floor}px), {desktop_width}px"'
    alt=cached.get('alt') or ui.text('Publisher article preview')
    caption=ui.ui('Publisher preview · {publisher}',publisher=html.unescape(source_label))
    return f'<figure class="news-visual"><img src="{html.escape(cached["src"], quote=True)}"{responsive} alt="{html.escape(alt, quote=True)}" width="{cached.get("width", 640)}" height="{cached.get("height", 480)}" loading="lazy" decoding="async"><figcaption>{caption}</figcaption></figure>'
