# Agent guide: hosted data migration and modification

This contract applies to coding agents inspecting, repairing, migrating, restoring,
or manually modifying hosted account data. Public code deployment is separate:
follow `docs/server-deployment.md`. Provisioning follows `SERVER-USER-GUIDE.md`.
A version bump never authorizes a personal-data migration.

## Required inputs and permission

Before any live write, require the owner's explicit authorization for the exact
accounts, files, operation, and intended changes. Permission to inspect, deploy,
or repair a queue does not authorize unrelated data or ownership changes.
If scope, identity, schema, or a previous mutation's outcome is unclear, stop and
ask. Do not infer approval from access to root SSH.

For a read-only audit, inspect all requested accounts, including disabled and
unprovisioned accounts. Do not initialize missing runtimes, migrate schemas, load
secrets into reports, or repair anything. Distinguish missing unused runtimes,
administrative backups, migration leftovers, and intentionally root-owned service
logs from files the account actually needs to read or write.

## Required sequence

### 1. Resolve the account and inventory its state

- Resolve the immutable account ID from the encrypted accounts database. Never
  choose an account, path, UID, or port from an unverified name or browser input.
- Verify the accounts mount and selected account vault are mounted gocryptfs
  volumes. Stop on an absent mount, unsafe path, unexpected symlink, or shared UID.
- Verify the volume owner and the account/viewer service `User` and `Group` agree.
  Account records belong to that dedicated non-root UID/GID. Shared account
  credentials and the backend registry remain root-owned and private.
- Inventory the exact source and destination, schema versions, ownership, modes,
  ACLs, directories, lock files, SQLite databases and journal/WAL/SHM sidecars.
  Include adjacent files an atomic replacement or later write will need.
- Record the deployed release and proposed tool version. Use supported helpers
  from that selected release; do not quietly run a development copy against live
  storage. Unknown or newer schemas require review, not forced conversion.

### 2. Establish a safe work boundary

- Inspect active sessions, pending questions/permissions, the global reservation,
  queued work, and suspended input. Reads must not pump or prune the queue.
- For a migration or restore requiring exclusive access, pause new website work
  only with authorization. Wait for normal work to finish. Pause does not cancel
  active agents or bypass pending questions. Stop if safe quiescence is unavailable.
- Stop only affected writers when the reviewed procedure requires it. Include
  account engines, viewers, scheduled helpers, and external calendar writers.
  Never restart or unmount vaults to obtain a write window.
- Never clear, discard, dispatch, or replay requests merely to pass a migration
  or deployment guard. A stuck reservation needs separate scoped authorization
  and evidence of the actual dispatch outcome.

### 3. Make and verify an encrypted rollback backup

- Keep personal records, snapshots, artifacts, and temporary files outside public
  source. Put backups in the owning encrypted vault or a reviewed root-only
  encrypted administrative volume. Never use plaintext `/tmp` for live records.
- Include the database, associated registries/records affected by the operation,
  and a private manifest of hashes, schema versions, UID/GID, modes and ACLs.
- Use SQLite's backup API with a coherent read transaction, as the file's owner.
  Do not copy a busy database's main file alone or discard its WAL/journal.
  Raw filesystem snapshots require confirmed quiescence and all relevant files.
- Test the backup's integrity and the restore procedure on an isolated encrypted
  copy. A backup file existing is not proof that rollback works.
- For read-only diagnostics, use a consistent SQLite snapshot without changing
  source sidecars. Stable copies of the main file and WAL may be inspected in an
  encrypted scratch directory only when unchanged source metadata proves a stable
  copy; otherwise mark the check incomplete. Never ignore a live WAL with
  `immutable=1` to manufacture a clean result. Retain hot-journal evidence and stop.

### 4. Test the exact operation on synthetic records

- Define expected changes and invariants before running the operation. Preserve
  identities, history, credentials, preferences, task outcomes, and unrelated files.
- Exercise the supported old/new schemas, empty and populated stores, interrupted
  writes, duplicate requests, failed validation, and wrong-UID execution.
- Verify idempotency or an explicit resume marker. When delivery is uncertain,
  inspect the durable receipt; do not retry a mutation blindly.
- Test backup restoration and service-account read/write access. Use disposable
  synthetic data and the actual UID boundary, not only administrator checks.
- Follow `AGENT-PROMPT-GUIDE.md` for modified agent instructions. Model responses
  do not replace database, permission, rollback, or application tests.

### 5. Apply only the authorized change under the correct identity

- Run personal-data helpers as the account's actual service UID/GID and groups,
  with its private `HOME`, runtime, cache and temporary directories. Verify the
  effective identity inside the writer. Root may orchestrate, not create personal
  databases, lock files, or atomic replacements on the account's behalf.
- Set `umask 0077` before creating files. Preserve account ownership on the final
  database, locks, sidecars and replacement directory; private files normally use
  0600 and private directories 0700. Do not make files world-readable to fix access.
- Prefer supported revision-checked helpers and transactions. Direct SQL needs
  explicit approval and a reviewed schema-aware procedure. Never replace a
  database with an empty one to make initialization succeed.
- Ownership repair is a separate metadata operation. Back up and record the exact
  previous metadata, then change only the approved paths. Check content hashes
  before and after. Never run blanket recursive `chown`, `chmod`, deletion, or
  journal cleanup across accounts. Do not grant root-owned administrative archives
  or credentials to service users.
- Record intent and the durable result privately. On failure, stop new writes;
  preserve partial state and the original exception type without logging secrets.
  Do not declare success, reset records, or replay an unknown operation.

### 6. Verify before reopening service

- Recheck database integrity, foreign keys, supported schema, required data
  contracts, intended counts/IDs and unchanged invariants against the backup.
- Verify ownership, modes, ACLs and directory traversal on databases, locks,
  sidecars and replacements. Check both reads and the supported write path as the
  dedicated account, not as root. Prove writes on an isolated copy; any live test
  mutation needs its own authorization and must leave a valid audited result.
- Verify the actual affected application path, such as workflow preparation, using
  the service identity. Administrator-readable data alone does not pass the gate.
  Read-only probes must not create lock files, sidecars, registries or migrations.
- Check every account when a shared migration touched multiple accounts. A healthy
  sample cannot establish fleet readiness. Label timed-out, changing or inaccessible
  databases as unverified; never include them in a clean bill of health.
- Restore only after reconfirming exclusive access. Never overwrite new user work
  with an older backup. If rollback needs to replace records or change ownership
  beyond the approved scope, stop and ask the owner.
- Resume paused service only after all affected gates pass. Report scope, checks,
  verified results, preserved backup, unresolved blockers and deployment status.
  Report identifiers/counts and necessary technical paths, never private record
  text, credentials, `.env` contents or raw transcripts.

## Completion and limits

Complete means the authorized change and invariants are verified under the actual
service identity, rollback is usable, and no account is left unintentionally paused
or unable to access its data. A failed or incomplete gate means blocked, not done.
Keep unrelated accounts and existing requests unchanged.

These safeguards address reproducible ownership, storage and dispatch failures.
They are not a promise of zero failures or protection from an administrator who
deliberately bypasses the procedure.
