"""Conservative lint for routine secretary boilerplate, not a warning stripper.

Materiality is an agent decision: preserve information that affects plans, safety,
requested coverage or a needed action. This catches known non-critical narration.
"""

import argparse
import json
from pathlib import Path
import re

PATTERNS = {
    "healthy_weather_narration": r"\bweather retrieval returned no warnings\b",
    "routine_aqi_caveat": r"\b(?:this is (?:model )?data,? not a local station measurement|model data, not (?:a )?(?:local )?station (?:measurement|observation))\b",
    "retry_bookkeeping": r"\bI have not started a retry loop\b|\bno automatic retr(?:y|ies) (?:was|were|has been|have been) (?:started|performed)\b",
    "unsolicited_news_backlog": r"\b(?:UK|China|national|news) reports? for [^\n.!?]{1,100} (?:are|is) also available if you want (?:them|it) later\b",
    "background_coverage_gap": r"\bolder coverage gaps remain unresolved\b",
    "generic_verification_caveat": r"\b(?:these are publisher[- ]feed headlines, not independently verified claims|a ranking score is a proxy, not verified truth or objective importance)\b",
    "routine_empty_status": r"\bthere are no pending (?:ideas or calendar reviews|calendar reviews or ideas)\b",
}


def boilerplate_categories(text):
    normalized = re.sub(r"\s+", " ", re.sub(r"[*_`]", "", text))
    return [name for name, pattern in PATTERNS.items() if re.search(pattern, normalized, re.I)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="Exact drafted reply; never read profiles or provider caches")
    parser.add_argument("--diagnostic", action="store_true", help="Only when the user explicitly requested technical diagnostics")
    args = parser.parse_args(argv)
    text = Path(args.file).read_text(encoding="utf-8")
    issues = [] if args.diagnostic else boilerplate_categories(text)
    print(json.dumps({"ok": not issues, "categories": issues}))
    return 0 if not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())
