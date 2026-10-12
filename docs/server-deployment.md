# Server deployment runbook

This is the exact procedure for deploying the three GoodMorning websites
(`gm.love765.me`, `gn.love765.me`, `sec.love765.me`). Follow it in order.
Do not improvise substitutions: every guard below exists because a past
deployment needed it.

## Terms

- `TCSFrontEnd`: the SSH alias for the production server (batch SSH plus
  passwordless sudo already configured). Never print authentication details.
- Release directory: `/opt/goodmorning/releases/<RELEASE-NAME>`, e.g.
  `20261011-ship-4320ad4`. The live pointer `/opt/goodmorning/current` is a
  symlink to exactly one release. Old releases are never deleted or reused.
- Deploy helper: `/tmp/opencode/tcsfrontend-openchamber-install/deploy_native.py`
  on the agent machine (outside this repo). It performs the guarded switch
  described below. Always copy it to the server staging directory together
  with the archive so the server runs the reviewed copy.
- Server Python: `/opt/goodmorning/python/bin/python` with `-B`.
- Private data lives under `/srv/goodmorning/live` on encrypted mounts.
  Deployment never writes there except for the protected deployment report.

## 1. Preconditions (local checkout)

1. `git status --short` shows only intended files; `git diff --check` is clean.
2. The deployer authors the patch note for this deployment as the newest entry
   of `assets/web/patch-notes.json` (date, author, English and Simplified
   Chinese text, each within the limits in `src/goodmorning/web/release.py`).
3. Full suites pass with no model calls:
   `python -m unittest discover -s tests -p 'test_*.py' -q`,
   `node --test tests/test_projects.mjs`, plus the affected
   `tests/browser/*.py` suites with private artifact directories.
3. Commit and push to `origin/main`. Record the commit hash.
   The deployed archive must be built from the pushed HEAD.

## 2. Build the filtered public archive

The helper refuses any archive containing non-public files, so filter first:

```sh
git archive --format=tar.gz --output=/tmp/opencode/<NAME>.tar.gz HEAD
python3 - <<'PY'
import hashlib,tarfile
from pathlib import Path
source=Path('/tmp/opencode/<NAME>.tar.gz');target=Path('/tmp/opencode/<NAME>-public.tar.gz')
allowed={'.gitignore','README.md','AGENTS.md','config.example.md','skill-source','scripts','src','assets','integrations','vendor','requirements','docs','templates','deploy','tests'}
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
2. Checks the live account DB schema, confirms no `generation` reservation or queued requests,
   parses every account profile and saved native edition, and confirms all
   engines are idle (no active sessions, no pending questions/permissions).
3. Snapshots password rows, account-language rows, and hashes of all protected
   private files (secretary records, `engine.json`, OpenChamber settings).
4. Backs up the four unit templates, atomically confirms the reservation and queue
   are still empty and takes the `generation` ticket, stops the
   gateway and viewers, re-verifies idle state and hashes, then stops account
   engines. Mounted encrypted vaults are never restarted.
5. Installs unit files from the candidate's `deploy/`, atomically switches the
   `current` symlink (never overwrites a release), reloads systemd, and starts
   gateway, account engines, and viewers.
6. Waits until every viewer answers `/chat` and all three HTTPS logins serve,
   re-verifies idle state, passwords, languages, hashes, active services, and
   that each engine's working directory is the new release. Clears the ticket.
7. Writes the protected report to
   `/srv/goodmorning/live/accounts/<RELEASE-NAME>-deployment.json` (mode
   `0600`) and prints a JSON summary. Record `verifiedPublicFiles`,
   `candidatePythonTests`, `candidateNodeTests`, `protectedPrivateFiles`.

On any error the helper stops services, restores the symlink to the previous
release, restores unit files, restarts, clears the ticket, and re-raises.
A manual rollback is the same sequence; never hand-edit the symlink.

## 4. Post-deploy verification

1. `tests/browser/login.py --artifacts <PRIVATE_DIR>`: all three hosts, both
   languages, 390/768/1440 px, secure host-only cookies, 401 on private APIs,
   native no-JavaScript redirects. No logins, no passwords.
2. Per account via the engine bridge (read-only): profile readiness, engine
   session titles, no `generation` reservation, all services active.
3. Confirm the previous release directory is intact under
   `/opt/goodmorning/releases`.

## Hard rules

- Never overwrite a release directory; never delete a previous release.
- Never restart vault services for a code deploy.
- Deploy only with zero active sessions, zero pending questions/permissions,
  no `generation` reservation, and no queued requests. A stuck reservation from another account's
  broken chat must be explicitly owner-authorized before clearing, and its
  cause recorded, never silently dropped.
- Never display passwords, tokens, or `.env` contents; never log private text.
- Live account maintenance (edition resets, chat cleanup) is separate from
  deployment and needs its own explicit authorization plus an encrypted
  rollback backup. See the per-task evidence notes, not this file.

## Queue-aware deployment guard

The global secretary queue stores pending work in the `generation_queue`
metadata key. Reading `GET /api/queue` can dispatch queued work, so deployment
checks read the database directly instead. The reviewed helper rejects every
non-empty or malformed queue, checks it again inside the transaction that takes
the deployment reservation, and rechecks it with account-idle verification.
These checks never prune, dispatch, or discard pending requests. Wait for normal
requests to finish; uncertain reservations need the explicit owner authorization
described above.
