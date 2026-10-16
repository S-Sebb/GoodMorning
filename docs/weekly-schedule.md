# Weekly schedule

The **Schedule** tab at `/schedule` is a read-only, live view of saved plans, not
an AI-generated weekly briefing. It requires the account's saved timezone, but
does not require a connected agent or a new morning/evening briefing.

## Display

- Monday–Sunday, with the account's actual local calendar date highlighted.
  Unlike briefings, the date changes at midnight, not 04:00.
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
  completion totals, timezone, and the saved-record check time. An amber dot on
  that control signals pending calendar review; the explanation and secretary
  link are inside the menu. There is no summary strip, sync footer, marketing
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
   appear on their projected due days and on confirmed completion days, marked
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
   per-occurrence `task --report`, with `confirmed_completion: true`. Neither
   opening the page nor an elapsed date marks work done or moves it forward.
5. **Excluded:** raw/undated TODOs, nudges, errands, reference notes, ideas, speculative project steps, unapproved
   new imports, cancelled events, and inferred deadlines. No browser action
   changes calendar or daily records. The secretary link starts ordinary chat;
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
- Calendar edits/review/cancellations, daily amendments and confirmed completion,
  and saved briefing tasks are picked up on the next check. The details menu reports
  when saved records were checked, explicitly **not** a provider-sync timestamp.
- Each check recomputes the local date, permitted weeks and day/night palette.
  Week navigation is relative to the current week, so the current-week view
  follows the new week on Monday. A browsed relative offset follows that shift
  too. Missing or unreadable records are never presented as confirmed free time;
  a failed source is marked without hiding the other source's readable plans.

The authenticated gateway forwards the page, API and immutable assets to the
logged-in account's private backend. Schedule reads use the existing access,
account-isolation, CSP and no-store rules; there is no schedule mutation endpoint.
