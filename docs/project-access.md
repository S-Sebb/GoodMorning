# Project access for agents

Run `node scripts/projects.mjs` from the repository root. Commands return one
compact JSON object; exit code 1 means failure or a partially failed batch.
Requires Linux, Node.js 22.18+, and Python 3.9+. Remote hosts need Python but
no GoodMorning installation. No npm install or separate daemon is required.

## One-time setup

Confirm aliases, exact paths, paired host IDs, and authorized write targets
with the owner. Create the git-ignored `secretary/projects.json` from
`templates/projects.registry.example.json`, removing example entries. Never
replace an existing registry or initialize personal data without consent.

Fields: `name` is the command alias; `host` is `local` or a paired desktop host
ID (a label works only when unique); `path` is absolute on that host;
`project_id` comes from remote discovery and is checked against its path;
`write_targets` lists exact relative files, not globs; `allow_exec` defaults
false; optional `shared_id` records owner-confirmed shared storage. Keep separate
host aliases for jobs, but do not duplicate shared-file writes through them.

```bash
node scripts/projects.mjs discover --host CONFIRMED_HOST_ID
```

Discovery changes no configuration. Credentials stay in OpenChamber's desktop
settings, never the registry. Override paths with `--registry`, `--settings`,
`GM_PROJECT_REGISTRY`, or `GM_OPENCHAMBER_SETTINGS`. Repair pairing in OpenChamber;
never print a token or silently change relay settings.
Paired credentials authenticate only inside encrypted HTTP headers, never in
relay routing URLs or grants. Rotate credentials used by the obsolete early
probes through owner-authorized re-pairing when safe.

## Normal workflow

```bash
node scripts/projects.mjs list
node scripts/projects.mjs status --all
node scripts/projects.mjs read PROJECT AGENTS.md --limit 2000
node scripts/projects.mjs read PROJECT PLAN.md --limit 2000
node scripts/projects.mjs jobs PROJECT
node scripts/projects.mjs ls PROJECT docs --limit 10
```

Read only relevant notes. `read` defaults to 4,000 Unicode characters, capped at
16,000. Continue using its `next_offset`; offsets refer to original source
characters, not displayed/redacted text. Directory pages default to 10 entries,
capped at 50. `read --tail` returns bounded UTF-8 log endings without a full hash.
Missing files and failed queries are errors, not evidence of no work.

Batch independent reads to reuse one connection per host; at most 20 read-only
operations, with four workers. Do not bulk-read every file simply because batching
is available:

```bash
node scripts/projects.mjs batch <<'JSON'
[{"op":"status","project":"PROJECT"},{"op":"read","project":"PROJECT","path":"PLAN.md","limit":1200},{"op":"jobs","project":"PROJECT"}]
JSON
```

## Writes and commands

Read project instructions and the full target first. Obtain authorization and
supply the updated document on stdin with the current SHA-256:

```bash
node scripts/projects.mjs write PROJECT PLAN.md --expect CURRENT_SHA256 --confirm < updated-plan.md
```

A truncated excerpt's hash covers the whole file, but the excerpt is not the
whole document. Read required pages before rebuilding it. Never replace a file
with an excerpt or reconstruct it from `redacted: true` output. Use `--expect
missing` only for an authorized new file. Writes cap at 32 KiB and require an
existing parent directory and exact registry scope.

Writes use atomic replacement and stable adjacent `.gm-write-HASH.lock` files.
Registration must authorize those coordination artifacts too. Keep production
locks: unlinking them can split concurrent owners. If the owner agrees, add
`.gm-write-*.lock` and `.gm-write-*.tmp` to that project's ignore rules. Never edit
another project's ignore files silently. Locks serialize cooperating adapters;
ordinary editors/patch tools can bypass them. A second hash check detects many
outside edits, but cannot eliminate the final check/replace race.

`write_conflict`: read and reconcile. **`outcome_unknown`: do not repeat the
mutation**; inspect the file hash or job state first. Writes and arbitrary commands
are never automatically retried. Reads get at most one retry within the same
per-request deadline: 20 seconds by default, configurable with `--timeout`.
That is not a whole-batch time budget.

The request deadline includes response-body reading and is enforced even if a
transport ignores abort signals. CLI shutdown flushes output before exiting so
WebSocket close timers do not turn a finished failure into another long wait.
Initialization uses the setup checker's shared elapsed budget around the whole
read-only project check; no mutations or pairing changes occur there.

```bash
node scripts/projects.mjs exec PROJECT --command 'short authorized command' --confirm
```

Execution additionally requires `allow_exec: true`. Output caps at 4,000 stdout
and 1,000 stderr characters; nonzero exits return `command_failed`. This is not
a long-job supervisor. Launches, cancellations, task edits, and existing terminal
control need explicit authorization. Never enable execution or broaden scope
because the model thinks it would help.

## Safety and limits

- Paths must stay inside the registered root. Traversal, symlinks below its
  canonical root, credential files, `.env*`, and internal lock paths are denied.
- Known pairing credentials and common credential assignments are masked.
  Full document reads mask assignments before pagination. This is not a general
  secret detector; never request secrets or environment dumps. Large-log tail
  windows cannot provide full redaction context, so avoid logs likely to contain credentials.
- Processes are limited to this user's selected workspace, without arguments or
  environment. Counts do not prove training progress, GPU ownership, or health.
- Task summaries retain IDs, names, enabled flags, last status, and available
  last-run timestamps (`last_run_at` is Unix milliseconds). This is scheduler
  run state, not proof of training health. Prompts, raw errors, and history are omitted.
- Queries are live; health/discovery caches last only for one invocation.
  Failures never become empty task/process lists.
- Full document reads cap at 512 KiB; larger logs need `--tail`. Listings stop
  above 100,000 visible entries. Responses/configuration have hard size caps.
- The relay source is pinned, not a stable public SDK. Before upgrading it,
  review the source pin, license, and hashes in the vendor manifest; run regression
  tests and live compatibility checks. Remote hosts must keep OpenChamber and
  their outbound relay connection running.
