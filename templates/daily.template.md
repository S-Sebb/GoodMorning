# daily/YYYY-MM-DD.md (user-local, git-ignored)

One file per day. Short lines, fixed headings (lowercase match is enough:
`state.py` detects headings case-insensitively). Full verbatim agent
replies live in sibling native snapshots `YYYY-MM-DD.gm.json` / `.gn.json` — this
file holds trimmed one-liners only, so the default read stays cheap.

```text
# YYYY-MM-DD

- gm: yes (session NAME) | answer: daily/YYYY-MM-DD.gm.json
- gn: no

## weather
- overcast, 12/18C, rain: yes — umbrella. AQI 27 good.

## news
- YYYY-MM-DD: AI/world/national counts; top: ...; gaps or source warnings: ...

## schedule
- 09:30-10:30 TA RSM338 @ RSM338 — pack slides tonight.

## must-do
- [ ] TA RSM338 9:30
- [ ] Send group slides by 22:00

## nice-to-do
- [ ] Gym 18:00 if energy left

## flexible
- [ ] Upload the reimbursement receipts
```

(`/gn` later ticks boxes off and appends `## feedback` / `## progress` —
those sections never exist before the first `/gn`, and no box is ever
newly checked by `/gm`.) Earlier user-confirmed completions are preserved.

Lifecycle rules:

- `/gm` writes run lines, weather/news/schedule, and must-do + nice-to-do + flexible
  with every box unchecked (`[ ]`). Nothing is done in the morning, so a
  new checked box inferred by `/gm` is a bug; never reset existing completions.
- A repeat `/gm` identifies the saved session and stops, never re-fetches or
  automatically opens the `.gm.json` snapshot. `state.py` already refuses
  the double-mark and points at the first session.
- `/gn` ticks boxes off (`[x]`) and appends `## feedback` / `## progress`.
- In-thread amendments: talking to the agent inside a `/gm` or `/gn` thread
  edits the saved files. If the user adjusts a task, ticks something off
  early, or changes a plan, the agent updates today's daily file in place
  and confirms what changed. Dated events additionally go through the
  custom-calendar rule (quote back, ask, then `--add`; never delete or edit
   silently). Future appointments live in `calendar.sqlite`; untimed task dates
  stay in their saved task/project records, not invented calendar appointments.
  They are picked up by that day's own `/gm`. The `.gm.json`/`.gn.json` snapshots
  stay as the original briefing; re-save them (`--mark --force`) only if
   the user asks for a full re-render.
- External calendar imports must pass the review queue before appearing in
  a briefing. Query `secretary_calendar.py --days N`; do not merge raw imports
  or bulk-read the database. Follow `docs/calendar-pipeline.md` for review.
- `- gm:` / `- gn:` lines are machine-read (`state.py --rebuild`
  recovers run state + sessions from them). Keep the `session NAME` and
  `| answer: path` parts verbatim; use `no` until the run happens.
- Sections are optional but keep their headings when present: `weather`,
  `news`, `schedule`, `must-do`, `nice-to-do`, `flexible`, `feedback`/`progress`. The
   sections drive presence flags, not proof of completed retrieval. News
   backfill/delivery lives in `news_reports.sqlite`: use `news.py --status`,
   `--backfill`, `--show`, and explicit `--ack` after presenting the report.
   News dates refer to publication/report dates, not the greeting's date.
- Flexible task titles dated today join the checklist unchecked. Exact wording
  deduplicates across the three task groups; existing priority and completion
  survive. Future/undated flexible rows remain in the briefing, not today's list.
- Keep each bullet to one line. Detail belongs in the `.gm.json`/`.gn.json`
  snapshots, not here.
Use `daily.py --show` and `--amend --expect HASH` for routine section/task edits;
see `docs/workflow-helpers.md`. Do not rewrite the entire file through the agent.
