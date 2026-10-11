# Setup and configuration reference

This is documentation, not a configuration file loaded by every script.
All examples are general; no personal profile or credentials are supplied.
Run helpers from the repository or installed skill root. Ask the globally
installed `goodmorning` skill for secretary setup, or use `/secretary` as a plain
workflow request. This checkout registers no skills or command wrappers.
Installing the skill does not initialize personal data.

Guided setup follows [the staged initialization workflow](docs/initialization.md):
reuse confirmed answers, save local records after consent, and verify only selected
integrations once under a shared elapsed deadline. Failed checks remain pending;
they do not require repeating preferences or fixing integrations during setup.

## User-local files

The first initialization question confirms the secretary's display name, saved
as `secretary_name` after storage consent (optional, 1-30 characters, allow skipping; existing profiles without it stay valid). Use it for self-reference and website/briefing greetings where appropriate.

For local use, the second initialization question confirms the secretary's reply language, saved
as `secretary_language` after storage consent. It applies to all five workflows,
setup/questions and follow-ups, independently of news-source language/country or
tone. Allow explicit language/script, bilingual or “follow my message language”
choices. Existing profiles without it are valid; never silently invent the field. For browser chats, skip the language question: replies follow the website language switch without writing the local field.

After confirming setup answers and file formats with the user:

1. Copy `templates/profile.template.md` to `secretary/profile.md` and fill the
    confirmed fields. Do not infer national news country from city or region.
    During setup, optionally ask about current occupations/roles and expertise/
    fields. Save confirmed answers in `occupations` and `expertise_fields` to
    guide relevant topics, examples, and explanation depth. Allow skipping;
    missing fields in an older profile do not invalidate it.
    For multiple national-news countries, confirm one primary `news_country` and
    store the others as comma-separated `news_additional_countries`.
2. Create `secretary/projects/` and `secretary/daily/`. Copy
   `templates/project.template.md` for each confirmed project.
3. Initialize `secretary/inbox.sqlite` with
   `python scripts/goodmorning.py inbox --secretary-dir RUNTIME --init` after storage consent.
   Capture exact actionable user input with `--add`; query current state through
   stable IDs and bounded pages, not a transcript. See `docs/inbox-pipeline.md`.
   Existing Markdown inboxes need explicit migration authorization; never overwrite
   them. Use `confirmed` only after authorized organization and `done` only on
   user-confirmed TODO completion. Do not put credentials in records.
4. Initialize `secretary/calendar.sqlite` with the calendar command below.
   Run `python scripts/goodmorning.py state --rebuild` to derive `secretary/state.json`.
5. Use `templates/daily.template.md` as the daily format reference when a
   briefing runs. Do not pre-mark greetings or summaries as completed.

`secretary/`, `.env`, and `.cache/` are git-ignored. Keep personal paths,
profiles, imports, and optional configuration under `secretary/`. These ignore
rules do not encrypt files. Never overwrite existing user-local files on setup.
Do not create the legacy `custom_schedule.md` for a new calendar.

Local preflight (no fetching or writes):

```bash
python scripts/goodmorning.py setup --secretary-dir secretary
```

After consent for the listed checks only:

```bash
python scripts/goodmorning.py setup --secretary-dir secretary --verify weather news projects calendar --budget 20
```

Checks run in parallel with a shared 20-second elapsed budget. Select a subset
instead of probing unauthorized sources. Inspect each status; local profile
readiness does not mean provider verification. No reports, delivery marks, event
imports, profile changes or calendar initialization occur in this check command.

## Weather

`python scripts/goodmorning.py weather` reads city from `secretary/profile.md`.
Use `--profile PATH` for another profile. City precedence is `--city`,
`GM_CITY`, `CITY`, then the profile. For verified coordinates, use
`--lat LAT --lon LON`. Weather and model AQI require no key.

WAQI is optional: register at <https://aqicn.org/data-platform/token/> and
provide `WAQI_TOKEN` (or `WAQI_API_TOKEN`) through the environment. Verify the
chosen location and sources during setup. Do not save a token in the profile.
`--aqi-source auto|open-meteo|waqi|off` selects the AQI source.

## News

Default feeds use importance-first candidate scoring plus required assistant
editorial review, not a recency-sorted headline dump. The agent reads collected
candidates, records its selection reasons, and uses `news.py --curate` before
presentation/acknowledgement. Primary announcements are not independent evidence.
See `docs/news-pipeline.md` for the exact candidate/revision workflow and coverage
limitations. Existing delivered reports and briefing snapshots remain intact.

If the user chooses current/breaking updates, set `news_latest: true` and fetch
`news.py --latest` separately from yesterday's report. It uses a five-minute feed
cache, is not a live ticker, and needs editorial review too. Never infer publication
dates from a new social submission or label every recent headline “breaking.”

For agent-managed collection and explicit delivery tracking:

```bash
python scripts/goodmorning.py news --backfill
python scripts/goodmorning.py news --show YYYY-MM-DD
python scripts/goodmorning.py news --ack YYYY-MM-DD --expect REPORT_ID --session NAME
```

These commands read the confirmed profile timezone, country, and optional news
config path. Backfill saves `secretary/news_reports.sqlite` separately from the
cache and daily Markdown. Present a saved report before acknowledging it; empty
sections stay unresolved. See `docs/news-pipeline.md` for statuses, retry limits,
read-only backlog queries, and historical windows. No new file is needed at init;
the first authorized backfill creates the report store.

For stateless retrieval, pass confirmed profile values explicitly:

```bash
python scripts/goodmorning.py news --timezone "$TIMEZONE" --country "$NEWS_COUNTRY"
```

Set these shell variables from confirmed values before running the example;
stateless retrieval does not read the profile or these variables automatically.
For non-bundled countries, create a user-local feed config following
`docs/news-pipeline.md`, verify its feeds, and add `--sources PATH`.
The default provider is free RSS plus Hacker News. `--provider gdelt` is opt-in;
`--provider newsapi` requires `NEWS_API_KEY` in the environment.

Initialization verifies feeds with `news.py --verify-sources --country CODE
--timezone ZONE --sources PATH`: fresh national feeds only, compact counts,
no headline archive/report/acknowledgement writes. The bounded setup checker runs
this for every confirmed country. Additional managed country reports use explicit
`--country CODE`, with separate namespaces in the same report store.

## Calendar

The calendar alone accepts a JSON config through `--config PATH`. Save this
optional example as `secretary/calendar.config.json`; fill `timezone` with the
confirmed IANA timezone before initializing:

```json
{
  "secretary_dir": "secretary",
  "timezone": "",
  "betterbird_path": ""
}
```

```bash
python scripts/goodmorning.py calendar --config secretary/calendar.config.json --init
```

Calendar precedence is CLI flags, environment, JSON config, then defaults.
Supported environment variables are `SECRETARY_DIR`, `CALENDAR_DB_PATH`,
`CALENDAR_TIMEZONE`, and `BETTERBIRD_PATH`. An optional `calendar_db` JSON key
overrides the default database path. If using another database, set
`CALENDAR_DB_PATH` for both calendar and state commands. Betterbird sync stages
imports; it does not approve them or write back to the external calendar.

## State and shared settings

State accepts `--secretary-dir PATH` or `SECRETARY_DIR`. Weather needs an explicit
`--profile` for a relocated profile; setting `SECRETARY_DIR` does not relocate it.
News and weather accept `GM_CACHE_DIR` or `--cache-dir PATH`.
The scripts do not automatically load `.env`; provide variables through the
launching environment. Never commit secrets or copy them into these examples.

Open the relevant usage guide only when needed: `docs/weather-pipeline.md`,
`docs/news-pipeline.md`, `docs/calendar-pipeline.md`, or `docs/state-pipeline.md`.

## Project registry

After confirming aliases, host IDs, workspace paths, exact write targets, and
coordination-lock consent for any write-enabled targets, create `secretary/projects.json` using
`templates/projects.registry.example.json`. Use `host: "local"` for local paths;
remote host references come from existing OpenChamber desktop pairing. Do not
copy credentials or infer shared storage from matching labels or path strings.
Read-only access uses `write_targets: []` and `allow_exec: false`; it needs no
write-lock artifact consent and must not silently broaden to write access.

The project CLI accepts `--registry` / `GM_PROJECT_REGISTRY` and `--settings` /
`GM_OPENCHAMBER_SETTINGS`. Pairing settings default to
`~/.config/openchamber/settings.json` and are read privately, never displayed.
Node.js 22.18+ and Python 3.9+ on Linux are required. See `docs/project-access.md`.
