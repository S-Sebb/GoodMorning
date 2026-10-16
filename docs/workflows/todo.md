---
name: todo
description: Capture a TODO with exact raw input, a clear revised title and grounded detail. Clarify ambiguous scheduling or targets before saving; never execute captured work.
---

# TODO capture

Trigger: `/todo` or an explicit task-capture request. Inputs: raw text, confirmed
runtime/timezone, actual session, stable request key, and supplied context.
Result: one verified pending TODO and linked action, not execution or a project-plan change.

Read `docs/core-rules.md` and `templates/todo.reply.template.md`. Use the package
root and selected absolute paths. `docs/reply-voice.md` is for detailed discussion;
simple capture uses the core voice rules. Route explicitly requested other work
to its workflow in this conversation; capture wording alone does not grant consent.

## Steps

1. Resolve blockers before writing. Ask for missing text; request redaction of
   credentials. If scheduling or the follow-up target is ambiguous, ask a native
   question before capture/append/task changes; save no pending note. If setup is
   missing, keep the text in the conversation and follow the secretary workflow.
   Say it is not saved. Do not ask unrelated optional questions. For forward-looking
   recurrence, use the confirmed local capture date as the default start and the
   saved timezone. Ask for start only if another effective date is indicated.
   If local date/timezone is not yet confirmed, `workflow --prepare todo` reads it
   without writing: use `capture_date` (calendar date), not the briefing-day `date`.
   Pass `--website-language CODE` in browser chat. For “every few
   days”, ask only the interval, then apply that answer with the default start.
   A time window without a frequency (“11月初”, “early November”) is ambiguous
   between one-off and repeat: ask both the frequency (one-off, daily, weekly)
   and the start date before any write, and never store the window in prose without
   a structured repeat, workday, or deadline. One action done once inside a stated
   window (“buy it between 23 and 28 October”) is clear: `defer_until` the first day,
   `due_date` the last.
2. Classify before saving with rule 2 of `docs/item-taxonomy.md` (read it when the
   input is anything but a plain action): a heads-up with nothing to finish is
   `task.kind:"nudge"`; something the user asks you to do for them each morning
   ("check the price and tell me when it's under £120") is `task.kind:"errand"`,
   whose detail says only what to find and when to tell them (try it once before
   saving, as rule 2 says); information for a trigger the system cannot see ("when X runs
   out") is `kind:"reference"` with `trigger`; "remind me daily until done" is
   `follow_up:"until-done"`; birthdays and appointments belong to the calendar, not
   tasks, and a habit with a flexible rhythm uses `custom --add`. If one request is
   two items, confirm the split with a native question, then send `also:[{...}]`.
   For any dated item decide its advance `notice` (rule 2): the user's stated "tell me
   N days before" wins; otherwise judge how early they need to hear and whether it
   can be done before its day (`early`), state it in the confirmation, and ask only
   when you genuinely cannot tell.
   For a new clear TODO, use the single capture helper:
   ```sh
   python scripts/goodmorning.py workflow --secretary-dir RUNTIME --capture todo --session SESSION --request-key KEY --input-stdin
   ```
   Supply exact `raw`, revised `summary`, and `task` with the same revised `title`
   plus grounded `detail`. Include only confirmed project/timing/context. The wrapper
   supplies `kind: "todo"` and checks setup; do not add `kind`, run separate
   preparation/profile/state reads except the date/timezone check in step 1, read
   old inbox history, or call `task --add` again.
3. For a clear follow-up, reuse the entry. Read `docs/inbox-pipeline.md`; append
   exact supplied wording with `inbox --append ENTRY --session SESSION --request-key KEY`.
   Read its linked action with `task --show TASK_ID`; reconcile supplied facts using
   revision-checked `task --update` and a separate stable operation key. A workday
   updates `planned_date`; a deadline updates only `due_date`. Verify reconciliation
   before marking the source reviewed at its current revision. Do not change
   records for punctuation/capitalization alone or duplicate an already captured turn.
4. Check the receipt. Rename successful local captures once to `Todo SUMMARY`
   using the revised title and shared language/title rules. Never rename browser chats.
   Brief factual progress may stay visible in the saved language/tone. Confirm the
   verified result, then stop. Confirm workday and deadline as separate facts; do not imply that
   assigning a workday ensures completion or enough time. A brief optional `Clarify` invitation
   requires no reply. Do not mark gm/gn or rebuild state for capture.
5. Only an explicit discussion request permits explanation/clarification. Save clear
   supplied facts first; reuse prior answers and ask only remaining relevant questions.
   Discussion is not organization or execution consent. Separately requested
   organization follows the secretary workflow and existing scope/confirmation rules.

## Wording and boundaries

- Preserve `raw` verbatim. Start titles with an imperative verb and specific object;
  capitalize the first letter, omit filler openers, trailing periods and project
  prefixes. Aim for fewer than 80 characters when possible.
- Detail adds 1–2 grounded sentences about why, current state or next step. Leave it
  empty if unsupported. Do not repeat title/project/deadline/priority; keep supplied
  timing in structured fields. Reminder mechanics and setup narration
  ("surface in Friday /gm", "setup choice confirmed", "no calendar time/place")
  belong in structured repeat/when fields and the inbox entry `context`, never in detail.
  Never invent facts, dates, priorities or progress.
- Example: “Currently there's a message-box stretch blocking typing” becomes
  “Fix message-box stretch blocking typing”; no unsupported detail is needed.
  “Work on it tomorrow” updates the identified action's workday, not its deadline.
- Do not ask for project/deadline/priority/breakdown by default or research, plan,
  execute, delegate, launch jobs, scan projects, fetch news/weather, edit work files
  or offer calendar changes during capture; the one exception is the single trial
  run of an errand. A dated TODO remains a TODO.
- Later workflows may display the open action; they must not invent a deadline,
  today's priority, duplicate task or clarification task. Only user-confirmed
  completion permits revision-checked `task --update`/`--report` under
  `docs/item-taxonomy.md`. Do not install a scheduler.

## Failure

A rejected write is not saved; an interrupted write may have an unknown outcome.
Inspect its receipt before retrying with the same key/input. Preserve unrelated
records and unresolved outcomes; do not duplicate writes or start code repairs.
