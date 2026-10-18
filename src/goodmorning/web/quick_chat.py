"""Floating quick chat for desk pages other than the Secretary page."""
import hashlib
import html
import json

from .chat_uploads import MAX_UPLOAD_BYTES

SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'


def widget(source, csrf):
    """Add the launcher and window once; the script reveals them only for a set-up secretary."""
    if 'id="quick-chat"' in source:
        return source
    config = html.escape(json.dumps({'workspaceScope': hashlib.sha256(('chat-workspace:' + csrf).encode()).hexdigest(), 'maxUploadBytes': MAX_UPLOAD_BYTES}), quote=True)
    markup = ('<aside id="quick-chat" hidden aria-label="Quick chat" data-config="' + config + '">'
              '<button id="quick-chat-launcher" type="button" aria-expanded="false" aria-controls="quick-chat-window">'
              '<span class="quick-chat-portrait" aria-hidden="true"><img alt=""></span>'
              '<span id="quick-chat-launcher-label" data-content>Ask your secretary</span>'
              '<span id="quick-chat-dot" hidden></span></button>'
              '<section id="quick-chat-window" role="dialog" aria-labelledby="quick-chat-title" tabindex="-1" hidden>'
              '<header class="quick-chat-header"><span class="quick-chat-portrait" aria-hidden="true"><img alt=""></span>'
              '<div class="quick-chat-heading"><h2 id="quick-chat-title" data-content>New conversation</h2><p id="quick-chat-mode" data-content>Secretary</p></div>'
              '<button id="quick-chat-new" class="quick-chat-tool" type="button" aria-label="New conversation" title="New conversation">' + SVG + '<path d="M12 5v14M5 12h14"/></svg></button>'
              '<a id="quick-chat-open" class="quick-chat-tool" href="/chat" aria-label="Open in Secretary" title="Open in Secretary">' + SVG + '<path d="M14 4h6v6M20 4l-9 9M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/></svg></a>'
              '<button id="quick-chat-minimize" class="quick-chat-tool" type="button" aria-label="Minimize quick chat" title="Minimize quick chat">' + SVG + '<path d="M6 12h12"/></svg></button></header>'
              '<p id="quick-chat-resume" role="status" hidden><span>A fresh space after 15 minutes away.</span> <a id="quick-chat-resume-link" href="/chat">Resume previous conversation</a></p>'
              '<div id="quick-chat-scroll" role="region" aria-label="Conversation" tabindex="0">'
              '<div id="quick-chat-empty"><p class="quick-chat-welcome">A little space to plan.</p><p>Ask something quick without leaving this page.</p></div>'
              '<div id="quick-chat-messages" role="log" aria-label="Conversation messages" aria-live="polite" aria-relevant="additions text"></div>'
              '<div id="quick-chat-questions"></div><p id="quick-chat-status" role="status" hidden></p></div>'
              '<div id="quick-chat-attachments" aria-live="polite" hidden></div>'
              '<form id="quick-chat-compose"><button id="quick-chat-attach" class="quick-chat-tool" type="button" aria-label="Attach files" title="Attach files">'
              + SVG + '<path d="m8 12 6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l9-9"/></svg></button>'
              '<input id="quick-chat-files" type="file" multiple hidden><textarea id="quick-chat-text" rows="1" maxlength="8000" placeholder="Your message…" aria-label="Your message" enterkeyhint="send"></textarea>'
              '<button id="quick-chat-send" type="submit" aria-label="Send message" title="Send message" disabled>' + SVG + '<path d="m4 5 16 7-16 7 3-7-3-7Zm3 7h13"/></svg></button></form>'
              '<p id="quick-chat-error" role="alert"></p></section></aside>')
    scripts = ''.join(f'<script src="/{name}" defer></script>' for name in ('questions.js', 'marked.js', 'markdown.js')
                      if f'/{name}"' not in source)
    source = source.replace('</head>', '<link rel="stylesheet" href="/quick-chat.css"></head>', 1)
    return source.replace('</body>', markup + scripts + '<script src="/quick-chat.js" defer></script></body>', 1)
