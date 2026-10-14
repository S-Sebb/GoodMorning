# Secretary agent usage

The inactive source `skill-source/goodmorning.md` installs as `SKILL.md` in the
GoodMorning package. Installing source never initializes or migrates personal data.
Workflow commands and equivalent natural-language requests are not registered
slash commands. Keep the current session/model; never delegate secretary work.

Read `docs/core-rules.md`, then only the matching `docs/workflows/` file. Identity,
timing and storage follow `docs/item-taxonomy.md`. Load operation guides only when
needed; `docs/skill-rules.md` is an edge-case reference, not a default read.

- Website chats use `docs/browser-chat.md`. Use the supplied website language;
  browser titles belong to the native engine. Follow a changed user request in
  the same conversation without requiring a manual mode switch.
  Interface/transport details are in `docs/browser-chat-runtime.md`, not the default prompt read.
- Website editions use `docs/browser-generation.md`: `job prepare`, immediate
  `init` for a fresh preview or resumed checkpoint's next step, then one section
  at a time through returned recipes and `finish`.
  Reuse the pinned date and actual browser feedback; code owns cumulative JSON.
- Schedule owns events, Tasks owns all work, Reminders owns due decisions.
  Evening Today reports actual outcomes; morning includes weather/sourced news.
  Showing/regenerating work never schedules, completes or executes it.
- The Schedule tab reads approved events, confirmed TBC drafts and agreed dated
  occurrences under `docs/weekly-schedule.md`. Deadlines alone reserve no workday.
- Clarify ambiguous scheduling/targets through a native question before saving
  anything outside the conversation. The waiting badge links back; no pending note.
- Clear TODO/idea: `workflow --capture todo|eureka`, exact raw JSON, actual session,
  stable input key and selected runtime. Verify, confirm, stop. TODO capture also
  creates its open action; an idea creates no work or daily clarification task.
- Follow-ups append exact wording to the same entry with session/request key.
  Explicit timing/details update its linked task with current revision. Do not
  recapture, invent missing facts or treat recording as execution consent.
- Secretary work uses targeted `inbox`/`task` reads and revision-checked writes.
  Calendar edits need exact confirmation; imports remain staged until reviewed.
  Daily Markdown is feedback/history, not live task state. Project writes retain
  their scope under `docs/project-access.md`; preserve unrelated records.
- Initialize follows `docs/initialization.md`: preserve preferences, obtain exact
  storage/access consent, create missing records only, verify providers separately.
  Existing v1 stores need owner-approved, backed-up migration, never a reset.

Never store credentials, broaden permissions, infer completion, approve your own
questions or retry uncertain writes with a different key. Use bounded pages and
receipts, not full histories/provider dumps. Explain material failures and needed
decisions naturally in the saved tone; internal IDs stay out of visible prose.

Tests use isolated synthetic records. Unit/browser tests verify mechanics;
separate opt-in real-model trials test agent behavior, not statistical reliability.
