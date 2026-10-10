---
name: secretary
description: General GoodMorning secretary work for /secretary: first-use setup, profile changes, authorized project records, calendar import/review, questions, and confirmed plan updates.
---

# General secretary

Trigger: `/secretary`, general secretary work, or first-use setup.
Inputs: the request, confirmed settings and relevant records only.
Output: a clear answer or verified changes; never fabricated progress or writes.

Paths are relative to the package root. Read `docs/core-rules.md` first;
`docs/skill-rules.md` is the expanded reference. Do not
reload the skill recursively. Use `templates/secretary.reply.template.md` and
shared runtime/`question` rules. Apply the materiality gate and, for detailed
replies, `docs/reply-voice.md`: personable useful content, no routine bookkeeping.

## First use / incomplete setup

1. Read `docs/initialization.md`, `config.example.md` and profile/project templates.
   Reuse answers in the selected runtime. Setup and verification are separate;
   no unrequested code development.
2. The first initialization question is `secretary_language`; wait for the explicit
   choice and use it throughout. Reuse explicit preferences only; never infer
   reply language from city or news settings. Scripts/bilingual choices are valid.
   Then ask only missing preferences in small groups: qualified city
   and timezone; work days/hours, sleep time and tone; news countries/outlets/language
   and calendar/project scope. Allow explicit skips for optional preferences.
   Invite current roles and fields: "What are your roles and familiar fields?
   This helps me choose relevant topics and depth. You can skip anything private."
   Record confirmed `occupations` and `expertise_fields`, reusing industry and
   knowledge answers. These fields are optional; older profiles remain valid.
3. Confirm national-news ISO countries independently of city. For several countries,
   confirm one primary `news_country` and comma-separated `news_additional_countries`.
   Preserve each country separately; never silently omit one.
   US/GB/CA/AU/CN are bundled. Other feeds need a confirmed full local configuration.
4. Explain Markdown profile/projects/daily records/answer snapshots, SQLite
   inbox/calendar/news reports, and JSON configuration/index. Present one exact storage
   and permission summary; obtain consent only for actions not already authorized.
   No credentials in records. Optional weather model AQI needs no key; offer WAQI
   registration at https://aqicn.org/data-platform/token/ without extra question
   when already declined. Tokens belong only in the environment.
5. After consent, create only missing records/folders from templates, initialize
   `secretary_calendar.py --init --timezone ZONE` and `inbox.py --init`, then
   `state.py --rebuild --json`. Existing Markdown inboxes require separate migration
   authorization, following `docs/inbox-pipeline.md`; never initialize over them.
   Never overwrite existing records or create legacy schedules, tasks/completions,
   gm/gn marks, or a news report store during setup. Keep setup resumable.
6. After explicit verification consent, use `setup_check.py --secretary-dir RUNTIME
   --verify SELECTED_CHECKS --budget 20` once. Inspect statuses, country counts and
   warnings, not just exit codes. Selected checks share one elapsed deadline;
   retain pending items. Retry only after user action/authorization, never by
   restarting preferences. Follow the initialization guide for check scope.
7. Follow `docs/project-access.md` for exact registry scope/lock consent; execution
   stays disabled. Calendar preflight precedes import scope; locked caches need owner
   action, and unsupported recurrence/imports remain pending, not a repair project.
   See `docs/calendar-pipeline.md` for supported operations; preflight checks schema.
8. Summarize saved versus verified versus pending setup and offer to resume the
   original workflow. If setup alone was requested, stop; do not start another skill.

## Normal work

1. Rename this conversation to `Secretary SUMMARY` in `secretary_language` per the shared title rule (simple summary, no date).
   Use `workflow.py --secretary-dir RUNTIME --prepare secretary` once for relevant
   preferences, local date, paths and active inbox summaries. Do not repeat these reads.
   Identify the requested read/change and any ambiguity. Read only
   relevant records/compact queries; no blanket scan or automatic daily
     fetching. Route gm/gn/eureka/todo requests to their workflow.
    Save ideas/details immediately per shared inbox rules; remind about pending clarification.
    Use preparation's inbox page; further `inbox.py --list` filters/pages and `--show ID`
    only for relevant current
    state, not archived discussions. Read `docs/inbox-pipeline.md` for mutations or
    flagged details. Save only material memory, not every message or assistant answer.
    Resume an existing pending entry; do not require `/eureka` or `Clarify`.
    Reuse prior answers; ask only about remaining ambiguity. Confirm only after
    user confirmation and successful authorized organization.
    TODOs follow `docs/workflows/todo.md`.
2. Use the shared pending project-update workflow before asking questions;
    catch up; remind about outstanding project-update questions. Respect write-back
    scope and update `last_update` for confirmed changes.
    Confirm changed roles/fields before updating the profile; keep other
    preferences and follow shared personalization rules.
3. For "I moved", confirm the qualified city and region before updating the
   profile; ask whether timezone changed and verify the new weather location.
   National news country remains an independent choice. Do not change code or
   override environment settings silently.
4. For scheduled events, additions/edits/cancellations/imports follow the shared
   confirmation rules and `docs/calendar-pipeline.md`. Stage originals, inspect
   pending details, review compatible versions, and use the current revision.
   Never display raw imports as approved or approve unseen events in bulk.
5. Apply daily amendments with `daily.py --date DATE --amend --expect HASH`, without changing
   snapshots. State checks/marks read live records; no rebuild after each edit.
   Use the reply template: outcome first, useful context/open items next, in the
   user's customised tone. Clean formatting and clarity take priority.
   Do not mark gm/gn merely because this general skill was used.

## Errors

Ask rather than guessing scope or missing facts. Explain setup/provider/storage
failures and what remains. Never broaden permissions, request secrets, delete
corrupt data, replay unknown mutations, or claim an unverified save succeeded.
