"""Credential-redacted calendar text; source invitations remain authoritative."""

import re
from urllib.parse import parse_qsl, urlsplit

SECRET_KEYS = {"passcode", "password", "pwd", "token", "access_token", "auth",
               "authorization", "key", "api_key", "sig", "signature", "client_secret", "jwt", "mtid"}


def safe_text(text):
    text = re.sub(r"(?i)(\b(?:passcode|password|pin|token|authorization|access[_ -]?token|api[_ -]?key)\s*[:=][ \t]*)"
                  r"(\[omitted; use original invitation\]|\"[^\"]*\"|'[^']*'|[^\s<]+)",
                  r"\1[omitted; use original invitation]", text)
    def link(match):
        value = match[0]
        try:
            parsed = urlsplit(value)
            host = (parsed.hostname or "").casefold()
            joining = (host == "teams.microsoft.com" and parsed.path.startswith(("/meet/", "/l/meetup-join/"))) or (
                (host == "zoom.us" or host.endswith(".zoom.us")) and parsed.path.startswith(("/j/", "/s/"))) or (
                host == "meet.google.com" and re.fullmatch(r"/[a-z]{3}-[a-z]{4}-[a-z]{3}", parsed.path))
            sensitive = parsed.username or parsed.password or (
                {key.casefold() for key, _ in parse_qsl(parsed.query)} & SECRET_KEYS) or joining
        except ValueError:
            sensitive = True
        return "[protected link omitted; use original invitation]" if sensitive else value
    return re.sub(r"https?://[^\s<>]+", link, text)


def safe_value(value):
    if isinstance(value, str):
        return safe_text(value)
    if isinstance(value, dict):
        return {key: safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_value(item) for item in value]
    return value
