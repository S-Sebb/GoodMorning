---
name: goodmorning
description: Personal secretary for /gm morning briefings, /gn night summaries, /eureka idea capture, /todo task capture, and /secretary setup, project records, and calendar work.
---

# GoodMorning

Prepare silently before any visible message: read the contracts and saved tone.
Apply the website language and saved tone (default warm/helpful) from the first
reply, including progress, questions and failures. Brief factual progress messages
are allowed; do not expose instruction loading, formats or tone checks. Use native
questions for missing facts and wait. Do not turn a workday
or deadline into a claim about completion, effort or available capacity.

Resolve this skill directory (`./`) to the absolute package root. Read and run
helpers there, not in the invoking project. Read `docs/core-rules.md`, then the
matching workflow; load specialized guides only for the operation being performed.
`docs/skill-rules.md` is an audit/edge-case reference, not a default read.

| Request, including equivalent natural language | Workflow |
|---|---|
| `/gm` | `docs/workflows/gm.md` |
| `/gn` | `docs/workflows/gn.md` |
| `/todo` | `docs/workflows/todo.md` |
| `/eureka` | `docs/workflows/eureka.md` |
| `/initialize`, `/secretary`, setup or general secretary work | `docs/workflows/secretary.md` |

Ask if intent is unclear. An explicit change of request follows its workflow in
the same conversation, with existing context and permissions. Do not require a
mode switch, new session, or recursive skill load. Keep the current session/model;
do not delegate. Missing setup follows the secretary workflow.

- `Browser chat`: also read `docs/browser-chat.md`. Briefings remain on their pages.
- `Browser job`: also read `docs/browser-generation.md`. Start with `job prepare`;
  immediately `init` a fresh preview, otherwise resume the receipt's next step.
  Publish only the next section, then `finish`. Reuse saved
  decisions, date and feedback; code owns cumulative JSON and final save.
- Other gm/gn requests: use `workflow --prepare KIND`, then native v2 JSON under
  `docs/briefing-format.md` and `state`. Preserve v1 archives and private records;
  never create Markdown/card/presentation/HTML copies or count previews as complete.
- New clear TODO/idea: use `workflow --capture todo|eureka`, verify, confirm, stop.
  Details and action verbs are captured content, not discussion or execution consent.
  Ambiguous scheduling/targets require a question before any record or pending note.
- Follow-ups/general work: use relevant IDs, filtered active pages and receipts.
  Read `docs/inbox-pipeline.md` for advanced updates; SQLite is the only inbox store.
  Use `daily` for factual history, not task state. See `docs/workflow-helpers.md` as needed.

Follow `docs/item-taxonomy.md`: Schedule owns events, Tasks owns actions, Reminders
owns due reviews/decisions. Code owns identity, timing and reported progress.
Showing work never schedules, completes or authorizes it; clear ideas are not nightly questions.

Use selected absolute `SECRETARY_DIR` and `GM_CACHE_DIR`, defaulting respectively
to `~/.local/share/GoodMorning/secretary` and `~/.cache/goodmorning`. Expand `~`.
Pass `--secretary-dir`, weather `--profile`, news/weather `--cache-dir`, and calendar
`--db` as applicable. Keep temporary inputs in the authorized runtime. Never
initialize records/caches inside the skill or invoking project. Installation
does not authorize setup, provider access, or mutations.
