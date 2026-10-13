# README demo screenshots

These PNGs show the current GoodMorning interface with fictional records pinned
to 13 October 2026. Weather values, news stories, example.com citations, plans,
and conversation text are demonstration content, not live reports or personal data.
The conversation responses are simulated; the viewer, assets, themes, and record
rendering are real. Theme image credits are in
[theme-asset-credits.md](../../docs/theme-asset-credits.md).

To refresh them, use the existing Playwright/Chromium environment:

```sh
python tests/browser/readme_demo.py /tmp/opencode/goodmorning-readme-demo
```

The helper creates a disposable runtime outside the repository, permits only its
loopback viewer's requests, and never dispatches model work or calls integrations.
It validates native briefing sources and checks desktop and phone-sized layouts,
loaded images, overflow, and browser errors. `result.json` records the checks.
Review the captures before copying only the PNGs into this directory; keep runtime
records and reports outside the source tree.

`priorities.png` keeps its existing filename for README links but now shows the
current **Tasks** section. Both README languages share this English-language demo.
