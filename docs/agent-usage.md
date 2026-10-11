# Secretary agent usage

The self-contained skill lives only in `~/.agents/skills/goodmorning/` and loads
by the `goodmorning` ID. The repository keeps an inactive source at
`skill-source/goodmorning.md`, ready to copy as `SKILL.md` without edits; the
repository registers no project skills or command wrappers.
`/gm`, `/gn`, `/eureka`, `/todo`, and `/secretary` are plain workflow requests, not registered
slash commands. Natural-language requests work too. Keep the current session and
model. The five workflows live in `docs/workflows/` and load only when requested.
Installing the skill does not initialize personal records.

Start with `/secretary` for owner-confirmed setup. The loaded skill and
`docs/core-rules.md` and the requested workflow are the execution instructions;
`docs/skill-rules.md` is an expanded reference. The sections below are a
quick overview. Reply shapes live in `templates/*.reply.template.md`.
Setup uses [staged initialization](initialization.md): reuse answers, save only
authorized local records, then run selected checks once under a shared elapsed
budget. Unsupported/failed optional integrations do not restart preferences or
authorize code development. Event import is a separate follow-up.

## Shared rules

- Ask `secretary_name` first during new setup, before other preferences, then for local use ask `secretary_language` second and use the explicit choice for all replies, OpenChamber conversation titles, and
   interactive questions. For browser chats skip the language question and follow the website language switch. Refer to yourself by the saved `secretary_name` when present. News language and country remain independent. Confirm
   missing required settings without resetting an existing profile.

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
   do not infer expertise from job titles or require optional context for readiness.
- Keep personal records outside the installed skill in the selected runtime. Never put credentials
  in records. Scripts fetch facts; the agent summarizes and asks for decisions.
- Read compact script output and today's daily record. Open detailed guides only
  for the operation needed. Do not bulk-read answer snapshots or provider data.
- Ask about ambiguous requirements. Record reported progress, not invented progress.
- Except record-only `/todo` capture, when a conversation suggests a scheduled event, quote its date, time,
  timezone, title, and place. Ask for missing details and confirmation before
  adding, changing, or cancelling it. Follow `docs/calendar-pipeline.md`.
- Prioritize clean formatting and clarity, then express the user's customised
  tone throughout every reply, including explanations, questions, and errors.
  Tone is not limited to greetings or closings; keep it subtle if it would obscure
  facts. Warmth is the default, not an override of the user's preference.
  Explain useful context and advice; use paragraphs or bullets as appropriate.
  Follow `reply-voice.md`: keep the agreed persona within useful section content.
  No extra framing; a brief grounded closing is optional. Use headings and horizontal rules,
  ordered weather parts, source-summary news bullets and calendar timetables.
  Reserve bold for key findings or urgent warnings, never section divisions.
  Keep internal reads and daily records compact, not the user's conversation.
  Preserve warnings, sources, stale markers and unresolved gaps internally.
  Apply the shared materiality gate: non-critical disclaimers, healthy retrieval,
  retry/delivery bookkeeping, empty queues and unsolicited news backlog never
  appear in normal messages. Show only concise issues that affect plans, safety,
  requested information or a needed decision. Keep the user's tone and work habits.

## `/gm`: morning briefing

1. Say good morning. Run `python scripts/goodmorning.py workflow --prepare gm` once for local context. If today already has
   a briefing, identify its session and use the saved record; do not fetch again.
   Remind the user about missed morning/night runs, oldest first. When proceeding
   with a new briefing, rename this conversation to `GoodMorning YYYY-MM-DD`
   in `secretary_language` for the selected daily date (see `docs/skill-rules.md`).
2. Run `scripts/goodmorning.py weather` once with the saved city. Report rain yes/no/unknown,
   umbrella/boots advice, temperature, AQI health level, source, and freshness.
3. Run `python scripts/goodmorning.py news --backfill` using the confirmed profile. Read its compact
   manifest, then `--show DATE` only for collected reports needing delivery.
   Separate yesterday's AI, world, and national news; preserve warnings and
   unresolved gaps. Already delivered reports need no repeat unless requested.
   After presenting a report, use `--ack DATE --expect REPORT_ID --session NAME`.
   Never acknowledge a draft or empty/partial report. Historical windows are
   explicit (`--ending DATE`); do not loop on exhausted gaps. News ledger dates
   refer to the news day, not the morning briefing's date.
4. Query `python scripts/goodmorning.py calendar --days N` for approved events. Surface pending
   reviews. Inspect relevant event details before reporting preparation needs.
5. Read relevant project records. Build weekly tasks with priorities, confirmed
   deadlines, and estimates where supported. Pick today's must-do and nice-to-do
    tasks. Add unchecked TODOs for pending idea clarification in the reply and
    daily task list.
6. Amend the daily record using `python scripts/goodmorning.py daily --amend --expect HASH`, with new tasks unchecked
   and earlier completions preserved; no full-file model rewrite.
   Save the verbatim reply using `python scripts/goodmorning.py state --mark-gm --session NAME
   --answer-file PATH` or `--answer-stdin`.
   Prefer `--json` for state commands. Saving/marking a morning reply does not
   acknowledge news delivery; these are separate operations.

## `/gn`: night summary

1. Use `python scripts/goodmorning.py workflow --prepare gn` for duplicate/missed runs, tasks and preferences.
   When proceeding with a new summary, rename this conversation to
   `GoodNight YYYY-MM-DD` in `secretary_language` for the selected daily date.
2. Use the returned task IDs and ask what the user completed. Mark only confirmed
   completions. Save feedback and actual progress.
3. Assess project progress from the user's report, suggest next steps, and update
    authorized project records. When Betterbird is the confirmed calendar source,
    stage imports on every run with review before display; if locked ask to close
    and retry. Remind about tomorrow's schedule and ask focused
    questions about pending idea clarification; deferral does not block the summary.
4. Say good night in the agreed tone, appropriate to the time. Save the daily
   record and verbatim reply with `python scripts/goodmorning.py state --mark-gn --session NAME` plus an
   answer input. Do not overwrite earlier snapshots without an explicit request.

## `/eureka`: idea capture

1. Once the raw idea is known (if none was supplied, ask first), rename this
   conversation to `Eureka SUMMARY` in `secretary_language` with a very short idea summary
   (see `docs/skill-rules.md`). Save the raw idea and any supplied details
   with `python scripts/goodmorning.py workflow --capture eureka` as pending in `secretary/inbox.sqlite`; note remaining ambiguity and
    confirm it was saved, then stop. Do not research, implement, delegate, change
    project/work files, or offer calendar changes. Action verbs inside the captured
    idea are not instructions to execute it.
2. Leave it pending by default, without a now/later question. Invite optional
   clarification via `Clarify`; the idea can also stay as is. Accept details
   directly in the initial request, a follow-up, or
    `/secretary` without starting discussion. Ask clarification questions only on
    an explicit discussion request; details alone do not request it. Preserve
   the raw idea and retain details with its entry, without duplicating it. Confirm
    the clarified meaning; organization needs a separate explicit request and
    never implies execution of the idea.
3. For ideas left pending, add a clarification TODO at the next `/gm`, ask a
   clarification question at `/gn`, or include a reminder at `/secretary`. Keep reminding
   until the user confirms and the idea is organized.

## `/todo`: TODO capture

1. Rename the conversation to `Todo SUMMARY` in `secretary_language` using a very
   short summary. Save the exact TODO with the local timestamp as a pending
   `kind: "todo"` inbox entry via `python scripts/goodmorning.py workflow --capture todo`; preserve multiline wording with JSON. Verify the
   save receipt and confirm briefly. Inbox-only changes need no state rebuild.
2. Record only: no default clarification questions, project/deadline questions,
   planning, research, delegation, task execution, or calendar changes. Save
   follow-up details without treating them as a request for discussion.
3. Discuss only on `Clarify`, an equivalent explicit request, or a request for a
   more detailed explanation. Discussion does not authorize execution. Later
   workflows surface open TODOs as tasks/reminders, not automatic clarification
   questions; only user-confirmed completion permits marking them done.
   Missing-input/setup/credential safety and failed-save rules still apply.

## `/secretary`: general work

Rename this conversation to `Secretary SUMMARY` in `secretary_language` with a simple summary, no date
(see `docs/skill-rules.md`). Handle setup, records, calendar review, questions, and confirmed plan changes.
Read relevant project files to understand context. Use `docs/project-access.md`
for authorized local/remote access and write-back; preserve unrelated work.
Save details about an existing idea without requiring `Clarify` or `/eureka`.
Start discussion only on an explicit request; do not repeat supplied answers.
Save details before asking, even if their target idea is unclear; follow shared
inbox rules for unassigned input and remind about pending clarification.
Save project progress reports and proposed TODO/goal changes immediately in the
configured inbox, including updates after meetings or discussions. Preserve the
user's wording before asking questions, note what requires clarification, and
catch up from relevant project records. Pending capture does not change the
confirmed plan or authorize external writes. Keep unanswered questions with the
same entry: the next `/gm` includes a clarification TODO, `/gn` asks clarification
questions, and later `/secretary` calls remind the user. Reuse answers and avoid
duplicate notes/tasks; resolve the entry only after clarification and authorized
updates succeed. See the pending project-update workflow in `docs/skill-rules.md`.
Use `docs/inbox-pipeline.md` for stable IDs, idempotent capture and revision-checked
current-state updates. Save only material memory, not a conversation transcript.
Normal reads use `python scripts/goodmorning.py workflow --prepare secretary`, then only relevant filtered
active/current IDs; raw text/history is explicit. See `docs/workflow-helpers.md`.
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
python tests/benchmarks/reply_templates.py
```

The synthetic fixture demonstrates natural, supportive sentences while retaining
all three saved headlines, source links, stale warnings, preparation details, and
open tasks. Reply sizes are descriptive measurements, not limits or quality
scores. User-facing replies have no sentence or token target; clean formatting
and clarity take precedence, with customised tone throughout. The tests still
verify accuracy and workflow safeguards.
