"""Bounded project operations, run locally or over the authenticated relay.

Internal JSON contract. Do not invoke this helper as a replacement for the
agent-facing CLI's registry and authorization checks.
"""

import base64
import fcntl
import hashlib
import heapq
import json
import os
import re
from pathlib import Path, PurePosixPath
import stat
import sys
import time
import uuid

MAX_BYTES = 512 * 1024
MAX_CHARS = 16_000
SECRET_ASSIGNMENT = re.compile(r'''(\b[a-z0-9_-]{0,128}(?:password|secret|token|api[_-]?key|authorization)["']?\s*[:=]\s*)("(?:\\.|[^"\\])*"?|'(?:\\.|[^'\\])*'?|(?:Bearer\s+)?[^\s,"'}]+)''', re.I)


def redact(text):
    # Equal-length masks preserve source character cursors across pages. Mask
    # the complete document before slicing so a page cannot begin inside a key.
    protected = SECRET_ASSIGNMENT.sub(lambda m: m[1] + "*" * len(m[2]), text)
    return protected, protected != text


class Failure(Exception):
    pass


def relative_parts(value):
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise Failure("invalid_path")
    p = PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts:
        raise Failure("invalid_path")
    for part in p.parts:
        name = part.lower()
        if name.startswith(".gm-write-"):
            raise Failure("reserved_path")
        if name.startswith(".env") or name.endswith((".pem", ".key")) or name in {".ssh", ".git", ".aws", ".azure", ".config", ".npmrc", ".netrc", "credentials.json", "secrets.json", "id_rsa", "id_ed25519", "relay-identity.json"}:
            raise Failure("secret_path")
    return p.parts


def open_directory(root, parts):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_file(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    stream = os.fdopen(fd, "rb")
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        stream.close()
        raise Failure("not_regular_file")
    return stream


def file_hash(parent, name):
    try:
        with read_file(parent, name) as f:
            data = f.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise Failure("file_too_large")
            return hashlib.sha256(data).hexdigest(), os.fstat(f.fileno()).st_mode
    except FileNotFoundError:
        return "missing", 0o600


def files(p):
    root = Path(p["root"])
    if not root.is_absolute():
        raise Failure("invalid_root")
    # Registered workspace roots may themselves be symlinks. Paths below the
    # canonical root may not: directory descriptors prevent symlink races.
    root = root.resolve(strict=True)
    parts = relative_parts(p.get("path", "."))
    op = p["op"]
    if op == "status":
        fd = open_directory(root, ())
        os.close(fd)
        return {"ready": True}
    offset = p.get("offset", 0)
    limit = p.get("limit", 4000 if op == "read" else 10)
    if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or limit < 1:
        raise Failure("invalid_bounds")
    if limit > (MAX_CHARS if op == "read" else 50):
        raise Failure("invalid_bounds")
    if op == "list":
        if offset > 10_000:
            raise Failure("invalid_bounds")
        fd = open_directory(root, parts)
        try:
            total = 0
            def visible(scan):
                nonlocal total
                for e in scan:
                    if e.name.lower().startswith((".env", ".gm-write-")) or e.name.lower() in {".git", ".ssh"}:
                        continue
                    total += 1
                    if total > 100_000:
                        raise Failure("directory_too_large")
                    yield e.name, "link" if e.is_symlink() else "dir" if e.is_dir(follow_symlinks=False) else "file"
            with os.scandir(fd) as scan:
                entries = heapq.nsmallest(offset + limit + 1, visible(scan))
            page = entries[offset:offset + limit]
            return {"entries": [{"name": n, "type": t} for n, t in page], "total": total, "next_offset": offset + len(page) if offset + len(page) < total else None}
        finally:
            os.close(fd)
    if not parts:
        raise Failure("invalid_path")
    parent = open_directory(root, parts[:-1])
    name = parts[-1]
    try:
        if op == "read":
            with read_file(parent, name) as f:
                before = os.fstat(f.fileno())
                if p.get("tail"):
                    f.seek(max(0, before.st_size - limit * 4))
                    data = f.read(limit * 4 + 1)
                    # The byte window may begin within one UTF-8 character.
                    while data and data[0] & 0xC0 == 0x80:
                        data = data[1:]
                    protected, masked = redact(data.decode("utf-8"))
                    text = protected[-limit:]
                    return {"bytes": before.st_size, "sha256": None, "text": text, "tail": True, "truncated": before.st_size > len(data) or len(protected) > limit, **({"redacted": True} if masked else {})}
                data = f.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise Failure("file_too_large")
                after = os.fstat(f.fileno())
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise Failure("changed_during_read")
            text, masked = redact(data.decode("utf-8"))
            excerpt = text[offset:offset + limit]
            return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "text": excerpt, "offset": offset, "next_offset": offset + len(excerpt) if offset + len(excerpt) < len(text) else None, "truncated": offset > 0 or offset + len(excerpt) < len(text), **({"redacted": True} if masked else {})}
        if op != "write":
            raise Failure("invalid_operation")
        if "/".join(parts) not in p.get("write_targets", []):
            raise Failure("write_not_allowed")
        content = p["content"].encode("utf-8")
        if len(content) > MAX_BYTES:
            raise Failure("file_too_large")
        expected = p.get("expect")
        if expected != "missing" and (not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected)):
            raise Failure("expected_hash_required")
        # Stable sidecar locks serialize cooperating adapters across shared
        # storage. Never unlink a lock: doing so splits concurrent lock owners.
        lock_name = f".gm-write-{hashlib.sha256(os.fsencode(name)).hexdigest()}.lock"
        lock_fd = os.open(lock_name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        temp = None
        try:
            deadline = time.monotonic() + 2
            while True:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise Failure("write_busy")
                    time.sleep(0.02)
            current, mode = file_hash(parent, name)
            if current != expected:
                raise Failure("write_conflict")
            temp = f".gm-write-{uuid.uuid4().hex}.tmp"
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, stat.S_IMODE(mode), dir_fd=parent)
            with os.fdopen(fd, "wb") as f:
                os.fchmod(f.fileno(), stat.S_IMODE(mode))
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            # Detect non-cooperating changes made during preparation too.
            if file_hash(parent, name)[0] != expected:
                raise Failure("write_conflict")
            os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
            temp = None
            try:
                os.fsync(parent)
            except OSError:
                raise Failure("outcome_unknown")
            return {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        finally:
            if temp:
                os.unlink(temp, dir_fd=parent)
            os.close(lock_fd)
    finally:
        os.close(parent)


def jobs(p):
    root = Path(p["root"]).resolve(strict=True)
    result = []
    # Read only this user's process metadata. Never expose command arguments,
    # environment variables, another user's processes, or raw GPU output.
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid() or int(entry.name) == os.getpid():
                continue
            cwd = (entry / "cwd").resolve(strict=True)
            if not cwd.is_relative_to(root):
                continue
            name = (entry / "comm").read_text().strip()
            result.append({"pid": int(entry.name), "command": name})
        except (OSError, ValueError):
            continue
    result.sort(key=lambda row: row["pid"])
    limit = p.get("limit", 10)
    if not isinstance(limit, int) or not 1 <= limit <= 50:
        raise Failure("invalid_bounds")
    return {"processes": result[:limit], "process_total": len(result), "truncated": len(result) > limit}


def main():
    try:
        raw = base64.b64decode(sys.argv[1], validate=True) if len(sys.argv) > 1 else sys.stdin.buffer.read(MAX_BYTES * 3)
        p = json.loads(raw)
        result = jobs(p) if p["op"] == "jobs" else files(p)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, separators=(",", ":")))
    except Failure as e:
        print(json.dumps({"ok": False, "error": str(e)}, separators=(",", ":")))
        sys.exit(1)
    except FileNotFoundError:
        print('{"ok":false,"error":"not_found"}')
        sys.exit(1)
    except PermissionError:
        print('{"ok":false,"error":"permission_denied"}')
        sys.exit(1)
    except (UnicodeError, ValueError, KeyError, TypeError):
        print('{"ok":false,"error":"invalid_data"}')
        sys.exit(1)
    except OSError:
        print('{"ok":false,"error":"filesystem_error"}')
        sys.exit(1)


if __name__ == "__main__":
    main()
