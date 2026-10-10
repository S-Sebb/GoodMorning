# GoodMorning Plan

Goal: build a general AI secretary project in this repo. Four skills plus scripts plus reusable templates. No personal data in source code.

Current deployment policy (2026-10-10): one self-contained `goodmorning` skill
is installed only in `~/.agents/skills/goodmorning/`. The checkout keeps inactive
source in `skill-source/goodmorning.md` and registers no skills or command wrappers.
Deployment is manual file copying; no installer or release-packaging scripts are needed.
Older project-skill and wrapper references below describe the historical plan.

User request in simple words. Each phase below can go to a different agent.

## Current Status — inspected 2026-10-09

- Setup files, weather, calendar, local/relay project access, hardened state,
  and managed news collection/delivery are implemented.
- All four project skills, same-session command wrappers, shared rules, and
  reply templates exist. File/script contracts and a deterministic fake-data
  morning/night workflow are tested. An authorized sandbox walkthrough exercised
  initialization, gm, gn and pending idea capture; feedback drove the final voice,
  layout, language-first setup and yesterday-only news behavior.
- Current verification: **244 Python tests and 26 Node tests pass**. Tests use
  synthetic fixtures; recurrence also had a separate read-only live cache check.
- Replies prioritize clean formatting and clarity, with customised tone
  throughout. Reply length is not a token or sentence target. Internals stay compact.
- Finalized for the supported agent-assisted deployment described in
  `docs/deployment.md`. Packaging excludes private data and includes vendor notices,
  file hashes and a bundle checksum. Deployment-specific provider/host checks remain
  owner steps; unsupported integrations are listed explicitly rather than promised.
- Personal setup is an owner-confirmed step, separate from general implementation.
  Authorized walkthrough records were removed on the owner's cleanup request.
  The real secretary runtime has not been initialized by this work.

### Betterbird recurring import repair — 2026-10-09

- Added bounded, standard-library expansion for common daily/weekly/monthly/yearly
  rules, RDATE/EXDATE, stored moved/cancelled exceptions, source timezones and
  stable PRTime occurrence identities. Unsupported rules fail atomically.
- Fifteen new fixture tests cover recurrence, DST, exceptions, cancellations,
  repeat staging and failure safety. An independent comparison matched
  python-dateutil for 315 supported rule combinations; it is not a dependency.
- A read-only selected-cache check expanded 26 occurrences over 30 days, including
  two cancellations, in 0.174 seconds. No source events or private runtime were
  changed. This checks expansion, not end-to-end approval or provider freshness.
- Updated recurrence limits and initialization guidance. The earlier sandbox
  prototype was not reused. See `docs/calendar-pipeline.md` for exact support.
- Redeployed eight public files and registered secretary guidance locally. All
  86 installed manifest hashes match; 244 Python tests pass in the installation.
  Private runtime files were unchanged; no real events were staged or approved.

### Deployment finalization — 2026-10-09

- Removed the explicitly authorized sandbox run, including 64 test files, copied
  preferences, calendar, ideas, caches and snapshots. No personal identifiers or
  remote project paths remain in public project files. The empty real runtime was
  left untouched; no credentials or external calendar/project data were modified.
- Fixture temp paths now have a portable fallback and explicit `GM_TEST_TMPDIR`
  override. Both suites passed with a separate disposable root, not just this
  harness's temporary directory. Release tests check private-file exclusion,
  symlink refusal, Python 3.9 grammar and vendored source/license hashes.
- Added an allowlisted deployment archive builder and GitHub validation workflow.
  CI execution on GitHub is not claimed as a local result. No source commit/push,
  live server deployment, real setup, scheduler or prototype promotion is implied.

### Initialization failure follow-up — 2026-10-09

- Separate confirmed local setup from consented integration checks and optional
  calendar review. Reuse answers/permissions; avoid dummy free-text choice buttons,
  repeated preference loops, automatic retries and code-repair detours.
- Added a no-fetch/no-write local preflight and parallel selected checks sharing
  a 20-second elapsed budget. Optional failures preserve profile readiness and
  report actionable pending items. Multiple national-news countries are explicit.
- Reproduced and fixed wrong-country first-result geocoding, changed-feed archive
  contamination, credentials saved before calendar review, and relay deadlines
  ignored by stalled transports/response bodies. CLI close timers no longer
  extend finished project commands. Calendar imports require consistent backups.
- Initially, metadata-only Betterbird probing rejected recurrence before import;
  production expansion was unsupported and the sandbox prototype was not promoted.
  The recurring import repair above supersedes that limitation for supported rules.
- Synthetic four-hung-check experiment: sequential waits 0.604 s versus shared
  budget 0.151 s (3.99x). This proves the bounded failure path, not a measured
  real-user initialization speedup or live provider availability.
- Regression tests use fictional inputs. No personal profiles or calendar data
  are copied into source/tests; existing sandbox records remain unchanged.

## 1. Scope

### Language-first initialization

- Ask the secretary's reply language before any other initialization preference.
  Save explicit language/script, bilingual or follow-message choices as
  `secretary_language` after storage consent and use it across all four skills.
- Keep reply language independent of source-news language, country, timezone and
  tone; do not translate machine-readable headings, paths, IDs or raw ideas.
- New templates require the language answer; older profiles lacking the field
  remain valid without invented preferences or forced reinitialization. Regression
  tests cover question order, persistence, independence and legacy compatibility.

### Brief takeaways and closing — latest refinement

- Night-flow refinement now applies the same headings/rules, restrained bold,
  optional grounded takeaways, clear progress entries and next-day timetable.
  Actual feedback is required before recording completion; assistant implementation
  and calendar presence never stand in for user-reported work. No routine news/
  weather fetching or empty reminder padding belongs in the night summary.

- Latest news-date preference: the sandbox morning briefing shows only the
  previous completed local day's top stories. `news_latest` is explicitly false;
  today's news is deferred to tomorrow, not shown in a same-day update section.

- Keep the structured layout, ordered weather, neutral source-based news and
  calendar timetables. Optional one- or two-sentence takeaways after sections and
  a short personal closing now add the agreed warmth without a long introduction.
- Do not require flavor in every section, repeat lists, add unsupported news
  commentary, infer feelings or bring operational disclaimers back into replies.
- Synthetic fixtures/tests preserve source summaries, citations and layout while
  allowing grounded takeaways and a closing. Saved briefings remain untouched.

### Earlier structured layout refinement

- The latest user feedback supersedes the earlier prose-led framing: short
  greeting/date only, clear Markdown headings and section rules, no extra opening,
  transitions or closing flavor paragraphs. Personality remains within useful content.
- Weather has separate temperature, precipitation, applicable extreme-warning
  and AQI parts in that order. Calendar output is a chronological timetable.
- News uses concise source-based summaries, preferably existing summaries where
  appropriate to reuse; neutral assessment is separate and evidence-grounded.
  No blanket claim of unbiased opinions, partisan framing or lengthy news flavor.
- Lists/tables are preferred when useful, not forced into simple confirmations.
  Bold is for exceptional importance/urgency, never heading substitutes.
- Six layout regression tests verify the structure, optional warning placement,
  timetables, source summary reuse and lack of bold section dividers. Existing
  saved user briefings were not rewritten by this instruction/template change.

### Earlier conversational voice design — superseded where noted above

- Added a shared voice design and references from all four skills/templates.
  The confirmed persona applies throughout explanations, transitions, questions
  and closing, not just a greeting attached to an impersonal dashboard.
- Clarified that the materiality gate removes operational caveats, not warmth,
  emotional acknowledgement, light agreed flirtation or useful explanation.
  Human-like language does not require pretending to be a real human, inventing
  feelings or intimacy, or imposing emotional dependence.
- Synthetic morning/night fixtures now use connected, expressive prose while
  preserving facts, citations, critical warnings, pending-work status and agency.
  Tests verify those contracts, not subjective warmth; the user remains the judge
  of the actual skill experience. No saved user briefing was replaced in this pass.

### Secretary message materiality — 2026-10-09

- All four skills/templates prohibit non-critical disclaimers and routine process
  narration. Full metadata remains internal; material safety, stale/missing data,
  conflicts and failed writes are surfaced concisely. Citations and dates remain.
- Removed default offers of older news and empty-queue statements. Healthy weather
  retrieval and routine model/station explanations no longer belong in replies.
- Added conservative known-boilerplate lint. gm/gn snapshot marking rejects a
  flagged draft before writing its snapshot or run line; it never strips warnings
  blindly or rewrites old replies. Other skills share the same drafting policy.
- Synthetic rendering verifies ordinary morning/night content without boilerplate
  while retaining AQI, stale-weather/refresh failure, required news gaps and prep.

### News-quality follow-up — 2026-10-09

- Diagnosed the configured China Daily RSS endpoint returning HTTP 404 over HTTP
  and HTTPS while its homepage worked. Replaced it with verified English SCMP
  China and Guardian China feeds, and broadened AI/world/UK publishers.
- Found that legacy selection favored publisher counts/RSS/recency rather than
  importance, and hard source quotas hid otherwise available UK stories.
- Added source/window diagnostics, short feed excerpts, transparent shortlist
  signals and genre controls. Scores are not editorial understanding or truth.
- Required assistant editorial selection of collected candidate IDs with written
  reasons; stale/tampered choices fail, pending reviews cannot be acknowledged,
  and delivered reports stay unchanged. No additional model API/key is needed.
- Added separately dated current-day snapshots, five-minute cache freshness,
  future timestamp exclusion and protection against rediscovered older articles.
- Live collection and captured-corpus review were exercised in the sandbox.
  Reviewed historical CN/GB reports each contain 4 AI, 4 world and 4 national
  stories; a current-day review retained only 1 qualifying AI update rather than
  padding it. This demonstrates the workflow, not exhaustive coverage, verified
  facts, or objective importance/Twitter parity. Original GM snapshot is preserved.

Build general code only. Do not initialize with real user data yet.

- Source = templates, empty schemas, example config, skill instructions, scripts with provider switch.
- User data = city, project paths, tone, work days, API keys. This lives in user-local files only, git-ignored.
- Skills: `/gm` morning greeting, `/gn` night summary, `/eureka` fast idea save, `/secretary` all other secretary work.

Triggers:
- `/gm` wakes morning greeting.
- `/eureka` wakes idea capture.
- `/gn` wakes night summary.
- `/secretary` wakes general record or reply work.

## 2. Repo Layout (implemented)

```text
GoodMorning/
  PLAN.md
  README.md
  .gitignore
  .opencode/skills/gm/SKILL.md
  .opencode/skills/gn/SKILL.md
  .opencode/skills/eureka/SKILL.md
  .opencode/skills/secretary/SKILL.md
  .opencode/commands/{gm,gn,eureka,secretary}.md
  scripts/weather.py
  scripts/news.py
  scripts/news_cache.py
  scripts/news_reports.py
  scripts/news_sources.json
  scripts/secretary_calendar.py
  scripts/calendar_store.py
  scripts/state.py
  scripts/runtime_files.py
  scripts/projects.mjs
  scripts/project_files.py
  scripts/relay_transport.mjs
  scripts/relay_frontend_shim.mjs
  scripts/vendor/openchamber-relay/  # source pin, manifest, and license
  templates/profile.template.md
  templates/project.template.md
  templates/daily.template.md
  templates/projects.registry.example.json
  templates/{gm,gn,eureka,secretary}.reply.template.md
  templates/custom_schedule.template.md  # legacy migration reference only
  config.example.md
  docs/skill-rules.md
  docs/agent-usage.md
  docs/{weather,news,state,calendar}-pipeline.md
  docs/project-access.md
  tests/                           # pipeline/contract tests and experiments
```

User-local runtime (created only after confirmed setup, git-ignored):

```text
secretary/
  profile.md
  projects/<project-name>.md
  daily/YYYY-MM-DD.md
  calendar.sqlite
  projects.json                   # confirmed aliases and exact write scopes
  news_reports.sqlite             # first authorized managed backfill creates it
  inbox.md
  state.json
```

`.gitignore` must cover `secretary/` user data and API keys (`.env`).
Snapshots live beside daily records. SQLite journals, stable runtime locks, and
optional user-local configuration remain private. `.cache/goodmorning/` is ignored
and stores transient weather/news retrieval data. Python 3.9+ is required;
state/managed news locks use Linux. Project access also requires Linux and
Node.js 22.18+, without npm installation.

## 3. Data Design

Keep notes short, clear, fixed format. Goal: enough meaning, no extra words, low token cost, good scalability.

### 3.1 profile.md

Fields: city (default empty), region flag (`global | mainland-china`), timezone, work days, sleep time, secretary tone, news preference, `news_country` (user-confirmed primary ISO code), optional `news_additional_countries` (comma-separated confirmed ISO codes), optional news source config path, calendar source, project root paths.

Optional personal context: `occupations` (current roles, possibly multiple) and
`expertise_fields`, alongside existing industry/project scope/knowledge area.
Invite these during setup and save only confirmed answers. Use them throughout
the skills to choose relevant topics, examples, and explanation depth, without
assuming expertise from titles or making every conversation work-related.
Users may skip; older profiles without these fields remain valid. This context
does not alter the clarity/tone priority or required news sections/country choice.

City rule: default empty. Init must ask. `/secretary` command "I moved to X" updates city plus region flag. No code change needed.

### 3.2 projects/<name>.md

One file per project. Fields: overall goal outline, current progress, TODO list, priority, deadlines, last update date.

Secretary reads relevant registered paths and writes confirmed ideas/progress
only within owner-authorized scope. `secretary/projects.json` is authoritative
for aliases, host/path, exact write targets, shared storage, and execution
permission (off by default). Records include registry alias, access method, and
write-back scope. Read instructions and the complete target before a hash-checked
write; preserve unrelated work. See `docs/project-access.md`.

### 3.3 daily/YYYY-MM-DD.md (+ answer snapshots)

Fields: gm ran (yes/no + session name), gn ran (yes/no + session name), weather summary, news summary, schedule, must-do list, nice-to-do list, user feedback, actual progress.

Verbatim agent replies live beside it, not in it:
`daily/YYYY-MM-DD.gm.md` / `daily/YYYY-MM-DD.gn.md` (write-once snapshots).
The daily file keeps concise summaries and an `| answer: path` pointer; the
verbatim reply follows the user's tone without a length budget. Default agent
reads use `state.py --check --json` plus the selected daily record, not raw indexes
or bulk snapshots. Open snapshots only on explicit need. Storage headings/run
lines are fixed in `templates/daily.template.md`. Section flags indicate presence,
not successful retrieval, completed work, or news delivery. News dates refer to
the news day, not the morning briefing's date.

### 3.4 inbox.md

Unconfirmed ideas: local timestamp/timezone, raw wording, status
(`pending | confirmed`), and optional linked project. Preserve multiline raw text
with reversible single-line JSON encoding. State counts the status column, not
words inside the idea. Keep entries pending until meaning is confirmed and the
agreed organization succeeds; failed write-back does not erase the idea.

### 3.5 state.json

Derived duplicate/missed-day index. The newest 14 daily entries persist; a bounded
filesystem-metadata cache supports 30-day reply costs. Older daily records remain
the source of truth and are rescanned locally. Fields include version/update
time/timezone, gm/gn dates/sessions, answer pointers/statistics, section presence,
inbox pressure, project update dates, calendar counts, and `history_before`.

Agents use compact `--check --json`: missed-day/project pages (default seven,
`--limit 1..30`, `--offset`), totals/next offsets, today's sections, warnings, news
overview, and accurate 7/30-day costs. Long gaps are counted without building
every row. History/costs are calculated before truncation; unchanged warm checks
do not reopen snapshots. Timezone precedence is explicit flag, confirmed profile,
then system local; `--today` supports explicit historical work.

`--rebuild` forces fresh statistics. Atomic replacement and `.state.lock` protect
cooperating commands; ordinary editors bypass the lock, and writes are not
multi-file transactions. Unsafe snapshot pointers are not opened, missing/orphan
snapshots warn, unreadable sources fail visibly, corrupt derived JSON can be
rebuilt, and unknown/newer schemas are preserved and refused. See
`docs/state-pipeline.md`; size estimates are descriptive, not reply budgets.

### 3.6 calendar.sqlite

User-set dates and approved external imports, managed by talking to the
secretary. SQLite provides indexed queries, stable IDs, transactional edits,
and history. Original imports stay separate from AI-reviewed versions.
New or changed imports wait in a review queue; changed imports keep their
previous approved version visible until review. Read commands never fetch
providers. See `docs/calendar-pipeline.md` for the full contract and limitations.

Maintenance rule (all skills: /gm, /gn, /secretary, /eureka): whenever the
user implies a likely scheduled event, the agent quotes back the parsed
date/time/title/place and asks to add it. On yes, it runs
`secretary_calendar.py --add --event-json EVENT` (the old shorthand is still
accepted). Never invent a missing date/time — ask. Edits/cancellations require
confirmation, a stable ID, and the current revision. Never edit silently.
Imports are also conversational: the secretary obtains an authorized source,
stages normalized original events, reads the queue/details, then approves a
compatible, possibly simplified version. No user-maintained import file.
Legacy Markdown is accepted only by explicit `--migrate-md`, source untouched.

### 3.7 news_reports.sqlite

Persistent compact reports, separate from the expiring HTTP/headline cache.
Each news date records stories, AI/world/national counts, retrieval warnings,
collection time/settings, an exact content ID, and optional delivery session.
Country, timezone, and effective feed configuration define separate namespaces;
changed scopes do not silently reuse or destroy earlier reports.

Statuses: `missing` (no stories), `partial` (some required sections empty),
`collected` (each section populated), and `delivered` (explicit acknowledgement
after actual presentation). Populated sections do not prove exhaustive coverage.
Empty/partial reports cannot be acknowledged. Marking gm/gn or writing a news
heading does not acknowledge delivery.

Default backfill selects the latest seven completed local days, newest first.
Collected/delivered reports skip automatic fetching. Incomplete reports have a
one-hour retry delay and at most three automatic online attempts per scope/date;
offline collection does not consume that budget. Historical seven-day windows
use `--ending DATE`; known older undelivered counts and a suggested ending date
remain visible. Explicit `--refresh` can override guards; agents must not loop.
SQLite and a stable `.news.lock` protect cooperating commands. See
`docs/news-pipeline.md` for read/delivery contracts and limitations.

## 4. Skill Behavior

### 4.1 Init (part of /secretary)

First use must run setup, not normal work. Steps:

1. Ask for project folder paths, city, timezone, work habits, tone, special needs.
   Confirm which country's national news the user wants alongside world news;
   do not infer it from city or region. Verify that country's feeds, save
   `news_country`, and use a user-local news config for countries not bundled.
2. Invite the user's current occupations/roles and expertise/fields, explaining
   that these help choose useful topics, examples, and explanation depth. Accept
   multiple roles and allow skipping. Ask about industry, project scope, and
   knowledge area only where not already answered. Record confirmed context
   briefly; do not infer skill level from a title or ask for unnecessary private
   details. Existing profiles do not need reinitialization for these optional fields.
3. After format agreement and consent, create only missing user-local records;
   never overwrite existing data. Initialize the calendar with
   `secretary_calendar.py --init --timezone ZONE` and rebuild state. Do not create
   `custom_schedule.md` or fake completions. Confirm aliases, exact write scopes,
   and lock-artifact consent before creating a project registry.
4. Verify weather and model AQI with `weather.py` using a qualified city or
   verified coordinates. Open-Meteo needs no signup. Offer the optional free
   WAQI station cross-check: register at `aqicn.org/data-platform/token/`, set
   `WAQI_TOKEN`, and verify both AQI sources if the user chooses it.
5. Agree on formats before saving and provider checks before fetching. Failed
   verification remains an open setup item, not a successful result.
6. Explain profile/projects, daily records/snapshots, inbox, calendar, and news
   reports. Offer custom-only, authorized external imports, or Betterbird staging;
   do not promise native login, ICS file parsing, or unsupported recurrence rules.

### 4.2 /gm Morning Greeting

Order:

1. Say good morning.
2. Run `state.py --check --json`. If gm already ran, identify its session and stop
   without fetching or marking; open the full reply only on request. Offer to
   finish the oldest missed run or continue today. Historical work uses an explicit
   date; never silently backdate or substitute today's forecast.
3. Run `weather.py` once with profile city and use the default compact brief,
   not JSON or raw API responses. Report rain yes/no/unknown, umbrella/boots
   advice, temperature, and AQI with health level and source. Keep timestamps,
   stale markers, and failure warnings; station cross-checks are optional.
4. Run `news.py --backfill` once using confirmed profile values and inspect its
   manifest. Use `--show DATE` for yesterday's needed report; separate AI/world/
   national news with sources and retrieval/date warnings. Offer older collected
   dates rather than dumping every headline. Empty means not collected, not no
   news. After actual delivery of all saved stories in a collected report,
   acknowledge its exact ID with `--ack DATE --expect REPORT_ID --session NAME`.
   Drafts/partial selections remain unacknowledged. If tools cannot run after the
   final reply, leave it collected until a later turn can verify delivery. Never
   acknowledge early just to avoid another turn.
5. Run `secretary_calendar.py --days N`. Show next few days schedule from the
   saved custom events and approved imports. Surface the pending review count;
   never treat raw imports as approved. Warn about prep: time, place, materials.
   Example: TA at RSM338 9:30 today; group meeting tomorrow 11:00, send slides by 22:00 today.
   If the user mentions a new dated event, confirm and add it via --add (§3.6).
6. Read `projects/*.md`. Build this week TODO per project. Estimate time, priority, fixed time needs. Pick "must finish today" vs "recommended today". Save to today's daily file.
7. Use the reply template with clean formatting, clarity, and customised tone
   throughout. Preserve daily records; new tasks are unchecked. Save the exact
   reply via `state.py --mark-gm` with the real session and answer input; verify
   success. Saving is not news delivery. Ordinary amendments preserve original
   snapshots; `--force` requires explicit replacement consent.

### 4.3 /gn Night Summary

Order:

1. Run `state.py --check --json`. Apply the same duplicate/missed-date rules as /gm.
2. Read today's must-do and recommended lists. Ask user what got done.
3. From user progress, judge if each project is safe or behind. Suggest next steps.
4. Remind tomorrow schedule.
5. Say good night in user tone, or follow special user rule. Respect time (late night vs evening).
6. Check only confirmed completions, preserve partial/open tasks, and add feedback
   and progress to the selected daily file. Update authorized project records and
   `last_update`. Save the exact reply via `state.py --mark-gn` with its real session
   and answer input. Do not mark while waiting for feedback.

### 4.4 /eureka Idea Capture

Order:

1. Immediately save raw ideas and supplied details to `inbox.md` with timestamp,
   before asking clarification; note remaining ambiguity. Confirm saved. If the
   idea implies a scheduled event, offer to add it to the custom calendar (§3.6).
2. Leave the rough idea pending by default, without a now/later question. Invite
   optional clarification via `Clarify`; the idea can also stay as is. No reply
   is required.
3. On a clarification request or directly supplied details (including through
   `/secretary`), reuse answers and ask only about remaining ambiguity. Preserve
   the raw idea and retain details with its entry, without duplication. Clarify
   and confirm meaning, then write to authorized project records
   and/or work files. Set `confirmed` only after agreed organization succeeds;
   keep unresolved writes pending. Rebuild the index without marking gm/gn.
   Never claim a failed capture was saved or install scheduled reminders without
   separate authorization.
4. Default / later: keep in inbox even without a follow-up reply. Next `/gm` adds
   an unchecked clarification TODO to the reply and daily tasks; `/gn` asks a
   clarification question; `/secretary` gives a reminder. Repeat until confirmed
   and organized, without blocking unrelated work if the user defers.

### 4.5 /secretary General

Handles setup, profile changes, records, questions, calendar review, and confirmed
plan amendments. Read relevant context and apply registry/confirmation rules to
writes. A move changes confirmed city/region and possibly timezone; national news
country stays independent. General work does not automatically mark gm/gn.
Direct details about a pending idea resume its clarification without requiring
`Clarify` or `/eureka`; ask which idea only if the target is ambiguous.

The installed skill lives only in `~/.agents/skills/goodmorning/`; its inactive
source is `skill-source/goodmorning.md`. No command wrappers are registered.
It uses the current session without changing models or spawning a child and
references `docs/skill-rules.md` and `templates/<name>.reply.template.md`.
`docs/agent-usage.md` summarizes their workflows.

During skill usage, prefer the session's available `question` tool (OpenChamber
structured question UI) for setup, preferences, progress, clarification, and
confirmations. Use helpful choices and built-in custom answers, with multiple
selection only where appropriate. Apply customised tone to questions while
prioritizing clarity. Wait for explicit answers before mutations; dismissal or
tool failure is not consent. Do not repeat answered questions. If the tool is
unavailable/unusable, ask normally and wait; never invent a tool action or bypass
confirmation. Normal briefings and explanations remain ordinary replies.

## 5. Scripts Spec

Skills format and judge. Scripts fetch facts. Deterministic steps become code.

- `scripts/weather.py [--city X | --lat LAT --lon LON] [--aqi-source auto|open-meteo|waqi|off] [--refresh | --no-cache] [--json]`
  Free sources only (paid providers excluded: no AccuWeather, QWeather, or CaiYun). Weather plus model AQI from Open-Meteo (keyless, no signup); ground-station AQI cross-check from WAQI when `WAQI_TOKEN` is set (free token at `aqicn.org/data-platform/token/`). Output: rain yes/no, temp, one-line advice, AQI with health level. City comes from profile, overridable by flag.
  Reviewed and improved 2026-10-09: independent geocoding/weather/AQI caches,
  parallel requests, bounded same-day stale fallback, daily rain/snow logic,
  visible partial failures, safe errors, and compact default output. WAQI
  remains live-only; its pollutant values are indexes, not concentrations.
  See `docs/weather-pipeline.md` for measurements, terms, and output changes.
- `scripts/news.py --backfill | --status | --show DATE | --ack DATE --expect REPORT_ID --session NAME`
  Managed mode reads confirmed profile timezone/country/optional feed config.
  Collection returns a manifest; read-only status/show never fetch. Acknowledgement
  is explicit, idempotent, and rejects stale IDs or empty sections. See §3.7.
  Stateless `--since YYYY-MM-DD --until YYYY-MM-DD` remains available, with a
  maximum seven-day window and explicit configuration. Concurrent RSS + HN, HTTP cache and
  35-day SQLite headline archive, offline reads, persistent 429 cooldowns,
  timezone-correct dating, conservative grouping and AI filtering. Default:
  four stories per section/day and one link; compact JSON or Markdown.
  `--country` adds user-confirmed national feeds alongside AI/world sections.
  GDELT and keyed NewsAPI are opt-in AI discovery, not automatic dependencies.
  Built/reviewed 2026-10-09; controlled equal-story JSON was 74% smaller. Managed
  synthetic manifests were about 93% smaller than printing all reports, retaining
  all 84 fixture stories; completed repeats made no provider calls. These measure
  retrieval/detail gating, not reply quality or live availability. See
  `docs/news-pipeline.md` for evidence and limits.
- `scripts/secretary_calendar.py --days N [--source auto|betterbird|custom] [--json]`
  Queries SQLite only: approved custom and imported events, bounded date/page
  output, time/place/prep warnings. `--add`, `--update`, `--cancel` manage
  custom/approved events. `--sync-betterbird` or secretary-prepared
  `--import-json` stages original imports; `--pending`, `--show`, `--approve`,
  `--reject` handle review. `--history` exposes revision history on demand;
  `--migrate-md` explicitly migrates old Markdown without editing it. Stdlib
  only. Common Betterbird recurrence rules expand into reviewable occurrences.
  Native provider auth and ICS file parsing are not implemented; unsupported
  rules need expanded exports. See `docs/calendar-pipeline.md`.
- `scripts/state.py --check [--json] | --mark-gm | --mark-gn` (+ `--rebuild`, `--tokens PATH`)
  Reads/writes `state.json` and daily index. Detects already-used (refuses
  double-mark unless `--force`) and missed days. `--mark-* --session NAME
  [--answer-file P | --answer-stdin]` saves the verbatim agent reply to
  `daily/YYYY-MM-DD.gm|gn.md` with size/token stats. `--check` also reports
  inbox pressure, stale projects, and 7d/30d answer re-read cost so agents
  open snapshots only on demand. `--tokens` audits one file.
  Hardened 2026-10-09: paged summaries, timezone dates, full-history missed counts,
  accurate 30-day costs, cached snapshot statistics, source validation, and writer
  protection. Mark/tokens/rebuild support compact JSON. Synthetic state summaries
  were about 92% smaller than an unbounded equivalent; snapshot reads fell from
  120 to 30 cold, with zero warm reads. This proves fixture behavior, not model
  judgment. See `docs/state-pipeline.md`.
- `scripts/projects.mjs list|discover|status|ls|read|jobs|batch|write|exec`
  Local/relay access through the private registry. Bounded reads and read-only
  batches reuse connections. Writes require exact scope, confirmation, and current
  hash; shared aliases must not duplicate file mutations. Execution additionally
  requires authorization and `allow_exec: true`. Unknown outcomes are not replayed.
  Pairing credentials stay in encrypted request headers, never the registry or
  relay routing URLs. Follow the guide's owner-authorized re-pairing advice for
  credentials used in obsolete early probes when applicable; never rotate silently.
  See `docs/project-access.md`.

All scripts: read config from env or user-local config, never hard-code keys. Clear error when key or login is missing.

## 6. Exploration Spikes (historical outcomes)

The outcomes below are preserved from the earlier plan. Original standalone
spike/remote-validation reports are not present in the current directory; that
does not prove the recorded tests did not happen. Current contracts live in the
pipeline/project-access guides. This inspection reran synthetic tests, not live
provider/server probes.

### Spike A: Teams calendar access — recorded done 2026-10-09

Historical result: 3 methods. (1) Custom-only via `custom_schedule.md` + `--add`.
(2) External + custom as a walkthrough-only option (a Graph implementation
was tried live, then removed: the tenant blocks app sign-ins via
Conditional Access). (3) Betterbird/Thunderbird local cache (incl. Owl for
Exchange), live-tested on a Flatpak profile while the app ran. Script is
stdlib-only; `scripts/calendar.py` was renamed (stdlib clash) and then
generalized from Teams-only to `scripts/secretary_calendar.py`.
(the old name shadows Python's stdlib `calendar` module).

Storage/review upgrade (2026-10-09): all active calendars use SQLite;
Betterbird is an explicit staging adapter, not a runtime merge. Imports are
reviewed conversationally before display. See `docs/calendar-pipeline.md`.

### Spike B: News source, user trusts GroundNews

Test: can agent fetch GroundNews directly or via API? Is it blocked without browser or login? Compare agent-friendly options: GDELT, NewsAPI, BBC/Reuters RSS, Hacker News for AI news. Likely result: daily fetch from RSS/API plus GroundNews for bias check. Report must name final default plus fallback.

Initial outcome (2026-10-09, verified live): GroundNews has no public API; homepage and article pages fetch fine without login but bias/factuality/ownership data is paywalled and search is JS-rendered, so GroundNews is link-out only for manual bias checks. Initial default = 11-feed RSS mesh + HN + GDELT. Reuters direct RSS returned 404; Guardian API excluded by owner decision (no key wanted).

Review upgrade (same day): ten-feed RSS + HN, cached and archived; the stale
AP mirror was removed and DW's RDF parser fixed. GDELT is opt-in; the daily path
uses bounded HTTP/headline caching, not an endless provider retry loop. Add
confirmed country feeds separately
(US/GB/CA/AU/CN bundled; others user-local). Headlines are not neutral rewrites,
and publisher counts do not prove independence. See `docs/news-pipeline.md`.

### Spike C: Remote HPC projects (biggest risk)

Regular users: local folder paths given at init, simple.

Original question: projects may be on remote HPC/servers behind ZScaler; relay
file/shell access needed investigation. The chosen implemented method is local
secretary plus paired private relay. SSH or hub hosting remains a future option,
not a prerequisite for the current adapter.

Test: list servers, OS, SSH layout, can servers SSH to each other, does relay expose files and shell, does ZScaler allow SSH keys. Compare: (1) local secretary plus relay reads, (2) direct SSH/SFTP with keys, (3) hub server hosting GoodMorning and reaching all others. Pick cheapest method that still allows read plus write-back so other agents stay in sync. Report must cover auth, network, and write-back path.

Initial live outcome (2026-10-09): both paired Ubuntu servers were reachable
through private relay with ZScaler disabled and without SSH. Project file
reads and temporary write-back passed in all four host/project combinations;
interactive terminal input/output, command job status, scheduled-task reads,
and GPU process visibility passed on both hosts. Cross-host temporary file
reads confirmed one shared workspace. All probe files and terminals were
removed; existing jobs and tasks were left untouched. The spike chose local
secretary plus private relay first. At that point a reusable adapter and registry
were still needed; the follow-up below implemented them. SSH/hub topology and
long-running job supervision remain untested.

Adapter follow-up (same day): `scripts/projects.mjs` now handles local/relay
aliases, bounded file/job reads, read-only batches, explicit short-command
authorization, and hash-checked atomic document writes with shared-storage
coordination. Relay source is unchanged upstream 2.2.0 with a commit/hash pin,
not extracted minified code. Live tests passed on both remote 2.1.1 hosts;
cross-host competing writes produced one success and one conflict. Final task
summaries were 91.4% smaller than raw responses (character-based estimate).
Private registry setup still requires confirmed aliases and write scopes;
the follow-up recorded no personal initialization. Current limits/instructions
are in `docs/project-access.md`; the earlier standalone validation report is not
in this source tree. These historical live results were not rerun in this update.

## 7. Templates Must Be Clean

/gm, /gn, /eureka, and /secretary replies prioritize clean formatting and clarity. Apply the user's customised tone throughout every reply, including explanations, questions, reminders, confirmations, and errors, not just greetings and closings. Express tone subtly if it would obscure important information; warmth is the default, not an override of the user's preference. Use natural sentences and helpful explanations; there is no reply token budget or sentence limit. Avoid exaggerated praise or pressure and retain sources and warnings. Internal script output and stored records remain compact.

## 8. Review Step

After skills plus scripts draft, review together:

- Is each rule reasonable and runnable?
- Any missing, unconsidered, or useful non-redundant use?
- Keep high usefulness, low redundancy.

The scoped final acceptance review is complete for the supported deployment.
Component/contract tests and the authorized walkthrough do not guarantee model
judgment, future provider availability or compatibility with every host/client.
Deployment-specific checks remain explicit owner steps in `docs/deployment.md`.

## 9. Build Phases for Other Agents

Split work like this:

- Phase A: repo skeleton, `.gitignore`, templates, `config.example.md`. Accept: general code only, no personal data, user-local path ignored. Setup files completed 2026-10-09: empty profile/project templates and configuration reference added; existing readers and calendar initialization verified on temporary fake data. Ignore rules verified; no user-local data initialized.
- Phase B: state, duplicate prevention, missed dates, and answer snapshots. Implemented and synthetic-tested 2026-10-09, including paged full-history checks, profile timezone, accurate 30-day costs, metadata caching, source validation, JSON responses, and cooperating-writer safety. See `tests/test_state.py`, `tests/benchmark_state_news.py`, and `docs/state-pipeline.md`.
- Phase C: `weather.py` free-only (Open-Meteo weather plus CAMS AQI, optional
  WAQI station cross-check) and adjustable city. Built and reviewed 2026-10-09:
  cache, parallel fetch, freshness/failure handling, daily rain/snow, compact
  output, and 28 focused tests. Live weather/model checks passed in three cities;
  real WAQI remains unverified. Init asks for a qualified city and offers WAQI
  registration; "I moved" changes the profile and therefore the lookup key.
- Phase D: Spike A (Teams) then `secretary_calendar.py`. SQLite/review upgrade
  built 2026-10-09: custom events, staged external imports, AI review, source
  changes/cancellations, history, migration, and compact queries tested on
  synthetic data. Original Betterbird reader was live-tested; new staging
  workflow still needs a user-authorized end-to-end live check. Common recurrence
  expansion now has fixture and read-only live checks. Native provider auth and
  ICS file parsing remain future work.
- Phase E: news retrieval plus bounded backfill and explicit delivery tracking. Implemented 2026-10-09: separate report ledger, missing/partial/collected/delivered states, read-only status/show, exact-ID acknowledgements, retry caps/cooldowns, historical windows, warnings, scope isolation, and repeat-fetch avoidance. Backfill uses the ledger, not Markdown headings. New managed behavior is synthetic-tested in `tests/test_news_reports.py`; earlier feed spike results are historical. See `docs/news-pipeline.md`.
- Phase F: project registry and local/relay read/write-back. Implemented: pinned-source transport, bounded reads/batches/job summaries, exact scopes, explicit execution permission, hash-checked writes, and shared-storage locks. Historical remote live results are preserved in §6; current verification is synthetic. Personal registry setup and future host/version compatibility checks require consent. See `docs/project-access.md` and the project/relay tests.
- Phase G: all four skills and same-session slash-command wrappers are implemented and discoverable. Metadata, references and routing are tested; an authorized sandbox walkthrough and owner feedback exercised all four workflows.
- Phase H: all four reply templates implemented, with a deterministic fake-data morning/night record/snapshot/delivery dry run. Clean formatting and clarity come first; customised tone applies throughout, with warmth only as the default. No sentence/token targets. Sources, warnings, and task state are tested; descriptive sizes are not quality scores. Real-user readability/tone review remains open.
- Phase I: scoped acceptance/finalization completed; confirmed walkthrough failures were repaired, regressions rerun and private sandbox records removed. Production integration boundaries remain documented.

Current commands: `python -m unittest discover -s tests -q` and
`node --test tests/test_projects.mjs`. Both passed in current validation: 244 Python
tests and 26 Node tests. Optional experiments live in `tests/benchmark_*.py` and
`tests/benchmark_projects.mjs`; measurements do not impose reply-length budgets.

## 10. Open Questions for Owner

- Weather providers: resolved free-only (Open-Meteo plus WAQI). AccuWeather, QWeather, CaiYun excluded as paid.
- ~~Teams login allowed for Graph API?~~ No — tenant blocks app sign-ins;
  Betterbird cache staging is available, other imports go through the secretary.
- GroundNews account or API key available? Answered 2026-10-09: no public API exists; account not needed (link-out only).
- Personal setup: confirm city/timezone, national-news country, tone/work habits,
  project aliases/paths, exact write scopes, and the calendar method. Templates
  remain general; do not infer these settings from source examples.
  Invite optional current occupations and expertise/fields for relevant topics
  and explanations, without making disclosure a setup requirement.
- Optional validation: choose WAQI and/or an authorized Betterbird source before
  live verification; supply credentials privately, never in chat/source records.
- SSH/hub hosting and long-job supervision are optional future design decisions,
  not blockers for the implemented local-plus-relay method.

## 11. Deployment-specific owner steps

1. Install the public bundle or committed source in the selected client/workspace.
2. Run language-first `/secretary` setup with confirmed storage/provider/project
   permissions; never substitute walkthrough preferences for a real owner profile.
3. Recheck the selected client/host and optional providers. Automated tests and
   owner-approved examples do not guarantee future generated prose or feed quality.
4. **Chosen live integrations:** verify optional WAQI and upgraded Betterbird
   staging/review with explicit authorization. Historical weather/remote results
   do not replace compatibility checks for the user's selected account/host/version.
5. **Owner-confirmed personal setup:** initialize or amend profile/registry only
   when requested; retain existing records and confirm exact scopes.

Deferred, not required for current core acceptance: native calendar provider
authentication/sync, ICS file parsing, arbitrary recurrence rules, external-calendar
write-back, SSH/hub deployment, and long-running job supervision. Scheduled news
collection also requires separate authorization; no scheduler is installed by
these source changes. Original standalone spike reports are absent; this plan
preserves recorded history and links to the current operational guides instead
of inventing replacement validation evidence.
