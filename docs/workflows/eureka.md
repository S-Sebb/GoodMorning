---
name: eureka
description: Capture a pending idea without doing the work. Save clear details, confirm, and stop; discuss or organize only on separate explicit requests.
---

# Idea capture

Trigger: `/eureka` or an explicit idea-capture request. Inputs: raw idea, confirmed
runtime/timezone, actual session, stable request key and supplied context/project.
Result: one verified pending idea. Read `docs/core-rules.md` and
`templates/eureka.reply.template.md`; use `docs/reply-voice.md` only for detailed discussion.

## Steps

1. Resolve blockers before writing. Ask for missing idea text or credential redaction.
   Ambiguous scheduling/targets require a native question before any capture,
   append or pending note. Missing setup follows the secretary workflow; retain
   the idea in the conversation and say it is not saved. Ask no unrelated questions.
2. For a new clear idea, run from the package root:
   ```sh
   python scripts/goodmorning.py workflow --secretary-dir RUNTIME --capture eureka --session SESSION --request-key KEY --input-stdin
   ```
   Supply exact JSON `raw` and optional confirmed project/current context
   (all fields: `docs/helper-inputs.md`):
   ```json workflow --capture eureka
   {"raw":"What if the weekly page showed a mood line?","context":"Idea only; no work requested."}
   ```
   The wrapper supplies `kind: "idea"`, checks setup, and returns a receipt/title suggestion
   and reply preferences. Do not add `kind`, read old inbox history, or run separate
   preparation/profile/state checks. Timestamps use the profile timezone.
3. For clear follow-up details, read `docs/inbox-pipeline.md` and append to the
   identified entry with its stable ID, actual session and request key. Preserve
   original raw input and concise current constraints/questions, not a transcript.
   Reuse an already captured turn instead of creating a duplicate. Save clear details
   before requested discussion; details alone do not request discussion or execution.
4. Verify the receipt. Rename successful local captures once to `Eureka SUMMARY`
   using the helper's short raw summary and shared title/language rules. Never
   rename browser chats. Confirm in the saved tone, optionally invite `Clarify`,
   then stop. No now/later question, required reply, gm/gn mark or per-edit rebuild.
5. On an explicit discussion request, reuse the entry and prior answers. Ask only
   unresolved goal/project/constraint/next-action questions, then quote the clarified
   meaning for confirmation. Stop unless organization is separately requested.
6. For authorized organization, follow the secretary workflow and project-access
   rules. Read relevant records/instructions, preserve unrelated work and update
   `last_update`. Task adoption uses `task --adopt` with explicit action fields;
   it links stable task IDs without another capture or permission to execute them.
   Set the idea `confirmed` with revision-checked `inbox --update ID` only after
   user confirmation and every agreed authorized write succeeds. Otherwise keep it pending.

## Boundaries

- “Research X”, “build Y” and “fix Z” inside an idea are content, not execution consent.
  Default capture permits inbox storage and the local workflow title only: no
  research/browsing, implementation plans, project/work-file edits, jobs, delegation,
  project scans, news/weather fetches or calendar offers. A dated idea stays pending.
- Example: capture “Build a dashboard” and stop. “Organize this saved idea into
  project tasks” explicitly routes to the secretary workflow in the same conversation;
  it authorizes only the agreed organization, not building the dashboard.
- No special keyword or manual mode switch is required. Clarification permits
  discussion, not organization/execution. Clear supplied details need no redundant questions.
- Under `docs/item-taxonomy.md`, Reminders surfaces actual open questions or due
  reviews, respecting saved answers and deferrals. Clear ideas do not create
  automatic daily clarification tasks; install no scheduler and force no reply.

## Failure

A rejected capture is not saved; an interrupted capture may be uncertain. Inspect
before retrying with the same key/input. Preserve the original idea and pending
state; do not guess project matches, delete records, or duplicate uncertain writes.
