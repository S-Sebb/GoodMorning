---
name: eureka
description: Record a pending idea via /eureka without doing the work. Save details, stop after confirmation, and discuss or organize only on separate explicit requests.
---

# Idea capture

Trigger: `/eureka`, or an explicit request to capture an idea in GoodMorning.
Inputs: the user's raw idea, confirmed runtime/timezone, optional project alias,
and any supplied details or request to clarify. Output: a saved pending idea first;
not execution of the idea. Clarification and organization require separate requests.

## Capture boundary

`/eureka` means record this idea, not do it. Even "research X", "build Y" or
"fix Z" with full requirements is captured content, not execution consent.
By default, save, confirm, then stop. Do not research, browse for the idea, plan
its implementation, edit project/work files, run jobs, delegate, scan projects,
or offer calendar changes. Only inbox capture and the workflow title are authorized.
An explicit `Clarify` or equivalent discussion request permits clarification,
not execution. Organizing the idea into project records also needs a separate
explicit request; confirming its meaning does not authorize doing the work.

If the user explicitly requests another mode's work, such as organizing a saved
idea into project records, automatically follow `docs/workflows/secretary.md`
or the matching workflow in this conversation. Do not require a manual mode
switch or special command. Reuse the saved idea; preserve scope and confirmation
requirements. An action written as idea content alone is not such a request.

All paths below are relative to the GoodMorning package root. Read
`docs/core-rules.md` first (`docs/skill-rules.md` is the expanded reference). Use
`templates/eureka.reply.template.md`. Run commands from root and resolve
the shared runtime directory. Do not ask for a now/later choice by default. Use
`question` only for needed clarification or confirmation. Do not fetch
weather/news or scan all projects.
Apply the shared materiality gate: no non-critical disclaimers or unrelated
diagnostic narration; show the actual capture outcome and useful next step.
Quick capture follows the shared voice essentials; read `docs/reply-voice.md`
only for detailed discussion. Reflect the idea naturally, without extra framing.
Brief grounded interest or a warm closing is optional, not mandatory padding.

## Steps

1. Check setup without delaying capture with unrelated questions. If setup is
    missing, retain the idea in the conversation, read `docs/workflows/secretary.md` for setup, and
   say it is not saved yet. If no idea was supplied, ask for it; do not create an
   empty entry.
2. Python helpers use `python scripts/goodmorning.py COMMAND`.
   For new raw input use `workflow --capture eureka --session SESSION --request-key KEY
   --input-stdin` with JSON `raw` and optional confirmed project/current context.
   This checks local setup and saves directly; no preparation/full profile/state read.
   It produces the English title suggestion and reply preferences. No `kind` in this
   payload (the wrapper supplies `kind: "idea"`). Read `docs/inbox-pipeline.md`
   only for follow-ups/review/organization, not simple capture. Timestamps use the profile.
    After a successful local receipt, rename once to `Eureka SUMMARY` in
    `secretary_language`, using the helper's very short raw summary per the shared
    title rule. Browser chats keep the native engine's automatically generated
    title; do not overwrite it. Captured text stays unchanged.
   Never read old inbox messages to append. Never persist credentials: ask for
   a redacted idea instead. Verify the write receipt before saying "Saved". If this same
    user turn was already captured, point to its entry rather than appending again.
   Save follow-up details immediately too, before any clarification question,
   using `--append ID`. Keep a concise current context and focused questions,
    not a transcript; note what still requires clarification. Supplied details
    alone do not request discussion or execution. If their target is unclear,
    save unassigned pending input before asking which entry it belongs to.
3. Apply the user's customised tone throughout the confirmation, questions, and
   reminders, while prioritizing clean formatting and clarity. Confirm what was
    saved in a natural reply using the template. By default, leave it pending and
    invite optional clarification via `Clarify`, not a question widget; the user
    can also leave the idea as is. Do not require a reply or a now/later
     choice. Without an explicit discussion request, stop after this confirmation
     and optional invitation. A dated idea stays pending; no calendar offer during
     capture. If clarification is explicitly requested, continue with step 5.
4. Default / later: leave it pending without requiring an explicit "later" reply.
    Follow `docs/item-taxonomy.md`: surface actual open questions or a due review
    in Needs attention, not automatic daily clarification work. Keep unresolved
   input pending even without a follow-up reply. Do not install a scheduler.
5. Clarification: accept `Clarify` or an equivalent explicit discussion request;
   no special keyword is required, but details alone are not such a request.
   Save details in the initial capture, a follow-up, or `/secretary` without
   automatically starting discussion. When discussion is requested, reuse supplied
   answers and relevant context. Ask which idea only if its target is ambiguous.
   Preserve the original raw idea and retain additional details with that pending
   entry via its stable ID, not as a duplicate idea. Ask focused questions only about remaining
   ambiguity in the goal, intended project, constraints, or next action. If those
   are already clear, skip clarification questions. Quote back the clarified
   meaning for confirmation. Then stop unless organization was separately requested.
   Clarification is not permission to execute the idea. Only for separately
   authorized organization, read relevant project records/instructions and write
   the confirmed idea into scoped records, updating `last_update` and preserving
   unrelated work. Saving a project TODO is not permission to complete that TODO.
6. Use `inbox --update ID --expect-revision REVISION` to change the entry to
    `confirmed` only after the user confirms and the agreed organization succeeds.
    Task adoption uses `task --adopt` with explicit action fields; it links the
    idea to stable task IDs without another capture or execution consent.
   If any required write is unresolved, keep it pending and describe what remains.
   State checks/marks already read current records; do not rebuild after every
   record edit. Never mark gm/gn for idea capture.

## Errors

Failed capture means "not saved", not "saved for later". Ask about ambiguous
project matches instead of guessing. Respect write conflicts/unknown outcomes;
never duplicate a possibly successful remote write or delete the original idea.
