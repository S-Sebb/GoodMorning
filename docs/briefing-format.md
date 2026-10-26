# Browser-native briefing format

Read `docs/item-taxonomy.md`. New canonical editions use JSON **v2**. Existing v1
archives and already-published legacy previews remain readable without rewriting
them; legacy section/checklist rules do not govern new tasks.

## Document and sections

Required root keys: `v:2`, `greeting`, `opening`, `sections`. Optional: `closing`,
`lang` (selected language tag). No other keys. Strings are plain UTF-8 text, not
Markdown/HTML; no fences, duplicate keys, comments, trailing commas or NaN.
The filename supplies date/edition; do not repeat internal IDs in visible prose.

Each section is `[type,blocks,note?,title?]`. Omit trailing optional fields.
Types: `schedule`, `tasks`, `attention`, `today`, `weather`, `news`. Blocks are
nonempty. Morning defaults to Weather, News, Schedule, Tasks, Reminders in that fixed order;
evening defaults to Today, Weather tomorrow, Schedule, Tasks, Reminders. Omit empty optional
sections. A material failed retrieval is unavailable, not an empty/free day.
Override section titles for the selected language or a different news window;
published titles must match the saved browser plan. Notes are grounded takeaways,
not repeated cards or news facts. Use `""` for note when only overriding title.

## Source-linked blocks

`task --briefing gm|gn --date DATE` returns normalized rows and ready-made `blocks`.
Copy nonempty blocks; follow each returned `next_offset` with the same date/edition.
Add grounded explanations without changing source identity, revision, date/status.
Briefings make no task writes: records are shaped in the conversation that
received the request. Use clear, informative prose in the confirmed tone. Code
fills row titles and details from each item's saved `display` wording; copy them.
Only rows the read lists in `fallback` (no fresh saved wording) may be reworded for
the page: a vague title as a clear imperative with the same meaning, a detail
shortened, keeping code labels and dropping the secretary's own notes. Never add
facts. Title and detail are not part of source validation.

- `["actions",[[task_id,revision,occurrence_id,date,status,title,detail],...]]`:
  only in Tasks or Today. Empty occurrence/date means no agreed workday. Date is
  ISO `YYYY-MM-DD`; status is open, partial, blocked or user-confirmed done.
  Code groups cards by workday, then by project, lifting a shared due target to
  the project heading. Keep source order inside each project so relevance stays
  deterministic. IDs/dates/status/revisions must match the code rows exactly;
  details may be clarified for display (they are not part of source validation)
  but must never repeat the title or restate project/due text code already shows.
  Titles must be imperative, specific, free of filler openers or trailing periods,
  and free of project prefixes (the project heading already shows the project).
  Leave detail empty when no grounded why/state exists. Material vagueness means a
  missing object, filler opener, non-imperative title or `etc.` fog — not mere punctuation.
  Add a short section note in the saved tone (default warm and helpful), naming the top 1–3 project groups and the next
  useful step (for example which group to pick today); do not repeat every card.
- `["events",[[event_or_draft_id,revision,date,time,title,place,preparation],...]]`:
  only in Schedule. Code supplies saved events and confirmed TBC drafts;
  retain timezone in adjacent prose and actual dates.
  Preparation is concise attendee requirements only, never meeting-invitation
  boilerplate (join instructions, Meeting IDs, help/meeting-options links,
  system references or privacy footers). Join via the original invitation.
  Add a short section note in the saved tone (default warm and helpful): for an
  empty day say only that no appointments are saved for that day, without
  claiming free time or availability; for a non-empty day name the count and
  earliest time plus the single most useful preparation; use plain words only,
  no mention of windows, glances, TBC, timed focus, or code blocks; do not
  repeat every card.
- `["decisions",[[entry_draft_or_calendar_id,revision,title,detail],...]]`: only in Reminders.
  These are actual pending questions, unreviewed material or due reviews.
  Code already humanizes calendar times (`Fri 23 Oct 11:00–12:00`) and uses
  `Canceled:`/`Updated:` prefixes instead of raw ISO/status dumps. Keep titles
  exact; details may be clarified for display but must stay grounded in the
  returned source/time. Add a brief note with the count and the single next
  action (for example review with the secretary); never paste raw timestamps.

IDs/revisions are hidden data references, never visible titles. One actionable
card per occurrence; Today may separately report its historical outcome. A task
deadline does not assign a workday; showing work never schedules or executes it.
V2 never uses legacy `tasks`, `flexible` or `agenda` blocks for live work/events.
Publish/save checks current sources, pinned windows and ownership. On a source
conflict, reread affected records; never infer progress or alter immutable sections.

## Other blocks

- `["p",text,sources?]`: paragraph; optional sources are `[[label,url],...]`.
- `["list",[text,...]]`: ordinary bullets, not hidden task completion cards.
- `["table",[column,...],[[cell,...],...]]`: reported progress or extra metadata;
  every cell is text and each row exactly matches its columns. Do not replace
  linked action/event blocks with unverified prose tables.
- `["weather",[[type,value,detail,label?],...],frame?]`: temperature, precipitation,
  applicable warning, then air, with no duplicates. Value is text or null when
  unavailable. Detail retains health advice, actual timestamps and material gaps.
  Rain, snow and umbrella advice belong only in the precipitation detail; the
  temperature detail covers temperature and what to wear.
  Unknown AQI is not good air; an unknown warning is not proof of no warning.
  Format values for display, never raw provider tokens:
  temperature uses °C with an en-dash range, e.g. `16°C (14.5–20.4°C)`;
  precipitation uses percent plus natural words, e.g. `65% – Rain likely`,
  never raw `rain yes/no/unknown`;
  air uses number plus level, e.g. `30 – Good`, never a `US AQI`/`EU AQI` prefix
  (the card label already says AQI; sources belong in detail).
  `frame` is the weather read's hourly forecast; code attaches it when the
  section is published, and the page draws charts and headlines from it. Never
  write or copy it.
- `["news",category,[[headline,summary,sources],...],country?]`: retain every
  selected story and all citations. Sources are nonempty `[[label,url],...]` with
  absolute HTTP(S) URLs and no credentials. Country is an optional uppercase
  two-letter code, independent of translated category. Assessments belong in note,
  not the reported summary. Default news title is the job's as-of time; override
  titles for other windows/languages.

Use JSON double quotes. Limits: 150,000 UTF-8 bytes, 1–80 sections, 1–100 blocks
per section, 200 rows/items per block and 16 sources per paragraph/story.
Greeting/opening: 350 characters; note/closing: 600; headings: 200; titles: 600;
details/paragraphs/cells: 5,000; URLs: 2,000. Split content rather than clipping
facts; material limit failures stay visible. Partial zero-section documents exist
only as unfinished previews, never saved editions.

## Save once

Browser jobs use `job prepare`, immediate `init`, then the next `publish`/`skip`
and `finish`. Code assembles the cumulative JSON and binds it to the owning job,
session/date. Do not create an agent-owned cumulative draft or save separately.
Validation precedes writes; check the receipt. Ordinary amendments preserve
original snapshots. Full replacement requires explicit authorization; browser
regeneration uses its owning job.
Unknown/interrupted saves require inspection before retry, not blind replay.
No Markdown, card, presentation or HTML copies. Return the browser link.
