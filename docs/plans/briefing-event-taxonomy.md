# Event taxonomy and briefing redesign

Status: proposal for review, not an implemented or approved contract.

## 1. Recommendation

Separate three independent questions:

1. What is this item? An event, a task, an idea, or an unresolved report.
2. What do we know about its timing and state? Dates, deadlines, recurrence,
   confirmation, completion and outstanding questions.
3. Where should this edition display it? Code selects a section from those facts.

Use **Schedule**, **Tasks**, and **Needs attention** in both editions. Morning
looks forward; evening adds **Today's review** and looks toward tomorrow. Project
membership and required/optional work are task attributes, not separate section
types. Retire Project steps / Optional project steps as top-level sections for new
editions. Do not call executable tasks "project ideas".

Ideas remain in the idea inbox until the user requests review or conversion.
A reminder is a reason to surface an existing item, not another copy of that item.
These rules concern records and briefings, not notification delivery or agent jobs.

## 2. Findings in the current implementation

The current system already has useful safeguards: transactional capture receipts,
immutable input, revision/hash checks, staged calendar imports, account isolation,
native JSON snapshots, and no automatic execution. Preserve them.

The remaining problems are structural:

- `records/inbox_store.py` stores `idea`, `todo`, and `project_update`, but dates,
  deadlines, recurrence and planning are free-text context. Input-review status and
  task completion share a status field.
- `records/daily.py` generates task IDs from date, group and wording. Those are
  display properties, not durable action identity. Project Markdown, inbox TODOs
  and daily checklists can represent the same work independently.
- `daily.planned_tasks()` copies every visible `must-do`/`nice-to-do` task into
  today's checklist, including undated project steps. It copies the title, not
  the detail or an inbox reference. The weekly schedule then treats those rows
  as dated work (`web/schedule.py`). Showing a next step can therefore look like
  scheduling it for today.
- Inbox-reference deduplication assumes one action per captured entry. Two
  distinct subtasks with the same reference can collapse into one.
- Completing a daily row does not complete its inbox TODO. Checking off every
  task requires reconciling several stores manually.
- Native task ownership validation detects equivalent titles, not action IDs.
  Rewording the same task can evade it.
- `calendar_store.normalize()` requires complete timed endpoints or an explicitly
  all-day event. The briefing format supports a TBC appointment, but there is no
  corresponding persistent draft-event contract.
- Workflows mention recurring untimed tasks without a recurring-task store/helper.
- "Dated TODO" does not clearly distinguish a deadline from an agreed workday.
- Eureka follow-up rules create clarification work even when an idea has no open
  question. Some examples contradict the current section rules; the project
  template still refers to unsupported `inbox.md`.

Evidence from this planning session:

- 128 existing tests passed across workflow helpers, inbox, native documents,
  browser jobs and weekly schedule. Passing tests preserve existing behavior;
  they do not establish that the taxonomy is correct.
- Isolated helper probes reproduced undated project-to-today copying, title-only
  persistence, acceptance of differently worded duplicate actions, two subtasks
  collapsing into one, daily/inbox completion divergence, and rejection of an
  appointment with no clock time.
- Muse Spark 1.3 Contributor evaluated 16 synthetic cases against the existing
  instructions. It explicitly identified unclear rules for deadlines, clear ideas,
  unknown-time appointments and recurring chores. This was a document-following
  probe, not an end-to-end agent test or a scored before/after evaluation.

## 3. Item definitions

| Item | Meaning | Examples | Not implied |
| --- | --- | --- | --- |
| Event | An attendance commitment, observance or reserved interval. A genuinely all-day event is explicit. | Dentist, meeting, conference, vacation, confirmed work time block. | Attendance/completion, provider freshness, or permission to execute work. |
| Task | An action with a meaningful completion condition. It can be personal or project-related, required or optional, dated or undated. | Buy milk, send Atlas report, compare baselines, wash towels. | A workday, calendar booking, priority or execution consent. |
| Idea | A possibility not yet adopted as work. Eureka capture remains an idea even when its wording contains action verbs or dates. | Maybe build a dashboard; research a possible feature. | A task, appointment, deadline or recurring clarification obligation. |
| Project update / unresolved report | Supplied facts or proposed changes awaiting reconciliation with a confirmed plan. | A possible scope change, an unclear progress report. | A confirmed replacement, completion or new task. |

Custom versus imported is event provenance, not a different category or section.
Project versus personal is task membership, not a different lifecycle.
Required versus optional is an explicit task attribute, not a separate top-level
briefing section. Do not convert importance into timing.

### Timing must be separate

- `planned_date`: the agreed day to work on an action.
- `due_date` / `due_at`: the latest acceptable completion date/time. A deadline is
  not an appointment or an agreed workday.
- Event start/end: an actual reserved interval, with timezone and duration.
- `repeat_rule`: confirmed recurring work, interpreted in its saved timezone.
- `review_after`: when a pending decision or idea should be reconsidered.
- Creation/update timestamps: audit metadata only, never scheduling instructions.

Examples:

| User input | Store/classification | Briefing owner |
| --- | --- | --- |
| `/todo Buy milk` | Open personal task; no date. | Tasks / Other open tasks when selected for display. |
| `/todo Send Atlas report by Friday` | Project task with a deadline, not a planned Friday workday. | Tasks / Deadlines when within the attention window. |
| `/todo Work on Atlas report Friday` | Task with a planned Friday occurrence. | Tasks / Friday, not Schedule. |
| `/eureka Maybe build an Atlas dashboard` | Idea; no task or calendar mutation. | Needs attention only when review was requested, is due, or an actual open decision affects current work. |
| `Plan shopping Thursday, no set time` | Task with a planned Thursday occurrence. | Tasks / Thursday. |
| `Dentist Thursday, time unknown` | Event draft with known date and unknown time. | Schedule / Time to confirm when the appointment's existence and day are confirmed. |
| `Maybe meet Sam next week if they agree` | Tentative event proposal, not an attendance commitment. | Needs attention if a decision/review is due. |
| `Wash towels every Saturday` | Recurring personal task; no clock time. | Tasks on applicable Saturdays. |
| `Work on Atlas Thursday 14:00-15:00` | Clarify whether this reserves a work block if intent is unclear. A confirmed block is an event linked to the existing task. | Schedule owns the reserved block; it may show the linked action inline instead of another identical Tasks card. |
| New imported meeting with timestamps | Staged calendar event, unapproved. | Needs attention / Calendar review; not the approved timetable. |
| Approved meeting with an unreviewed change | Keep the last approved event plus a visible change marker. | Schedule; the marker can link to its review without another event card. |

Unknown-time appointments are not all-day events. A task deadline with a timestamp
does not automatically create an event. An event's preparation note creates a
separate task only when the user has actually adopted that preparation action.

### State transitions

- Task: open, partial, blocked, done or cancelled. Deferral is a saved date, not
  completion. Only explicit user reports establish done; elapsed dates do not.
- Repeating task: the series stays active until explicitly stopped. Each
  occurrence has its own state. One completed Saturday never completes next
  Saturday's chore.
- One-off task planned over several days: a partial daily report leaves the
  action open. Completing a reserved work session is not proof that the action
  itself is finished; ask only if the reported completion scope is ambiguous.
- Idea: captured, review-requested/deferred, adopted or archived. Adoption creates
  linked action IDs only on explicit organization permission. No adopted action
  is automatically done or authorized for execution.
- Event draft: tentative, needs-details, ready-for-confirmation, converted or
  withdrawn. A tentative proposal does not reserve availability.
- Imported event: pending, approved or rejected review, with approved event
  status independently confirmed/cancelled. Keep these existing meanings.
- Project update: pending questions until confirmed reconciliation succeeds.
  Record-review state is independent of action-completion state.

## 4. Storage: one authoritative action record

Recommendation: extend the existing account-private `inbox.sqlite` rather than
introduce another independent task database. Keep `calendar.sqlite` separate for
its already reliable import/version-review model. No SQLite table corresponds to
a briefing section.

### `inbox.sqlite`

Retain existing tables:

- `entries`: immutable original input and bounded current capture/review state.
  Ideas and project reports remain here. Add a schedule-proposal capture kind and
  structured review/defer fields. A captured TODO is evidence for a task, not a
  second authoritative completion record.
- `events`: existing capture/follow-up audit and retry receipts.

Add:

- `tasks`: durable `task_id`, title/details, project alias, optionality, explicit
  priority, action status, deadline fields, recurrence/timezone, revision and
  source-entry reference. Multiple tasks may reference one source entry; the
  source-entry ID is never a unique action key. Do not split compound input into
  arbitrary subtasks unless separately supplied or explicitly requested.
- `task_occurrences`: durable occurrence identity, task ID, agreed work date,
  per-occurrence state and explicit overrides. This supports planned workdays,
  recurring chores, and confirmed partial/blocked/completed work. Completing one
  recurring occurrence never completes its whole series.
- `task_events`: task/occurrence change audit, user/session provenance and stable
  request-key receipts. Canonical mutations and receipts commit together.
- `event_drafts`: source entry, proposed/confirmed date, known details, time state,
  outstanding questions and any eventual calendar event ID. This handles an
  appointment without a time without falsifying calendar endpoints.

A TODO capture saves its raw entry and minimal open task in one SQLite transaction.
Unknown dates stay unset; preserve their supplied wording without guessing. An
idea capture saves only the idea, not a task. Follow-up input is saved before
questions, then reconciled against affected IDs/revisions.

For a repeating task, store a bounded, explicit rule rather than generating an
unlimited collection of dated rows. Compute applicable occurrence IDs
deterministically; persist assignments, reports and exceptions on authorized
writes. Reads and page opens do not initialize stores or materialize records.
Initial recurrence support should cover weekday-based chores; unsupported or
ambiguous recurrence stays recorded with a targeted question.

### `calendar.sqlite`

- Keep `events` and `history`, including source identity, original versus approved
  data, pending revisions, cancellation history and explicit timezones.
- Retain staged-review imports. New imported events stay out of the timetable
  until reviewed; an unseen change never overwrites its approved version.
- Custom event additions use an exact, confirmed event payload. Missing fields
  belong in an event draft, not fake defaults.
- Draft-to-calendar conversion uses a stable operation/draft identity. Record the
  resulting calendar ID and reconcile an interrupted conversion before retrying.
  The two databases do not provide a shared atomic transaction; do not claim they
  do. A successful calendar save with a failed draft-finalization must not create
  a duplicate event on retry or duplicate cards in the view.

### Files and snapshots

- Project Markdown retains goals, milestones, reports, access rules and optional
  authorized task references/exports. It is not a second independently completed
  task checklist. External project-plan edits become scoped reconciliation input;
  they never silently override confirmed task identity or completion.
- Daily Markdown retains run markers and factual daily feedback/history. Existing
  historical checklists remain untouched. New task identity/status lives in SQLite.
- Briefing JSON is an immutable presentation snapshot, not task storage or
  scheduling consent. Showing a task never assigns it to that day.
- `state.json` remains a derived index.
- The weekly Schedule page reads approved events and task occurrences for the
  selected week. Undated next actions and deadline-only tasks do not silently
  become a day's planned work.

## 5. Briefings and questions

Use the same nouns in both editions. Group project and personal tasks under
Tasks; label optional actions inline. Omit empty optional sections.

### Morning

1. **Schedule**: today's approved appointments/all-day events, confirmed
   unknown-time appointments clearly marked TBC, and a separate upcoming glance.
2. **Tasks**: today's agreed/recurring work; overdue and approaching deadlines;
   upcoming agreed work; selected other open actions. A task appears once, in the
   first applicable subgroup. Deadline cards retain "no workday assigned" when
   true. Project membership is shown on the card.
3. **Needs attention**: due reviews, real unresolved decisions, event details that
   affect attendance, calendar changes requiring review and relevant blockers.
   Do not manufacture clarification TODOs from every saved idea.
4. **Weather**: preserve existing weather order and material warnings.
5. **News**: preserve existing source/date/selection/delivery rules.

Morning questions are exceptional, not an intake interview. Ask only for a missing
fact or permission that changes today's safe/useful plan. Do not ask every task
for a date, priority or progress report. Optional reviews can remain visible
without blocking the edition. Never resolve another person's agreement by guess.

### Evening

1. **Today's review**: actual reported completion, partial work and blockers. The
   browser asks about today's planned occurrences and any user-reported additional
   work, not every project step or idea shown this morning. Reuse saved answers.
2. **Schedule**: tomorrow's appointments and TBC commitments, plus a clearly
   separate upcoming glance.
3. **Tasks**: tomorrow's explicitly agreed/recurring work; deadline attention;
   today's still-open work and consequential blockers. A remaining task stays
   open without acquiring tomorrow's date. Omit a general undated backlog dump.
4. **Needs attention**: review-due decisions and material unknowns affecting
   tomorrow. Respect deferrals and do not re-ask already answered questions.

Evening asks what actually happened, then asks about changed plans only when a
decision is necessary or requested. A completion report completes the exact task
or occurrence once. Partial/blocked work stays open. Attendance, silence, elapsed
time and this agent's work do not establish completion. Rescheduling requires
explicit agreement; no default rollover.

Progress narrative may mention an action that also has a future plan. That is
historical reporting, not a second actionable card. Validate outcome records and
future action ownership by purpose and source ID rather than banning all repeated
words.

### Proposed display defaults for approval

- Morning schedule/upcoming: today plus the next two calendar days.
- Evening schedule/upcoming: tomorrow plus the following two calendar days.
- Deadline attention: overdue plus the next seven calendar days; preserve the
  distinction between due date and workday.
- Other undated actions: explicit focus/priority and confirmed project next
  actions first, otherwise stable oldest-first ordering. A bounded page exposes
  counts and continuation; the agent does not silently discard later records.
- Clear ideas are not questioned nightly. Review happens on an explicit request,
  a saved review date, or a real unresolved decision affecting current work.

These are proposed product defaults, not inferred user preferences.

## 6. Helper boundaries and agent invocation

Keep the existing command facade, `python scripts/goodmorning.py`, and extend it
with a focused `task` helper. Exact CLI flags are an implementation decision; the
following operations describe the required contract, not commands available now.

| User intent | Agent invokes | Result |
| --- | --- | --- |
| Bare TODO capture | `workflow --capture todo` | Atomic original-input + minimal task save; receipt, brief confirmation, stop. |
| Bare Eureka capture | `workflow --capture eureka` | Idea save only; receipt, confirmation, stop. |
| Material follow-up | Inbox append, then revision-checked reconciliation | Preserve supplied input without re-capture or premature plan changes. |
| Save/plan a task in secretary chat | Task capture/update/plan operation | Set only supplied/authorized fields; one durable task and any agreed occurrence. |
| Save an incomplete appointment | Schedule-proposal/draft capture | Persist known details immediately; ask only for necessary missing details. |
| Add a complete custom event | Existing calendar add after required exact confirmation | Approved custom event; reuse consent already given for that exact payload. |
| Import schedules | Existing stage/show/approve workflow | Preserve provenance and review state; no raw-import timetable. |
| Adopt an idea as work | Explicit conversion linking the idea to task IDs | No duplicate capture and no implicit execution. |
| Report completion/progress | Revision-checked task/occurrence report | Update canonical state and daily factual feedback, not unrelated work. |
| Generate/regenerate a briefing | Saved preparation and existing job helper | Read/classify source-linked records; write only the authorized snapshot/run bookkeeping. |

Capture does not trigger project scans, weather/news fetching, task execution,
calendar offers or clarification interviews. For ambiguous capture, save supplied
facts first and defer interpretation. For explicitly requested scheduling or
organization, ask only the ambiguity needed to perform that requested operation.

## 7. Make routing code-owned

`workflow --prepare` / saved browser preparation should return source-linked
normalized records with:

- durable item/occurrence ID and revision;
- confirmed timing/state/project fields;
- display owner and eligibility reason;
- source evidence and outstanding questions;
- pagination and continuation counts.

Code assigns event records to Schedule, action records to Tasks, and actionable
review/decision records to Needs attention. It applies the pinned edition date,
display windows and explicit deferrals before publishing. The model writes
natural explanations and factual summaries; it does not pick a different storage
table or section from prose.

Use a source-linked native JSON revision for new editions. Readers retain v1
archive support without rewriting old files. New records carry hidden task/event
references and row purpose, so publishing can reject:

- another action card for the same occurrence;
- a task incorrectly placed as an appointment;
- an unapproved import shown as approved;
- an invented planned date or unsupported completion;
- a stale revision or superseded action version.

Define the normalized owner map before the first task/event section becomes
immutable. Regeneration uses current state but never replays task completion,
calendar conversion, external project writes or earlier consent.

## 8. Concise instruction contract

Put one short routing contract in `docs/item-taxonomy.md`; replace conflicting
paragraphs elsewhere with references. Keep examples and schema details outside
the default agent read path. The core contract should express:

1. Save material input before questions; use one stable key and check the receipt.
2. Event = attendance/reserved time; task = completable action; idea = unadopted
   possibility. Custom/imported and project/personal do not change those meanings.
3. Workday, deadline, appointment time and review date are distinct fields.
4. TODO capture creates open work, not execution; Eureka creates an idea, not work.
5. Unknown-time appointments stay event drafts; never invent a time or all-day flag.
6. Use one durable action/occurrence ID; show one actionable card per occurrence.
7. Code assigns Schedule / Tasks / Needs attention from confirmed records.
8. Showing work does not schedule it. Completion and rescheduling require actual
   user confirmation; recurring completion affects one occurrence only.
9. Morning prepares; evening records actual outcomes and previews agreed work.
10. Ask real unresolved questions only. Respect answers/deferrals; don't turn every
    idea into a daily clarification task.

The approved contract replaces, rather than supplements, contradictory ownership,
automatic idea follow-up and checklist-copy rules in core rules, workflows,
browser-generation, briefing-format, reply templates and skill-source references.

## 9. Implementation sequence and safety

1. Approve the taxonomy, section meanings and idea-review policy before behavior
   changes. Freeze a gold test matrix, including empty days and ambiguous input.
2. Add canonical task/occurrence and event-draft storage, atomic receipts, typed
   timing fields and read-only projection helpers. Preserve existing CLI clients
   through compatibility adapters; do not maintain two independently writable
   action-status stores.
3. Add owner-authorized, resumable migration with a dry-run report and SQLite API
   backups. Import explicit identities/confirmed dates; legacy `must-do` rows alone
   do not prove an agreed workday. Legacy descriptions can contain lost timing
   information; report uncertainty instead of reconstructing it from titles.
   Never merge similar titles automatically or infer completion transfer.
4. Update preparation, preflight progress selection, job publication, native
   validation/rendering, state bookkeeping and weekly schedule reads. Remove
   briefing-to-task title copying only after the canonical path is covered.
5. Replace overlapping instructions and contradictory examples. Keep account
   isolation, encryption, redaction, hash/revision checks and import review intact.
6. Run helper/unit/browser tests plus real-model trials; retain only changes that
   demonstrate a useful improvement.

Likely implementation touchpoints:

- `src/goodmorning/records/{inbox_store,inbox,workflow,daily,state}.py`
- a focused task-store/helper and routing module under `records/`
- `src/goodmorning/calendar/{calendar_store,secretary_calendar}.py`
- `src/goodmorning/briefings/{briefing_preflight,briefing_job,briefing_stream,briefing_document}.py`
- `src/goodmorning/web/schedule.py`, translated labels and briefing assets
- core/browser/workflow/format/storage docs, templates, skill-source and tests

No private data, production migration or deployment is part of this planning work.

## 10. Before/after evaluation

Use Muse Spark 1.3 Contributor with the same model configuration, synthetic
profiles, dates, inputs and approved permissions for baseline and candidate.
Use fresh sessions so the candidate cannot learn from baseline answers. Repeat
critical cases to expose variation. Expand the existing 16-case probe with:

- same action reworded, same title on different actions, and two actions from one
  capture;
- deadline versus workday versus reserved interval, including all-day/TBC cases;
- personal/project and required/optional work;
- recurrence, timezone/day rollover, DST and one-occurrence completion;
- proposed imports, changed approved events and cancellation review;
- capture-only boundaries, task-to-idea/idea-to-task requests and mode changes;
- partial completion, blockers, deferral, no automatic rollover;
- interrupted saves, retry keys, revision conflicts and regeneration;
- preserved archives, migration uncertainty, and account isolation.

Test both document-following classification and actual helper calls against private
synthetic runtimes. Inspect final database state, receipts, normalized owner maps,
questions and rendered gm/gn output. Do not accept a model saying "saved" as proof.

Acceptance criteria:

- Every gold case gets the correct type, temporal meaning, storage operation and
  section owner; ambiguity is recorded/asked, never guessed.
- Zero unauthorized execution, calendar changes, invented dates/completions,
  duplicate captures/cards, dropped subtasks, silent rollovers or cross-account
  reads/writes.
- Task identity and completion stay consistent across chat, briefings and the
  weekly page; repeating work preserves separate occurrence state.
- Existing preservation/security tests pass. Failed source reads remain visibly
  unavailable, not an empty/free day.
- Report baseline versus candidate results and remaining failures separately.
  A finite successful trial supports the tested cases, not universal reliability.

## Approval needed

The main product decision is whether to replace the two project-step sections
with **Tasks**, using project/optional labels, and replace generic Reminders/Notes
with **Needs attention**. This proposal recommends doing so. It also recommends
no automatic nightly questioning of clear ideas and no task mutation merely from
publishing a briefing. Confirm these before implementation; display windows can
be adjusted without changing the underlying taxonomy.
