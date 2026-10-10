# GoodMorning

AI secretary scripts and templates. Installed personal runtime data belongs in
`~/.local/share/GoodMorning/secretary/`, outside the skill package. An explicitly
selected checkout runtime remains git-ignored. Requires Python 3.9+. Bounded setup, state and managed news
backfill use Linux file locks; project access also requires Linux and Node.js
22.18+. No npm install is needed. This is an agent-assisted project, not an
autonomous background service. See [deployment](docs/deployment.md) for manual
file copying, updates and supported integration boundaries.

Start with [setup and configuration](config.example.md).
The first setup question confirms the secretary's reply language, independently
of news-source language. The explicit preference applies across all four workflows.
One self-contained `goodmorning` skill is copied only into
`~/.agents/skills/goodmorning/`. The inactive source lives in
`skill-source/goodmorning.md`; this checkout registers no skills or commands.
Workflow instructions are in `docs/workflows/`. Use `/gm`, `/gn`, `/eureka`, or
`/secretary` as plain workflow requests, not custom slash commands, or ask in
natural language. Start with `/secretary` to confirm setup before
creating personal records. See [agent workflows](docs/agent-usage.md).
Initialization now separates saved local preferences from optional verification;
see [the staged setup workflow](docs/initialization.md). Failed integrations stay
pending rather than restarting setup or launching code repairs.

| Task | Command | Guidance |
|---|---|---|
| Setup preflight | `python scripts/setup_check.py --secretary-dir secretary` | [Initialization](docs/initialization.md) |
| Weather/AQI | `python scripts/weather.py` | [Weather](docs/weather-pipeline.md) |
| News backfill | `python scripts/news.py --backfill` | [News and delivery tracking](docs/news-pipeline.md) |
| Schedule | `python scripts/secretary_calendar.py --days 3` | [Calendar](docs/calendar-pipeline.md) |
| State and missed runs | `python scripts/state.py --check --json` | [State](docs/state-pipeline.md) |
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

Reply shapes are in `templates/*.reply.template.md`; shared skill rules are in
`docs/skill-rules.md`. User-facing replies prioritize clean formatting and clarity,
with the user's customised tone throughout, not just greetings and closings.
There are no sentence limits or token budgets for replies. Internal records and
script output stay compact. Validate with `python -m unittest discover -s tests -q`
and measure synthetic reply size with `python tests/benchmark_reply_templates.py`.

To set up the skill, copy `skill-source/goodmorning.md` as `SKILL.md` into
`~/.agents/skills/goodmorning/`, alongside `scripts/`, `docs/`, `templates/`, and
`config.example.md`. No installer, package builder, or command wrappers are needed.
See [manual deployment](docs/deployment.md) for the file layout and safe updates.
Do not copy profiles, caches, credentials, or sandbox fixtures. Personal records
stay at `~/.local/share/GoodMorning/secretary/` (or the explicitly selected
`SECRETARY_DIR`). Copying files does not initialize personal records.
