# Initialization: save locally, verify separately

Result: confirmed preferences/permissions, saved local records, and separate
verified/pending provider statuses. Initialization never authorizes integration
development, extra access, retries or code changes.

## Conversation, in order

If a review request already confirms keeping all saved settings and skipping blank
optional fields, check mandatory setup locally. If it is ready, summarize the
retained values and finish without re-confirming them or writing anything. If
mandatory values are missing, ask only those. Reviewing settings grants no new
integration access or verification consent.

1. Resolve the selected absolute runtime/cache/tmp paths once. A sandbox request
   must not access the real runtime. Inspect existing filenames and preserve data;
   confirm a private ignore rule when needed. Do not read `.env` or pairing credentials.
2. Ask the optional secretary display name first, alone. It must be 1–30 characters,
   contain a letter/number, and contain no control characters. Allow skipping;
   older profiles without a name remain valid. Reuse an answer already supplied.
    After storage consent, save exact `secretary_name` spelling for the assistant,
    never the user's name. Refer to it as the secretary's name, not “you are NAME”.
3. Next, alone, ask what the secretary should call the user: optional, same length
   and character rules, any name or form of address (“Sam”, “Dr. Lee”, “小王”).
   Allow skipping; never infer it from account names, records or email. After
   storage consent, save the exact spelling in `user_name`.
4. Browser requests use supplied `Website language`; never ask for reply language
   or rewrite local `secretary_language`. Pass `--website-language CODE` to setup/workflow.
   Local setup asks reply language next, alone; offer genuine choices/custom
   answers, including bilingual/follow-message language. The current conversation
   language is not consent to save it. Wait for the explicit choice, use it throughout,
   and save it only after storage consent. Source language/country/persona remain separate.
5. For explicit Initialize, review all remaining preferences in small related
   groups, showing saved values and allowing retention. For missing-setup recovery,
   ask only missing settings. Reuse confirmed answers; change only explicitly
   confirmed values. Group location/timezone, work/sleep/tone, news/calendar/project
   scope. Optional roles/fields, special needs and interests may be skipped; reuse
   industry/expertise answers and never invent optional defaults.
6. Prefer `question` with meaningful options and built-in custom input; no dummy
   “Provide a city” buttons. For unsupported text-only forms, ask plainly and wait.
   State date/timezone where needed. Clear answers within an agreed scope need no
   repeat confirmation; ask only genuine ambiguity/substantive changes. Combine
   related event discrepancies, mention conflicts without cancelling, and offer
   unsupported-tone alternatives once.
7. Confirm news countries independently of location: one primary `news_country`
   and comma-separated `news_additional_countries`. Ask if primary intent is unclear.
   Keep separate country namespaces. Confirm a full local feed configuration that
   preserves bundled feeds/adds selected outlets; never substitute feeds after failure.
8. Present one exact file-format/storage/access summary, including runtime,
   authorized remote reads/writes and selected checks. Reuse existing consent only
   for its exact scope. Check-only registry access uses empty write targets and
   disabled execution; do not request write-lock consent for read-only checks.

## Save checkpoint

After consent, create only missing authorized profile/projects/configuration and
runtime folders, initialize missing SQLite calendar/inbox, then rebuild state.
Use `python scripts/goodmorning.py COMMAND`; see `docs/inbox-pipeline.md`.
Keep runtime `tmp/` private and set absolute `TMPDIR` for calendar imports.
No daily task/completion checklists, briefing snapshots/marks, news reports/delivery
acknowledgements, scheduled jobs or external events belong to this checkpoint.

Never reinitialize v1 storage. Review read-only `task --migrate` with the owner;
require explicit backed-up upgrade consent before `--migrate --confirm`. Preserve
history/preferences and flagged legacy reconciliation. A declined upgrade blocks
generation, not the already saved profile.

`setup --secretary-dir RUNTIME` checks locally without fetching, creating files or
external access. Local `profile_ready` requires city, timezone, primary news country
and confirmed reply language. Browser checks add `--website-language en|zh-CN`
instead of requiring a local language field. Neither check changes preferences or
proves optional settings/provider verification complete. Do not restart setup for
missing optional context. Save concise confirmed answers/permissions and separate
saved/verified/pending statuses; a provider failure leaves verification pending.
Without authorized checks, say no checks were performed this time. Do not infer
that integrations are disabled, available or verified, or that all daily functions
work, from `profile_ready` alone.

## Verify only authorized providers

Run selected checks once with a shared elapsed budget:

```sh
python scripts/goodmorning.py setup --secretary-dir RUNTIME --verify SELECTED_CHECKS --budget 20
```

Replace `SELECTED_CHECKS` with only approved names: `weather`, `news`, `projects`,
`calendar`. Browser calls also pass website language. The shared 20-second budget
covers DNS, reads and worker shutdown; unfinished checks remain pending. Inspect
statuses/counts/warnings, not exit codes alone; no private output dumps.

- Weather: confirmed qualified city/model AQI; mismatches, multiple matches, stale
  values, warnings or missing AQI are unresolved, not a fully verified setup.
- News: fresh national-feed `--verify-sources` only, no archive/cache fallback or
  headline/report/delivery writes. Inspect each country's dated counts. Reachability
  does not prove historical coverage, every story's language or editorial truth.
- Projects: already authorized registry only; no probes/writes. Detailed reads are
  separate scoped work; batch them. Pairing repair belongs to the owner.
- Betterbird: `--probe-betterbird` checks metadata compatibility only, not descriptions,
  staging or storage initialization. Busy caches need owner action. Supported schema
  does not prove every recurrence rule valid; defer unsupported rules or request
  expanded event data under `docs/calendar-pipeline.md`, not a coding detour.

Do not fetch omitted checks, retry failures, refresh caches, change outlets, expand
access or adopt a sandbox prototype automatically. State actionable pending items
once. Resume only after a request or owner resolution of the stated prerequisite.

## Optional calendar follow-up

Metadata permission does not authorize event contents. Confirm source calendar,
timezone and exact date window/exclusive end before importing. Use a consistent
SQLite backup, not a raw live copy. Stage credential-redacted originals; protected
links/passcodes stay in source invitations. Inspect each event/current revision
before approval, preserve preparation, and ask only ambiguous/substantive changes.
Never infer attendance/completion. Initialization need not import events.

Validate changes with synthetic records, never personal data. Unit/helper checks
verify mechanics, not actual model behavior or live-provider availability.
