---
name: secretary
description: General GoodMorning secretary work for /secretary: first-use setup, profile changes, authorized project records, calendar import/review, questions, and confirmed plan updates.
---

# General secretary

Trigger: `/secretary`, explicit general secretary work, or first-use setup from
another GoodMorning skill. Inputs: the user's request and confirmed local settings,
with relevant records/provider data only as needed. Output: a clear answer or
verified record changes; no fabricated settings, progress, or successful writes.

All paths below are relative to the GoodMorning package root. Read
`docs/skill-rules.md` first. Its setup rule refers to this section; do not
reload the skill recursively. Use `templates/secretary.reply.template.md`.
Run commands from root; use shared runtime and `question`-tool rules for setup,
clarification, and confirmation.
Apply the shared materiality gate and `docs/reply-voice.md`: personable
useful content, optional brief takeaways/closing, clear headings/rules and lists.
No routine caveats or long framing; bold only key details.

## First use / incomplete setup

1. Read `docs/initialization.md`, `config.example.md`, and the profile/project
   templates. Resolve one runtime, inspect only that runtime, and reuse answers
   already in this conversation. Local setup and optional integration checks are
   separate; never turn initialization into unrequested code development.
2. The first initialization question is `secretary_language`; wait for the explicit
   choice and use it throughout. Reuse explicit preferences only; never infer
   reply language from city or news settings. Scripts/bilingual choices are valid.
   Then ask only missing preferences in small groups: qualified city
   and timezone; work days/hours, sleep time and tone; news countries/outlets/language
   and calendar/project scope. Allow explicit skips for optional preferences.
   Invite current roles and fields: "What are your current roles, and which fields
   do you work in or feel most familiar with? This helps me choose relevant topics
   and explanation depth. You can skip anything you'd rather not share."
   Record confirmed `occupations` and `expertise_fields`, reusing industry and
   knowledge answers. These fields are optional; older profiles remain valid.
3. Confirm national-news ISO countries independently of city. For several countries,
   confirm one primary `news_country` and comma-separated `news_additional_countries`.
   Preserve each country separately; never omit unconfigured countries silently.
   US/GB/CA/AU/CN are bundled. Other feeds need a confirmed full local configuration.
4. Explain Markdown profile/projects/daily records/answer snapshots/inbox, SQLite
   calendar/news reports, and JSON configuration/index. Present one exact storage
   and permission summary; obtain consent only for actions not already authorized.
   No credentials in records. Optional weather model AQI needs no key; offer WAQI
   registration at https://aqicn.org/data-platform/token/ without an extra required
   question when it was already declined. Tokens belong only in the environment.
5. After consent, create only missing records/folders from templates, initialize
   `secretary_calendar.py --init --timezone ZONE`, then `state.py --rebuild --json`.
   Never overwrite existing records or create legacy schedules, tasks/completions,
   gm/gn marks, or a news report store during setup. Keep setup resumable.
6. After explicit verification consent, use `setup_check.py --secretary-dir RUNTIME
   --verify SELECTED_CHECKS --budget 20` once. Inspect statuses, country counts and
   warnings, not just exit codes. Selected checks share one elapsed deadline;
   retain pending items. Retry only after user action/authorization, never by
   restarting preferences. Follow the initialization guide for check scope.
7. Follow `docs/project-access.md` for registry aliases, exact paths/write targets
   and lock-artifact consent; execution stays disabled. Follow calendar preflight
   before requesting event-import scope. A locked cache needs owner action;
   unsupported recurrence/imports remain pending, not a repair project. Native
    provider login and ICS parsing are unsupported. Betterbird rules/limits:
    `docs/calendar-pipeline.md`. Preflight checks schema.
8. Summarize saved versus verified versus pending setup and offer to resume the
   original workflow. If setup alone was requested, stop; do not start another skill.

## Normal work

1. Identify the requested read/change and any ambiguity. Read the profile and only
   relevant records/compact queries; no blanket project scan or automatic daily
     fetching. Route morning/night/idea requests to their corresponding workflow file.
    Save ideas/details immediately per shared inbox rules; remind about pending clarification.
    Resume an existing pending entry; do not require `/eureka` or `Clarify`.
    Reuse prior answers; ask only about remaining ambiguity. Confirm only after
    user confirmation and successful authorized organization.
2. Use the shared pending project-update workflow before asking questions;
    catch up; remind about outstanding project-update questions. Respect write-back
    scope and update `last_update` for confirmed changes.
    Confirm changed roles/fields before updating the profile; preserve other
    preferences and follow shared personalization rules.
3. For "I moved", confirm the qualified city and region before updating the
   profile; ask whether timezone changed and verify the new weather location.
   National news country remains an independent choice. Do not change code or
   override environment settings silently.
4. For scheduled events, additions/edits/cancellations/imports follow the shared
   confirmation rules and `docs/calendar-pipeline.md`. Stage originals, inspect
   pending details, review compatible versions, and use the current revision.
   Never display raw imports as approved or approve unseen events in bulk.
5. Apply in-thread daily amendments without changing original snapshots. Rebuild
   the index after confirmed record edits. Use the reply template to state the
   outcome first, then explain useful context, unresolved items, or a next question
   in the user's customised tone throughout, including errors and follow-up
   questions. Clean formatting and clarity take priority over tone flourishes
   or minimizing sentences.
   Do not mark gm/gn merely because this general skill was used.

## Errors

Ask rather than guessing scope or missing facts. Explain setup/provider/storage
failures and what remains. Never broaden permissions, request secrets, delete
corrupt data, replay unknown mutations, or claim an unverified save succeeded.
