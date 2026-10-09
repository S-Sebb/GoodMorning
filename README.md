# GoodMorning

AI secretary scripts and templates. Personal runtime data belongs in the
git-ignored `secretary/` directory. Requires Python 3.9+. Bounded setup, state and managed news
backfill use Linux file locks; project access also requires Linux and Node.js
22.18+. No npm install is needed. This is an agent-assisted project, not an
autonomous background service. See [deployment](docs/deployment.md) for packaging,
installation, upgrade and supported integration boundaries.

Start with [setup and configuration](config.example.md).
The first setup question confirms the secretary's reply language, independently
of news-source language. The explicit preference applies across all four skills.
Project skills and slash-command wrappers are in `.opencode/`: `/gm`, `/gn`,
`/eureka`, and `/secretary`. Start with `/secretary` to confirm setup before
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

Run from the repository root. Replace example settings with confirmed values.
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

Build a private-data-free deployment bundle with:

```bash
python scripts/package_release.py --output dist/GoodMorning-deploy.zip
```

The allowlisted ZIP includes a per-file manifest and an adjacent SHA-256 checksum.
Do not deploy profiles, caches or sandbox fixtures. No real setup is performed by
validation or packaging; the owner initializes after installation.
