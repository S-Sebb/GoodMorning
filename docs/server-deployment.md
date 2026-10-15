# Server deployment runbook

This is the exact procedure for deploying GoodMorning at `gm.love765.me`.
Morning, Evening and Secretary use tabs on this one host. Follow it in order.
Do not improvise substitutions: every guard below exists because a past
deployment needed it.

## Terms

- `TCSFrontEnd`: the SSH alias for the production server (batch SSH plus
  passwordless sudo already configured). Never print authentication details.
- Release directory: `/opt/goodmorning/releases/<RELEASE-NAME>`, e.g.
  `20261011-ship-4320ad4`. The live pointer `/opt/goodmorning/current` is a
  symlink to exactly one release. Old releases are never deleted or reused.
- Deploy helper: `deploy_native_queue.py`, the reviewed helper last used for
  0.45.1, kept outside this repo in `~/.local/share/goodmorning-ops/deploy-helper/`
  on the agent machine. It performs the guarded switch described below. Copy it
  to the server staging directory together with the archive so the server runs
  the reviewed copy. If it is missing, stop and ask the owner; never rewrite it
  from memory.
- Server Python: `/opt/goodmorning/python/bin/python` with `-B`.
- Private data lives under `/srv/goodmorning/live` on encrypted mounts.
  Deployment writes there only for the protected deployment report and the
  deployment pause flag (`maintenance` metadata key). No other private writes.
- Deployment pause: the gateway flag that stops all new website work during a
  deploy. Set with the SSH-only admin CLI; the gateway serves a cute bilingual
  503 maintenance page (`assets/web/maintenance.html`) with `Retry-After: 60`
  for every page (including pre-login) and 503 JSON for APIs. Static assets
  (`/maintenance.css`, `/desk-secretary.png`, `/icons/gm.svg`, fingerprinted
  `/assets/...`) and `/api/release` still serve. `POST /api/auth/logout` still
  works; every other POST returns the maintenance JSON. The queue pump still
  reconciles finished work but never dispatches new queued work while paused.

## 1. Preconditions (local checkout)

1. The release steps in `docs/development.md` are complete: every change,
   including the release PR unless this is a silent update, is merged into
   `origin/main`.
2. In the primary checkout, run `git pull --ff-only` on `main`; `git status --short`
   is empty and `HEAD` equals `origin/main`. Record the commit hash and name the
   release `YYYYMMDD-ship-<short hash>`, or `YYYYMMDD-<topic>-silent-<short hash>`
   for a silent update. The deployed archive must be built from this HEAD.
3. Full suites pass on this HEAD with no model calls:
   `python -m unittest discover -s tests -p 'test_*.py' -q`,
   `node --test tests/test_projects.mjs`, plus the affected
   `tests/browser/*.py` suites with private artifact directories.
4. Confirm the live website is not already paused by someone else:
   `sudo /opt/goodmorning/python/bin/python -B /opt/goodmorning/current/scripts/goodmorning.py admin --account-mount /srv/goodmorning/live/accounts pause-status`
   must report live. A paused website means another deploy or incident is in
   progress; stop and ask the owner before proceeding.

## 1b. Pause the website before staging

Pause before building the archive, so no new work can slip in after the idle
checks. All pause commands are SSH-only and require root:

```sh
sudo /opt/goodmorning/python/bin/python -B /opt/goodmorning/current/scripts/goodmorning.py admin \
  --account-mount /srv/goodmorning/live/accounts pause --reason "deploy <RELEASE-NAME>" --by "<your-name>"
sudo /opt/goodmorning/python/bin/python -B /opt/goodmorning/current/scripts/goodmorning.py admin \
  --account-mount /srv/goodmorning/live/accounts pause-status
```

While paused, browsers see the cute maintenance page (English + Simplified
Chinese, emoticon `(＾▽＾)`, desk-secretary image) with HTTP 503,
`Retry-After: 60`, `Cache-Control: no-store`. APIs return 503 maintenance JSON
with the same `Retry-After`. No login, generation, chat message, reply,
recovery, upload, or password change can take a reservation or join the queue;
the background pump only reconciles finished work and never dispatches new
work. Sign-out still works.

Wait for in-flight work to settle, then verify idle exactly as the helper does:
no `generation` reservation, no `generation_queue` entries, no
`generation_waiting` entries, no active sessions, no pending questions or
permissions. Uncertain reservations still need explicit owner authorization
before clearing; never silently drop them. Keep the pause enabled through the
entire deploy and paused verification; resume only after Section 4's paused gates
pass, then perform its public login checks immediately:

```sh
sudo /opt/goodmorning/python/bin/python -B /opt/goodmorning/current/scripts/goodmorning.py admin \
  --account-mount /srv/goodmorning/live/accounts resume
```

## 2. Build the filtered public archive

The helper refuses any archive containing non-public files, so filter first.
Ensure its public-file allowlist includes the root `LICENSE` and the agent,
provisioning and data-modification guides referenced by `AGENTS.md`; retain them
in every release:

```sh
git archive --format=tar.gz --output=/tmp/opencode/<NAME>.tar.gz HEAD
python3 - <<'PY'
import hashlib,tarfile
from pathlib import Path
source=Path('/tmp/opencode/<NAME>.tar.gz');target=Path('/tmp/opencode/<NAME>-public.tar.gz')
allowed={'.gitignore','LICENSE','README.md','AGENTS.md','AGENT-PROMPT-GUIDE.md','SERVER-USER-GUIDE.md','SERVER-DATA-GUIDE.md','config.example.md','skill-source','scripts','src','assets','integrations','vendor','requirements','docs','templates','deploy','tests'}
count=0
with tarfile.open(source) as archive,tarfile.open(target,'w:gz') as public:
 for member in archive.getmembers():
  path=Path(member.name)
  if not member.isfile() or path.parts[0] not in allowed:continue
  assert not path.is_absolute() and '..' not in path.parts and '__pycache__' not in path.parts and not path.name.startswith('.env')
  public.addfile(member,archive.extractfile(member));count+=1
print({'publicFiles':count,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'archive':str(target)})
PY
```

Record the file count and SHA-256.

## 3. Stage on the server and deploy

`<RELEASE-NAME>` must not exist under `/opt/goodmorning/releases`:

```sh
ssh -o BatchMode=yes TCSFrontEnd 'install -d -m 755 /tmp/opencode/<NAME>/'
scp /tmp/opencode/<NAME>-public.tar.gz /tmp/opencode/tcsfrontend-openchamber-install/deploy_native.py TCSFrontEnd:/tmp/opencode/<NAME>/
ssh -o BatchMode=yes TCSFrontEnd 'sudo /opt/goodmorning/python/bin/python -B /tmp/opencode/<NAME>/deploy_native.py /tmp/opencode/<NAME>/<NAME>-public.tar.gz <RELEASE-NAME>'
```

The helper then, in order:

1. Extracts to the new release dir, verifies every file hash, and runs the
   candidate's full Python suite plus Node suite. Any failure aborts before
   touching live state.
2. Verifies the deployment pause flag (`maintenance` metadata) is enabled and
   refuses to proceed when it is missing. Then checks the live account DB
   schema, confirms no `generation` reservation, queued requests or suspended input,
   parses every account profile and saved native edition, and confirms all
   engines are idle (no active sessions, no pending questions/permissions).
   An enabled login without a registered backend is left untouched only if its
   private runtime does not exist and its vault, engine and viewer units are all
   inactive. Partial provisioning blocks deployment; never initialize or disable
   accounts as part of a code deployment.
3. Snapshots password rows, all account website preferences, and hashes of all protected
   private files (secretary records, `engine.json`, OpenChamber settings).
4. Backs up the four unit templates and the production NGINX config, atomically confirms the reservation and queue
   are still empty and takes the `generation` ticket, stops the
   gateway and viewers, re-verifies idle state and hashes, then stops account
   engines. Mounted encrypted vaults are never restarted.
5. Installs unit files from the candidate's `deploy/`, atomically switches the
   `current` symlink (never overwrites a release), reloads systemd, and starts
   gateway, account engines, and viewers. For attachments, update only the existing
   `client_max_body_size` directive from `20k` to the candidate's `50m`, preserving
   other production NGINX settings. Apply the candidate's deployment-pause NGINX
   locations (`= /maintenance.html` internal with `no-store` + `Retry-After 60`,
   `= /maintenance.css`, `= /desk-secretary.png`, `= /icons/gm.svg` with
   `public, no-cache`) from `deploy/nginx-goodmorning.conf`, preserving all other
   production settings. Validate with `nginx -t`, then reload NGINX.
   The reviewed helper must include these guarded updates and restore the original
   config on rollback; merely shipping `deploy/nginx-goodmorning.conf` does not
   change the live upload ceiling or the pause fallback.
   For the single-host migration, the reviewed helper must also remove
   `gn.love765.me` and `sec.love765.me` from the production NGINX server names,
   preserving other settings and restoring the original config on rollback.
   Do not add redirects for these retired hosts. Update the existing certificate's
   renewal names to only `gm.love765.me` before removing the retired DNS records,
   so future renewals do not require those records. Retain the existing certificate
   path. Perform DNS and certificate changes only during the authorized deployment,
   not during source preparation.
   Install the candidate's `deploy/goodmorning-certbot-hook.py` at the existing
   GoodMorning renewal-hook path; back up and restore the old hook on rollback.
6. Waits until every viewer answers `/chat` and the `gm.love765.me` HTTPS login serves,
   re-verifies idle state, passwords, languages, hashes, active services, and
   that each engine's working directory is the new release. Confirms the pause
   flag is still enabled. Clears the deployment `generation` ticket but never
   clears the pause flag: the website stays paused after a successful switch.
7. Writes the protected report to
   `/srv/goodmorning/live/accounts/<RELEASE-NAME>-deployment.json` (mode
   `0600`) and prints a JSON summary. Record `verifiedPublicFiles`,
   `candidatePythonTests`, `candidateNodeTests`, `protectedPrivateFiles`, and
   `nginxUploadCeiling`.

On any error the helper stops services, restores the symlink to the previous
release, restores unit files and any changed NGINX config, restarts, keeps the
pause flag enabled, clears the ticket, and re-raises.
A manual rollback is the same sequence; never hand-edit the symlink.

## 4. Post-deploy verification

1. While still paused, confirm the pause is visible: `curl -k -i https://gm.love765.me/`
   returns `503` with `Retry-After: 60` and `Cache-Control: no-store`, and the
   body contains the bilingual maintenance page (`maintenance-status`,
   `Please come back later`, `请稍后再来`, `(＾▽＾)`). Confirm
   `/maintenance.css`, `/desk-secretary.png`, and `/icons/gm.svg` return `200`.
   Stop the gateway socket briefly only if the owner explicitly authorizes an
   NGINX-fallback drill; NGINX must then serve the same static
   `/maintenance.html` with `no-store` + `Retry-After: 60`.
2. Per account via the engine bridge (read-only): profile readiness, engine
   session titles, no `generation` reservation, all services active.
3. Confirm the previous release directory is intact under
   `/opt/goodmorning/releases`.
4. Confirm `/api/release` reports the committed candidate version and the required
   root guides are present in that release. Login pages intentionally return 503
   while paused; do not bypass maintenance or weaken authentication to test them.
5. Only after paused steps 1–4 pass, resume the website with the SSH-only admin CLI
   and confirm it is live again:

   ```sh
   sudo /opt/goodmorning/python/bin/python -B /opt/goodmorning/current/scripts/goodmorning.py admin \
     --account-mount /srv/goodmorning/live/accounts resume
   sudo /opt/goodmorning/python/bin/python -B /opt/goodmorning/current/scripts/goodmorning.py admin \
     --account-mount /srv/goodmorning/live/accounts pause-status
   ```

   `pause-status` must report live.
6. Immediately run `tests/browser/login.py --artifacts <PRIVATE_DIR>`:
   `gm.love765.me`, both
   languages, 390/768/1440 px, secure host-only cookies, 401 on private APIs,
   native no-JavaScript redirects. No logins, no passwords.
   Confirm Morning, Evening and Secretary share the same host and login, and
   that retired hosts no longer serve the app. “Open activity” must navigate the
   current tab to the exact chat or edition without opening another browser tab.
   If public verification fails, immediately pause again and inspect the failure.
   Roll back only after rechecking the same idle/reservation/queue guards; do not
   interrupt work that arrived after resume. A failed gate is not a successful
   deployment, and a broken release must not remain open to new work.
7. After every gate passes, tag the deployed commit and push the tag:
   `git tag deploy/<RELEASE-NAME> <hash> && git push origin deploy/<RELEASE-NAME>`.
   A rolled-back deployment gets no tag.

## Hard rules

- Never overwrite a release directory; never delete a previous release.
- Never restart vault services for a code deploy.
- Never deploy without the pause flag enabled. Pause before staging, keep it
   enabled through the switch and paused verification, and resume only after
   Section 4's paused gates pass. Complete its public login checks immediately
   after resume. The helper must refuse to run without the flag and must never clear
  it, on success or rollback.
- Deploy only with zero active sessions, zero pending questions/permissions,
  no `generation` reservation, and no queued requests. A stuck reservation from another account's
  broken chat must be explicitly owner-authorized before clearing, and its
  cause recorded, never silently dropped. Never prune, dispatch, or discard
  queued work to make the pause or the deploy proceed; wait for normal work to
  finish.
- Never display passwords, tokens, or `.env` contents; never log private text.
- Live account maintenance (edition resets, chat cleanup) is separate from
  deployment and needs its own explicit authorization plus an encrypted
  rollback backup. Follow [the hosted data modification guide](../SERVER-DATA-GUIDE.md)
  and retain per-task evidence. A version bump does not authorize a data migration.

## Queue-aware deployment guard

The NGINX credential limiter must use the candidate's method/path map: only
POST `/api/auth/login` and `/api/auth/password` receive a nonempty key. Never
apply a per-IP login bucket to assets, pages, or read-only polling. Preserve
the application's own credential/session limits, CSRF checks and private routing.
Back up and review this exact configuration change before `nginx -t` and reload;
shipping the template alone does not update the live configuration.

The global secretary queue stores pending work in the `generation_queue`
metadata key. Reading `GET /api/queue` can dispatch queued work, so deployment
checks read the database directly instead. The reviewed helper rejects every
non-empty or malformed queue, checks it again inside the transaction that takes
the deployment reservation, and rechecks it with account-idle verification.
These checks never prune, dispatch, or discard pending requests. Wait for normal
requests to finish; uncertain reservations need the explicit owner authorization
described above.

The `generation_waiting` metadata key must also be absent or an empty list.
Never discard suspended questions or permissions to make deployment proceed.
