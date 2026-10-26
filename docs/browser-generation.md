# Browser generation contract

Inputs: `/gm|/gn`, browser job ID, selected runtime and website language. Result:
a verified saved edition and browser link; code owns cumulative JSON, validation
and final save.

Browser agents do not read this file up front. `job prepare` returns a localized
`contract`, and every receipt's `next.guide` carries the rules for that one step
(`src/goodmorning/briefings/briefing_guides.py`, English and Chinese). The
contract sends the agent to `docs/core-rules.md` and `docs/item-taxonomy.md`
only for feedback no guide covers. This file is the full reference behind those
guides: when a rule here changes, update the matching guide in both languages.

## Prepare and resolve gates

```sh
python scripts/goodmorning.py job --secretary-dir RUNTIME --job JOB prepare
```

Use the real session from `OPENCODE_SESSION_ID`, or `--session REAL_SESSION`.
Ownership is checked. Reuse returned preparation, pinned date/paths/preferences,
actual browser feedback and `website_language`. The edition retains this language
through questions/titles/document `lang`; later interface changes affect future
requests, not this edition or earlier content. Never ask another reply language.
Each success receipt includes `reply_context`: use its pinned language and saved
tone for any visible text, even when helper instructions are written in English.
Chinese requests state the edition and label the job/runtime in Chinese; the job ID, selected paths and
`Website language` pin are unchanged. All labels refer to the same saved job.

- Follow each receipt's `next` command and position. For a fresh job,
  immediately `init` before fetching or additional reads. Use the default plan
  unchanged, including titles. For an existing checkpoint, resume its returned
  next step; do not replace its greeting/opening/plan. Never invent flags.
- v2 receipts run the next section's read recipes themselves, after the
  previous publication, and return them as `next.results` (`command`, `exit`,
  `output`). This removes one model turn per read without collecting future
  sections. The agent reruns a result's command only for a later Tasks page or
  a fresh Today read after a feedback write. Legacy v1 receipts still list
  `read` commands for the agent to run.
- Do not rerun `workflow`, ask missing-edition questions or re-ask supplied progress.
  Additional questions cover unresolved material ambiguity/consent only. Browser
  jobs use their pinned current briefing day (04:00 profile-timezone rollover),
  leaving archive gaps read-only. News covers the 24 hours before the job was created;
  weather keeps actual timestamps.
- `migration_required`: stop generation and use Secretary for read-only
  `task --migrate` review and explicit backed-up upgrade consent. Keep saved setup;
  never reset the runtime or loop on generation.
- False saved `integration_policy` values prohibit live project access, calendar
  sync or publisher images despite imported profile settings.
  Use authorized copied records only; never auto-approve or infer progress.
- Conditional reminders use the original request timestamp, including queue arrival,
  not model finish/wake time. Regeneration keeps that trigger; unknown future
  conditions do not assign a day or create timed calendar bookings.

## Publish only the next section

Workflow steps describe section content, not permission to collect the entire
edition before publication. After allowed feedback reconciliation, publish Today
before reading Schedule or Reminders; then follow each receipt's next position.
Task-section recipes carry `--browser-job` and `--session`; reads check owner, date, edition,
language and next position. Active browser actors remain bound if that flag is
omitted. An out-of-turn read error means publish the current section first, not
that the provider is unavailable. Original evening attribution may read Tasks;
regeneration cannot use that prerequisite exception.

Use small JSON objects on stdin. Serialize nontrivial text with
`json.dumps(..., ensure_ascii=False)`; do not manually escape nested quotes or
write agent-owned cumulative drafts. Check exits and `error`/`next` after every call.

1. **init:** `{"greeting":"…","opening":"…"}`. Optional `lang` must equal the
   pinned language; optional `plan` must equal the default. Greeting/opening remain
   immutable. Keep the opening factual before collection, not a speculative overview.
2. **publish:** gather only the next section from saved context/returned results,
   follow pages/review requirements, then submit
   `{"position":N,"section":[TYPE,BLOCKS,NOTE?,TITLE?]}`. This notation describes
   fields, not literal JSON: omit unused trailing fields. `position` is zero-based
   and includes skipped positions. Submit one complete section, not the whole
   briefing. Its title must match the saved plan; earlier sections cannot change.
3. **skip:** `{"position":N}` only for genuinely empty Tasks/Reminders positions.
   Never skip required Weather/News/Schedule/Today or turn failed retrieval into
   empty success. Publish material unavailability instead; keep all plan positions.
4. **finish:** `{"closing":"…"}` or `{}` after every position is resolved.
   Code verifies owner/session/date/edition/exact preview, saves native JSON/run
   marker, and repairs its derived index. A snapshot alone never proves completion.
   New v2 editions copy no tasks to daily checklists. Already-published v1 previews
   may finish under their saved contract, never as new canonical plans.

The init and finish receipts, and Sunday's letter read, carry `memory`, the note
the secretary keeps about the user (`docs/workflows/secretary.md`, *Memory*), when
memory is on and the note has text. Only the greeting, an optional closing and the
letter's sign-off may lightly reflect it; sections, notes and progress never use
it, and it never adds a closing on its own. After an evening save (not a
regeneration) with memory on, the finish receipt also carries the note and the
user's chat messages since the last tidy: the agent folds in what is missing,
drops `lately` items that are over, writes with `memory --write` and only then
hands over the link.

Example (replace `RUNTIME`/`JOB` with supplied values; use the same flags throughout):

```sh
python scripts/goodmorning.py job --secretary-dir RUNTIME --job JOB publish <<'JSON'
{"position":0,"section":["weather",[["p","Weather is unavailable; check before travelling."]]]}
JSON
```

Order: gm Weather, News (the 24 hours before the job's as-of time), Schedule, Tasks, Reminders; gn Today, Weather tomorrow, Schedule, Tasks, Reminders, then New episodes
when `anime_updates` is on, Game sales when `game_sales` is on and Stocks when
`stock_report` is on. Either edition ends with the Weekly letter when one is due:
Sunday's evening, or the first briefing after a week ended without its letter
(never skipped; `docs/weekly-letters.md`). Do not alter the
default plan. Use code-owned blocks/pages under `docs/item-taxonomy.md`. Project/
personal and optional/required are task labels, not new sections. Read all selected
news/citations before publishing. Presentation grants no task creation, scheduling,
completion or execution; authorized unrelated record changes retain their own scope.

## Feedback, recovery and replacement

- Browser preflight saves gn feedback and completes only selected exact IDs under
  `docs/item-taxonomy.md`; partial work stays open. Reuse those answers without
  applying completions again. No choices means ask about actual accomplishments,
  not an empty checklist. Failed/uncertain feedback saves block dispatch; no run
  marker while waiting. Reconcile original-run partial/blocked reports only as the
  gn workflow specifies, never during regeneration.
- **Prepare again** reopens stopped undispatched preflight. **Refresh task list**
  preserves earlier questions and requests fresh confirmation of changed plans;
  neither discards uncertain saves nor invents completions.
- **Continue existing session** targets a known idle owner with no pending inputs,
  retaining published sections. Uncertain dispatch requires inspection, never
  automatic replay. Recovery is account-local, today-only and reservation-controlled.
- A question the secretary asks during generation is saved in the job registry and
  closed in the engine; the job waits without holding the model slot, across restarts
  and deployments. The answer continues the same session from its checkpoint (moved to
  the running release, with the generation prompt and the answer), even after the
  edition's day has passed; the edition keeps its own date.
- **Regenerate today's briefing** needs explicit confirmation and a new owning job/
  session. It refuses active/pending/uncertain work; superseded jobs cannot publish,
  save or accept replies. Old context/previews, saved JSON/run marker and private
  rollback backup remain preserved until verified replacement. Original snapshot/run
  checks reject unrelated changes. Do not use `--force` or save from a foreign session.
- Regeneration replaces presentation only. Reuse saved feedback/current records;
  never replay completions, daily/inbox/project/calendar writes or earlier execution.
  Tasks, other editions, delivery records and preferences stay unchanged. Reconcile
  confirmed replacements under `docs/briefing-format.md`, not obsolete daily titles.
  Feedback's returned `date` is its reporting day. Anchor relative words to the
  pinned edition date, not the host clock: regenerating the same day's report does
  not make today's blocker yesterday's or move its agreed workday.
- Schema/content errors: fix only unpublished input using returned field/line errors.
  Source conflicts: reread affected rows, never rewrite immutable sections. Identical
  published-position retries reuse their result. Interrupted final save: inspect,
  then retry `finish` only in the same job with its exact document/closing. Matching
  saves/run markers are verified, not rewritten; unknown mutations are never blindly replayed.

## Presentation and delivery

Use confirmed language/tone, a short greeting/opening and grounded optional notes.
Visible progress may name the user's section (for example, checking the weather),
not helper actions such as `init`, schema checks or numbered publication positions.
The viewer owns date navigation; no repeated date, Markdown/HTML in JSON strings,
generic reassurance or restated timetable rows. Preserve material failures, actual
times and uncertainty. No appointments does not establish free time; open actions
have no invented workday. Clear ideas are not nightly interviews.
The next receipt's localized `writing` reminder applies at that authoring step.
Action-row dates are workdays, not deadlines. Open work is not proven ready or
unblocked; one removed blocker does not prove all prerequisites are met. Do not
promise automatic updates when a provider recovers. Keep warmth in verified facts.

Return a short browser-link handoff; a brief delivery label in the saved tone is
allowed, not a second summary. No text/card/presentation/dated HTML copies or cleanup
of private records. Code owns rendering, section animation/progress and the one
checkpoint; only a verified completed preview is cleaned up.
After verified `finish`, do not recap sections or append an invitation in chat;
use its `url` as a relative Markdown link. No hostname is needed. Do not search
ports, accounts, test runners or other runtimes to construct a URL; a domain in
documentation is not this request's website origin.
The saved page contains the greeting, findings and closing. A failed collection
supports reporting unavailable data, not inventing a retry page, button or future
recovery. Offer only a recovery action present in the actual receipt or website.

Publisher images need
separate permission. With saved `publisher_images: true`, the job caches news
previews before advancing, never on ordinary page reads. Failed previews keep
placeholders and may retry after one hour; successes deduplicate. `web --fetch-images`
updates saved image objects without exporting/rewriting briefings. Browser authors
use the job helper, not its lower-level stream/state components directly.
