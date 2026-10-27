# Create a hosted server user

For coding agents with authorized root SSH access. Use the deployed release,
not a development worktree. Account creation is separate from personal initialization.
Existing-account data migration or repair follows [SERVER-DATA-GUIDE.md](SERVER-DATA-GUIDE.md),
not the account-creation procedure. Do not rerun provisioning to repair record ownership.

## Paths

- Server: SSH alias `TCSFrontEnd` (batch SSH, passwordless sudo)
- Python: `/opt/goodmorning/python/bin/python`
- CLI: `/opt/goodmorning/current/scripts/goodmorning.py`
- Encrypted accounts mount: `/srv/goodmorning/live/accounts`
- New account volume: `/srv/goodmorning/live/ACCOUNT_ID`

## Provision

1. **Check prerequisites.** The deployed release must include `admin provision`
   (`/opt/goodmorning/current/src/goodmorning/security/briefing_provision.py` exists).
   If it does not, stop and ask the owner to deploy first; never provision by hand.

2. **Run one command per username**, one at a time:
   ```sh
   ssh TCSFrontEnd 'sudo /opt/goodmorning/python/bin/python -B /opt/goodmorning/current/scripts/goodmorning.py admin \
     --account-mount /srv/goodmorning/live/accounts provision USERNAME --gm-host gm.love765.me'
   ```
   It runs these steps, skipping each one that is already done:
   - create the login with a random 24-character temporary password and the
     server-default model, writing the password only to a root-owned, mode-0600
     `USERNAME-initial-password-TIMESTAMP.txt` in the accounts mount;
   - initialize and mount the account's encrypted vault and create its Linux user;
   - write `engine.json` with free loopback ports and fresh keys, and the OpenCode
     default model;
   - install the `User`/`Group` and engine-port drop-ins, then enable and start the
     vault, the engine socket and the viewer; the engine itself starts on demand;
   - register the server-default provider credential if the engine does not yet offer
     every website model, then wait until it does;
   - add the account to `backends.json`, keeping every other entry;
   - run the read-only `check-backend` readiness gate. It sends no model request.

   Output contains usernames, IDs, file names, Linux users and ports, never
   passwords or keys.

3. **Require exit status 0.** On failure, read the error, fix the cause (for example
   a stopped service), then rerun the same command. A rerun reuses the existing
   account ID, vault, ports, keys and password; it never resets them. If the
   failure is not understood after one rerun, stop and report it.

4. **Hand over.** Tell the owner the handover file's path. The owner sends the
   temporary password through an approved private channel; the user must change
   it at first login, then complete Initialize themselves.

## Never

- Expose passwords, keys, cookies, `.env`, or private configuration in tool output,
  chat, command arguments, logs, screenshots, or public source.
- Copy another user's HOME, profile, database, conversations, credentials, or permissions.
- Weaken encryption, authentication, service isolation, or origin/CSRF checks.
- Recreate a login, reset its password, or reinitialize its vault to fix a backend outage.
- Create accounts with `admin create` or hand-written steps instead of `provision`.

Report only the username, account ID, entry URL (`https://gm.love765.me`), readiness
result, handover file path and blockers. Use SSH-only `admin reset USERNAME` for password recovery. A reset, rename,
disable or enable signs the account out everywhere, unlinks all its phones and
turns off browser notifications; the user links phones again under Account →
Linked phones and turns notifications on again on each browser. Detailed security and
service requirements: [docs/website-security.md](docs/website-security.md).
