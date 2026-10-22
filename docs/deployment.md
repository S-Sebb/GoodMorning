# Manual deployment

GoodMorning is an OpenCode/OpenChamber skill with standard-library CLI helpers,
not a standalone autonomous daemon. An agent or the user copies its public files
into `~/.agents/skills/goodmorning/`. No installer or package builder is needed.

## Requirements

- Linux; Python 3.14+ with IANA timezone data. CI tests Python 3.14.
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
| `LICENSE` | `LICENSE` |
| `skill-source/goodmorning.md` | `SKILL.md` |
| `config.example.md` | `config.example.md` |
| `scripts/` | `scripts/` |
| `src/` | `src/` |
| `assets/` | `assets/` |
| `integrations/` | `integrations/` |
| `vendor/` | `vendor/` |
| `requirements/` | `requirements/` |
| `docs/` | `docs/` |
| `templates/` | `templates/` |

The entry file is ready to copy unchanged; only its filename changes. Preserve
the directory layout, including `vendor/openchamber-relay/` and its
license/manifest. Exclude generated `__pycache__/` directories and `.pyc` files.
Do not copy personal profiles, SQLite data, ideas, snapshots, caches, credentials,
sandbox fixtures, `.git`, tests, or the entire checkout. Inspect an existing
destination before replacing files; preserve unknown files and local changes.

The copied skill has no checkout dependencies. The repository's source is
inactive; opening the checkout registers no skills or command wrappers.
OpenCode/OpenChamber discovers the global skill by the `goodmorning` ID.
`/gm`, `/gn`, `/eureka`, `/todo`, and `/secretary` are plain workflow requests, not custom
slash commands; natural-language requests work too.

## Validate

Briefings use browser delivery. The obsolete inline image plugin is not part of
the deployment; do not install it or request its former card tool.

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

Morning news covers the 24 hours before the briefing job was created. News
editorial review, delivery acknowledgement and briefing snapshot
saves are separate operations.

## Update and rollback

The production service templates use a dedicated Python environment at
`/opt/goodmorning/python/`. Create it once and install
`requirements/browser.txt` there before validating a candidate release. Do not
modify the operating system's Python packages. Native rendering needs only the
standard library; Pillow supports optional publisher images.
Include `.gitignore` in releases used to run the source-layout tests.

- The package-layout migration requires a clean public release, not an overlay
  of an old release that would leave obsolete scripts behind. Copy all listed
  public directories together. See [project structure](project-structure.md).
  Hosted HTTPS deployments follow the separate [server runbook](server-deployment.md).
  Validate the copied release before switching the release pointer.
- Update the account, viewer, gateway, and vault service command templates to
  `scripts/goodmorning.py`. Stop new requests and check account sessions, pending
  questions, permissions, and the global reservation before restarting idle
  account engines and viewers. Never restart mounted encrypted vaults merely
  to update their next-start command. Preserve the previous release and units.

- Workflow upgrades copy the source package, entry points, and public resources
  together with `docs/core-rules.md`, routed workflows and the skill
  entry. No personal-data migration is required. Verify on disposable records,
  then use read-only preparation on the selected live runtime. Start a fresh session
  to load new instructions. Existing missing-calendar reads now require setup.
- Back up the private runtime before updates. Use SQLite's backup API for active
  databases, or stop writers before copying SQLite files/journals.
- Copy changed public skill files only; retain personal records and environment.
- Inbox storage uses SQLite only. No text migration commands are supported.
  Keep initialized profiles and personal files unchanged during public-code updates.
- Preserve unknown/newer schemas, corrupt data and stable production locks. Do
  not force migrations, reset databases or replay unknown mutations.
- Retain the previous public skill files for rollback and revalidate them against
  the runtime schema before resuming writes. Restoring old code does not authorize
  discarding newer user records.
- When migrating old registrations, verify the self-contained global skill before
  removing obsolete project skills or command wrappers. Never delete unknown files
  or an old personal runtime during cleanup.

## Supported boundaries

Website language is account-wide English or Simplified Chinese. The encrypted
account metadata stores it without altering password records or local profiles.
All three hosts use that setting; only a non-secret pre-login preference cookie
uses their common parent domain. Authentication cookies remain host-only.
The selector works on login, password change, setup, chat, current and archived
briefing pages. Selecting a language applies and saves it immediately; only the
no-JavaScript fallback needs an Apply button. Saved content is not translated. Active agent requests keep their
starting language; new requests receive the latest language explicitly.

- Published calendar feeds (`.ics` links) expand common daily/weekly/monthly/yearly
  rules, additions, exclusions and moved exceptions. Unsupported rules are refused
  without partial imports; see `calendar-pipeline.md` for supported components.
- Native provider login, arbitrary recurrence rules, Twitter/X
  ingestion, automatic collection scheduling and unattended model calls are not implemented.
- Feed reachability, historical RSS coverage and model-authored editorial relevance
  are not guaranteed by passing tests. Source attribution and material gaps remain.
- Open-Meteo's free tier is for non-commercial use. Check provider/feed terms for
  the intended deployment. GoodMorning uses the root MIT license; retain it and
  the supplied upstream vendor license/manifest and font license notices.
- Real-host pairing repair, optional WAQI verification and deployment-specific
  permissions remain owner steps.
