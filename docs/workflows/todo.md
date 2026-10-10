---
name: todo
description: Record a user's TODO via /todo without clarification, planning, or doing the task. Preserve supplied wording and details; discuss only when explicitly requested.
---

# TODO capture

Trigger: `/todo`, or an explicit request to record a TODO in GoodMorning.
Inputs: the user's raw TODO, confirmed runtime/timezone, optional confirmed
project, and supplied follow-up details. Output: a verified saved pending TODO,
not execution of the task or a change to the confirmed project plan.

All paths below are relative to the GoodMorning package root. Read
`docs/skill-rules.md` first, then use `templates/todo.reply.template.md` and
`docs/reply-voice.md`. Run helpers from root with explicit absolute runtime paths.
Apply the shared materiality gate and the user's customised tone throughout.
Keep the current session and model; do not delegate.

## Steps

1. Check existing setup without unrelated questions. If setup is missing, retain
   the TODO in the conversation, follow `docs/workflows/secretary.md`, and say it
   is not saved yet. If no TODO text was supplied, ask for it; never save an empty
   entry. Never persist credentials; ask for redacted wording instead.
2. Rename this conversation to `Todo SUMMARY` in `secretary_language` per the
   shared title rule, using a very short summary of the raw TODO.
   Append to the existing runtime inbox without replacing other entries:
   `- YYYY-MM-DD HH:MM TIMEZONE | JSON_TODO | pending | PROJECT`.
   Use the real local timestamp. JSON_TODO is a single-line JSON object with
   `kind: "todo"`, `raw` containing the user's exact wording, and `details`
   containing supplied follow-up wording. JSON encoding preserves multiline text,
   quotes, and pipes. Use only a confirmed project; otherwise leave PROJECT empty.
   Do not ask for a project, deadline, priority, or task breakdown by default.
   If this same user turn was already captured, reuse its entry instead of
   duplicating it. Save follow-up details immediately with the same entry,
   preserving `raw`; supplied details alone do not request clarification.
   If the target is unclear, save them as unassigned pending TODO input first;
   leave them unassigned unless the user identifies the target or requests discussion.
3. Verify the write and rebuild the index with
   `python scripts/state.py --secretary-dir RUNTIME --rebuild --json`.
   Never mark gm/gn for TODO capture. Confirm the saved TODO briefly, using the
   reply template. Do not require a reply or a now/later choice. A brief optional
   `Clarify` invitation is allowed, not a clarification question.
4. By default, just record what the user says. Do not ask clarification questions,
   infer missing details, research, plan, execute the TODO, launch agents/jobs,
   scan projects, fetch news/weather, or change project/work files or calendars.
   A dated TODO stays a TODO; do not offer calendar confirmation during capture.
   Recording a task is not authorization to do it. Leave it pending until the
   user explicitly reports completion or authorizes its organization elsewhere.
5. Discuss only if the user says `Clarify`, explicitly asks for equivalent
   clarification, or requests a more detailed explanation. Save all supplied
   input first, reuse existing answers, and use `question` only for remaining
   ambiguity within the requested discussion. Explain only what was requested;
   discussion still does not authorize execution or project/calendar changes.
   Any separately requested organization follows shared scope and confirmation
   rules; unresolved writes stay pending.
6. Later `/gm`, `/gn`, and `/secretary` workflows may surface an open TODO as a
   task/reminder, not an automatic clarification TODO or question. Do not invent
   a due date, force it into today's must-do list, or duplicate an existing task.
   Only user-confirmed completion permits marking it `done`; rebuild the index
   after changes. No scheduler is needed.

## Errors

A failed write means not saved. Distinguish a verified inbox save from a failed
index rebuild. Preserve unrelated records and unknown outcomes; inspect before
retrying so a possibly successful capture is not duplicated. Do not turn a
capture failure into an unrequested code-repair or task-execution detour.
