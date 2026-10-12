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
takeaway, not news facts; include useful notes for Optional project steps when present.
Use `""` for note if only overriding a title. Multiple sections of the same type
are permitted; their notes stay independent. Omit empty sections.

English default titles follow the type, except `must-do` is `Project steps` and
`nice-to-do` is `Optional project steps`. These stable JSON types and daily groups
remain compatible with existing records; they do not mean general day obligations.
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
  only, in chronological order. Use ISO `YYYY-MM-DD` event dates so the viewer can
  show prominent weekday/date groups and Today/Tomorrow relative to the pinned
  edition date, including in archives and streamed sections. Existing non-ISO
  date text is preserved without guessing a weekday. Missing place/preparation may be `""`; unknown time
  must be explicit, e.g. `"TBC"`, not fabricated. Default labels are Date, Time,
  Event, Place, Preparation; translated labels must contain five entries in that
  order. Put the confirmed timezone in an adjacent paragraph. Use other paragraphs
  for conflicts and pending-review counts; do not encode them as approved events.
- `['table', [column, ...], [[cell, ...], ...]]`: arbitrary table; rows must exactly
  match the columns. Use for reported progress with outcomes/next steps or extra
  event metadata not covered by the agenda shape. Every cell is a string.
- `['flexible', [[date,status,title,detail], ...]]`: untimed work at the end of
  `schedule` or `tomorrow`, after all `agenda` blocks. The viewer supplies the
  localized Flexible schedule heading and groups task cards by date. Date is ISO
  `YYYY-MM-DD` when supported, otherwise `""` (No date assigned); status/title/detail
  follow `tasks`. Preserve known deadlines, estimates, recurrence, place and
  preparation in detail, never invent a clock time. An appointment whose time is
  unknown stays in `agenda` with `TBC`; it is not a flexible task. Include relevant
  date-confirmed TODOs, agreed plans and applicable recurring work, not every
  backlog item or unresolved idea. An empty calendar is not proof of a free day.
  Morning rows dated today synchronize into the daily `flexible` checklist group;
  future/undated rows do not. Existing exact-title tasks keep their stored group
  and completion; stored groups are not instructions for briefing placement.
  Night rows do not create, complete or reschedule daily tasks.

Use actual JSON double quotes. The single quotes above distinguish the shapes
from a document to save. Limits: 150,000 UTF-8 bytes, 1–80 sections, 1–100 blocks
per section, at most 200 rows/items per block and 16 sources per paragraph/story.
Greeting/opening: 350 characters each; note/closing: 600; section/category/column
labels: 200; task/news headline: 600; ordinary detail/paragraph/cell: 5,000;
URLs: 2,000. These are guardrails, not a demand to pad or truncate needed evidence.
Split long content into appropriate blocks; report material size failures.

Minimal shape example, not wording to repeat:

```json
{"v":1,"greeting":"Good morning.","opening":"Leave some room for the important work today.","sections":[["weather",[["weather",[["temperature","14°C","London; bring a jacket."],["precipitation","40%","Rain possible after 15:00."],["air","31","Good air."]]]],"Allow extra time if the afternoon turns wet."],["nice-to-do",[["tasks",[["open","Demo project: read one relevant paper","Explore a method gap; no deadline assigned."]]]],"A small reading slot is enough."]]}
```

## Task selection and section ownership

Before publishing the first task-bearing section, reconcile the relevant prepared
daily tasks with current active inbox constraints, saved project records and
confirmed feedback. Read only relevant details/pages, not the whole briefing or
archived history. Daily records are preserved history, not a list to copy verbatim.

- Identify each distinct action using exact wording, an explicit task/inbox link,
  or a confirmed correction that clearly names the earlier action. A shared project
  or similar wording alone is not proof of equivalence; one inbox entry can contain
  several distinct subtasks. Ask when identity or the effective change is unclear.
- If a confirmed update replaces a task's wording, date, scope or priority, select
  one current title and the latest confirmed constraints. Do not display the old
  version as another task, optional alternative, reminder or preparation card.
  A moved meeting does not create two prep actions or prove prep is due today.
  Pending proposals do not replace confirmed plans. Keep necessary distinctions
  and supported dates; do not invent a deadline or clock time.
- Reuse an existing exact title when the action has not changed. For a confirmed
  replacement, use the current title consistently. Omitting obsolete presentation
  is not deleting, completing, reopening or renaming daily history. Do not claim
  the old checklist row was removed or replay mutations during regeneration.
  If completion is ambiguous across linked versions, ask; never invent progress.

Assign each current action one owner, in this order:

| Section | What belongs here | What stays out |
| --- | --- | --- |
| Schedule / Tomorrow | Approved appointments, plus important work committed to the displayed day: dated obligations, agreed plans and applicable recurring work. Urgent project actions also belong here when their day commitment is supported. Use `agenda` for appointments and `flexible` for untimed actions. | A dump of daily history, the project backlog, optional ideas, or an unfinished task moved to tomorrow without agreement. |
| Project steps (`must-do`) | Concrete necessary next steps for sustained progress on ongoing projects, supported by current records and confirmed reports. Name the project and why this step matters. | Anything already scheduled, one-off personal obligations, completed or obsolete work, or invented busywork. |
| Optional project steps (`nice-to-do`) | Useful but optional project improvements or exploratory next steps. Preserve explicit user priorities. | Scheduled actions, required project steps, unrelated personal errands, or alternative wording for the same action. |
| Reminders / Notes | Relevant background nudges, pending reviews and unresolved questions that are not already represented as an action. | Repeated schedule/project tasks or new execution plans from unconfirmed ideas. |

Do not downgrade scheduled work into Optional project steps to fill a section.
An explicit user priority is retained in the owning task's detail even when that
task belongs in Schedule. A flexible block is optional when no eligible actions
remain; omit empty optional sections. No timed appointments does not establish
a free day, especially when project steps remain. Undated work keeps an empty
date only when it is an explicitly agreed important plan, not backlog padding.

For `/gn`, Today reports actual outcomes; Still open summarizes remaining work
and blockers without relisting every action from Tomorrow or the project sections.
Mentioning reported progress is not another task card. Project steps do not assign
tomorrow dates. Unassigned unfinished work remains open, never silently rolled over.

Before each publish, compare the new actions with earlier published sections and
the reconciled current task choices. One task card per action per occurrence;
recurring actions on distinct confirmed dates may have separate schedule rows.
Do not repeat actions in prose, takeaways or Reminders to bypass this rule. New
publications and saves reject exact-title/whitespace-equivalent duplicate task
cards before writes; code does not guess semantic equivalence. Old saved documents
remain readable without being rewritten. Different-title replacements require the
source reconciliation above, not a claim that checklist deduplication will fix them.

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
