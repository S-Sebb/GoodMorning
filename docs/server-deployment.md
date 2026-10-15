# Server deployment runbook

How to deploy GoodMorning to `gm.love765.me`. Deploy only when the owner asks,
after the release steps in `docs/development.md`. Every guard exists because a
past deployment needed it; do not improvise substitutes.

## Deploy

From the primary checkout on an up-to-date `main`:

```sh
git pull --ff-only
uv run --no-project python deploy/release.py
```

`deploy/release.py` runs these steps and stops at the first failure:

1. **Preflight.** The checkout is clean, `HEAD` equals `origin/main`, CI
   `contracts` passed on that commit, the patch notes are valid, and the website
   is live. A website that is already paused means another deployment or
   incident is in progress: stop and ask the owner.
2. **Build.** It builds the public archive of `HEAD`, using only regular files
   under the top-level names in `ALLOWED` in `deploy/deploy_native.py`. The
   release is named `YYYYMMDD-ship-<short hash>`.
3. **Stage, while the website stays live.** It uploads the archive and
   `deploy/deploy_native.py` from the same commit to `/tmp/opencode/<NAME>/` on
   the server and runs `deploy_native.py stage`. Stage unpacks into
   `/opt/goodmorning/releases/<NAME>`, verifies every file hash, runs the full
   Python and Node suites on the server's Python, and checks the account
   database schema read-only.
4. **Pause.** It enables the deployment pause.
5. **Switch.** `deploy_native.py switch` waits up to 10 minutes for idle: no
   reservation, queue or suspended input, no active sessions, and no pending
   questions or permissions. It then:
   - snapshots passwords, language settings and the hashes of protected
     private files;
   - takes the deployment ticket;
   - stops the gateway and viewers, rechecks idle, and stops the account engines;
   - installs only the unit files, certificate hook and NGINX config that differ
     from the release's `deploy/`;
   - switches `/opt/goodmorning/current` and restarts;
   - verifies that nothing protected changed and that engines run the new
     release, then clears the ticket. The pause stays on.
6. **Paused checks.** The site serves the maintenance page (503,
   `Retry-After: 60`, `no-store`, both languages), its assets load, and
   `/api/release` reports the new version.
7. **Resume**, then run the public Chromium login check (`tests/browser/login.py`).
8. **Tag** the commit `deploy/<NAME>` and push the tag.

It prints a JSON summary including `pausedSeconds`. Report that summary to the
owner.

## When it stops

The message says what state the website is in:

| Stopped at | Website | Next |
|---|---|---|
| Preflight, build or stage | Live, unchanged | Fix the cause. A failed stage leaves an unused release directory; a new commit gets a new name. |
| Switch: not idle in time | Resumed, unchanged | Retry later. A reservation that never clears needs the owner's explicit authorization and a recorded cause before anyone clears it. |
| Switch: any other error | Paused; previous release restored | Inspect the helper output, then resume or retry with the owner. |
| Paused checks | Paused; new release live | Inspect, then resume or roll back. |
| Public login check | Paused again; new release live | Inspect, then resume or roll back. |

**Roll back** by running `switch` for the previous release, with the website
paused: `sudo -n /opt/goodmorning/python/bin/python -B /tmp/opencode/<NAME>/deploy_native.py switch <PREVIOUS-NAME>`.
It re-verifies the release's files against its stage marker or earlier deployment
report in `/srv/goodmorning/live/accounts`. Never hand-edit the `current` symlink.

## Manual commands

Admin CLI, SSH-only, as root:

```sh
sudo /opt/goodmorning/python/bin/python -B /opt/goodmorning/current/scripts/goodmorning.py admin \
  --account-mount /srv/goodmorning/live/accounts pause|resume|pause-status [--reason TEXT --by NAME]
```

While paused, pages return the bilingual maintenance page with HTTP 503 and
`Retry-After: 60`, and APIs return 503 JSON. Static assets, `/api/release` and
sign-out still work. The queue pump only reconciles finished work; it never
dispatches new work.

## Server

- `TCSFrontEnd`: SSH alias for the server (batch SSH, passwordless sudo).
  Never print authentication details.
- Releases: `/opt/goodmorning/releases/<NAME>`; `/opt/goodmorning/current` points
  to exactly one. Releases are never overwritten or deleted.
- Python: `/opt/goodmorning/python` is a symlink to the uv-managed environment
  `/opt/goodmorning/python-3.14`. Its CPython lives in `/opt/goodmorning/uv/python`,
  and the environment holds only Pillow. `/opt/goodmorning/python-3.12` stays for
  rollback. For a Python patch update, run as root:
  `UV_PYTHON_INSTALL_DIR=/opt/goodmorning/uv/python uv python upgrade 3.14`; the
  next deployment restarts services on it. Install packages with
  `uv pip install --python /opt/goodmorning/python-3.14/bin/python --index-url https://pypi.org/simple`;
  the server's default pip index is unreachable.
- Private data lives under `/srv/goodmorning/live` on encrypted mounts. A
  deployment writes there only the pause flag, the deployment ticket, the
  staging marker, backups of replaced system files, and the report
  `<NAME>-deployment.json` (mode 0600).
- `deploy/nginx-goodmorning.conf` is the exact live NGINX config. Only POST
  `/api/auth/login` and `/api/auth/password` get a per-IP limiter key; never rate
  limit assets, pages or read-only polling.

## Hard rules

- Never restart vault services for a code deployment.
- Never switch without the pause enabled. The helper refuses, and it never clears
  the pause, on success or rollback.
- Never clear, prune, dispatch or discard queued work, reservations, or suspended
  questions or permissions to make a deployment proceed. Wait for normal work to
  finish. Deployment checks read the database directly, because `GET /api/queue`
  can dispatch work.
- Never initialize, disable or partially provision accounts during a deployment.
  The helper leaves enabled-but-unprovisioned logins untouched and rejects
  partial provisioning.
- Never display passwords, tokens or `.env` contents, and never log private text.
- Live account maintenance (edition resets, chat cleanup, migrations) is separate
  from deployment and follows `SERVER-DATA-GUIDE.md`. A version bump never
  authorizes a data migration.
- An NGINX-fallback drill (stopping the gateway socket) needs the owner's
  explicit authorization.
