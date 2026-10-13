---
name: todo
description: Record a user's TODO via /todo without clarification, planning, or doing the task. Preserve exact raw input, but save a revised clear title and useful detail.
---

# TODO capture

Trigger: `/todo`, or an explicit request to record a TODO in GoodMorning.
Inputs: the user's raw TODO, confirmed runtime/timezone, optional confirmed
project, conversation context, and supplied follow-up details. Output: a verified saved pending TODO
with a revised clear title and useful detail, not execution of the task or a
change to the confirmed project plan.

All paths below are relative to the GoodMorning package root. Read
`docs/core-rules.md` first (`docs/skill-rules.md` is the expanded reference), then use `templates/todo.reply.template.md` and
the shared voice essentials; `docs/reply-voice.md` is for detailed discussion.
Run helpers from root with explicit absolute runtime paths.
Apply the shared materiality gate and the user's customised tone throughout.
Keep the current session and model; do not delegate.

If the user explicitly requests another mode's work, automatically follow
`docs/workflows/secretary.md` or the matching workflow in this conversation.
Do not require a manual mode switch or special command. Reuse the saved TODO
and preserve scope and confirmation requirements; task wording alone is not
authorization to do the task.

## Steps

1. Check existing setup without unrelated questions. If setup is missing, retain
   the TODO in the conversation, follow `docs/workflows/secretary.md`, and say it
   is not saved yet. If no TODO text was supplied, ask for it; never save an empty
   entry. Never persist credentials; ask for redacted wording instead.
2. Apply the core-rule exception first: ambiguous scheduling uses a native question
   before any capture or pending note. Clear input keeps the fast path below.
   Python helpers use `python scripts/goodmorning.py COMMAND`.
   For new raw input use `workflow --capture todo --session SESSION --request-key KEY
   --input-stdin` with `raw` containing the user's exact wording and optional confirmed
   project/current context. No `kind` in the payload (the wrapper supplies `kind: "todo"`).
   It checks setup and returns the receipt, title suggestion and reply preferences;
   no separate preparation/profile/state read. Always revise the wording before saving:
   keep `raw` verbatim for audit, but supply an improved `summary` plus a `task`
   object with the same revised `title` and a useful `detail`. Title rules: imperative
   verb first, specific object, no filler openers ("currently", "there is", "please"),
   no trailing period, capitalize the first letter, keep it under ~80 characters where
   possible, and do not prefix the project name when the structured `project` field
   already holds it (use topic wording such as "Draft convincing-paper outline", not
   "Draft MRHarmon convincing-paper outline"). Detail rules: 1–2 grounded sentences with why it matters plus the
   current state or next concrete step, drawn only from supplied facts and conversation
   context; never invent deadlines, priorities, projects or progress. If no grounded
   why/state exists, leave `detail` empty. Example payload:
   `{"raw":"Currently there's a weird stretch of the message box ...",
   "summary":"Fix secretary page message-box stretch blocking input",
   "task":{"title":"Fix secretary page message-box stretch blocking input",
   "detail":"Message box sometimes stretches and blocks typing; keep open until Seb confirms after deployment."}}`.
   Read `docs/inbox-pipeline.md` only
    for follow-ups/completion/discussion, not simple capture. Append material
    follow-ups with `inbox --append ENTRY --session SESSION --request-key KEY`
    and `{"detail":"exact supplied wording"}`. Then reconcile supplied task facts
    through `task --show TASK_ID` and revision-checked `task --update` with a separate
    stable operation key. If the target or scheduling meaning is unclear, ask a
    native question before appending/capturing anything, per core rules.
    "Also work on it tomorrow" updates `planned_date` on the
    existing task; a new deadline updates only `due_date`. This records the stated
    plan, not execution or unsolicited discussion. After verified reconciliation,
    mark the source reviewed with its current inbox revision; ambiguity stays pending.
   JSON preserves multiline text, quotes, and pipes. The helper uses the profile
   timezone. Use only a confirmed project; otherwise leave `project` empty.
   Never read old inbox messages to add a TODO; verify its compact receipt.
    After a successful local capture, rename once to `Todo SUMMARY` in
    `secretary_language`, using the revised clear title (not the verbatim raw) per the shared
    title rule. Browser chats keep the native engine's automatically generated
    title; do not overwrite it. Raw input stays verbatim in storage; the saved
    `summary`/`title`/`detail` carry the improved wording.
   Do not ask for a project, deadline, priority, or task breakdown by default.
   When supplied, keep `detail` to useful extra notes only: never repeat the title,
   project, deadline or priority in it; put supplied timing in structured `task`
   fields (`due_date`, `planned_date`), never in prose. A vague user title such as "Write convincing
   paper" (project MRHarmon) must become something specific like "Draft convincing-paper outline",
   with detail drawn only from supplied context (paper, current state, agreed next step).
   If no why/state was supplied, leave `detail` empty rather than inventing facts;
   an honest empty detail beats a fabricated one. Punctuation or capitalization alone
   is not a reason to bump a revision; polish only materially vague copy.
   Code shows each once per project group;
   duplication is what makes the Tasks page read as a billion identical cards.
   If this same user turn was already captured, reuse its entry instead of
   duplicating it. Save follow-up details immediately with the same entry,
   preserving `raw`; supplied details alone do not request clarification.
   If the target is unclear, ask a native question before recording anything;
   do not save an unassigned pending TODO. Update the identified action after the answer.
3. Verify the write receipt from
   `python scripts/goodmorning.py workflow --secretary-dir RUNTIME --capture todo` (with the required payload,
   session and request key). No full state rebuild is needed for inbox changes.
   Never mark gm/gn for TODO capture. Confirm the saved TODO briefly, using the
   reply template. Do not require a reply or a now/later choice. A brief optional
   `Clarify` invitation is allowed, not a clarification question.
4. For clear requests, record what the user means with clearer wording, not a verbatim
   title copy. Do not ask unnecessary clarification questions,
   infer missing details, research, plan, execute the TODO, launch agents/jobs,
   scan projects, fetch news/weather, or change project/work files or calendars.
   Improving the title/detail wording from supplied facts needs no extra question;
   only ambiguous scheduling/targets require asking before any write.
   A dated TODO stays a TODO; do not offer calendar confirmation during capture.
   Recording a task is not authorization to do it. Leave it pending until the
   user explicitly reports completion or authorizes its organization elsewhere.
5. Discuss only if the user says `Clarify`, explicitly asks for equivalent
   clarification, or requests a more detailed explanation. Save all supplied
   clear input first, reuse existing answers, and use `question` only for remaining
   ambiguity within the requested discussion. Explain only what was requested;
   discussion still does not authorize execution or project/calendar changes.
   Any separately requested organization follows shared scope and confirmation
   rules; unresolved writes stay pending.
6. Later `/gm`, `/gn`, and `/secretary` workflows may surface an open TODO as a
   task/reminder, not an automatic clarification TODO or question. Do not invent
   a due date, force it into today's must-do list, or duplicate an existing task.
    Only user-confirmed completion permits marking the canonical task/occurrence
    done; use revision-checked `task --update`/`--report` under
    `docs/item-taxonomy.md`. No scheduler is needed.

## Errors

A failed write means not saved. Preserve unrelated records and unknown outcomes; inspect before
retrying so a possibly successful capture is not duplicated. Do not turn a
capture failure into an unrequested code-repair or task-execution detour.
