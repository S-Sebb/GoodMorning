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


# Meeting-invitation boilerplate never belongs in briefing preparation.
# Preparation is concise attendee requirements (slides, questions, materials).
# Join instructions, help links, organiser controls and privacy footers stay
# in the original invitation; the schedule only references that invitation.
_BOILERPLATE_URL_PARTS = (
    "aka.ms/jointeamsmeeting",
    "teams.microsoft.com/meetingoptions",
    "teams.microsoft.com/l/meetup-join",
    "teams.microsoft.com/meet/",
)

_BOILERPLATE_URL_RE = re.compile(r"https?://[^\s<>\]]+")


def _is_boilerplate_url(url: str) -> bool:
    lowered = url.casefold()
    return any(part in lowered for part in _BOILERPLATE_URL_PARTS)


def clean_preparation(text: str | None) -> str:
    """Return concise preparation requirements without meeting boilerplate.

    Removes Teams join/help/organiser/privacy footers, redacted credential
    placeholders, meeting IDs and separator runs. Keeps legitimate
    preparation text and unrelated public links. Idempotent.
    """
    if not text or not isinstance(text, str):
        return ""
    cleaned = safe_text(text)
    # Remove full boilerplate constructs that pair a label with a URL.
    cleaned = re.sub(r"(?i)need help\?\s*https?://[^\s<>\]]+", " ", cleaned)
    cleaned = re.sub(r"(?i)for organisers?:\s*meeting options\s*<?https?://[^\s<>\]]+>?",
                     " ", cleaned)
    cleaned = re.sub(r"(?i)meeting options\s*<?https?://teams\.microsoft\.com/meetingoptions[^\s<>\]]*>?",
                     " ", cleaned)
    cleaned = re.sub(r"(?i)privacy and security\s*<?https?://[^\s<>\]]+>?", " ", cleaned)
    cleaned = re.sub(r"(?i)\[company logo\]\s*", " ", cleaned)
    cleaned = re.sub(r"(?i)system reference:\s*<?\[.*?omitted.*?\]>?", " ", cleaned)
    # Strip bare boilerplate URLs, keeping unrelated public links.
    cleaned = _BOILERPLATE_URL_RE.sub(
        lambda match: " " if _is_boilerplate_url(match[0]) else match[0], cleaned)
    # Remove redacted credential placeholders and their dangling labels.
    cleaned = re.sub(r"\[protected link omitted; use original invitation\]", " ", cleaned)
    cleaned = re.sub(r"\[omitted; use original invitation\]", " ", cleaned)
    cleaned = re.sub(r"(?i)microsoft teams meeting\s*join:\s*", " ", cleaned)
    cleaned = re.sub(r"(?i)\bmeeting\s*id\s*:?\s*[\d\s\-]*", " ", cleaned)
    cleaned = re.sub(r"(?i)\b(passcode|password|pin)\s*:\s*", " ", cleaned)
    # Drop stray angle brackets left by <url> wrapping.
    cleaned = re.sub(r"[<>]+", " ", cleaned)
    # Split into lines and keep only lines with real preparation content.
    kept: list[str] = []
    for raw_line in cleaned.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip(" _-| \t")
        if not line:
            continue
        lowered = line.casefold()
        if not re.search(r"[a-z0-9]", lowered):
            continue
        if "meeting options" in lowered:
            continue
        if "for organis" in lowered:
            continue
        if "system reference" in lowered:
            continue
        if "company logo" in lowered:
            continue
        if "privacy and security" in lowered:
            continue
        if lowered in ("need help?", "need help"):
            continue
        if "microsoft teams" in lowered and (
                "join" in lowered or "http" in lowered or "omitted" in lowered
                or "meeting id" in lowered):
            continue
        # A line that is only punctuation/labels after stripping is not preparation.
        if re.fullmatch(r"[\W_]+", line):
            continue
        kept.append(line.strip(" -|"))
    result = "\n".join(kept)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    result = re.sub(r"[ \t]{2,}", " ", result)
    if result and not re.search(r"[A-Za-z0-9]", result):
        return ""
    return result
