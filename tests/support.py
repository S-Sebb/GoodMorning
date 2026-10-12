"""Portable fixture location; never a personal secretary runtime."""

import os
import json
from pathlib import Path
import tempfile

TEMP_ROOT = os.environ.get("GM_TEST_TMPDIR") or (
    "/tmp/opencode" if Path("/tmp/opencode").is_dir() else tempfile.gettempdir())
Path(TEMP_ROOT).mkdir(parents=True, exist_ok=True)


def returning_viewer(runtime):
    """Unrelated browser suites use an account that already dismissed this release."""
    from goodmorning.web.release import patch_note
    (Path(runtime) / 'release-seen.json').write_text(json.dumps({'version': patch_note()['version']}))
