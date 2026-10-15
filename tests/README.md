# Tests

All tests use isolated synthetic records, never a personal runtime. Fixtures go
under `/tmp/opencode` when it exists, or `GM_TEST_TMPDIR`. Write browser
artifacts to a private directory outside the checkout.

Shorthand below: `PY` = `uv run --no-project --with-requirements requirements/browser.txt python`.
Browser suites also need Playwright: add `--with playwright` and install
Chromium once with `PY -m playwright install chromium`.

## Required gates

| Gate | Command | Runs in |
|---|---|---|
| Unit and system tests | `PY -m unittest discover -s tests -p 'test_*.py' -q` | every PR (CI), deploy |
| Project-access helper | `node --test tests/test_projects.mjs` | every PR (CI), deploy |

`test_public_assets.py` also runs `test_network.mjs` when Node is available.
Shared fixtures (`FakeChamber`, `MockChamber`, the gateway and live-viewer HTTP
fixtures, `start_server`) live in `support.py`; import them from there.

## Writing tests

- Test behavior through the real helpers. Do not assert exact instruction or
  interface wording, grep source text, or repeat one fixture's facts across files.
- Keep coverage of distinct behavior, failure recovery, data preservation,
  authentication, encryption, consent and account isolation.
- Boundary tests use just enough records to cross the boundary.
- Fixture base classes carry no tests, so subclasses do not rerun them.

## Browser suites (opt-in, free)

These run the real viewer or gateway in Chromium with synthetic data and make no
model calls. Run the suites for the pages you changed, as
`PY tests/browser/NAME.py /ABS/PRIVATE/DIR` unless noted. Browser emulation does
not prove physical phone behavior, real-model behavior, load capacity or backup
restoration.

| Suite | Covers |
|---|---|
| `activity` | Activity reminders across tabs, owner isolation, outage, motion, both languages |
| `auth`, `auth_scroll` | Login form toggles; mobile auth layout under touch scrolling and viewport changes |
| `avatar` | Shared briefing avatars and layout alignment |
| `chat` | Mode switch and conversation flow |
| `chat_actions` | Question, answer, permission and change cards: all palettes, contrast, drafts, one-shot and reduced motion |
| `chat_action_ownership` | Real chat API rendering native, browser-chat and browser-turn receipts in all modes |
| `chat_compact` | Compact layout, centered welcome, always-open history |
| `chat_history` | Tab-scoped restore, 15-minute idle reset, Resume, draft warnings, login changes, outages, independent tabs |
| `chat_markdown` | Rendered Markdown, privacy, history, palettes |
| `chat_mobile_viewport` | Composer access and reading or draft preservation with simulated phone keyboards |
| `chat_response` | Unreadable responses recover; uncertain sends never replay |
| `quick_chat` | Floating quick chat on desk pages: shared tab conversation with the Secretary page, Open in Secretary, 15-minute reset, questions, setup gating, layouts in both languages |
| `chat_theme`, `color_schemes` | Edition colours in account time; whole-site palette switching through the gateway |
| `day_scenes`, `starry_twinkle` | Scene contrast, background motion, reduced motion |
| `desk_icons` (`--screenshots DIR`) | Decorative icons, translations, narrow layouts |
| `future`, `mobile_sections` | Varied far-future editions; touch section picker |
| `gateway_assets` (no argument) | Every asset and error page through a real gateway, with all requests intercepted |
| `generation`, `stream`, `regeneration` | Briefing dispatch round trip; section-by-section publication; confirmed replacement of today's edition |
| `image_refresh` | Late cached images refresh a news preview without rewriting its text |
| `initialization`, `setup_pending` | Localized initialize start; readable gateway failures on all layouts |
| `language` | Bilingual flow through the real gateway |
| `night_preflight` | Evening completion choices and the empty state |
| `schedule` (`--canonical`) | Schedule tab with v2 tasks, statuses and TBC items; refresh, Chinese, mobile, source failures, no JavaScript |
| `scroll_rails` | Phone scroll rails on all four tabs, drag, keyboard control, drafts |
| `taxonomy` (`--screenshots DIR`) | v2 renderer at desktop and phone widths, English and Chinese |
| `update` | Patch-note discovery, history, dismissals, safe updates |
| `readme_demo` (`OUTPUT_DIR`) | Regenerates README screenshots; review before copying into `assets/readme/` |
| `briefing`, `polish` (`--url URL`) | Briefing rendering and motion against a running private preview |
| `briefing_model_output` (`--trial DIR --output DIR`) | Renders documents from a preserved paid trial; no new model calls |
| `login`, `public_security` | **Public deployment.** Need explicit deployment access; create only synthetic accounts |

## Benchmarks (opt-in, free)

`tests/benchmarks/` holds size and speed experiments that informed past design
choices: `briefing_format`, `inbox`, `initialization`, `news`, `state_news`,
`weather`, `workflow` and `projects.mjs`. They are evidence, not release gates.
`reply_templates.py` and `native_bridge.py` are shared helpers.
`tests/integration/native_chat_titles.py --binary PATH` checks the native
auto-title flow against a loopback-only fake provider.

## Paid live-model trials (opt-in)

Required for prompt changes as set out in `AGENT-PROMPT-GUIDE.md`. Every trial uses copied
public source, a synthetic account and fresh native sessions; it never lists
unrelated sessions or copies credentials. Session metadata verifies the actual
model and variant. Output directories hold an exclusive lock: a refused run or
`--resume` means another runner still owns it. Never delete the lock, even after
a server restart. Assertions alone never accept a prompt: tone, language and
grounding need manual review of the retained transcripts. Trials do not cover
public HTTPS, encrypted deployment, real providers or load.

| Trial | Command | Covers |
|---|---|---|
| Website | `PY tests/benchmarks/website_live.py --output DIR` | Capture, follow-ups, Schedule, evening feedback, regeneration through real browser routes. `--blocked-report`: reported blockers. `--ambiguity`: a recurrence question comes before any write |
| Task and tone | `PY tests/benchmarks/task_tone_live.py --output DIR` | English and Chinese × default, formal and playful tones, run twice: capture, clarification, duplicate request identities, refused writes, fault recovery |
| Briefing tone | `PY tests/benchmarks/briefing_tone_live.py --output DIR --language en` (then `zh-CN` in a new directory) | Morning and evening prompts: empty and opted-in sections, unavailable providers, resume, evening feedback, regeneration, ambiguous attribution, and two judgment cases: vague task titles and messy evening feedback with a task move |
| Custom schedule | `PY tests/benchmarks/custom_tone_live.py --output DIR --language en\|zh-CN` | Custom-schedule prompts: ask until clear, save once, tone |
| Manual | `PY tests/benchmarks/manual_trial.py --help` | Ad-hoc cases you drive by hand |

Task and tone options: `--model deepseek-flash` and `--language en|zh-CN` test a
pairing without changing production routing; `--tone-only` reruns the six tone
settings after a tone fix; `--strict-chat` adds structural reply checks;
`--system-file PATH` is an experiment that overrides only the copied trial's base
prompt; `--resume` skips finished cases and never resends an in-flight request,
and must keep the original language, model, scope and prompt hash.
`website_live.py --resume` only continues its preserved TBC interruption.
`briefing_tone_live.py` never replays a directory or answers model questions
itself: inspect interrupted work before continuing.

Unit tests for the trial harnesses (`test_task_tone_trial.py`,
`test_briefing_tone_trial.py`, `test_native_trial_bridge.py`) run in the
required suite.
