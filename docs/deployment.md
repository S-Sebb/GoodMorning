# Deployment

GoodMorning is an OpenCode/OpenChamber agent project with standard-library CLI
helpers, not a standalone autonomous daemon. Deploy the project files, then run
`/secretary` in that checkout to initialize the owner's private runtime.

## Requirements

- Linux; Python 3.9+ with IANA timezone data. Prefer a currently maintained Python
  release such as 3.12 or newer. Legacy-version syntax is checked locally; CI is
  configured to test the actual interpreter matrix when run on GitHub.
- Node.js 22.18+ for local/paired-remote project access. No npm install is needed.
- An OpenCode/OpenChamber client that loads project skills/commands and supports
  the question tool; ordinary conversation is the documented fallback.
- Outbound HTTPS for weather/news. No key is required for normal weather/model
  AQI or RSS/HN. Optional WAQI/NewsAPI credentials stay in the launching environment.
- Existing owner-authorized OpenChamber pairing for remote projects. Do not copy
  pairing credentials into project files or the deployment archive.

## Validate and build

```bash
python -m unittest discover -s tests -p 'test_*.py' -q
node --test tests/test_projects.mjs
python scripts/package_release.py --output dist/GoodMorning-deploy.zip
sha256sum -c dist/GoodMorning-deploy.zip.sha256
```

The bundle uses an explicit public-file allowlist, not Git tracking status. It
includes skills, wrappers, scripts, templates, documentation, tests, and pinned
vendor source/license. It excludes profiles, SQLite data, ideas, snapshots, caches,
`.env`, sandbox runs and `.git`. `RELEASE-MANIFEST.json` hashes every packaged file;
the adjacent SHA-256 hashes the ZIP. Existing outputs are not overwritten.
For a Git-based deployment, commit the intended public project files before
pushing; packaging does not stage, commit or push unrelated checkout changes.

Fixture locations are portable. `GM_TEST_TMPDIR` can select a disposable directory;
otherwise tests use the existing approved temporary root or the OS default. Tests
do not require a personal runtime or live provider credentials.

## Install and initialize

1. Extract the ZIP into the intended checkout/workspace and open its `GoodMorning/`
   directory in OpenCode/OpenChamber. Keep the relative directory layout intact.
2. Run `/secretary`. The first question confirms reply language. The agent then
   confirms remaining preferences, file formats and exact project/provider scope.
3. After consent, private records live in `secretary/` or the confirmed
   `SECRETARY_DIR`. Never ship an initialized profile as a general default.
4. Run only owner-authorized verification checks. Saved local setup can remain
   usable with explicit pending integrations; do not fabricate verification.
5. Use `/gm`, `/gn` and `/eureka`. Normal morning news covers yesterday only;
   same-day updates require an explicit opt-in. News editorial review and delivery
   acknowledgement are separate from briefing snapshot saves.

For relocated storage pass `--secretary-dir`, weather `--profile`, source/cache
paths and calendar `--db` as documented. Create the authorized runtime `tmp/` and
set `TMPDIR` for calendar imports. These scripts do not automatically read `.env`.

## Upgrade and rollback

- Back up the private runtime before upgrades. Use SQLite's backup API for active
  databases, or stop writers before copying SQLite files/journals.
- Replace public project files only; retain the owner's runtime and environment.
  New reply-language preferences do not force older profiles to reinitialize.
- Preserve unknown/newer schemas, corrupt data and stable production locks. Do
  not force migrations, reset databases or replay unknown mutations.
- Retain the previous public bundle for rollback and revalidate it against the
  runtime schema before resuming writes. Restoring old code is not authorization
  to discard newer user records.

## Supported boundaries

- Production Betterbird staging expands common daily/weekly/monthly/yearly rules,
  additions, exclusions and stored exceptions. Unsupported rules/schemas and
  locked caches are refused without partial imports. Metadata preflight verifies
  schema only; see `calendar-pipeline.md` for supported components and limits.
- Native provider login, ICS file parsing, arbitrary recurrence rules, Twitter/X ingestion,
  automatic collection scheduling and unattended model calls are not implemented.
- Feed reachability, historical RSS coverage and model-authored editorial relevance
  are not guaranteed by passing tests. Source attribution and material gaps remain.
- Open-Meteo's free tier is for non-commercial use. Check provider/feed terms for
  the intended deployment. No new project-wide open-source license is granted by
  this packaging step; retain the supplied upstream vendor license/manifest.
- Real-host pairing repair, optional WAQI verification and deployment-specific
  permissions remain owner steps. No real profile is initialized by building a ZIP.
