---
name: gm
description: Morning briefing: weather, yesterday's news, approved schedule, priorities and optional dated latest developments. Save without duplicate runs.
---

# Morning briefing

Trigger: `/gm`, or an explicit request for the GoodMorning morning workflow.
Inputs: confirmed preferences, current session/date, relevant records and script output.
Output: a personalised briefing, concise daily record and exact snapshot; delivery is separate.

All paths below are relative to the GoodMorning package root. Read
`docs/core-rules.md` first (`docs/skill-rules.md` is the expanded reference). Use
`templates/gm.reply.template.md` for the reply and
`templates/daily.template.md` for storage. Commands below run from root;
apply shared runtime/date rules and use the `question` tool for needed choices
or confirmations, including missed runs and unclear tasks.
Apply the shared materiality gate and `docs/reply-voice.md`: personable sections,
ordered weather, factual cited news and calendar timetables. Keep useful detail;
omit routine bookkeeping, extra framing and repeated summaries.

## Steps

1. Use the confirmed tone and run
   `python scripts/workflow.py --secretary-dir RUNTIME --prepare gm`. Use its dates,
   preferences, paths, daily task page and active inbox page; do not repeat those reads.
   Handle duplicates and missed runs
   before fetching. For a duplicate, identify its session and stop; no refresh.
   When proceeding with a new briefing, rename this conversation to
   `GoodMorning DATE` in `secretary_language` per the shared title rule.
2. For today, run `weather.py` once with the profile's qualified city using
   explicit `--city CITY` (and `--profile PATH` when relocated). Read its compact
   brief, not JSON. Present distinct parts in this order: temperature, precipitation
   forecast/advice, extreme-weather warning only if applicable, then AQI/health.
   Use labeled bullets or subheadings. Keep routine source/freshness diagnostics
    internal; short labels are enough. Surface stale/unavailable data and health
    warnings only when material, without generic model/station caveats.
   For historical work, label unavailable weather; never substitute today's data.
3. Read `docs/news-delivery.md`. Run `news.py --backfill` once per confirmed country and inspect the manifest and
   source/window diagnostics. Scores are proxies. Use `--audit` for suspect selection on a narrow
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
   only when requested. Use Markdown AI/world/national subheadings and summary
   bullets. Prefer existing source summaries where appropriate to reuse; otherwise
   paraphrase faithfully, cite, keep quotes brief and separate any useful neutral
   assessment from facts. No news preambles, flavor text or partisan commentary.
   Preserve sources and
   material gaps. Keep unrequested older-report availability internal.
    Follow the shared post-delivery acknowledgement rule; never acknowledge drafts.
   Default news is yesterday only in the profile timezone; today's news waits
   until tomorrow. With `news_latest: false`, omit same-day collection/sections.
   Only if `news_latest: true` or separately requested, run
   `news.py --latest --country CODE --timezone ZONE --format json` separately for
   each country with selected runtime/source/cache paths and a distinct date/as-of
   heading. Do not mix dates or treat submissions as new publications. Latest is
   stateless; keep mechanics internal, show material gaps and deduplicate stories.
   If editorial review is required, save the exact latest JSON inside the runtime
   and use `--curate-latest FILE --selection-file PATH --expect CANDIDATE_BATCH_ID
   --session NAME --secretary-dir RUNTIME --view stories` after reviewing its candidates. Preserve
   cutoff/freshness notes and label analysis or social discovery appropriately.
4. Query `secretary_calendar.py --from DATE --days 3 --timezone ZONE --json --details`.
   Use approved events only, show pending review counts, and inspect relevant
    details for preparation. Show a chronological timetable with date/time/timezone,
    event, place and prep where known. Put conflicts beneath it; no duplicate prose.
5. Read relevant project records; use authorized project access only if needed.
   Build this week's next steps per project, then choose today's must-do versus
   nice-to-do tasks with priority, fixed times, and clearly labeled estimates.
    Explain useful advice within sections in the user's tone; keep it easy to scan.
   Do not invent deadlines or progress.
      Use preparation's inbox page; fetch further `inbox.py --list` filters/pages only
      as needed, then `--show ID` only for relevant
     current constraints. Never read archived discussions. Review flagged new
     details per `docs/inbox-pipeline.md`; do not silently omit reminders from later pages.
     Read relevant pending ideas and add unchecked clarification TODOs to the reply
    and daily task list per the shared reminder rule, preserving existing tasks.
    Use the shared pending project-update workflow: clarification TODOs,
    not unconfirmed actions; no duplicate tasks.
    TODOs: record-only.
6. Compose the reply using the template. Use `daily.py --date DATE --amend --expect HASH` from
   the preparation result for concise sections/task additions, preserving existing content.
   See `docs/workflow-helpers.md` for the structured payload. New tasks
   are unchecked. Save the exact reply through `state.py --mark-gm` with session,
   answer input, and `--json`; verify success. Present it without extra repeated
   summaries. Acknowledge only reports whose actual delivery is now verifiable.

7. For chosen image delivery, follow `docs/image-delivery.md` after saving text.

## Errors and follow-up

Preserve warnings; show material failures as unavailable, not empty or complete.
Respect duplicate refusals and shared confirmation rules. In-thread amendments
use daily/project helpers; original snapshots remain unchanged.
