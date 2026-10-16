"""Small user-local file helpers: explicit profiles, atomic writes, bounded locks."""

import contextlib
import json
import os
from pathlib import Path
import re
import tempfile


def secretary_path(explicit=None):
    return Path(explicit or os.environ.get("SECRETARY_DIR") or
                "~/.local/share/GoodMorning/secretary").expanduser().resolve()


def cache_path(explicit=None):
    return Path(explicit or os.environ.get("GM_CACHE_DIR") or
                "~/.cache/goodmorning").expanduser().resolve()


def calendar_config(directory):
    try:
        value = json.loads((Path(directory) / "calendar.config.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict):
        raise ValueError("calendar configuration must be an object")
    return value


def calendar_path(directory, explicit=None, config=None):
    config = calendar_config(directory) if config is None else config
    selected = explicit or os.environ.get("CALENDAR_DB_PATH") or config.get("calendar_db") or Path(directory) / "calendar.sqlite"
    return Path(selected).expanduser().resolve()


def profile_fields(directory):
    path = Path(directory) / "profile.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    return {m[1].lower(): m[2].strip().strip("\"' ")
            for m in re.finditer(r"^([a-z_]+)[ \t]*:[ \t]*([^\r\n]*)$", text, re.M | re.I)}


SECRETARY_NAME_MAX = 30


def normalize_secretary_name(value, field="secretary_name"):
    """Optional short display name: the AI secretary's, or how it calls the user.

    Returns "" for missing/empty, otherwise the stripped name.
    Raises ValueError for unsafe or overlong names.
    """
    if value is None:
        return ""
    text = str(value).strip().strip("\"' ")
    if not text:
        return ""
    if len(text) > SECRETARY_NAME_MAX or len(text) < 1:
        raise ValueError(f"invalid {field}: use 1-30 characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError(f"invalid {field}: no control characters or newlines")
    if not any(ch.isalnum() for ch in text):
        raise ValueError(f"invalid {field}: include at least one letter or number")
    return text


def normalize_user_name(value):
    return normalize_secretary_name(value, "user_name")


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".gm-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def runtime_lock(directory, name):
    """Serialize cooperating commands without deleting a stable lock file (Linux)."""
    import fcntl

    with open(Path(directory) / name, "a", encoding="utf-8") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("runtime_busy: another command is active; retry later") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
