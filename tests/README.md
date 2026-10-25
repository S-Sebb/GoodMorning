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
| `avatar` | Shared briefing avatars, day and night scenes, animated portraits under reduced motion, custom uploads and layout alignment |
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
| `notifications` | Notification settings through the gateway: defaults, saving across reloads and devices, failed turn-on leaves no worker, both languages, phone and desktop |
| `night_preflight` | Evening check-in dialog: due-today answers, early finishes by project, reopening, and the empty state |
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
choices: `briefing_format` (add `--with tiktoken --with pyyaml`), `inbox`,
`initialization`, `news`, `weather` and `projects.mjs`. They are evidence, not
release gates.
`reply_templates.py` and `trial_engine.py` are shared helpers.
`tests/integration/native_chat_titles.py --binary PATH` checks the native
auto-title flow against a loopback-only fake provider.

## Paid live-model trials (opt-in)

Required for prompt changes as set out in `AGENT-PROMPT-GUIDE.md`. Each synthetic
account gets a private engine started like a hosted account's: the latest OpenChamber
with the OpenCode and Node it pins (cached in `~/.cache/goodmorning/trial-engines`),
a fresh HOME and database, a copied public release as working directory, and the
production `LocalBridge`. Trial sessions therefore never reach your OpenCode
service, sidebar or notifications, and agents load only the release's own
instructions and skills, not your global `AGENTS.md`, skills or plugins. Your
OpenCode Go key is read from your OpenCode database in-process and registered in
each private engine, as provisioning does; it is never printed, logged or put in
an environment variable. Session metadata verifies the actual model and variant.
Assertions alone never accept a prompt: tone, language and grounding need manual
review of the retained transcripts. Trials do not cover public HTTPS, encrypted
deployment, real providers or load. Locally the agent's shell still runs as you,
so permission rules, not Unix users, keep it inside its account.

Start every trial with `trial.py`, which runs it detached, so OpenChamber restarts
and the agent's shell ending do not stop it:

```
PY tests/benchmarks/trial.py start NAME HARNESS [ARGS]   # e.g. start en briefing_tone_live --language en
PY tests/benchmarks/trial.py wait NAME                   # exit 0 passed, 1 failed or stopped, 2 still running
PY tests/benchmarks/trial.py status [--all]
PY tests/benchmarks/trial.py stop NAME                   # interrupts its model work, stops its engines
PY tests/benchmarks/trial.py clean [NAME]                # one run, or every run of this checkout
```

Runs live in `/var/tmp/goodmorning-trials/<checkout>/NAME` (on disk, outside any
home directory or git checkout, like a release) with `NAME.log` beside them.
`wait` returns after `--timeout` seconds (default 600); call it again rather
than watching processes. Killing a runner stops its engines and their model work.
Each output directory holds an exclusive lock: a refused start or `--resume`
means another runner still owns it. Never delete a lock by hand; `clean` refuses
while a run is active. Once the results are reviewed and the PR is up, run
`clean` without a name.

For a fair baseline, run both arms in the same checkout's task folder, at the
same time, on the same engine (pinned per task in `engine.json`): export the
merge-base into `B=/var/tmp/goodmorning-trials/<checkout>/base-src` with
`mkdir -p $B && git archive $(git merge-base origin/main HEAD) | tar -x -C $B`,
then start the baseline with `--source $B`. The same harness and fixtures then
give the agent the other release (instructions, docs and helper scripts). The
website server code (chat dispatch, briefing jobs) still comes from the checkout
running the harness, so for a change there, start the baseline with that
checkout's own `trial.py` instead, e.g. from the primary checkout on `main`.
Models are not deterministic: repeat each arm under a new NAME and compare the
repetitions before attributing a difference.

| Trial | Harness and arguments | Covers |
|---|---|---|
| Website | `website_live` | Capture, follow-ups, Schedule, evening feedback, regeneration through real browser routes. `--blocked-report`: reported blockers. `--ambiguity`: a recurrence question comes before any write |
| Task and tone | `task_tone_live` | English and Chinese × default, formal and playful tones, run twice: capture, clarification, duplicate request identities, refused writes, fault recovery |
| Briefing tone | `briefing_tone_live --language en` (then `zh-CN` under another NAME) | Morning and evening prompts: empty and opted-in sections, unavailable providers, resume, evening feedback, regeneration, ambiguous attribution, and two judgment cases: vague task titles and messy evening feedback with a task move |
| New episodes | `anime_live --language en\|zh-CN [--model NAME]` | Evening New episodes section with episodes, nothing new and a failed source (copied block, short note, no watch links); turning it on in chat from a clear request and from one that needs the source and season asked first. AniList and Bangumi are synthetic fixtures |
| Game sales | `games_live --language en\|zh-CN [--model NAME]` | Evening Game sales section with deals, nothing on sale and a failed store (copied block, short note, no buying push or price guesses); turning it on in chat from a clear request (wishlist, threshold, one game with its own discount) and from one that needs the region and discount asked first. The Steam store is a synthetic fixture |
| Stocks | `stocks_live --language en\|zh-CN [--model NAME]` | Evening Stocks section with holdings plus one unknown code, and a failed quote read (copied block, market totals in the note, no advice or forecasts); saving holdings in chat from pasted broker text, a broker screenshot (market-value and P/L columns as traps), a sell-and-buy update, a full replacement, several swaps, share corrections and an unclear new list (asks replace or add), each confirmed before saving. Tencent quotes are synthetic fixtures |
| Custom schedule | `custom_tone_live --language en\|zh-CN` | Custom-schedule prompts: ask until clear, save once, tone |
| Item categories | `category_live --language en\|zh-CN` | Real-usage requests (nudge on habit days, secretary errand, reference note, daily follow-up, birthdays, weekly TBC class, linked preparation, split request, dependent step, routine plus deadline, day and deadline tasks); checks the saved records. `--only SCENARIO...` reruns chosen scenarios under a new NAME |
| Category briefings | `category_briefing_live --language en\|zh-CN` | A synthetic week with every category: real models write a Wednesday morning and a Friday evening (form answered); checks each edition shows its focus day only, does its errands (web allowed), reports only what their conditions ask and compares with the last saved result, shows older items with notes in their details cleanly without rewriting them, and saves desktop/mobile screenshots for manual review |
| Category week (free) | Run directly: `PY tests/benchmarks/category_week.py --output DIR` | No model calls: prints what each morning, evening and Schedule-tab day shows for the same synthetic week |
| Manual | Run directly: `PY tests/benchmarks/manual_trial.py --help` | Ad-hoc cases you drive by hand; each command starts the case's engine until it settles |

Task and tone options: `--model deepseek-flash` and `--language en|zh-CN` test a
pairing without changing production routing; `--tone-only` reruns the six tone
settings after a tone fix; `--strict-chat` adds structural reply checks;
`--system-file PATH` is an experiment that overrides only the copied trial's base
prompt; `--resume` (`trial.py start` with the same NAME) skips finished cases and
never resends an in-flight request, and must keep the original language, model,
scope and prompt hash.
`website_live.py --resume` only continues its preserved TBC interruption.
`briefing_tone_live.py` never replays a directory or answers model questions
itself: inspect interrupted work before continuing.

Unit tests for the trial harnesses (`test_task_tone_trial.py`,
`test_briefing_tone_trial.py`, `test_trial_engine.py`) run in the
required suite.
