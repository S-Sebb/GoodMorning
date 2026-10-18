# Items, timing and section ownership

This is the shared routing contract. Never choose a database table from a briefing
heading. Use `scripts/goodmorning.py` with the selected absolute runtime.

1. Save clear material input with the actual session, stable key and receipt.
   Ambiguous scheduling must first use a native browser question: write no inbox
   entry, pending note, task, draft or calendar event until answered. Conversation
   messages/forms stay durable and visible through the Little desk waiting badge.
   Save the resolved input once; reuse the key/input on uncertain retries.
2. **Categories.** Use the first that fits. Code derives each saved item's
   `category` from its fields (`task --show` returns it); never store a label instead.
   1. **Appointment**, reserved time the user attends: a calendar event with exact
      times, or an event draft for a known day with time TBC (rule 6). A weekly
      TBC series is one draft with `repeat:{"weekdays":[N],"start":DATE,"until":DATE}`
      (`start` equals `date`), never one draft per week.
   2. **Occasion**, a date to remember: an all-day calendar event. Birthdays and
      anniversaries use `repeat:{"yearly":true,"start":DATE}`. Describe it to the
      user by its date ("every 6 January"), never by the exclusive end date.
   3. **Idea**, a possibility not adopted as work (idea capture, `docs/workflows/eureka.md`).
   4. **Nudge**, a heads-up with nothing to tick off ("bring gym clothes on
      training days", "check the price"): task `kind:"nudge"`. Its trigger is a
      `repeat`, `planned_date`, `when.planned_task_id` or `when.custom_rule_id`
      (habit days); with none it appears every morning until cancelled. For "on
      my X days", first match a saved plan (`workflow --prepare secretary` lists
      `habits`; `task --briefing` shows routines); ask only if none matches. Never
      asked at night or completed; retire it with `status:"cancelled"`.
   5. **Errand**, work the user asks the secretary itself to do ("check the chair
      price for me and tell me when it's under £120", "look up whether the library
      has the book"): task `kind:"errand"`. `title` is the job ("Check the black SIHOO
      M18 price on Amazon UK"); `detail` is the instruction in the user's terms: what
      to find and when to tell them ("Tell me only when it is under £120."). The
      secretary does it while writing each morning briefing on the nudge triggers
      above and shows a card only when the result is worth telling; nothing is
      shown otherwise. Never asked at night or completed; retire it with
      `status:"cancelled"`. Never save as a nudge something the user asked you to do.
      Checking a published calendar link is not an errand: save the feed with
      `calendar --sync-ics` (`docs/calendar-pipeline.md`), which briefings sync themselves.
      Before saving: if the condition, source or rhythm is unclear ("when it's
      cheap", no shop named), ask first. Then do the errand once now with your own
      tools; only a figure read on the source page itself counts, not a search
      snippet. If it works, save it with that result in `extra` and its card heading in
      `display` (see Display wording below), and tell the user
      ("It's £139.99 now, so I'll stay quiet until it's under £120."). If you cannot get a
      reliable result, save nothing yet: say plainly that you could not check it and
      offer alternatives with a native question (a source you did read, a daily
      nudge for them to check it themselves, or leaving it), then save only the choice.
   6. **Reference note**, saved information for a trigger the system cannot see
      ("when a supplement runs out, rebuy brand X"): `kind:"reference"`, `trigger`,
      `detail`, no dates or conditions. Never in briefings; `workflow --prepare
      secretary` lists `references`, so match the user's words to a trigger there.
   7. **Routine**, a fixed rhythm: task `repeat` (weekdays, interval, explicit
      dates), or `{"event_subject":"Lab meeting","offset_days":-1,"start":DATE}`
      for preparation that follows every approved appointment with that exact subject.
   8. **Habit**, a rhythm that follows actual completion, chases misses or has a
      weekly cap: `custom --add` (rule 5).
   9. **Project step**, work toward a project goal: `project`, optional `optional`,
      soft target `due_soft:true`, and `after:"task_ID"` when it waits for another step.
   10. One-off action: an agreed day is a **Day task** (`planned_date`); "must be
      done by" is a **Deadline task** (`due_date`; window start `defer_until`);
      neither is an **Anytime task**.
   Shared attributes: `when` conditions; `follow_up:"until-done"` brings a one-off
   up every day from its start until confirmed done (not a repeat; one tick closes
   it); `project`, `optional`, `priority`. A hard deadline needs a real outside
   consequence the user stated; never invent one. When one request is two items
   (watch + act, weekly check-in + final deadline), confirm the split, then save
   one capture with `task` plus `also:[{...}]` siblings. Custom/imported is provenance.
   **Where text goes.** `detail` is what the user sees: 1–2 sentences of why, current
   state or next step. `extra` (any task or draft, at most 2000 characters) is the
   secretary's own dated notes for next time: what it found or observed, progress
   history, what failed and why, linked IDs, a preference the user mentioned; newest
   first, short, never credentials, never a substitute for structured fields. The
   inbox entry `context` records the request as agreed at capture; do not copy it
   into `detail` or `extra`. Sort every new or changed item this way in the
   conversation, before saving, and confirm what was saved; briefings only read it.
   **Display wording** (`display`, tasks including errands, drafts and calendar events;
   not reference notes) is how the item reads on each page, decided when you save it:
   `{"en":{"morning":{"title","detail"},"evening":{"title","detail"},"schedule":"…"},"zh":{…}}`.
   Write both languages every time you create an item or change its title, detail,
   kind, project, subject, location or notes. **morning** gets it done today: the
   action and the key detail needed to do it. **evening** gets the user ready for
   tomorrow: what to prepare tonight, or a heads-up; omit it when it would read the
   same as morning. **schedule** is a short label for the week grid (at most 40
   characters). Titles are clear imperatives or the appointment's name; details are
   one plain sentence or empty. Never write dates, times, "today"/"tomorrow", status
   or project/deadline labels: pages add those ("tonight" is fine in evening wording). Example for "Call the IT helpdesk,
   ext. 4471, about the receipt upload error": morning `{"title":"Call extension 4471
   about the receipt upload error","detail":""}`, evening `{"title":"IT helpdesk
   call","detail":"Have a screenshot of the upload error ready."}`, schedule "IT
   helpdesk call". Code fingerprints the described fields: when they change without
   new wording, pages fall back to the saved fields until you write it again. For an
   errand only the morning title is shown, as the heading of its result card; leave
   its detail empty and give it a schedule label anyway (the check requires one).
   When the user asks how an item should read on a page ("show X in my morning
   briefing as Y"), read it with `task --show` (or `calendar --show`), change only that
   place, use their words as given and adapt the other language to match, keep the
   other places, and save the whole `display` with a revision-checked update. If their
   words include a relative time such as "tomorrow", explain that pages add the day
   and ask how to word it without it.
   **Advance notice** (`notice`) fits any dated item: tasks with `planned_date`,
   `repeat` or `due_date`, TBC drafts, and calendar events. `{"morning":N}` shows it in
   morning briefings from N days before its day (0 = on the day); `{"evening":N}` in
   evening briefings from N days before (1 = the night before, 0 = never); tasks add
   `"early":false` when it can only be done on its day (shown as a heads-up, never
   offered as done early) or `true` when doing it beforehand counts. Save what the user
   states. Otherwise judge from the item: a gift or booking for an occasion needs days,
   a form due Friday that can be sent any time is `early:true`, claiming this week's pay
   on Friday is `early:false`; say the chosen notice in the confirmation in plain words
   and ask only when you cannot tell. Leave it out when the default fits (on the day;
   hard deadlines seven mornings and the night before).
3. Keep workday, deadline, appointment start/end, recurrence, review date and audit
   timestamps separate. "By Friday" is a deadline; "work on Friday" is a workday.
   A timestamp alone does not establish a reserved interval. A window without a
   frequency ("11月初", "early November") is ambiguous between one-off and
   repeat: ask frequency and start date, never default to one-off or strand the
   window in prose without a structured repeat, workday, or deadline. One action
   done once inside a stated window ("buy it sometime between 23 and 28 October")
   is not ambiguous: a Deadline task with `defer_until` 23 and `due_date` 28. "Remind me
   daily until it's done" is a one-off with `follow_up:"until-done"`, not a repeat. Ask when requested
   scheduling is ambiguous; never infer duration, timezone or another person's agreement.
4. To-do capture (`docs/workflows/todo.md`) uses `workflow --capture todo`: exact raw input plus a revised clear task
   commit together. `raw` stays verbatim for audit; `summary` and `task.title` carry the
   improved imperative title and `task.detail` carries 1–2 grounded sentences (why it
   matters plus current state or next step from supplied facts only). Optional `task`
   fields preserve supplied explicit timing and project facts. `detail` is useful extra
   notes only: never repeat the title, project, deadline or priority — those live in structured fields and the page already
   shows them once per project group. This holds for every task write, not only to-do capture. Rhythm and presentation mechanics plus setup
   narration stay in structured repeat/when fields, the inbox entry `context` (the request as agreed)
   or the task's `extra` (notes for next time), never in `detail`. Idea capture saves only an idea, even with action verbs/dates.
   For clear input, capture, confirm, stop. The clarification-before-recording rule
   above applies to ambiguous scheduling; no unsolicited calendar offer or execution.
   Keep to-do capture in its helper even when dates are supplied: use its optional
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
   is not a reserved-time plan. A clothing nudge uses
   `when:{"planned_task_id":"task_ID"}` for a task plan or
   `when:{"custom_rule_id":"cu_ID"}` for a habit, without its own repeat/planned
   date, so it follows that plan's due days.
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
   Never substitute all-day. A series draft converts with the first date's confirmed
   time and needs `until`; code adds every remaining date at that local time.
   Complete drafts convert through `task --convert ID
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
   A Today read with no outcome cards returns `block: null`, never an empty card list.
9. Each edition has one focus day: the morning shows today, the evening previews
    tomorrow. Appointments, occasions, TBC days, day tasks, routines, habits and
    nudges and errands appear only on their own day unless they carry a `notice`. The other
    exceptions are hard deadlines (default morning: due within seven days or
    overdue; evening: due tomorrow or overdue), work still open from an earlier
    day, and morning daily follow-ups. Earlier cards appear under "Coming up". Morning also offers at most three steps per project (required
    before optional) and other open actions; evening reviews actual outcomes. Nudges, errands and reference notes are
    never evening questions; a step waiting on `after` stays hidden until that task
    closes. The Schedule tab shows deadlines on their due day, marked "no workday
    assigned", and habit days marked flexible. Evening completion choices cover
    today's planned occurrences, daily follow-ups, hard deadlines due today or overdue,
    plus still-open tasks in today's saved morning briefing; project steps from it
    also get one optional progress box per project (up to three).
    Present them split: due-today checks first, then an optional Future tasks
    section for undated background and upcoming dated work ticked only if fully
    done early (overdue morning work stays with due-today). Group browser completion choices by current canonical project; unassigned
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
    Records are shaped in the conversation that receives the request; a briefing
    makes no task writes of its own (saved evening feedback is still recorded). It
    presents rows with their saved `display` wording; only rows without fresh
    wording may be reworded for the page (same meaning, no new facts), never the record. Errand results live in the saved morning edition (`errands` rows with a
    private `note`); the next morning reads the latest one as `last`. Project Markdown supplies goals/reports, daily Markdown supplies historical
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
