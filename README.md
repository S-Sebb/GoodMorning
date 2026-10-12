# GoodMorning

Browser-based AI secretary, helper commands, and templates. Installed personal runtime data belongs in
`~/.local/share/GoodMorning/secretary/`, outside the skill package. An explicitly
selected checkout runtime remains git-ignored. Requires Python 3.9+. Bounded setup, state and managed news
backfill use Linux file locks; project access also requires Linux and Node.js
22.18+. No npm install is needed. This is an agent-assisted project, not an
autonomous background service. See [deployment](docs/deployment.md) for manual
file copying, updates and supported integration boundaries.

Start with [setup and configuration](config.example.md).

Public multi-user deployment uses the [website security boundary](docs/website-security.md):
SSH-only accounts, HTTPS login, encrypted volumes and isolated agent homes.

New gm/gn editions use [validated browser-native JSON](docs/briefing-format.md),
without Markdown or presentation copies. The [private browser viewer](docs/browser-delivery.md)
renders saved briefings as HTML with inline sections and clickable sources;
its live mode offers a seven-day archive and explicit generation in a dedicated OpenChamber
session, with browser questions and permissions. New browser jobs publish sections
top-down with individual loading placeholders; finished sections are readable while
later ones are prepared. Previews remain explicitly unfinished until the final save.
Public deployment adds authenticated HTTPS and isolated encrypted accounts.
Briefing days roll over at 04:00 in each
user's configured timezone; all behavior lives in this package's source.
Live pages render on demand with shared cacheable assets, bounded memory caches
and deduplicated publisher images, rather than duplicating webpages/resources daily.
Briefings are delivered on their browser pages, not as inline OpenCode image cards.
Schedule and Tomorrow show timed events followed by a flexible schedule for
untimed work. No appointments does not imply a free day; dated plans stay visible
in the schedule instead of being buried in reminders.
No image-delivery plugin is required.
The website offers English and Simplified Chinese, with one account-wide setting
shared by Morning, Night and Secretary, including other devices. New agent requests
use that setting; active requests finish in their starting language. Saved content
and existing local preferences are not translated or rewritten. Website initialization
therefore skips the separate reply-language question. For local skill use, the first
setup question still confirms the secretary's reply language independently of news.
The Secretary page explains when to choose Secretary, To-do, Eureka or Initialize.
The website uses beta versions (`0.minor.patch`). A blue update arrow, or a
checkmark when current, opens bilingual patch notes with a past-version sidebar.
Each new version appears automatically until dismissed; that preference is
shared across the account's devices. See the [patch-note guide](docs/server-deployment.md#patch-note-procedure).
Authenticated pages also share an active-work reminder across Morning, Night and
Secretary tabs. It links to work that is running, waiting for an answer or queued;
idle work disappears. Closing a tab never cancels a pending question.
One self-contained `goodmorning` skill is copied only into
`~/.agents/skills/goodmorning/`. The inactive source lives in
`skill-source/goodmorning.md`; this checkout registers no skills or commands.
Workflow instructions are in `docs/workflows/`. Use `/gm`, `/gn`, `/eureka`, `/todo`, or
`/secretary` as plain workflow requests, not custom slash commands, or ask in
natural language. Start with `/secretary` to confirm setup before
creating personal records. See [agent workflows](docs/agent-usage.md).
`/todo` records the user's wording without questions, planning, or doing the task.
Clarification or a more detailed explanation happens only when explicitly requested.
Initialization now separates saved local preferences from optional verification;
see [the staged setup workflow](docs/initialization.md). Failed integrations stay
pending rather than restarting setup or launching code repairs.

| Task | Command | Guidance |
|---|---|---|
| Setup preflight | `python scripts/goodmorning.py setup --secretary-dir RUNTIME` | [Initialization](docs/initialization.md) |
| Weather/AQI | `python scripts/goodmorning.py weather` | [Weather](docs/weather-pipeline.md) |
| News backfill | `python scripts/goodmorning.py news --backfill` | [News and delivery tracking](docs/news-pipeline.md) |
| Schedule | `python scripts/goodmorning.py calendar --days 3` | [Calendar](docs/calendar-pipeline.md) |
| State and missed runs | `python scripts/goodmorning.py state --check --json` | [State](docs/state-pipeline.md) |
| Capture and active memory | `python scripts/goodmorning.py inbox --secretary-dir RUNTIME --list` | [Inbox](docs/inbox-pipeline.md) |
| Workflow context / fast capture | `python scripts/goodmorning.py workflow --secretary-dir RUNTIME --prepare gm` | [Helpers](docs/workflow-helpers.md) |
| Safe daily amendments | `python scripts/goodmorning.py daily --secretary-dir RUNTIME --date DATE --show` | [Helpers](docs/workflow-helpers.md) |
| Local/remote projects | `node scripts/projects.mjs --help` | [Project access](docs/project-access.md) |

Run from the repository or installed skill root. Replace example settings with confirmed values.
Use compact output by default; open only the guide needed for an operation.
Calendar changes need confirmation, imports need review, and project writes need
an authorized target and current hash.

News collection is not delivery: read saved reports with `--show`, present them,
then acknowledge their exact IDs with `--ack`. Empty sections remain unresolved.
Default news now requires assistant editorial review of collected candidates with
source citations and importance reasons; keyword scores are only shortlist aids.
Optional `--latest` keeps current developments separately dated from yesterday.
Secretary replies use a materiality gate: routine diagnostics and non-critical
disclaimers stay internal. Only actionable or materially important warnings appear.
That gate is not a brevity filter: personality and useful explanations belong
within clearly divided sections, with optional brief takeaways and a warm closing.
Avoid long introductions, repeated summaries or routine disclaimers.
See [secretary voice](docs/reply-voice.md): headings/rules, ordered weather parts,
source-based news summaries and calendar timetables make replies easy to scan.
State summaries are paged; do not bulk-read the index or answer snapshots.
Inbox memory uses SQLite, stable IDs, bounded current-state queries, idempotent
capture and revision-checked updates. Save material inputs and decisions, not
every exchange. Original wording/history stays separate from normal model context.
No Markdown inbox or calendar migration is supported.

Reply shapes are in `templates/*.reply.template.md`; shared skill rules are in
`docs/core-rules.md`. The expanded `docs/skill-rules.md` loads only for edge cases.
User-facing replies prioritize clean formatting and clarity,
with the user's customised tone throughout, not just greetings and closings.
There are no sentence limits or token budgets for replies. Internal records and
script output stay compact. Validate with `python -m unittest discover -s tests -q`
and measure synthetic reply size with `python tests/benchmarks/reply_templates.py`.
Workflow preparation/capture and daily bookkeeping are deterministic helpers;
editorial judgment, prioritization, clarification and consent remain with the agent.
Measure context savings with `python tests/benchmarks/workflow.py`; see the
[workflow audit](docs/workflow-audit.md) for decisions and boundaries.

To set up the skill, copy `skill-source/goodmorning.md` as `SKILL.md` into
`~/.agents/skills/goodmorning/`, with the public directories listed in
[deployment](docs/deployment.md). No pip installation or package builder is needed.
See [manual deployment](docs/deployment.md) for the file layout and safe updates.
Do not copy profiles, caches, credentials, or sandbox fixtures. Personal records
stay at `~/.local/share/GoodMorning/secretary/` (or the explicitly selected
`SECRETARY_DIR`). Copying files does not initialize personal records.

## Project layout

- `src/goodmorning/`: Python application code, grouped by responsibility.
- `scripts/`: only the Python and Node.js command entry points.
- `assets/web/`: browser styles, JavaScript, templates, and fonts.
- `integrations/projects/`: local/relay project adapter and its internal helper.
- `vendor/`: unchanged third-party relay source, license, and integrity manifest.
- `requirements/`: optional browser-rendering dependencies.
- `tests/test_*.py`, `tests/test_projects.mjs`: automated unit/contract tests.
- `tests/browser/`, `tests/benchmarks/`: opt-in browser and performance experiments.
- `deploy/`: service and HTTPS deployment templates.
- `docs/`, `skill-source/`, `templates/`: instructions, inactive skill entry, and reply guides.

See [structure and command migration](docs/project-structure.md). The original
design plan is preserved in `docs/history/plan.md`; it is not current setup guidance.
