"""Small user-local file helpers: explicit profiles, atomic writes, bounded locks."""

import contextlib
import os
from pathlib import Path
import re
import tempfile


def profile_fields(directory):
    path = Path(directory) / "profile.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    return {m[1].lower(): m[2].strip().strip("\"' ")
            for m in re.finditer(r"^([a-z_]+)[ \t]*:[ \t]*([^\r\n]*)$", text, re.M | re.I)}


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
