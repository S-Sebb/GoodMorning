# Secretary agent usage

The four project skills live in `.opencode/skills/<name>/SKILL.md`; wrappers in
`.opencode/commands/` provide `/gm`, `/gn`, `/eureka`, and `/secretary` without
switching models or spawning another session. Skills can also be loaded directly
by ID. These definitions do not initialize personal records.

Start with `/secretary` for owner-confirmed setup. The loaded skill and
`docs/skill-rules.md` are the execution instructions; the sections below are a
quick overview. Reply shapes live in `templates/*.reply.template.md`.
Setup uses [staged initialization](initialization.md): reuse answers, save only
authorized local records, then run selected checks once under a shared elapsed
budget. Unsupported/failed optional integrations do not restart preferences or
authorize code development. Event import is a separate follow-up.

## Shared rules

- Ask `secretary_language` first during new setup, before other preferences, then
  use the explicit choice for all replies and interactive questions. News language
  and country remain independent. Older profiles do not require reinitialization.

- Prefer the session's interactive `question` tool (OpenChamber question UI) for
  setup, clarification, progress choices, and confirmations. Use relevant options,
  built-in custom answers, and multiple selection only where appropriate. Wait
  for explicit answers before mutations; dismissed/failed questions are not consent.
  If the tool cannot be used, ask in normal conversation and wait. Do not repeat
  already answered questions or use a question widget in place of the briefing.
- On first use, confirm setup answers and formats using `config.example.md` and
  `templates/profile.template.md`. Do not overwrite existing user-local files.
- Invite optional current-role and expertise/field context during setup. Use
  confirmed answers for relevant topics and explanations throughout the skills;
  do not infer expertise from job titles or force older profiles to reinitialize.
- Keep personal records under the git-ignored `secretary/`. Never put credentials
  in records. Scripts fetch facts; the agent summarizes and asks for decisions.
- Read compact script output and today's daily record. Open detailed guides only
  for the operation needed. Do not bulk-read answer snapshots or provider data.
- Ask about ambiguous requirements. Record reported progress, not invented progress.
- When any conversation suggests a scheduled event, quote its date, time,
  timezone, title, and place. Ask for missing details and confirmation before
  adding, changing, or cancelling it. Follow `docs/calendar-pipeline.md`.
- Prioritize clean formatting and clarity, then express the user's customised
  tone throughout every reply, including explanations, questions, and errors.
  Tone is not limited to greetings or closings; keep it subtle if it would obscure
  facts. Warmth is the default, not an override of the user's preference.
  Explain useful context and advice; use paragraphs or bullets as appropriate.
  Follow `reply-voice.md`: keep the agreed persona within useful section content.
  No extra framing or closing flavor text. Use headings and horizontal rules,
  ordered weather parts, source-summary news bullets and calendar timetables.
  Reserve bold for key findings or urgent warnings, never section divisions.
  Keep internal reads and daily records compact, not the user's conversation.
  Preserve warnings, sources, stale markers and unresolved gaps internally.
  Apply the shared materiality gate: non-critical disclaimers, healthy retrieval,
  retry/delivery bookkeeping, empty queues and unsolicited news backlog never
  appear in normal messages. Show only concise issues that affect plans, safety,
  requested information or a needed decision. Keep the user's tone and work habits.

## `/gm`: morning briefing

1. Say good morning. Run `python scripts/state.py --check`. If today already has
   a briefing, identify its session and use the saved record; do not fetch again.
   Remind the user about missed morning/night runs, oldest first.
2. Run `weather.py` once with the saved city. Report rain yes/no/unknown,
   umbrella/boots advice, temperature, AQI health level, source, and freshness.
3. Run `news.py --backfill` using the confirmed profile. Read its compact
   manifest, then `--show DATE` only for collected reports needing delivery.
   Separate yesterday's AI, world, and national news; preserve warnings and
   unresolved gaps. Already delivered reports need no repeat unless requested.
   After presenting a report, use `--ack DATE --expect REPORT_ID --session NAME`.
   Never acknowledge a draft or empty/partial report. Historical windows are
   explicit (`--ending DATE`); do not loop on exhausted gaps. News ledger dates
   refer to the news day, not the morning briefing's date.
4. Query `secretary_calendar.py --days N` for approved events. Surface pending
   reviews. Inspect relevant event details before reporting preparation needs.
5. Read relevant project records. Build weekly tasks with priorities, confirmed
   deadlines, and estimates where supported. Pick today's must-do and nice-to-do
   tasks. Remind about pending ideas.
6. Save concise output using `templates/daily.template.md`, with tasks unchecked.
   Save the verbatim reply using `state.py --mark-gm --session NAME
   --answer-file PATH` or `--answer-stdin`.
   Prefer `--json` for state commands. Saving/marking a morning reply does not
   acknowledge news delivery; these are separate operations.

## `/gn`: night summary

1. Check state for duplicate or missed runs and identify the previous session.
2. Read today's task lists and ask what the user completed. Mark only confirmed
   completions. Save feedback and actual progress.
3. Assess project progress from the user's report, suggest next steps, and update
   authorized project records. Remind about tomorrow's schedule and pending ideas.
4. Say good night in the agreed tone, appropriate to the time. Save the daily
   record and verbatim reply with `state.py --mark-gn --session NAME` plus an
   answer input. Do not overwrite earlier snapshots without an explicit request.

## `/eureka`: idea capture

1. Save the raw idea with a timestamp as pending in `secretary/inbox.md` and
   confirm it was saved. Offer calendar confirmation if it implies a dated event.
2. Ask whether to clarify now or later. If now, resolve ambiguity before writing
   the confirmed idea to project records or authorized work files.
3. If later, remind at today's `/gn`, otherwise the next `/gm`. Keep reminding
   until the user confirms and the idea is organized.

## `/secretary`: general work

Handle setup, records, calendar review, questions, and confirmed plan changes.
Read relevant project files to understand context. Use `docs/project-access.md`
for authorized local/remote access and write-back; preserve unrelated work.
When the user moves, confirm and update the profile city and region, then verify
the weather location. National news country remains an independent choice.

## In-thread amendments

Update today's daily record when the user changes tasks or reports progress.
Update project records as authorized. Future dated changes belong in the
calendar after confirmation. Keep answer snapshots as the original replies;
use `--force` only when the user requests a full replacement briefing.

## Validation

`tests/test_skills.py` checks metadata, relative references, command routing,
reply rendering, and a deterministic fake-data morning/night workflow. The dry
run preserves unchecked morning tasks, records only confirmed night completions,
saves exact snapshots, and keeps news collection separate from simulated delivery.
It uses temporary records, not real user data or live providers. This verifies
file/script contracts, not a model's end-to-end judgment or client UI behavior.

```bash
python -m unittest discover -s tests -p 'test_skills.py' -v
python tests/benchmark_reply_templates.py
```

The synthetic fixture demonstrates natural, supportive sentences while retaining
all three saved headlines, source links, stale warnings, preparation details, and
open tasks. Reply sizes are descriptive measurements, not limits or quality
scores. User-facing replies have no sentence or token target; clean formatting
and clarity take precedence, with customised tone throughout. The tests still
verify accuracy and workflow safeguards.
