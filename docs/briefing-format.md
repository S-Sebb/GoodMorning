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
nonempty. Morning defaults to Schedule, Tasks, Needs attention, Weather, News;
evening defaults to Today, Schedule, Tasks, Needs attention. Omit empty optional
sections. A material failed retrieval is unavailable, not an empty/free day.
Override section titles for the selected language or a different news window;
published titles must match the saved browser plan. Notes are grounded takeaways,
not repeated cards or news facts. Use `""` for note when only overriding title.

## Source-linked blocks

`task --briefing gm|gn --date DATE` returns normalized rows and ready-made `blocks`.
Copy nonempty blocks; follow each returned `next_offset` with the same date/edition.
Add grounded explanations without changing source identity, revision, date/status.

- `["actions",[[task_id,revision,occurrence_id,date,status,title,detail],...]]`:
  only in Tasks or Today. Empty occurrence/date means no agreed workday. Date is
  ISO `YYYY-MM-DD`; status is open, partial, blocked or user-confirmed done.
- `["events",[[event_or_draft_id,revision,date,time,title,place,preparation],...]]`:
  only in Schedule. Code supplies approved events and confirmed TBC drafts;
  retain timezone in adjacent prose, actual dates and pending-change markers.
  Preparation is concise attendee requirements only, never meeting-invitation
  boilerplate (join instructions, Meeting IDs, help/meeting-options links,
  system references or privacy footers). Join via the original invitation.
- `["decisions",[[entry_draft_or_calendar_id,revision,title,detail],...]]`: only in Needs
  attention. These are actual pending questions, unreviewed material or due reviews.

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
- `["weather",[[type,value,detail,label?],...]]`: temperature, precipitation,
  applicable warning, then air, with no duplicates. Value is text or null when
  unavailable. Detail retains health advice, actual timestamps and material gaps.
  Unknown AQI is not good air; an unknown warning is not proof of no warning.
- `["news",category,[[headline,summary,sources],...],country?]`: retain every
  selected story and all citations. Sources are nonempty `[[label,url],...]` with
  absolute HTTP(S) URLs and no credentials. Country is an optional uppercase
  two-letter code, independent of translated category. Assessments belong in note,
  not the reported summary. Default news title is yesterday's pinned date; override
  titles for other windows/languages. Saving is not delivery acknowledgement.

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
Local runs use one reusable draft under the selected private runtime, then:

```bash
python scripts/goodmorning.py state --secretary-dir RUNTIME --today DATE --mark-gm --session REAL_SESSION --answer-file DRAFT --json
```

Use `--mark-gn` for evening. Validation precedes writes; check the receipt. Ordinary
amendments preserve original snapshots. Full replacement requires explicit
authorization; browser regeneration uses its owning job, never `--force`.
Unknown/interrupted saves require inspection before retry, not blind replay.
No Markdown, card, presentation or HTML copies. Return the browser link.
