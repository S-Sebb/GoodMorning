# Project record

<!-- Copy to secretary/projects/<project-name>.md after confirming the project.
Use short bullets. Fill last_update with YYYY-MM-DD whenever the record changes.
Keep the last_update field as a plain key: value line for state.py. -->

name: ""
root_path: ""
access_method: ""
registry_alias: ""
shared_workspace_id: ""
write_back_scope: ""
priority: ""
last_update: ""

## Goal outline

<!-- State the overall goal and the main milestones. -->

## Current progress

<!-- Record completed work, active work, and blockers; do not invent progress. -->

## Task references

<!-- Link authorized canonical task IDs with their purpose or milestone.
Use the task helper for current timing/status. Do not maintain another checkbox
completion list here or turn proposed project prose into work without adoption. -->

## Deadlines

<!-- Use YYYY-MM-DD; include time and timezone when relevant.
Likely scheduled events also require confirmation before adding to SQLite. -->

## Write-back rules

- Use only registered paths and the agreed read/write-back scope.
- Record confirmed ideas and reported progress here. Update work project files
  when authorized so other agents see the same plan; preserve unrelated work.
- Keep unconfirmed ideas and project updates in the configured runtime's
   `inbox.sqlite`, not in the confirmed plan. Canonical actions and completion use
   `task` helpers; this record keeps goals, reports and authorized task references,
   not a second independently completed checklist. Save clear raw reports promptly;
  for ambiguous scheduling/targets, ask before any record or pending note.
  Retain due unresolved questions for gm/gn/secretary follow-up.
- Resolve ambiguous changes before applying them here. Update `last_update` after edits.
- Use the confirmed `registry_alias` with `scripts/projects.mjs`; the private
  registry is authoritative for host, path, and exact write targets. See
  `docs/project-access.md`. Never invent aliases or broaden their scope.
- Remote read/write-back requires agreed, tested access. Read current instructions
  and the complete target before writing; use its hash and explicit confirmation.
  Treat unknown write outcomes as unresolved, not permission to retry.
