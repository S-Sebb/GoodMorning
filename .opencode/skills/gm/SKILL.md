---
name: gm
description: Morning secretary briefing for /gm: weather, yesterday's consequential news, optional separately dated latest developments, approved schedule, and today's priorities. Save records without duplicate runs.
---

# Morning briefing

Trigger: `/gm`, or an explicit request for the GoodMorning morning workflow.
Inputs: confirmed profile, current session, optional explicit date, daily/project
records, and compact script results. Output: a clear briefing in the user's custom
tone plus saved daily
record and verbatim snapshot; news delivery is tracked separately.

The repository root is `../../..` from this skill directory. Read
`../../../docs/skill-rules.md` first. Use
`../../../templates/gm.reply.template.md` for the reply and
`../../../templates/daily.template.md` for storage. Commands below run from root;
apply shared runtime/date rules and use the `question` tool for needed choices
or confirmations, including missed runs and unclear tasks.
Apply the shared materiality gate throughout: no non-critical disclaimers or
process narration in the greeting, briefing, questions or closing.
Use `../../../docs/reply-voice.md`: this is a conversational personal assistant,
not a dense essay or a cold dashboard. Keep the agreed personality within useful
section content; no extra framing paragraphs. Use headings/rules, weather order,
source-based news lists and calendar timetables; bold only genuinely key details.
Brief optional section takeaways and a warm closing may add flavor; keep news items factual.

## Steps

1. Use the profile's customised tone throughout the briefing, while prioritizing
   clean formatting and clarity. Greet in that tone; do not assume their mood.
   Check setup, then run
   `python scripts/state.py --check --json`. Handle duplicates and missed runs
   before fetching. For a duplicate, identify its session and stop; no refresh.
2. For today, run `weather.py` once with the profile's qualified city using
   explicit `--city CITY` (and `--profile PATH` when relocated). Read its compact
   brief, not JSON. Present distinct parts in this order: temperature, precipitation
   forecast/advice, extreme-weather warning only if applicable, then AQI/health.
   Use labeled bullets or subheadings. Keep routine source/freshness diagnostics
    internal; short labels are enough. Surface stale/unavailable data and health
    warnings only when material, without generic model/station caveats.
   For historical work, label unavailable weather; never substitute today's data.
3. Run `news.py --backfill` once per confirmed country and inspect the manifest and
   source/window diagnostics. Follow shared editorial rules: scores are proxies,
   not truth or final judgment. Use `--audit` for suspect selection on a narrow
   window; never acknowledge a report whose selected stories were omitted.
   When `editorial_review_pending` is set, read that day's collected candidates
   with `--show`. Select distinct consequential stories using semantic judgment,
   not just proxy scores; record candidate_id/reason choices in runtime JSON and
   run `--curate DATE --selection-file PATH --expect REPORT_ID --session NAME`
   with the matching country/runtime/sources. Reread the reviewed report before
   presentation. Do not skip review or invent citations; fewer items are fine.
   For historical work,
   use an explicit `--ending` date before the requested briefing date. Read
   `--show DATE` for yesterday's undelivered report; show already-delivered news
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
   --session NAME --secretary-dir RUNTIME` after reviewing its candidates. Preserve
   cutoff/freshness notes and label analysis or social discovery appropriately.
4. Query `secretary_calendar.py --from DATE --days 3 --timezone ZONE --json`.
   Use approved events only, show pending review counts, and inspect relevant
    details for preparation. Show a chronological timetable with date/time/timezone,
    event, place and prep where known. Put conflicts beneath it; no duplicate prose.
5. Read relevant project records; use authorized project access only if needed.
   Build this week's next steps per project, then choose today's must-do versus
   nice-to-do tasks with priority, fixed times, and clearly labeled estimates.
    Explain useful advice within sections in the user's tone; keep it easy to scan.
   Do not invent deadlines or progress.
   Remind about pending ideas without
   opening the entire inbox unless clarification is needed.
6. Compose the reply using the template. Write concise weather/news/schedule/task
   sections into the selected daily file, preserving existing content. New tasks
   are unchecked. Save the exact reply through `state.py --mark-gm` with session,
   answer input, and `--json`; verify success. Present it without extra repeated
   summaries. Acknowledge only reports whose actual delivery is now verifiable.

## Errors and follow-up

Preserve all warnings internally and surface material weather/news or calendar/
project failures briefly; say unavailable,
not empty or complete. Stop duplicate writes on state refusal. Ask about unclear
tasks or likely new events using shared confirmation rules. In-thread changes
update daily/project records; snapshots stay original unless replacement is asked.
