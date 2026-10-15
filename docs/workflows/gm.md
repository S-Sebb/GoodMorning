---
name: gm
description: Morning plan with weather, sourced news, Schedule, Tasks and Reminders in fixed order.
---

# Morning briefing

Trigger: `/gm` or a morning-briefing request. Inputs: confirmed runtime, session,
language and date; browser jobs supply saved preparation. Result: a verified native
v2 morning edition and browser link, not a new task plan.

Read `docs/core-rules.md`, `docs/item-taxonomy.md`, `docs/briefing-format.md` and
`docs/reply-voice.md`. Browser jobs also read `docs/browser-generation.md`.
Run `python scripts/goodmorning.py` from the package root with selected absolute
runtime/cache paths. Keep the current session/model and use the confirmed language.
Use the default plan in order: Weather, News, Schedule, Tasks, Reminders, with
opted-in dated latest News only when the plan includes it. Browser jobs keep every
plan position and use `skip` for empty optional ones; local JSON omits empty optional sections.

1. Browser jobs start with `job --secretary-dir RUNTIME --job JOB prepare`, then
   follow its receipt: immediately init a fresh preview with the unchanged default
   plan, or resume an existing checkpoint. Reuse saved decisions/date/context;
   do not run local preparation or re-ask browser preflight questions. Local requests
   use `workflow --prepare gm` once. Resolve setup, migration, duplicate and local
   missing-edition decisions before fetching. Duplicates identify the original and stop.
2. Weather: fetch once with qualified city and explicit profile/cache paths.
   Order temperature, precipitation/advice, applicable extreme warning, AQI/health.
   Values are display-ready: `16°C (14.5–20.4°C)`, `65% – Rain likely`
   (never `rain yes`), `30 – Good` (never `US AQI` prefix).
   Retain material stale/unavailable data. Historical editions never use today's
   weather as historical fact.
3. News: follow `docs/news-delivery.md`. Default is yesterday in the saved timezone,
   per confirmed country. Review actual candidates and retain every selected story,
   citation and material coverage gap. Latest collection requires saved opt-in or
   explicit permission and a separate dated heading. A snapshot is not delivery;
   acknowledge only after actual visible delivery is verified.
4. Publish Schedule from the normalized approved event/draft rows. Morning shows
   today's timed appointments only; all-day events and unknown-time confirmed
   appointments stay TBC across today and the next two days. Upcoming timed
   appointments stay out of the morning edition. Tentative proposals and unseen
   imports are not attendance commitments. Surface
   pending changes and material availability failures, not healthy bookkeeping.
   Preparation is concise requirements only; never copy join instructions,
   Meeting IDs, help/meeting-options links or privacy footers into it.
   Add a short note in the saved tone summarizing the day in plain words (empty:
   no appointments saved, without claiming free time; non-empty: count and
   earliest time plus most useful preparation); do not mention windows, glances,
   TBC, or timed focus; do not repeat every card.
5. Publish Tasks from code-owned rows: agreed/recurring work, deadline attention,
   still-open work and selected undated actions. Project and optional labels are
   attributes. First walk through today's displayed rows from
   `task --briefing gm --date DATE --section tasks` (follow `next_offset`); where a
   title/detail is materially vague (missing object, filler opener, `etc.`/parens fog,
   verb at the end, non-imperative title — not mere punctuation or capitalization), fix it with
   revision-checked `task --update`
    using title/detail only (same meaning, no date/status/project/scheduling change,
    stable `polish:SESSION:taskID:revision` keys; a moved revision gets a fresh key
    with the new revision), then reread and pack the exact
    updated rows. Reminder mechanics and setup narration are trimmed
    by the same update (possibly to an empty detail); other details may only be
    lightly clarified for display. Preserve dates, details, source IDs and revisions; follow pages.
    Also read code-owned `custom --briefing gm --date DATE` rows; due custom schedules are shown with Tasks using their computed next-due and weekly count. Word warmly; never invent custom dates.
    Leave already-clear titles unchanged. A project name within the specific object
    ("Send Atlas report") is not a decorative prefix ("Atlas: Send report"); do not
    strip it or make a cosmetic write merely because project grouping repeats it.
   Code groups cards by workday then project with a shared due target in the
   heading; review with a short note in the saved tone naming the top project groups and the
   next useful step instead of repeating every card.
   Titles must read as clear imperative actions with specific objects and no project
   prefix (the project heading already shows it); details add
   why plus current state or next step without repeating title/project/due text.
   Leave detail empty when no grounded why/state was supplied; never invent one.
   Do not promote ideas, copy project Markdown into new tasks or assign a workday
   merely by showing a task. No appointments does not establish a free day.
6. Reminders contains due decisions/reviews. Code humanizes calendar times and
   uses `Canceled:`/`Updated:` prefixes. Keep titles exact, keep details grounded,
   and add a brief note with the count and single next action. Ask only missing material facts
   or permissions affecting today's useful/safe plan. Do not interview every task,
   invent clarification work from clear ideas or re-ask saved answers. Skip an
   empty optional browser position using `skip`, or omit it from local JSON. Pending optional
   decisions do not block unrelated work.
7. Browser jobs publish one complete next section and finish through `job`. Local
   saves use native v2 JSON and `state --mark-gm` with the actual session/date.
   Neither path schedules or creates tasks from the presentation. Return the
   browser link, not repeated JSON, Markdown/card/presentation/HTML copies.

New tasks, changes or feedback supplied in the conversation follow the capture/task
workflow before presentation. No execution is implied. Preserve archived snapshots,
unrelated records, failed/unknown writes and existing completions.

If collection fails, publish its material unavailability; do not present an empty
successful result. For source conflicts, reread affected rows. For interrupted
publication, inspect the job and reuse identical input only under its receipt's
retry contract; never rewrite earlier published sections or replay record mutations.
