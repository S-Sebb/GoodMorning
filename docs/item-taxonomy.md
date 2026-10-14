# Items, timing and section ownership

This is the shared routing contract. Never choose a database table from a briefing
heading. Use `scripts/goodmorning.py` with the selected absolute runtime.

1. Save clear material input with the actual session, stable key and receipt.
   Ambiguous scheduling must first use a native browser question: write no inbox
   entry, pending note, task, draft or calendar event until answered. Conversation
   messages/forms stay durable and visible through the Little desk waiting badge.
   Save the resolved input once; reuse the key/input on uncertain retries.
2. **Event** means attendance, an explicit all-day observance or reserved time.
   **Task** means an action with a completion condition. **Idea** means a possibility
   not adopted as work. Custom/imported is provenance; project/personal and
   required/optional are task attributes, not different section types.
3. Keep workday, deadline, appointment start/end, recurrence, review date and audit
   timestamps separate. "By Friday" is a deadline; "work on Friday" is a workday.
   A timestamp alone does not establish a reserved interval. Ask when requested
   scheduling is ambiguous; never infer duration, timezone or another person's agreement.
4. `/todo` uses `workflow --capture todo`: exact raw input plus a revised clear task
   commit together. `raw` stays verbatim for audit; `summary` and `task.title` carry the
   improved imperative title and `task.detail` carries 1–2 grounded sentences (why it
   matters plus current state or next step from supplied facts only). Optional `task`
   fields preserve supplied explicit timing and project facts. `detail` is useful extra
   notes only: never repeat the title, project, deadline or priority — those live in structured fields and the page already
   shows them once per project group. `/eureka` captures only an idea, even with action verbs/dates.
   For clear input, capture, confirm, stop. The clarification-before-recording rule
   above applies to ambiguous scheduling; no unsolicited calendar offer or execution.
   Keep `/todo` in its capture helper even when dates are supplied: use its optional
   `task` object, not a second `task --add` capture.
5. Secretary task writes use `task --add` or revision-checked `--update`.
   `planned_date` assigns a workday; `due_date`/`due_at` does not. A repeat rule is
   `{"weekdays":[5],"start":"YYYY-MM-DD"}` with timezone (0=Monday, 6=Sunday),
   optional `until`. Clarify ambiguous requested recurrence before recording it.
   Repeats also support `interval_days` or explicit `dates` instead of `weekdays`,
   and optional `include`/`exclude` dates for confirmed exceptions; every rule needs
    `start` and timezone. Exclusions win; bounds still apply to inclusions.
    A forward-looking repeat without a supplied start uses the confirmed current
    local capture date and saved timezone. Ask about start only when the user
    indicates a different or ambiguous effective date; ask only for other unresolved
    fields, such as an unclear interval. This default applies to all supported repeats.
    Never approximate an every-two-day rule with weekly weekdays. Unsupported or ambiguous
   requested rules require clarification before a write, not an unscheduled capture.
   A confirmed morning trigger uses task `when:{"morning_before":"10:00"}` with
   explicit timezone and any weekday rule. Code checks the original generation
   request timestamp, including queue arrival, not completion time or wake time.
   Exactly 10:00 is excluded. Unknown future triggers reserve no day; regeneration
   retains the original trigger. The underlying task can still have actual reports.
   `when:{"unless_experiment_plan":true}` suppresses a reminder only on dates with
   approved calendar text containing “实验” or dated, concrete task plans tagged
   `work_kind:"experiment"`. Generic ideas/mentions are not experiment plans.
   `follow_up:"one-outstanding"` with an interval rule keeps one latest outstanding
   reminder, no makeup backlog. Confirmed actual completion clears that reminder
   without changing the original cadence or claiming completion on missed dates.
   Fixed repeats never shift, re-anchor to a finish, or stop after a weekly count.
   When a request needs that flexibility, use a custom schedule, not a fixed repeat.
   Ask with native questions until rhythm, start, restart rule, miss rule, weekly
   limit and nightly checks are unambiguous; write nothing until answered. Save once
   with `custom --add` (session, stable key, receipt). Code computes due dates from
   the saved rule plus user-confirmed completions; the secretary words the result
   without inventing dates. Example: every 2 days from 2026-10-13, restart from each
   finish, chase misses daily, stop at 3 per Mon-Sun week, check every evening.
   Counter-example: “gym regularly” without rhythm or limit stays in conversation only.
   Completions use `custom --report --date ACTUAL_DAY` with revision, session, key
   and `confirmed_completion:true`; future dates are refused. Confirmations name
   the workflow's pinned date as today; never advance it by a day. Morning and evening
   briefings read code-owned `custom --briefing` rows; evening checkboxes complete
   exact custom IDs like tasks. Silence never counts.
   `when:{"unless_timed_plan":true}` also suppresses on days with approved timed
   calendar appointments, even outside the activity window; an all-day birthday
   is not a reserved-time plan. A clothing reminder uses
   `when:{"planned_task_id":"task_ID"}` without its own repeat/planned date, so it
   follows the canonical workout plan, not off-cadence actual completions.
   Soft project targets use `due_soft:true` and are labelled as soft, not hard deadlines.
   "Plan shopping Thursday, no fixed time" already supplies a workday: save that
   task without asking for a clock time or place. An undated unblocked backlog
   task is a morning option, not automatically an evening still-open card. Trust
   code's date-window eligibility rather than guessing which days are displayed.
6. Unknown-time appointments use `task --capture-draft` with raw input and a
   `draft` object: title, date, timezone, location/detail, `confirmed_day` boolean.
    A confirmed day displays TBC in Schedule; a tentative proposal reserves nothing.
    If the user already confirms attendance, a clear day and place, and explicitly
    leaves the time unknown, save the confirmed TBC draft directly. Resolve a clear
    weekday from the confirmed current date/timezone. Do not ask for a clock time,
    duration or repeated approval merely to save that draft; ask only genuinely
    missing or ambiguous facts. Timed conversion still requires exact approved details.
   Never substitute all-day. Complete drafts convert through `task --convert ID
   --expect-revision REV --confirm` with `{"event":CALENDAR_PAYLOAD}` after exact
   confirmation. Resume the same conversion key/input after uncertain outcomes.
    For a complete appointment awaiting conversion, obtain any missing facts and
    exact approval through a question only if not already supplied. After approval,
    `state:"ready-for-confirmation"`
   with `event:CALENDAR_PAYLOAD` can be the retry-safe intermediate before conversion.
   Both fields are inside `draft`; set `confirmed_day:false` until approval:
   After the user has answered/approved: `{"raw":"Add dentist Thursday...","draft":{"title":"Dentist",
   "state":"ready-for-confirmation","confirmed_day":false,"event":{
   "subject":"Dentist","start":"2026-10-15T14:00:00+01:00",
   "end":"2026-10-15T15:00:00+01:00","location":"Town Clinic"}}}`.
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
   **Schedule** owns events; **Tasks** owns project/personal actions; **Reminders**
   owns due reviews and real unresolved decisions. Preserve source
   IDs/revisions/titles/dates/status. One actionable card per occurrence.
   Browser recipes use `--section schedule|tasks|attention|today`: return only that
   section's rows, `block`, counts and warnings, avoiding repeated whole-plan reads.
9. Morning shows agreed work, deadlines and other open actions; evening reviews
    actual outcomes and previews agreed work. Evening completion choices cover
    today's planned occurrences plus still-open tasks in today's saved morning briefing.
    Group browser completion choices by current canonical project; unassigned
    work belongs under “Other tasks”, after every named project. “None of these
    today” stays outside the groups. Use clear, friendly wording and place the
    progress text box above the mutually exclusive “Nothing else to add” choice.
    Selecting an undated or differently dated morning task reports actual completion
    today without assigning a workday or changing recurring rules. Archived titles,
    revisions and statuses never override current task state. Unchecked choices stay
    open, not assumed failed or overdue. If there are no choices, ask about actual
    accomplishments/progress with a text answer or “Nothing extra to add today”;
    omit the completion checkbox question and “None of these today.”
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
    A confirmed completion outside the planned dates uses `--report ID --actual
    --date ACTUAL_DAY` with `confirmed_completion:true`; future completion is refused.
    It records the actual day, not a replacement workday. One-off actions close;
    recurring series retain their original rule.
11. Publishing/regenerating a v2 briefing never creates/schedules/completes tasks.
    The one allowed pre-presentation maintenance is wording polish: after reading the
    Tasks section rows, the secretary may fix materially vague titles/details with
    revision-checked `task --update` (title/detail only, same meaning, no date/status/
    project/scheduling changes, stable `polish:SESSION:taskID:revision` keys), then reread
    and pack the exact updated rows. Project Markdown supplies goals/reports, daily Markdown supplies historical
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

For a reviewed v1 migration, supply JSON `{"reviewed_tasks":{"ib_ID":[TASK_FIELDS],...}}`
to `task --migrate` with the actual session; confirm only after the dry run and
encrypted rollback snapshot. Account for every captured TODO, including an empty
list for reference-only records, duplicates and calendar-owned attendance.
Use explicit `status:"cancelled"` for cancelled actions, not `done`. Additional
authorized actions may reference existing idea/project-update captures. The
upgrade preserves every original capture/audit row and records a separate reviewed
migration receipt. It creates no guessed daily outcomes and rewrites no Markdown.
