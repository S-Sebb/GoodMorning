# Browser generation contract

The dispatch request contains only `/gm` or `/gn`, the browser job ID, and its
selected runtime and website language. Read core rules, this contract, the matching workflow and
`docs/briefing-format.md`. Stable instructions belong here, never in dispatch.

## Prepare once

Use the saved `website_language` from `job prepare` for this entire edition,
including questions, titles and the document's `lang`. It overrides the local
profile's reply language. Never ask for another language during initialization.
Changing the interface language does not restart or translate an active edition;
it affects future requests. Preserve all earlier published and saved content.

The page offers explicit recovery controls. “Prepare again” reopens an
undispatched preflight after “Stop for now”. “Refresh task list” preserves the
previous question and presents the changed daily plan for fresh confirmation.
It never invents completions or discards an uncertain feedback save.
“Continue existing session” sends a new prompt only to a known idle session with
no pending inputs, retaining its published sections. Uncertain dispatches require
inspection in OpenChamber and are never automatically replayed. Recovery is
account-local, limited to today, and uses the global request reservation.

“Regenerate today’s briefing” starts a new owning job and session after explicit
confirmation. It is limited to today and refuses active sessions, pending engine
inputs and uncertain dispatches. Old jobs are superseded and cannot publish,
save or accept replies. Their context and previews remain preserved.
The previous saved JSON and run marker stay in place during preparation; a
private backup is retained. The replacement checks the original snapshot and
edition's run marker before saving, and refuses unrelated changes. Final-save
retries accept only this job's exact completed document. No `--force` is needed.
Saved `/gn` feedback is reused without completing tasks or appending it again;
uncertain feedback saves must reconcile first. New feedback is collected only
when none was saved. Existing checklist tasks, completions, other edition's run,
news delivery records and preferences are never reset. A regenerated `/gm` adds
new exact-title tasks through the normal merge; it does not remove old tasks.
Regeneration authorizes a new presentation and the helper's final save only,
not replaying daily/inbox/project/calendar mutations or earlier execution consent.
Use current records for progress and reuse saved feedback without reapplying it.
Reconcile confirmed replacements under `docs/briefing-format.md`; do not republish
every preserved daily title or present obsolete wording alongside its replacement.

```sh
python scripts/goodmorning.py job --secretary-dir RUNTIME --job JOB prepare
```

Publication rejects final-save content errors before making a section immutable.
If final saving is interrupted, retry `finish` in the same owning job. Matching
saved editions and run markers are verified without rewriting them; only the
derived index is repaired. Never use `--force` to recover a browser job.

Use the real session ID from `OPENCODE_SESSION_ID`, or pass `--session REAL_SESSION`.
The helper checks ownership and returns saved preparation, pinned date/paths,
preferences, inbox/task context, and actual browser feedback. Do not rerun
`scripts/goodmorning.py workflow`, ask another missed-run question, or ask for progress already supplied.
Additional questions use the normal question tool, only for unresolved material
ambiguity or consent. Never auto-approve permissions or infer user progress.
Saved `integration_policy` false values prohibit live project access, calendar
synchronization, publisher images or news acknowledgement, even if an imported
profile describes those normal integrations. Use only authorized copied records.

The server resolves missing-edition choices once before model dispatch. Past
missing editions remain read-only; users can continue today or stop. For `/gn`,
the browser collects actual completed tasks and other progress first. Code saves
that feedback and completes only selected exact IDs. Partial work stays open.
No edition/run is marked while waiting. Failed feedback saves block dispatch.

Briefing days roll over at 04:00 in the profile timezone. Use the pinned date,
not the shell's calendar day. News windows still cover completed calendar days;
weather retains actual observation/forecast timestamps. Pass the pinned date to
backfill. No historical reconstruction through the generation button.

Each success receipt supplies `next`: the exact command, position and only the
next section's read recipes. Run `init` immediately after preparation, **before**
weather/news/calendar collection or additional record reads. Use the default plan
unless the confirmed language/window needs different titles. Do not invent flags;
use receipt commands or a script's `--help`. Inbox filters use `--status pending`
and bounded page receipts, not larger limits.

## Publish one section at a time

All actions below consume a small JSON object from standard input. Do not write
agent-owned cumulative draft files: code assembles, validates and saves them.
For nontrivial text, serialize the object with `json.dumps(..., ensure_ascii=False)`
and pipe it to the receipt command. Do not manually escape nested quotes. Syntax
failures report line/column; schema failures report the field and accepted shape.
Repair only the new input. Never alter published sections to resolve a failure.

1. `init`: `{"greeting":"…","opening":"…","lang":"en","plan":[["weather","Weather"],…]}`.
   Language and plan are optional; code supplies the dated default plan. Plan titles must match eventual section titles, including
   custom language and dated news windows. Greeting/opening cannot change later.
   Keep the opening suitable before facts are gathered; no speculative overview.
2. Gather and author the **next section only**, then immediately `publish`:
   `{"position":0,"section":["weather",[…],"Grounded takeaway."]}`.
   Position is the zero-based plan index, including skipped entries. Only one
   complete section arrives per call. Earlier sections cannot change; an identical
   position/input retry is reused. Read prerequisite context as needed, but never
   collect the whole briefing before publication.
3. `skip`: `{"position":N}` only for a genuinely empty optional section. Failed
   weather/news/schedule retrieval must appear as material unavailability, not an
   empty section. Required sections cannot be skipped.
4. After all positions resolve, `finish`: `{"closing":"…"}` or `{}`. Code checks
   the owning session, pinned date, edition and exact preview; synchronizes visible
    gm task titles into the daily checklist; then saves JSON and the run marker.
    Flexible rows dated today join the checklist without invented priority;
    future/undated rows do not become today's tasks. Exact-title duplicates keep
    existing completion and stored checklist classification. Stored groups do not
    determine the section that owns an action in the current briefing.
   New tasks are unchecked; existing completions and unrelated work are preserved.
   Project steps / Optional project steps use typed `tasks` blocks under the
   stable `must-do`/`nice-to-do` types, never hidden in prose/lists.
   The model may still make authorized project/daily amendments for other records.

Example invocation (use the same flags for every action):

```sh
python scripts/goodmorning.py job --secretary-dir RUNTIME --job JOB publish <<'JSON'
{"position":0,"section":["weather",[["p","Weather is unavailable; check before travelling."]]]}
JSON
```

Typical order: gm Weather, yesterday's News, opted-in dated latest News, Schedule,
Project steps, Optional project steps, material Reminders. gn Today, Still open,
Tomorrow, Project steps, Optional project steps, material Notes.
Both editions reserve optional project sections:
review relevant saved project records and confirmed reports, publish typed `tasks`
for actual outstanding project work, and skip either priority section if there are
no supported tasks for it. Name each project and concrete next action; distinguish
necessary ongoing steps from optional improvements, preserving explicit
priorities. Do not invent work, deadlines or progress, access live projects against
policy, or treat a priority as execution consent. Night priorities do not reschedule
unfinished work or create tomorrow tasks; retain only supported/agreed dates.
Scheduled actions never repeat in project sections. Apply the task selection and
section ownership contract in `docs/briefing-format.md` before Schedule/Tomorrow
becomes immutable; reuse those reconciled choices for later sections.
Review all selected news and retain citations before publishing its section.
Do not use `--force`; check every receipt's exit/error/next. Failed/interrupted
previews remain readable. Finish retries may reconcile only an identical saved
document bound to the same job. Snapshot existence alone never means ready.

## Presentation and delivery

Use the confirmed language/tone throughout. Short natural greeting, useful content
and grounded section notes (including Optional project steps when present). No repeated date:
the viewer owns navigation. JSON strings are plain UTF-8, not Markdown/HTML. Do
not invent feelings, availability, deadlines or progress. No generic reassurance,
empty-queue bookkeeping, or commentary merely restating timetable rows. Distinguish
free calendar slots from confirmed availability; use exact known times.
For Schedule/Tomorrow, review the saved task context and relevant active inbox/
project constraints before any availability statement. Publish timed agenda rows
first, then a `flexible` block for important untimed day commitments when present,
even when there are no appointments. Use the pinned target date only for work
supported on that day;
unassigned work keeps an empty date. Unknown appointment times remain `TBC` in
agenda, not flexible tasks. Leave undated unfinished work in Still open unless
the user has agreed to move it; never call tomorrow empty while it has planned
tasks. Reminders/Notes are for background nudges and unresolved ideas, not a
substitute for the flexible schedule.

Return the browser link, not repeated text/JSON. No Markdown, presentation, card
or dated HTML copies. Private records must not be overwritten by cleanup.
Shared assets/cache own rendering. Only the next section
animates; later sections stay queued. Progress counts resolved sections, not time.
One checkpoint is overwritten; only a verified completed preview is cleaned up.

Saving/publishing is not news delivery; never acknowledge based on it. Publisher
images require separate authorization. With saved `publisher_images: true`, the
job helper caches previews after publishing news, before moving to the next section.
It never fetches on ordinary page reads. Failures retain placeholders and can retry
after one hour; successes are deduplicated. `web --fetch-images` populates
saved-edition image objects without exporting or rewriting briefings. Use the job
helper for browser authoring; stream/state are its publication/save components.
