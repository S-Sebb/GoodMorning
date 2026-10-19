# Helper inputs

Every write helper takes one JSON object: `--input-stdin` with a quoted heredoc
(`<<'JSON'`), or `--input-json '…'`. This page is the complete input contract.
Code rejects unknown fields and invalid values with an `invalid_input: …` message
that names the fix. Never read source code or tests to learn an input format; if
a rejection is unclear, fix what its message names, then report the failure.
Every write also needs the actual `--session` and a stable `--request-key`.
Examples are tested against the real helpers.

## Capture: `workflow --capture todo|eureka`

Fields: `raw` (required, the user's words verbatim), `summary` (revised title),
`context` (the request as agreed), `project`, `review_after` (YYYY-MM-DD). Ideas
only: `questions` (at most 12 open questions). TODO only: `task` (TASK, below) and
`also` (1–4 sibling TASKs, each with its own `title`). Never send `kind`; an
unclear TODO gets a native question before capture, not saved `questions`.

```json workflow --capture todo
{"raw":"Add new todo, record muscle training at home videos for my mom.",
 "summary":"Record at-home muscle-training videos for Mom",
 "task":{"title":"Record at-home muscle-training videos for Mom","detail":"",
  "display":{
   "en":{"morning":{"title":"Record at-home muscle-training videos for Mom","detail":""},
         "schedule":"Training videos for Mom"},
   "zh":{"morning":{"title":"给妈妈录居家力量训练视频","detail":""},
         "schedule":"给妈妈录训练视频"}}}}
```

```json workflow --capture eureka
{"raw":"What if the weekly page showed a mood line?","context":"Idea only; no work requested."}
```

## TASK fields

All optional except `title` in a new task. Unset dates and text use `""`; unset
`repeat`/`when` use `null`. Category rules and wording are in `docs/item-taxonomy.md`.

| Field | Value |
|---|---|
| `title` | Imperative, at most 600 characters |
| `detail` | 1–2 grounded sentences, or `""` |
| `extra` | Secretary's own notes for next time, at most 2000 characters |
| `kind` | `""` (action), `nudge`, `errand` or `reference` |
| `trigger` | Reference notes only: the situation that recalls it |
| `project`, `optional`, `priority` | Text; boolean; `""`, `high`, `normal` or `low` |
| `status` | `open`, `partial`, `blocked`, `done`, `cancelled` |
| `planned_date` | Agreed workday, YYYY-MM-DD |
| `due_date`, `due_soft` | Deadline day; `true` for a soft project target |
| `due_at` | ISO timestamp with offset; needs `timezone` |
| `defer_until` | First day the work may start |
| `timezone` | IANA zone; required with `repeat`, `when` or `due_at` |
| `repeat` | `{"start":DATE}` plus exactly one of `weekdays` (0=Monday..6=Sunday), `interval_days` (1–366), `dates`, or `event_subject` (with `offset_days` -14..0); optional `until`, `exclude`, `include`. No `planned_date` alongside |
| `when` | `morning_before` (`"HH:MM"`), `unless_experiment_plan`, `unless_timed_plan`, `planned_task_id`, `custom_rule_id` |
| `follow_up` | `""`, `until-done` (one-off) or `one-outstanding` (with `interval_days`) |
| `after` | `task_…` ID this undated step waits for |
| `work_kind` | `""` or `experiment` |
| `notice` | `{"morning":N,"evening":N,"early":BOOL}`, any subset; dated actions only |
| `display` | DISPLAY, below |

**DISPLAY**: `{"en":{"morning":{"title","detail"},"evening":{"title","detail"},"schedule":TEXT},"zh":{…}}`.
Both languages; `morning` and `schedule` required, `evening` optional. One-line
text: titles at most 120 characters, details at most 240 (may be `""`), schedule at most 40.
No relative day words (today, tomorrow, 今天, 明天…; evening may say "tonight").
Never send `source`; code adds it.

## `task --add` and `task --capture-draft`

`task --add` takes the TODO capture fields above. `task --capture-draft` saves an
unknown-time appointment: `raw`, optional `summary`/`context`/`project`, and
`draft` with `title`, `date`, `timezone`, `location`, `detail`, `confirmed_day`,
`state` (`tentative`, `needs-details`, `ready-for-confirmation`), `event`,
`repeat` (`{"weekdays":[…],"start":DATE,"until"?,"exclude"?}`, start equal to
`date`, confirmed day only), `notice` (`morning`/`evening`), `extra`, `display`.

```json task --add
{"raw":"Remind me to bring gym clothes on Tuesdays and Thursdays",
 "summary":"Bring gym clothes",
 "task":{"title":"Bring gym clothes","kind":"nudge","timezone":"Europe/London",
  "repeat":{"weekdays":[1,3],"start":"2026-10-20"}}}
```

```json task --capture-draft
{"raw":"Dentist on Thursday at Town Clinic, time not confirmed yet",
 "summary":"Dentist",
 "draft":{"title":"Dentist","date":"2026-10-22","timezone":"Europe/London",
  "location":"Town Clinic","confirmed_day":true}}
```

## `task --update ID --expect-revision REV`

Only the changed TASK (or, with `--draft`, draft) fields. Completion adds
`"confirmed_completion":true` after the user confirmed it. A repeating task is
completed one day at a time with `--report`.

```json task --update
{"planned_date":"2026-10-23","notice":{"morning":1}}
```

## `task --report ID --date DATE --expect-revision REV`

One day of a dated task: `status`, optional `detail`, and
`"confirmed_completion":true` for `done`. Add `--actual` when the user did it on
a day outside the plan; the date must not be in the future.

```json task --report
{"status":"done","detail":"Finished before lunch.","confirmed_completion":true}
```

## `inbox --append ID` and `inbox --update ID --expect-revision REV`

`--append` adds the user's follow-up wording: `{"detail":"…"}`. `--update` changes
`summary`, `context`, `project`, `questions` (ideas only), `status` (`pending`,
`confirmed`, `done`), `reviewed` (boolean), `review_after`, and
`confirmed_completion` (closing a TODO).

```json inbox --append
{"detail":"Also film the stretching warm-up."}
```

```json inbox --update
{"summary":"Weekly mood line","reviewed":true}
```

## `custom --add`, `custom --update ID`, `custom --report ID --date DATE`

A habit whose rhythm a fixed repeat cannot express. `--add` needs `title`,
`timezone` and `policy`, plus optional `detail`. `policy` has `base`
(`interval_days` or `weekdays`, with that field), `start`, `anchor` (`fixed`, or
`last_completion` to restart the gap from each finish), `miss_policy` (`chase`
daily or `fixed`), `weekly_cap` (1–7 per Monday–Sunday week, or `null`) and
`nightly` (`due_only` or `always`). `--update` sends changed `title`, `detail`,
`timezone`, `policy` (whole) or `status`. `--report` records a confirmed finish
on its actual day: `{"status":"done","confirmed_completion":true}` with optional
`detail`.

```json custom --add
{"title":"Go to the gym","detail":"","timezone":"Europe/London",
 "policy":{"base":"interval_days","interval_days":2,"start":"2026-10-13",
  "anchor":"last_completion","miss_policy":"chase","weekly_cap":3,"nightly":"always"}}
```

```json custom --report
{"status":"done","confirmed_completion":true}
```

## Other inputs

- `task --adopt ENTRY` and `task --convert ID`: `docs/item-taxonomy.md` rules 6–7.
- Calendar events (`calendar --approve`, `event`): `docs/calendar-pipeline.md`.
- `daily --amend`: `docs/workflow-helpers.md`.
- New-episode updates: `anime --source anilist|bangumi|myanimelist --check-account NAME` (or `--check-account LINK`, which picks the source) and
  `--search "TITLE"` only read; the profile lines they inform follow the rule
  below (`docs/workflows/secretary.md`, step 4).
- Game-sale updates: `games --check-account NAME` and `--search "TITLE" --country CC`
  only read; the same rule applies.
- Stock holdings: `stocks --search "NAME OR CODE"` and `--check "ENTRIES"` only
  read; the same rule applies.
- Profile fields (names, tone, city): no helper. Edit only that field's
  `key: "value"` line in `RUNTIME/profile.md`, quoted as in
  `templates/profile.template.md`, then read the line back.
