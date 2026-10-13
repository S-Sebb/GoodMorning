# Items, timing and section ownership

This is the shared routing contract. Never choose a database table from a briefing
heading. Use `scripts/goodmorning.py` with the selected absolute runtime.

1. Save material input before questions. Use the actual session, one stable request
   key and a verified receipt. Reuse the key/input on uncertain retries.
2. **Event** means attendance, an explicit all-day observance or reserved time.
   **Task** means an action with a completion condition. **Idea** means a possibility
   not adopted as work. Custom/imported is provenance; project/personal and
   required/optional are task attributes, not different section types.
3. Keep workday, deadline, appointment start/end, recurrence, review date and audit
   timestamps separate. "By Friday" is a deadline; "work on Friday" is a workday.
   A timestamp alone does not establish a reserved interval. Ask when requested
   scheduling is ambiguous; never infer duration, timezone or another person's agreement.
4. `/todo` uses `workflow --capture todo`: original input and a minimal open task
   commit together. Optional `task` fields preserve supplied explicit timing and
   project facts. `/eureka` captures only an idea, even with action verbs/dates.
   Capture, confirm, stop. No automatic clarification, calendar offer or execution.
   Keep `/todo` in its capture helper even when dates are supplied: use its optional
   `task` object, not a second `task --add` capture.
5. Secretary task writes use `task --add` or revision-checked `--update`.
   `planned_date` assigns a workday; `due_date`/`due_at` does not. A repeat rule is
   `{"weekdays":[5],"start":"YYYY-MM-DD"}` with timezone (0=Monday, 6=Sunday),
   optional `until`. Unsupported recurrence remains recorded for clarification.
   "Plan shopping Thursday, no fixed time" already supplies a workday: save that
   task without asking for a clock time or place. An undated unblocked backlog
   task is a morning option, not automatically an evening still-open card. Trust
   code's date-window eligibility rather than guessing which days are displayed.
6. Unknown-time appointments use `task --capture-draft` with raw input and a
   `draft` object: title, date, timezone, location/detail, `confirmed_day` boolean.
   A confirmed day displays TBC in Schedule; a tentative proposal reserves nothing.
   Never substitute all-day. Complete drafts convert through `task --convert ID
   --expect-revision REV --confirm` with `{"event":CALENDAR_PAYLOAD}` after exact
   confirmation. Resume the same conversion key/input after uncertain outcomes.
   Save complete appointment requests before awaiting confirmation too: draft
   `state:"ready-for-confirmation"` with `event:CALENDAR_PAYLOAD` preserves known
   times without adding an approved event. Needs attention requests confirmation.
   Both fields are inside `draft`; set `confirmed_day:false` until approval:
   `{"raw":"Add dentist Thursday...","draft":{"title":"Dentist",
   "state":"ready-for-confirmation","confirmed_day":false,"event":{
   "subject":"Dentist","start":"2026-10-15T14:00:00+01:00",
   "end":"2026-10-15T15:00:00+01:00","location":"Town Clinic"}}}`.
   A bare "every Saturday" request is forward-looking; anchor its repeat start to
   the confirmed current local capture date, not a guessed historical start. Ask
   about start only when the user indicates a different or ambiguous effective date.
7. Ideas/project reports become actions only on requested organization: `task
   --adopt ENTRY --expect-revision REV --confirm` with `{"tasks":[TASK_FIELDS,...]}`.
   Reconcile saved follow-ups first. Several actions can share one capture; do not
   deduplicate by source-entry ID or split compound wording without authorization.
   To split an existing TODO on explicit request, the same operation also requires
   `replace:[{"id":"task_ID","revision":REV},...]`. It supersedes only those exact
   source-linked actions, preserves their history and atomically creates the
   requested subtasks. It never transfers completion by similar wording.
8. Code owns placement. `task --briefing gm|gn --date PINNED_DATE` returns normalized
   items and ready-to-use source-linked `blocks`; omit empty blocks. Follow
   `next_offset` with the same date/edition and retain counts/material warnings.
   **Schedule** owns events; **Tasks** owns project/personal actions; **Needs
   attention** owns due reviews and real unresolved decisions. Preserve source
   IDs/revisions/titles/dates/status. One actionable card per occurrence.
   Browser recipes use `--section schedule|tasks|attention|today`: return only that
   section's rows, `block`, counts and warnings, avoiding repeated whole-plan reads.
9. Morning shows agreed work, deadlines and other open actions; evening reviews
   actual outcomes and previews agreed work. Evening completion choices cover
   today's planned occurrences, not every undated action shown in the morning.
   Reuse browser feedback. Never infer progress or roll work into tomorrow.
   Say "still open on its original workday", not "carries/rolls over", unless a
   new date was explicitly agreed. Say "no other saved appointments", not a
   "clear/free day": open work and unknown availability remain separate.
   Card counts establish neither a light/heavy workload nor a duration estimate.
10. Complete exact tasks through `task --update` or exact recurring occurrences
    through `task --report ID --date DATE`, both with revision, session, request key
    and `confirmed_completion:true` for done. A work-session report does not
    establish completion of its larger action. Stop a recurring series explicitly;
    completing one occurrence never completes later dates.
11. Publishing/regenerating a v2 briefing never creates/schedules/completes tasks.
    Project Markdown supplies goals/reports, daily Markdown supplies historical
    feedback, and SQLite owns live task state. No task table represents a section.
12. Clear ideas are not nightly questions. Surface actual saved questions,
    unreviewed material or a due `review_after`; respect future review dates and
    existing answers. Ask only unresolved material facts/consent needed for the
    requested work. A review can remain pending without blocking other sections.

All task/draft operations use `inbox.sqlite` tables `tasks`, `task_occurrences`,
`task_events`, `event_drafts`; ideas/reports remain in `entries`/`events`.
Approved/imported calendar versions remain in `calendar.sqlite`.
Writes accept JSON stdin (`--input-stdin`) or `--input-json`; task/draft reads use
`task --show ID` (`--draft` for drafts). Task captures return `task_id`, drafts
return `draft_id`. They do not authorize doing the captured work.

Existing v1 storage needs explicit migration: `task --migrate` is a read-only
report; `task --migrate --confirm` backs up SQLite and upgrades it. It preserves
captures/history and imports inbox TODOs without guessing dates. Legacy daily and
project checklists require explicit identity/date reconciliation; never silently
merge titles or infer that a legacy daily row was an agreed workday. Do not run
migrations or project-file edits without owner authorization.
