# Manual deployment

GoodMorning is an OpenCode/OpenChamber skill with standard-library CLI helpers,
not a standalone autonomous daemon. An agent or the user copies its public files
into `~/.agents/skills/goodmorning/`. No installer or package builder is needed.

## Requirements

- Linux; Python 3.9+ with IANA timezone data. Prefer a currently maintained Python
  release such as 3.12 or newer. CI checks the supported interpreter matrix.
- Node.js 22.18+ for local/paired-remote project access. No npm install is needed.
- An OpenCode/OpenChamber client that discovers `~/.agents/skills` and supports
  the question tool; ordinary conversation is the documented fallback.
- Outbound HTTPS for weather/news. No key is required for normal weather/model
  AQI or RSS/HN. Optional WAQI/NewsAPI credentials stay in the launching environment.
- Existing owner-authorized OpenChamber pairing for remote projects. Never copy
  pairing credentials into the skill.

## Copy the skill files

Create `~/.agents/skills/goodmorning/` and copy these files from the checkout:

| Source | Destination inside the skill |
|---|---|
| `skill-source/goodmorning.md` | `SKILL.md` |
| `config.example.md` | `config.example.md` |
| `scripts/` | `scripts/` |
| `docs/` | `docs/` |
| `templates/` | `templates/` |

The entry file is ready to copy unchanged; only its filename changes. Preserve
the directory layout, including `scripts/vendor/openchamber-relay/` and its
license/manifest. Exclude generated `__pycache__/` directories and `.pyc` files.
Do not copy personal profiles, SQLite data, ideas, snapshots, caches, credentials,
sandbox fixtures, `.git`, tests, or the entire checkout. Inspect an existing
destination before replacing files; preserve unknown files and local changes.

The copied skill has no checkout dependencies. The repository's source is
inactive; opening the checkout registers no skills or command wrappers.
OpenCode/OpenChamber discovers the global skill by the `goodmorning` ID.
`/gm`, `/gn`, `/eureka`, and `/secretary` are plain workflow requests, not custom
slash commands; natural-language requests work too.

## Validate

From the checkout:

```bash
python -m unittest discover -s tests -p 'test_*.py' -q
node --test tests/test_projects.mjs
```

The tests copy the documented files into a disposable skill directory and check
that helpers work without the checkout. `GM_TEST_TMPDIR` can select a disposable
directory; otherwise tests use the existing approved temporary root or OS default.
Tests use synthetic fixtures, not personal records or live provider credentials.
Copying or validating the skill does not initialize personal records.

## Initialization and storage

Ask the `goodmorning` skill for secretary setup. The first question confirms reply
language; the agent then confirms remaining preferences, file formats and exact
project/provider scope. Run only owner-authorized verification checks. Failed
optional integrations stay pending; they do not authorize code repairs.

Personal records default to `~/.local/share/GoodMorning/secretary/`, or the
explicitly selected `SECRETARY_DIR`. Cache files default to `~/.cache/goodmorning/`,
or the explicitly selected `GM_CACHE_DIR`. Keep both outside the skill.
Pass absolute `--secretary-dir`, weather `--profile`, source/cache paths, and
calendar `--db` as documented. Create the authorized runtime `tmp/` and set
`TMPDIR` for calendar imports. Helpers do not automatically read credential files.

Normal morning news covers yesterday only; same-day updates require explicit
opt-in. News editorial review, delivery acknowledgement and briefing snapshot
saves are separate operations.

## Update and rollback

- Back up the private runtime before updates. Use SQLite's backup API for active
  databases, or stop writers before copying SQLite files/journals.
- Copy changed public skill files only; retain personal records and environment.
  New reply-language preferences do not force older profiles to reinitialize.
- Preserve unknown/newer schemas, corrupt data and stable production locks. Do
  not force migrations, reset databases or replay unknown mutations.
- Retain the previous public skill files for rollback and revalidate them against
  the runtime schema before resuming writes. Restoring old code does not authorize
  discarding newer user records.
- When migrating old registrations, verify the self-contained global skill before
  removing obsolete project skills or command wrappers. Never delete unknown files
  or an old personal runtime during cleanup.

## Supported boundaries

- Production Betterbird staging expands common daily/weekly/monthly/yearly rules,
  additions, exclusions and stored exceptions. Unsupported rules/schemas and
  locked caches are refused without partial imports. Metadata preflight verifies
  schema only; see `calendar-pipeline.md` for supported components and limits.
- Native provider login, ICS file parsing, arbitrary recurrence rules, Twitter/X
  ingestion, automatic collection scheduling and unattended model calls are not implemented.
- Feed reachability, historical RSS coverage and model-authored editorial relevance
  are not guaranteed by passing tests. Source attribution and material gaps remain.
- Open-Meteo's free tier is for non-commercial use. Check provider/feed terms for
  the intended deployment. Copying files grants no new project-wide open-source
  license; retain the supplied upstream vendor license/manifest.
- Real-host pairing repair, optional WAQI verification and deployment-specific
  permissions remain owner steps.
