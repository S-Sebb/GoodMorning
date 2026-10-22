# State usage

Use compact command output, not raw `state.json` or bulk answer snapshots.

```bash
python scripts/goodmorning.py state --check --json
python scripts/goodmorning.py state --check --json --limit 7 --offset 7
python scripts/goodmorning.py state --rebuild --json
python scripts/goodmorning.py state --tokens PATH --json
```

Set `--secretary-dir PATH` or `SECRETARY_DIR` for relocated records. Commands
require an existing directory; confirm setup first. The local date uses
`--timezone`, then the profile's IANA timezone, then system local time.
`--today YYYY-MM-DD` selects an explicit date for historical work/tests.
Invalid named timezones are errors, not silent fallbacks.

## Agent contract

- `--check --json` returns one compact object: today's run/session/answer pointers,
  section flags, missed-day page and total, project page and total, inbox/calendar
  counts, warnings, and 7/30-day reply costs.
- Missed days are oldest first. Default page size is seven; `--limit 1..30` and
  `--offset` page missed days and project records. Use `next_offset` and
  `projects_next_offset`. Long gaps are counted without constructing every row.
- Save concise daily records using `templates/daily.template.md`. New browser
  editions live in `daily/YYYY-MM-DD.gm.json` and `.gn.json` (`docs/briefing-format.md`).
- Briefing saves call `state --mark-gm|--mark-gn` internally from the browser
  job's `finish`; agents never run them. They accept either an answer file or stdin, never both. They preserve
  daily tasks/feedback. JSON replies expose date, kind, session, answer pointer,
  and size. Inputs cap at 1,048,576 characters. Native JSON input is required.
- Every save parses/validates the document version before writing. New editions
  use v2 with source checks; existing v1 archives/owned previews remain compatible.
  Saving compacts whitespace without changing string values. It creates one briefing,
  no Markdown/presentation/HTML copies. Invalid input returns `briefing_invalid`
  and a field path without marking. Unrelated text files are ignored and preserved.
- Duplicate marks and existing snapshots are refused with exit 2. Inspect the
  original; replacement goes through browser regeneration.
- Keep `session NAME`, `| answer: path`, and recognized headings intact. Fenced
  examples are ignored; duplicate run lines are errors rather than guesses.
  Inbox counts come from `inbox.sqlite` without loading messages/history into
  context. Use `docs/inbox-pipeline.md` for current entries.
- Active inbox entries include a count and oldest date; newly supplied details on
  closed entries stay active until reviewed. Counts are live, not cached behind a
  required inbox rebuild. Canonical tasks/occurrences remain in SQLite; Reminders
  shows due real questions/reviews under `docs/item-taxonomy.md`, respecting saved
  answers and deferrals. Counts alone do not authorize repeated clarification tasks.
- Exit 0 means success; exit 1 means runtime/storage failure; exit 2 means a
  refused mark or invalid arguments. Operational errors with `--json` contain
  `error` and `next`; argparse validation errors remain on stderr.

## Storage and recovery

- Daily run/history files, canonical inbox/task state and calendar SQLite are
  sources of truth for their respective roles; `state.json` is
  derived. Only the newest 14 daily entries persist. A separate bounded metadata
  cache supports the 30-day cost window. Older run history is rescanned locally.
  Missed days and 30-day totals are computed before truncation.
- Normal checks reuse snapshot statistics when filesystem metadata is unchanged.
  Cold checks stream only snapshots in the 30-day window. `--rebuild` forces fresh
  statistics. Character/4 token estimates are not a model tokenizer.
- Snapshot pointers must identify that day's canonical `.gm.json`/`.gn.json`
  inside `daily/`. External/symlink pointers are not read. Invalid dates, missing
  snapshots, and orphan snapshots produce warnings. Unreadable source records
  fail visibly rather than being interpreted as missing work.
- Corrupt derived JSON can be rebuilt from source records. A newer/unknown schema
  is refused and preserved. Never delete original records to repair an index.
- Linux commands use a stable `.state.lock`, unique temporary files, and atomic
  replacement. A concurrent cooperating command gets `runtime_busy`, not a lost
  update. Do not delete locks. Ordinary editors bypass this lock; atomic writes
  are not a multi-file transaction. An interrupted mark may leave an orphan
  snapshot: inspect it before any replacement.
- Calendar counts come from SQLite. Set `CALENDAR_DB_PATH` for both state and
  calendar commands when using a non-default database.

## Focused verification

```bash
python -m unittest discover -s tests -p 'test_state.py' -v
```

The synthetic 120-day fixture returns seven of 119 missed days with the full
total intact. Its bounded JSON is about 92% smaller than an unbounded, indented
summary. Cold snapshot reads fall from 120 to 30; unchanged warm checks read zero
snapshots while retaining the correct 30-day cost. These measure local read work
and output characters, not exact model tokens or live service behavior.
