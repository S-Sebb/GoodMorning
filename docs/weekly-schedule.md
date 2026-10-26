# Weekly schedule

The **Schedule** tab at `/schedule` is a live view of saved plans, not an
AI-generated weekly briefing. It is read-only except for one action: ticking a
to-do or habit done, or back, on today or an earlier day (see
[Ticking to-dos](#ticking-to-dos)). It requires the account's saved timezone, but
does not require a connected agent or a new morning/evening briefing.

## Display

- Monday–Sunday, with the account's current local day highlighted. Like
  briefings and chat, the day changes at 04:00, not midnight. Before 04:00, events
  on both that day and the calendar date show whether they ended.
- Previous/next navigation covers this week and three weeks on either side.
  `This week` returns to the current week. Both the page and API enforce the range.
- Desktop uses one softly framed calendar sheet with seven day columns, a compact
  month/week header, and a circled date for today. Smaller screens have a compact day
  navigation strip and two-column or single-column agendas, without horizontal
  scrolling. Today is identified with text as well as color.
- Inside that same sheet, **Events** is the upper band and **To-dos**
  is the lower band. All seven to-do cells begin on one shared vertical baseline,
  including days without calendar events. The busiest calendar cell sets the
  upper band's height, so expanded details and busy days never overlap work below.
  There is no second card, separate background, or hard horizontal divider.
  Tablet columns share that baseline in pairs; phones use compact stacked bands.
- Appointments are chronological, with all-day and continuing events identified.
  Expand an appointment for its end time, preparation notes, and source.
  An overnight/multi-day event appears on every day it overlaps; an exclusive
  midnight end does not add another day. The weekly appointment count counts
  each event once.
- Untimed work stays separate. Canonical agreed workdays and recurrence appear
  with project/optional labels and explicit partial/blocked/completed status.
  Legacy daily checklists remain a pre-migration fallback only. Confirmed
  completion remains visible. Empty days say nothing is saved, not that the day
  is free. Past weeks are the current saved records, not immutable snapshots.
- The corner **Schedule details** menu holds appointment/task counts, confirmed
  completion totals, timezone, and the saved-record check time. There is no summary strip, sync footer, marketing
  introduction, or general help section around the calendar. Real read failures
  remain visible as concise notices. The adjacent refresh icon checks saved plans.
  The menu has no provider-sync disclaimer; the check timestamp is labelled as a
  saved-record check, not as an external synchronization.

## Exactly how content gets filled

There is no second schedule store and no extraction from chat text.

1. **Appointments:** use the existing secretary/calendar workflow. Custom events
   require an explicitly confirmed title, date, time, duration, timezone and
   location. They appear after a successful calendar save. Authorized provider
   imports must be staged and reviewed before they become visible. Changes to
   an already approved import show its last approved version and a review notice;
   approving a cancellation removes it. Recurrence uses the existing import
   expansion, not a new browser recurrence engine.
2. **Dated work:** use canonical `task` writes with an explicit `planned_date` or
   confirmed recurrence under `docs/item-taxonomy.md`. Undated tasks, nudges, errands and
   reference notes do not appear. A hard deadline appears only on its due day,
   marked "no workday assigned"; it reserves no workday. Habits (`custom.sqlite`)
   appear on their projected due days and on confirmed completion days
   (including today, once ticked), marked
   flexible because the next date follows actual completion. A weekly TBC series
   appears on each of its dates. Project/optional are attributes.
   The tab shows project, optionality, supplied deadline, partial/blocked status
   and reported detail with the task, without creating another calendar event.
   Confirmed appointments with unknown time appear under Events as TBC, never
   all-day. Tentative or awaiting-confirmation proposals reserve nothing.
3. **Briefing plans:** native v2 snapshots do not create task occurrences. Saved
   canonical plans appear here without another AI call. Legacy daily checklists
   remain preserved history and require explicit reconciliation during migration.
4. **Completion:** user-confirmed IDs use revision-checked `task --update` or
   per-occurrence `task --report`, with `confirmed_completion: true`, the
   evening check-in's Done, or a tap on the Schedule (below). Neither opening
   the page nor an elapsed date marks work done or moves it forward.
5. **Excluded:** raw/undated TODOs, nudges, errands, reference notes, ideas, speculative project steps, cancelled events, and inferred deadlines. No browser action
   changes calendar or daily records; the only browser write is a to-do tick. The secretary link starts ordinary chat;
   it does not send a prompt or create a task automatically.

The web account reads only its own `calendar.sqlite` and `inbox.sqlite` task
occurrences (legacy daily files remain readable until migration). Process-wide calendar environment overrides and
browser-supplied paths do not select another calendar. Records are opened
read-only; viewing does not initialize or migrate a database. Existing calendar
credential redaction and HTML escaping apply to all displayed content.

## Exactly when it updates

- The server renders current saved records on every page open, including without
  JavaScript. With JavaScript, `/api/schedule?week=N` checks once on opening,
  on week navigation, on browser back/forward, on focus/return to the page, on
  **Refresh saved plans**, and 60 seconds after each completed visible check.
- A hidden page stops checking. The next return checks immediately. No generation
  job, scheduled task, provider fetch, or external sync is started.
- A revision derived from the rendered records replaces the view only when
  content changes. Expanded appointments are retained when still present. A
  failed check keeps the last readable view with a visible error.
- Calendar edits/imports/cancellations, daily amendments and confirmed completion,
  and saved briefing tasks are picked up on the next check. The details menu reports
  when saved records were checked, explicitly **not** a provider-sync timestamp.
- Each check recomputes the local date, permitted weeks and day/night palette.
  Week navigation is relative to the current week, so the current-week view
  follows the new week at 04:00 on Monday. A browsed relative offset follows that shift
  too. Missing or unreadable records are never presented as confirmed free time;
  a failed source is marked without hiding the other source's readable plans.

The authenticated gateway forwards the page, API and immutable assets to the
logged-in account's private backend. Schedule reads and the tick endpoint use the existing access,
account-isolation, CSP and no-store rules. `POST /api/schedule/tick` is the only
schedule write; calendar events have no write endpoint.

## Ticking to-dos

A tap on a to-do's mark (○/✓) saves at once. It means exactly what the evening
check-in's **Done** means (`TaskStore.complete_day`): a one-off task, even one
spread over several workdays, becomes finished as a whole; a recurring task or
habit is done only on that day. Habits save through `CustomStore.report`.
A notice with **Undo** stays about 6 seconds. Undo, or tapping the mark again
later, restores exactly the state before the tap (for example Partial with its
note), as long as nothing else changed the task since. A done mark that came
from somewhere else (the secretary, the check-in) is reopened instead: that day
becomes open, and a one-off task becomes open. Unticking a habit on a past day
withdraws that completion, so the row leaves that day.

- **Tickable:** planned to-dos and habits on today and earlier days. Future
  days, deadline markers ("no workday assigned"), stopped habits, calendar
  events and legacy daily checklists stay read-only, and the server refuses
  them (future dates and unplanned days are rejected, not just hidden).
- **Without JavaScript** the page renders the marks as disabled buttons; ticking
  is unavailable.
- **Records:** writes go only through `TaskStore.tick` (inside the inbox
  transaction) and `CustomStore.tick`. Each tap is revision-checked,
  request-keyed and logged as a `tick` task event or a `report`/`withdraw`
  habit event, with the replaced state in its snapshot. The page never writes
  SQLite directly.

### Request contract

Browser: `POST /api/schedule/tick` with the session cookie, same-origin `Origin`
and `X-Briefing-CSRF`. Android: `POST /api/app/schedule/tick` with the app token
(`X-GoodMorning-App`); the gateway forwards the same body to the account's
backend. Both take `Content-Type: application/json`:

```json
{"id": "task_0123456789abcdef", "date": "2026-10-13", "revision": 2,
 "done": true, "key": "3f0c9b8e-5a2d-4c1e-9f7a-1b2c3d4e5f60"}
```

- `id`, `revision`: the row's `id` and `revision` from the schedule data
  (`cu_…` IDs are habits, anything else a task).
- `date`: the row's day, `YYYY-MM-DD`, today or earlier in the account's
  timezone, where today changes at 04:00 as on the page.
- `done`: `true` to tick, `false` to untick. Undo is the opposite tap with the
  `id`, `date` and `revision` from the previous response.
- `key`: a fresh random retry key per tap, 16–64 characters of `A–Z a–z 0–9 _ -`.
  Resending the same key and body returns the first response without saving
  again; reusing a key with other input is refused.

Responses:

- `200` `{"saved": true, "id", "date", "done", "revision"}`: `revision` is the
  row's new revision. Revisions are shared by all days of one task or habit, so
  read the schedule again before tapping another of its rows.
- `409` `{"error"}`: the row cannot be ticked as read: a stale revision, a day
  that is not (or no longer) planned work such as a deadline marker, a stopped
  habit, or a task that is gone. The row keeps its old mark; re-read the
  schedule. `error` is the localized website message.
- `400` `{"error"}`: malformed input or a future date. `403`: authentication,
  origin or CSRF failure; for the app, link the phone again.

### Widget rows

`GET /api/app-schedule` (inside `/api/app/sync` as `schedule`) gives each task
row `{text, done, tickable}`. A row with `tickable: true` also has `id` and
`revision` for the request above; rows on future days, deadline markers and
other read-only rows have `tickable: false` and no `id`. `days[0]` is today.
