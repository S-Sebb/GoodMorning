---
name: gm
description: Morning briefing: weather, yesterday's news, approved schedule, priorities and optional dated latest developments. Save without duplicate runs.
---

# Morning briefing

Trigger: `/gm` or a morning briefing request.
Inputs: preferences, session/date and records.
Output: JSON and daily record; delivery is separate.

Paths are package-root relative. Read `docs/core-rules.md`; `docs/skill-rules.md` is for audits.
Use `docs/briefing-format.md` and `templates/daily.template.md`; the native authoring
guide is `templates/gm.reply.template.md`. Python commands below use
`python scripts/goodmorning.py COMMAND`. Run from root with shared runtime/date rules;
use `question` for missed runs, unclear tasks and consent.
Apply the materiality gate and `docs/reply-voice.md`: personable sections, ordered
weather, cited factual news and calendar timetables. Omit routine bookkeeping and repetition.

## Steps

Browser jobs: read `docs/browser-generation.md` before step 1. Initialize after its
decisions, before fetching; follow its recipes and publish top-down, not at step 6.

1. Browser jobs use the job helper's saved preparation; do not rerun it or repeat
   answered decisions. Other invocations use the confirmed tone and run
   `workflow --secretary-dir RUNTIME --prepare gm`. Use its dates,
   preferences, paths, daily task page and active inbox page; do not repeat those reads.
   Handle duplicates and missed runs
   before fetching. For a duplicate, identify its session and stop; no refresh.
    Rename new runs to `GoodMorning DATE` in the browser job's website language, or `secretary_language` for local use, per the shared title rule.
2. For today, run `weather` once with the profile's qualified city using
   explicit `--city CITY` (and `--profile PATH` when relocated). Read its compact
   brief, not JSON. Present distinct parts in this order: temperature, precipitation
   forecast/advice, extreme-weather warning only if applicable, then AQI/health.
     Keep routine diagnostics internal; surface material stale/unavailable data
     and health warnings without generic caveats.
    For historical work, label unavailable weather; never substitute today's data.
3. Read `docs/news-delivery.md`. Run `news --backfill --today DATE` per confirmed country; inspect manifest and
   window diagnostics. Scores are proxies. Use `--audit` for suspect selection on a narrow
   window; never acknowledge a report whose selected stories were omitted.
   When `editorial_review_pending` is set, read that day's collected candidates
    with `--show DATE --view candidates`, following `next_offset` pages. Select distinct consequential stories using semantic judgment,
    not just proxy scores; record candidate_id/reason choices in runtime JSON and
   run `--curate DATE --selection-file PATH --expect REPORT_ID --session NAME`
   with the matching country/runtime/sources and `--view stories`. Use the returned
   saved stories directly. Do not skip review or invent citations; fewer items are fine.
   For historical work,
   use an explicit `--ending` date before the requested briefing date. Read
   `--show DATE --view stories` for yesterday's undelivered report; show already-delivered news
    only when requested. Use AI/world/national news blocks with explicit dates/countries.
     Paraphrase faithfully, cite, keep quotes brief and separate assessment from
     facts. No news preambles, flavor text or partisan commentary.
   Preserve sources and
   material gaps. Keep unrequested older-report availability internal.
    Follow the shared post-delivery acknowledgement rule; never acknowledge drafts.
   Default news is yesterday only in the profile timezone; today's news waits
   until tomorrow. With `news_latest: false`, omit same-day collection/sections.
   Only if `news_latest: true` or separately requested, run
   `news --latest --country CODE --timezone ZONE --format json` separately for
   each country with selected runtime/source/cache paths and a distinct date/as-of
   heading. Do not mix dates or treat submissions as new publications. Latest is
   stateless; keep mechanics internal, show material gaps and deduplicate stories.
   If editorial review is required, save the exact latest JSON inside the runtime
   and use `--curate-latest FILE --selection-file PATH --expect CANDIDATE_BATCH_ID
   --session NAME --secretary-dir RUNTIME --view stories` after reviewing its candidates. Preserve
    cutoff/freshness notes and label analysis or social discovery appropriately.
4. Query `calendar --from DATE --days 3 --timezone ZONE --json --details`.
   Use approved events only, show pending review counts, and inspect relevant
    details for preparation. Show a chronological timetable with date/time/timezone,
      event, place and prep where known. Put conflicts beneath it; no duplicate prose.
    Before publishing Schedule, review preparation's tasks and relevant active
    inbox/project constraints (including further pages where needed). Append a
    typed `flexible` block after the timetable for today's chosen work, dated TODOs
    and applicable recurring tasks without fixed times. Include supported future
    dates within the schedule window; unassigned work keeps an empty date. Never
    manufacture time slots or describe the day as free from calendar emptiness.
5. Read relevant saved project records and confirmed reports; use authorized live
   project access only if needed and allowed. Include concrete project next actions
   in Must-do/Nice-to-do when there is actual outstanding work relevant to today's
   plan. Name the project in each task and explain why it matters. Must-do is
   necessary or time-sensitive work; Nice-to-do is optional progress or improvement.
   Preserve explicit user priorities. Omit either section when it has no supported
   tasks; do not invent weekly steps, busywork, fixed times or deadlines to fill it.
   Use only confirmed fixed times and clearly labeled, grounded estimates.
     Give grounded advice in the user's tone.
    Do not invent deadlines or progress. Must-do/Nice-to-do express priorities;
    keep titles identical when also showing those tasks in the flexible schedule
    so checklist synchronization creates one task, not duplicate completions.
      Use preparation's inbox page; fetch further `inbox --list` filters/pages only
      as needed, then `--show ID` only for relevant
     current constraints. Never read archived discussions. Review flagged new
     details per `docs/inbox-pipeline.md`; do not silently omit reminders from later pages.
     Read relevant pending ideas and add unchecked clarification TODOs to the reply
    and daily task list per the shared reminder rule, preserving existing tasks.
     Use the shared pending project-update workflow: clarification TODOs, not actions.
     TODOs: record-only.
6. Browser jobs finish through `job`; code synchronizes typed visible
   task titles and saves the edition/run together. Do not duplicate that work.
   Other amendments use `daily --date DATE --amend --expect HASH` from
   the preparation result for concise sections/task additions, preserving existing content.
    See `docs/workflow-helpers.md` for payloads. New tasks
    are unchecked. Author/validate/save per `docs/briefing-format.md` using
     `state --mark-gm` with actual session, native JSON input, `--today DATE`
     and `--json`; verify success.
      Do not create text or card copies.
    Acknowledge only reports whose actual delivery is now verifiable.

7. Return the browser link, not JSON/repeated text. Do not attach image cards in chat.

## Errors and follow-up

Preserve warnings; show material failures as unavailable, not empty or complete.
Respect duplicate refusals and shared confirmation rules. In-thread amendments
use daily/project helpers; original snapshots remain unchanged.
