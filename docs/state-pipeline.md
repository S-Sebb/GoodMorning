# State usage

Use compact command output, not raw `state.json` or bulk answer snapshots.

```bash
python scripts/state.py --check --json
python scripts/state.py --check --json --limit 7 --offset 7
python scripts/state.py --mark-gm --session NAME --answer-file PATH --json
python scripts/state.py --mark-gn --session NAME --answer-stdin --json
python scripts/state.py --rebuild --json
python scripts/state.py --tokens PATH --json
```

Set `--secretary-dir PATH` or `SECRETARY_DIR` for relocated records. Commands
require an existing directory; confirm setup first. The local date uses
`--timezone`, then the profile's IANA timezone, then system local time.
`--today YYYY-MM-DD` selects an explicit date for historical work/tests.
Invalid named timezones are errors, not silent fallbacks.

## Agent contract

- `--check --json` returns one compact object: today's run/session/answer pointers,
  section flags, missed-day page and total, project page and total, inbox/calendar
  counts, news overview, warnings, and 7/30-day reply costs.
- Missed days are oldest first. Default page size is seven; `--limit 1..30` and
  `--offset` page missed days and project records. Use `next_offset` and
  `projects_next_offset`. Long gaps are counted without constructing every row.
- News counts use the confirmed profile's default configuration. Use
  `news.py --status` for the authoritative backlog or explicit overrides.
  A Markdown news heading indicates presence, never collection or delivery.
- Save concise daily records using `templates/daily.template.md`. Verbatim
  replies live in `daily/YYYY-MM-DD.gm.md` and `.gn.md`. Open only on explicit need.
- Mark commands accept either an answer file or stdin, never both. They preserve
  daily tasks/feedback. JSON replies expose date, kind, session, answer pointer,
  and size. Inputs cap at 1,048,576 characters. Missing answer input remains
  supported but emits a note.
- Duplicate marks and existing snapshots are refused with exit 2. Inspect the
  original; use `--force` only for an authorized replacement.
- Keep `session NAME`, `| answer: path`, and recognized headings intact. Fenced
  examples are ignored; duplicate run lines are errors rather than guesses.
  Inbox counts use the status column, not words inside the raw idea.
- Pending ideas include a count and oldest date. Remind at today's `/gn`,
  otherwise the next `/gm`, until confirmed and organized.
- Exit 0 means success; exit 1 means runtime/storage failure; exit 2 means a
  refused mark or invalid arguments. Operational errors with `--json` contain
  `error` and `next`; argparse validation errors remain on stderr.

## Storage and recovery

- Daily files and the calendar database are sources of truth; `state.json` is
  derived. Only the newest 14 daily entries persist. A separate bounded metadata
  cache supports the 30-day cost window. Older run history is rescanned locally.
  Missed days and 30-day totals are computed before truncation.
- Normal checks reuse snapshot statistics when filesystem metadata is unchanged.
  Cold checks stream only snapshots in the 30-day window. `--rebuild` forces fresh
  statistics. Character/4 token estimates are not a model tokenizer.
- Snapshot pointers must identify that day's canonical `.gm.md` or `.gn.md`
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
- Calendar counts come from SQLite; `custom_schedule.events` is a compatibility
  key, not a Markdown event count. Set `CALENDAR_DB_PATH` for both state and
  calendar commands when using a non-default database.

## Focused verification

```bash
python -m unittest discover -s tests -p 'test_state.py' -v
python tests/benchmark_state_news.py
```

The synthetic 120-day fixture returns seven of 119 missed days with the full
total intact. Its bounded JSON is about 92% smaller than an unbounded, indented
summary. Cold snapshot reads fall from 120 to 30; unchanged warm checks read zero
snapshots while retaining the correct 30-day cost. These measure local read work
and output characters, not exact model tokens or live service behavior.
