# Create a hosted server user

For coding agents with authorized root SSH access. Use the deployed release,
not a development worktree. Account creation is separate from personal initialization.
Existing-account data migration or repair follows [SERVER-DATA-GUIDE.md](SERVER-DATA-GUIDE.md),
not the account-creation procedure. Do not rerun provisioning to repair record ownership.

## Paths

- Server: SSH alias `TCSFrontEnd` (batch SSH, passwordless sudo)
- Python: `/opt/goodmorning/python/bin/python`
- CLI: `/opt/goodmorning/current/scripts/goodmorning.py`
- Source: `/opt/goodmorning/current/src`
- Encrypted accounts mount: `/srv/goodmorning/live/accounts`
- New account volume: `/srv/goodmorning/live/ACCOUNT_ID`

Verify these paths on the target server. Replace `USERNAME` and `ACCOUNT_ID` below.

## Required steps, in order

1. **Check prerequisites.** Require the encrypted accounts mount. Load
   `server_defaults(Accounts(account_mount))` from
   `goodmorning.security.briefing_admin`; stop if unavailable. If the username
   already exists, resume its provisioning using its immutable ID; do not recreate it.

2. **Create the login.** Generate 24 random ASCII letters/digits with Python
   `secrets`, ensuring at least one letter and one digit. Do not ask the owner
   for an initial password or AI credentials. In a private Python process, call
   `Accounts.create(USERNAME, password)`, retain the returned `ACCOUNT_ID`, and call
   `Accounts.website_model(ACCOUNT_ID, defaults['model'])`. Save the password only
   to a new root-owned, mode-0600 handover file inside the encrypted accounts mount.

3. **Create its vault and Linux user.** For a new ID only, run the CLI's
   `vault --root /srv/goodmorning init ACCOUNT_ID`, enable/start
   `goodmorning-vault@ACCOUNT_ID.service`, then run
   `vault --root /srv/goodmorning user ACCOUNT_ID`. Retain the returned Linux user.
   Never initialize an existing vault. Keep private directories mode 0700.

4. **Configure its services.** Write account-owned, mode-0600 `engine.json` in
   its volume with unused loopback `chamberPort` and `viewerPort`, plus independent
   `secrets.token_urlsafe(48)` values for `uiPassword` and `gatewayKey`.
   Create fresh `home/.config/opencode/opencode.json` with the provider/model from
   `goodmorning.web.models.MODELS[defaults['model']]`; GoodMorning applies its
   variant per session. Use the `deploy/` service templates unchanged except for
   per-instance `User`/`Group` drop-ins on both `goodmorning-account@ACCOUNT_ID`
   and `goodmorning-viewer@ACCOUNT_ID`, using the Linux user from step 3.
   Run `systemctl daemon-reload`, then enable/start both services.

5. **Connect and register.** Use `goodmorning.security.briefing_runtime.LocalBridge`
   with this account's engine port, deployed source directory, and `uiPassword`.
   Resolve the provider's integration through `/api/integration`, then call
   `POST /api/credential` with `integrationID`, `value: defaults['credential']`,
   and `activate: true`. Verify provider connection and offered models through
   bounded read-only checks; never replay an uncertain credential write.
   Atomically add `ACCOUNT_ID: {"port": viewerPort, "key": gatewayKey}` to the
   accounts mount's `backends.json`, preserving other entries and root ownership/mode 0600.

6. **Verify before handover.** Require exit status 0 from:
   ```sh
   sudo /opt/goodmorning/python/bin/python -B /opt/goodmorning/current/scripts/goodmorning.py admin \
     --account-mount /srv/goodmorning/live/accounts check-backend USERNAME --gm-host gm.love765.me
   ```
   Confirm the encrypted mount, dedicated service UID, independent ports, and
   provider/model availability. This gate does not call a paid model.
   Deliver the temporary password through an approved private channel; the user
   must change it before access, then complete Initialize themselves.

## Never

- Expose passwords, keys, cookies, `.env`, or private configuration in tool output,
  chat, command arguments, logs, screenshots, or public source.
- Copy another user's HOME, profile, database, conversations, credentials, or permissions.
- Weaken encryption, authentication, service isolation, or origin/CSRF checks.
- Recreate a login, reset its password, or reinitialize its vault to fix a backend outage.

Report only the username, account ID, entry URL, readiness result, and blockers.
Use SSH-only `admin reset USERNAME` for password recovery. A reset, rename,
disable or enable signs the account out everywhere and unlinks all its phones;
the user links them again under Account → Linked phones. Detailed security and
service requirements: [docs/website-security.md](docs/website-security.md).
