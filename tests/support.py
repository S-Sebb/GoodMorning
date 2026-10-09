"""Portable fixture location; never a personal secretary runtime."""

import os
from pathlib import Path
import tempfile

TEMP_ROOT = os.environ.get("GM_TEST_TMPDIR") or (
    "/tmp/opencode" if Path("/tmp/opencode").is_dir() else tempfile.gettempdir())
Path(TEMP_ROOT).mkdir(parents=True, exist_ok=True)
