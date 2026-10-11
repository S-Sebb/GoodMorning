# Workflow helpers

All paths below are absolute selected runtime paths. Run from the installed root.
Helpers automate mechanical operations, never choose goals, grant permissions,
decide task completion, approve imports, select news or claim delivery.

## Prepare once

```bash
python scripts/goodmorning.py workflow --secretary-dir RUNTIME --cache-dir CACHE --prepare gm
python scripts/goodmorning.py workflow --secretary-dir RUNTIME --prepare gn --today YYYY-MM-DD
python scripts/goodmorning.py workflow --secretary-dir RUNTIME --prepare secretary
```

This returns relevant confirmed preferences (including optional `secretary_name` for self-reference and website labels), local date/adjacent dates, resolved
paths, bounded daily tasks and active inbox summaries. No provider or remote
project access, setup writes, snapshot reads, briefing marks or index rebuild/save.
Duplicate gm/gn returns only the original session/pointer and stop instruction,
before loading tasks/inbox content. Missed-day metadata shows the oldest; the
agent still asks which date to work on. Continue task/inbox pages only as needed.
Fetch weather/news only when the agent has resolved duplicate/missed/setup gates.
For capture with supplied raw input, skip preparation and use the fast path.

English title suggestions are deterministic. For other languages, `title:null`
means translate the workflow prefix using the confirmed language, not guess a
preference or translate raw idea/TODO wording. Rename through the session tool;
do not rename a duplicate briefing. The helper does not touch session services.

## Save-first capture in one command

```bash
python scripts/goodmorning.py workflow --secretary-dir RUNTIME --capture todo --session SESSION \
  --request-key STABLE_KEY --input-stdin
```

JSON stdin: `{"raw":"Buy milk","project":"ConfirmedAlias"}`. `project`, `summary`,
`context` and `questions` are optional; omit unknowns. Use `--capture eureka` for
ideas. `kind` comes from the workflow, not the payload. The command checks local
setup, uses the actual timestamp and calls the transactional inbox once. Output
is a save receipt, minimal reply preferences and title suggestion; no historical
context, full profile or state check. Retry with the same key/input, not another
capture. `--input-file PATH` is also supported. No user text means ask first.
No weather/news, task execution, project reads, calendar changes or auto-setup.
Follow-ups/organization/completion use `docs/inbox-pipeline.md`.

## Daily records without full-file rewrites

```bash
python scripts/goodmorning.py daily --secretary-dir RUNTIME --date DATE --show
python scripts/goodmorning.py daily --secretary-dir RUNTIME --date DATE --show --section feedback
python scripts/goodmorning.py daily --secretary-dir RUNTIME --date DATE --amend --expect SHA256 --input-stdin
```

`--show` returns the whole record's hash (`missing` when absent), current task IDs,
completion flags and `next_offset`. Long task previews are explicitly flagged;
read the relevant section with character pages before relying on omitted text.
Tasks page at seven by default (max 30); section text pages at 2,000 characters
(max 8,000). All unrelated text remains protected by the hash without entering
the model's context. `--offset` follows the returned offset for that view.

Amendment JSON example:

```json
{"append":{"feedback":["User reports the outline is blocked."]},
 "tasks":{"must-do":[{"text":"Clarify the saved idea","ref":"ib_0123456789abcdef"}]},
 "complete":["TASK_ID_FROM_CURRENT_VIEW"],"confirmed_completion":true}
```

- `append` adds exact nonduplicate bullet lines under weather/news/schedule/
  feedback/progress. `replace` replaces only explicitly named such sections for
  an authorized amendment; omitted sections/run lines/unknown text are untouched.
- `tasks` adds unchecked must-do/nice-to-do items. Existing checked items are never
  reset or deleted. Exact wording deduplicates across both lists; an explicit
  inbox `ref` deduplicates a changed reminder without erasing its completion.
  Omit refs for unrelated project subtasks; code never guesses equivalent meaning.
- `complete` changes only exact IDs from the current view and requires the caller's
  `confirmed_completion:true`, representing actual user confirmation, not permission
  to infer it. Partial/blocked work stays open. No automatic reopening/removal.
- `--expect` uses the latest hash; the helper shares `.state.lock` with state marks
  and atomically replaces one file. Other editors can bypass locks; a second hash
  check detects many outside edits, not an impossible cross-editor transaction.
  A conflict requires a focused reread/reconciliation. Repeat exact amendments
  with a fresh hash after verifying an uncertain outcome; dedup makes them no-ops.
- After daily amendments, mark gm/gn using the exact answer file/stdin through
  `scripts/goodmorning.py state`. Do not mark a waiting `/gn`, acknowledge news, or alter snapshots
  during a normal amendment. Index reads/marking already rescan current records;
  do not run a redundant `--rebuild` after every edit.

## News and calendar reads

`python scripts/goodmorning.py news --show DATE --view candidates --limit 10 --offset N` returns complete
candidate records and a `next_offset`, preserving IDs and current report ID. Read
all pages needed for editorial judgment; pagination is not permission to ignore
evidence. `--view stories` returns every selected story, source/summary/date,
coverage warning and review state without reprinting candidate/diagnostic history.
`--curate ... --view stories` returns the saved reviewed stories directly; no
second `--show` is needed. The full view remains for explicitly requested diagnostics.
None of these commands acknowledge delivery or automate editorial judgment.

Calendar `--json --details` on a narrow approved window includes actual notes and
organizer in one query. No per-event detail reread unless examining an import/
change/original. Ordinary calendar reads are read-only; missing storage is a setup
failure, not an empty schedule or permission to initialize a database.
