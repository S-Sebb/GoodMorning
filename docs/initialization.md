# Initialization: save locally, verify separately

Initialization should establish confirmed preferences and permissions, not become
an integration-development session. Failures do not erase answers or authorize
extra reads, retries, imports, or code changes.

## Conversation

An explicit `/initialize` reviews all existing preferences in small groups. Show
saved values and allow retaining them. Change only explicitly confirmed values;
preserve all records, permissions and answers already given in this conversation.

1. Resolve the runtime once, including its cache and temporary paths. A sandbox
   request must not read or initialize the real secretary runtime. Inspect existing
   filenames first; preserve existing data and confirm a private ignore rule if
    needed. Never read `.env` or pairing credentials.
2. Ask for the secretary's display name first, alone: “What would you like
   to call me as your secretary?” It is an optional short name (1-30
   characters, at least one letter or number, no control characters). Allow
   skipping; older profiles without `secretary_name` stay valid. Wait for the
   answer before other setup questions. Keep it in the conversation until
   storage consent, then save the exact confirmed spelling in `secretary_name`.
   Use it for assistant self-reference and website labels, not the user's name.
   **Website:** use the supplied `Website language` for all replies and questions;
   do not ask for a separate reply language or write it into the local profile.
   `setup`/`workflow` helpers use `--website-language CODE` for browser requests.
   **Local use:** the second initialization question is the secretary's reply language, alone:
   “Which language would you like me to use as your secretary?” Use the current
   conversation language only to ask that initial question; it is not consent to
   save a preference. Offer genuine language/script choices and custom answers,
   including bilingual or “follow my message language.” Reuse a language preference
   only when explicitly given. Wait for the answer before other setup questions.
   Keep it in the conversation until storage consent, then save `secretary_language`
   in the selected profile. Continue all setup/questions in the chosen language.
   It does not set news-source language, country, timezone, industry or persona.
3. Reuse all clear answers. Ask only missing details in a few small related groups:
   location/timezone; schedule/tone; news/calendar/project preferences. Invite
   optional roles/fields, special needs and knowledge interests without redundant
   industry/expertise questions. Optional skips are explicit, not invented defaults.
4. Use real choices in question widgets. Do not offer buttons such as “Provide a
   city” or “Specify a time”: clicking them supplies no data and creates another
   round. For text-only questions, use the built-in custom input without dummy
   options when supported; otherwise ask plainly and wait. Explain the current
   date/timezone so the user can give a complete correction in one answer.
5. A clear answer within an already stated date/timezone/scope need not be reconfirmed.
   Ask once about genuine ambiguity or a substantive change; combine related event
   discrepancies into one review. Mention scheduling conflicts without silently
   cancelling either event. Offer unsupported-tone alternatives once, not repeatedly.
6. Confirm national-news countries separately from location. Save primary
   `news_country` and any comma-separated `news_additional_countries`; never infer
   a primary when the user's order/intent is unclear. Each country uses its own
   news run/report namespace. A full local feed config preserves bundled feeds
   and adds confirmed outlets; no arbitrary feed substitution after failure.
7. Explain the file formats and present one storage/access summary covering exact
   runtime, authorized remote reads/writes, and selected provider checks. Existing
   consent is reusable for those exact actions; new scope still needs consent.
   Check-only remote access uses empty write targets and disabled execution, so
   there is no need to seek write-lock consent for it.

## Local checkpoint

After consent, create only missing profile, project records, runtime folders
and agreed configuration. Initialize an empty SQLite calendar and inbox
(`inbox --secretary-dir RUNTIME --init`), then rebuild state. Do not overwrite
unrelated private files. See `docs/inbox-pipeline.md` for the storage contract.
Include an authorized runtime `tmp/` folder; set `TMPDIR` to its absolute path
for calendar import commands so disposable source snapshots stay in the runtime.
No daily tasks/completions, briefing snapshots/marks, news reports/acknowledgements,
scheduled jobs, or external calendar events belong to this checkpoint.

`python scripts/goodmorning.py setup --secretary-dir RUNTIME` is a compact local check.
It never fetches, creates files or accesses configured external projects/calendar
caches. `profile_ready` requires city, timezone, primary news country and an
explicitly confirmed reply language for local use. A browser check passes
`--website-language en|zh-CN`, using the website setting instead of a profile
language field. Neither mode changes existing preferences during a check.
The check does not determine whether
every optional preference has been discussed or providers verified. Ask only for
missing required settings; never reset existing answers or infer a language.
Missing optional context is not a reason to restart setup.

Save a concise setup-status record with confirmed answers, permissions and separate
saved/verified/pending items. Provider failures leave setup **saved with verification
pending**, not “fully verified” or a reason to repeat preference collection.

## Bounded verification

After explicit consent, select only authorized checks:

```bash
python scripts/goodmorning.py setup --secretary-dir RUNTIME --verify weather news projects calendar --budget 20
```

The checks run concurrently with a **shared 20-second elapsed budget**, including
DNS, response reading and subprocess shutdown. This is different from a socket
timeout, which can be exceeded by DNS or several sequential requests. Failed
workers are stopped; queued checks with no time left stay pending. The budget is
configurable, not permission to retry repeatedly. Output is counts/statuses, not
whole news reports, event descriptions or private settings.

- Weather checks the confirmed qualified location and model AQI. A country/region
  mismatch or multiple matches is unresolved, never the first arbitrary city.
  Warnings, stale data or missing AQI are not a fully verified weather setup.
- News uses fresh `--verify-sources` checks for national feeds only, with no
  archive/cache fallback and no headline/report/delivery writes. Inspect each
  requested country's dated-item counts. Reachable feeds do not prove historical
  coverage, language compliance of every story, or editorial truth.
- Projects check only an already authorized registry, without probes or writes.
  More detailed project-note reads are separate authorized work; batch related
  reads and reuse the connection. Pairing repair belongs to the owner.
- Betterbird uses `--probe-betterbird` for compatibility metadata only. It does not
  initialize secretary storage, read descriptions, or stage events. A busy cache
  needs owner action (usually closing Betterbird). Modern recurrence schemas are
  supported; metadata preflight does not validate individual rules. Unsupported
  schemas or rules need deferral or expanded event data, not a code-writing detour
  inside initialization. See `calendar-pipeline.md` for expansion limits.

Do not auto-fetch omitted checks, retry failures, change outlets, refresh caches,
expand access or adopt a sandbox prototype. Surface actionable pending items once.
Resume checks only after the user requests them or resolves a stated prerequisite.

## Calendar review is optional follow-up

Metadata access is not consent to read event contents. Before importing, confirm
the exact source calendar and date window (including timezone and exclusive end).
Use a consistent SQLite backup, never a raw live-file copy as “verified.” Stage
credential-redacted originals; keep passcodes/protected joining links in source
invitations. Review each event and current revision before approval. Ask only about
ambiguous details or substantive edits, preserve preparation requirements, and do
not infer attendance or task completion. Initialization need not import any events.

## Failure lessons and validation

The walkthrough exposed repeated dummy-button questions, long socket-timeout runs,
first-result geocoding, changed-feed cache contamination, late recurrence discovery,
locked-calendar copies, and credentials persisted before review. Regressions cover
these code failures and instruction boundaries with synthetic inputs. No real
preferences, project paths, calendar descriptions or credentials belong in tests.

Run `python -m unittest discover -s tests -p 'test_*.py'` and
`node --test tests/test_projects.mjs`. A passing suite proves these contracts, not
that an actual model will ask fewer questions or that live providers will work.
