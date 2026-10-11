# Browser-native briefing format, version 1

New `/gm` and `/gn` briefings use one JSON document, not Markdown plus presentation.
Author the JSON directly. Never write an intermediate Markdown/HTML briefing or
ask a helper to infer facts from prose. Existing Markdown editions remain readable.
All workflow consent, dates, source fidelity, actual progress, duplicate and news
delivery rules still apply. Daily task/progress records remain separate.

## Authoring contract

Required keys: `v:1`, `greeting`, `opening`, `sections`. Optional: `closing`, `lang`
(a language tag matching the confirmed language, such as `en` or `zh-CN`). No other
root keys. The filename supplies date and edition; do not repeat them or internal
IDs in the document. Strings are plain UTF-8 text, not Markdown or HTML. Escape
quotes/backslashes/newlines using JSON rules. No code fences, comments, duplicate
keys, trailing commas, NaN, or embedded executable code. Do not invent missing data.

Each section is `[type, blocks, note?, title?]`. Omit trailing optional fields.
`type` is `weather`, `news`, `schedule`, `must-do`, `nice-to-do`, `reminders`,
`today`, `still-open`, `tomorrow`, or `notes`. Use `notes` plus an explicit title for
custom content. `blocks` is a nonempty ordered array. `note` is a separate grounded
takeaway, not news facts; include useful notes, explicitly Nice-to-do when present.
Use `""` for note if only overriding a title. Multiple sections of the same type
are permitted; their notes stay independent. Omit empty sections.

English default titles follow the type (e.g. `must-do` becomes `Must-do`);
`news` defaults to `News — YESTERDAY` using the pinned briefing date. **Always
override titles for other languages and different news windows**, e.g. same-day
latest or explicitly requested older news. Default labels save repeated UI tokens,
not permission to remove material timestamps, uncertainty or warnings.

Block shapes (all positional fields shown below are required unless marked `?`):

- `['p', text, sources?]`: paragraph; optional sources are `[[label,url], ...]`.
- `['list', [text, ...]]`: ordinary bullets, not task completion records.
- `['tasks', [[status,title,detail], ...]]`: status is `open`, `done`, `partial`,
  or `blocked`. Only actual user-confirmed completion permits `done`. Keep partial
  and blocked tasks unchecked. Empty detail is `""`; preserve known dates,
  estimates, priorities and blockers in title/detail without inventing them.
- `['weather', [[type,value,detail,label?], ...]]`: types in this order:
  `temperature`, `precipitation`, applicable `warning`, `air`. No duplicates.
  `value` is a string such as `"14°C"`, `"40%"`, `"31"`, or `null` when unavailable.
  `detail` retains context/advice/health and material actual timestamps/gaps.
  Defaults: Temperature, Precipitation, Extreme warning, AQI; override labels for
  other languages. Never interpret an unknown warning as absent or unavailable AQI
  as good. Do not infer current conditions merely from forecast probabilities.
- `['news', category, [[headline,summary,sources], ...], country?]`: preserve every
  selected story and all sources. Headline is separate from summary; dashes/bold-like
  text never determine fields. Sources are nonempty `[[label,url], ...]` with absolute
  HTTP(S) URLs, no credentials. Category is visible prose; optional two-letter
  uppercase country code chooses a flag, independently of translated text. Assessments
  belong in the section note, not in the reported summary. Group by category/country.
- `['agenda', [[date,time,event,place,preparation], ...], labels?]`: approved events
  only, in chronological order. Missing place/preparation may be `""`; unknown time
  must be explicit, e.g. `"TBC"`, not fabricated. Default labels are Date, Time,
  Event, Place, Preparation; translated labels must contain five entries in that
  order. Put the confirmed timezone in an adjacent paragraph. Use other paragraphs
  for conflicts and pending-review counts; do not encode them as approved events.
- `['table', [column, ...], [[cell, ...], ...]]`: arbitrary table; rows must exactly
  match the columns. Use for reported progress with outcomes/next steps or extra
  event metadata not covered by the agenda shape. Every cell is a string.

Use actual JSON double quotes. The single quotes above distinguish the shapes
from a document to save. Limits: 150,000 UTF-8 bytes, 1–80 sections, 1–100 blocks
per section, at most 200 rows/items per block and 16 sources per paragraph/story.
Greeting/opening: 350 characters each; note/closing: 600; section/category/column
labels: 200; task/news headline: 600; ordinary detail/paragraph/cell: 5,000;
URLs: 2,000. These are guardrails, not a demand to pad or truncate needed evidence.
Split long content into appropriate blocks; report material size failures.

Minimal shape example, not wording to repeat:

```json
{"v":1,"greeting":"Good morning.","opening":"Leave some room for the important work today.","sections":[["weather",[["weather",[["temperature","14°C","London; bring a jacket."],["precipitation","40%","Rain possible after 15:00."],["air","31","Good air."]]]],"Allow extra time if the afternoon turns wet."],["nice-to-do",[["tasks",[["open","Read one paper","Choose a focused gap, not a new deadline."]]]],"A small reading slot is enough."]]}
```

## Validate and save once

Keep a single reusable draft input file inside the selected runtime, not a fresh
temporary file for every day. Do not overwrite unrelated user files. Author it in
the confirmed language/tone; the helper does not write the greeting or commentary.

Browser jobs use `briefing_job.py finish`; code owns draft assembly and final save.
For other invocations, save after daily amendments through:

```bash
python scripts/goodmorning.py state --secretary-dir RUNTIME --today DATE --mark-gm --session REAL_SESSION --answer-file DRAFT --json
```

Use `--mark-gn` for evening. Parsing and schema validation happen **before** saving
or marking. Invalid input returns `briefing_invalid` with the field path; repair
the draft, preserving evidence and warnings, then retry. Do not use `--force` to
fix validation failures or overwrite an existing edition. A valid save compacts
whitespace only, writes `daily/DATE.gm.json` or `.gn.json`, and records the pointer
using the existing locked, atomic state path. It creates no Markdown briefing,
presentation sidecar or HTML export. Save receipt is not proof of news delivery.
Storage failures remain inspect-before-retry; this is not a multi-file transaction.

Browser generation jobs follow `docs/browser-generation.md`: the same cumulative
draft starts with zero sections **only for an unfinished preview**, then grows one
complete section at a time. Saved v1 documents still require at least one section;
there is no partial-file format in `daily/`. The job helper requires a resolved plan
and an exact match to the published preview before marking; do not save separately.

The live viewer validates native content and escapes every string before direct
component rendering. It does not invoke a Markdown parser or recognize fields
from punctuation/translated headings. Invalid/unknown versions remain untouched
and are not reported ready; inspect and repair only with appropriate authorization.
Only native JSON is supported. Unrelated private files are ignored and never
converted or deleted by the viewer or save command.
