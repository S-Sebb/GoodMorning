 # Workflow efficiency audit

Scope: all five workflows, setup, records, weather, news, calendar, project access,
reply policy and deployment. No live provider calls, jobs, approvals, scheduling,
task completion, or personal-record amendments were used to validate changes.

## Changes retained after focused verification

| Area | Inefficiency / risk | Change |
|---|---|---|
| Instructions | Every invocation loaded the full expanded rulebook and repeated pipeline/voice guidance | Compact mandatory core; workflows load only relevant specialized guides |
| Preparation | Agent repeatedly resolved paths/dates/countries, read full profile prose, state, daily files and inbox | `workflow.py --prepare` returns relevant preferences, deterministic dates/paths and paginated local context once |
| Quick capture | Separate readiness/profile/state reads and payload/type/title construction | `workflow.py --capture todo/eureka` checks setup and captures in one command, preserving idempotency and raw input |
| Duplicate briefings | Full state/context checks before stopping a duplicate | Inspect today's run source first; stop before history, tasks, inbox or provider activity |
| Preparation I/O | Reply-cost scans and unrelated project/calendar scans for data not used in preparation | Read run flags without snapshot bodies/context scans; retain full state checks for explicit diagnostics and marks |
| Daily records | Model repeatedly rebuilt Markdown, deduplicated reminders and toggled checkboxes | Hash-checked deterministic section amendments, exact task IDs, explicit completion flag, preserved prior completions/run lines/unrelated text |
| News review | Full saved reports repeated candidates/diagnostics after selection; extra reread after curate | Complete paginated candidate view; selected-story view retains all stories/links/warnings; curate returns the saved selected stories directly |
| Calendar | Narrow schedule query followed by individual preparation-note reads | Query approved `--json --details` once; keep individual original/revision reads for import review |
| Calendar storage | Ordinary read command could create schema/directories or rewrite journal configuration | Existing database opened read-only; missing store is a setup error, not an empty schedule |
| Runtime defaults | Several helpers searched/wrote under the current checkout or installed package | Shared user-local runtime/cache resolution with explicit overrides and tilde expansion |
| Configuration | Calendar path differed between context/state/calendar commands | Shared calendar-path precedence; optional bad calendar configuration remains a material component error, not erased profile setup |
| Documentation | Daily template could imply resetting completed boxes or auto-opening duplicate snapshots; voice overview contradicted optional closing | Align with preservation, duplicate-stop and agreed voice rules |

## Deliberately not converted into fixed code

- News significance, semantic event deduplication, bias/genre interpretation and
  source-claim assessment need evidence-based judgment. Keyword ranking remains
  a shortlist, not editorial approval. All chosen stories remain visible and each
  country/report ID retains its own delivery boundary.
- Priorities, estimates, interpretation of reported progress, clarified project
  changes and personal tone remain agent work. Code only applies explicit choices;
  it does not invent deadlines, equivalence, completion or permission.
- Setup and calendar/project consent stay conversational. Existing bounded setup
  checks already parallelize only selected checks. Native calendar normalization,
  recurrence expansion, unchanged-import deduplication, revision guards and source
  redaction were already code; no second orchestrator was added.
- Weather already fetches independent sources concurrently with separate caches.
  News already caches/revalidates responses, archives bounded dates and guards
  retries. Project access already batches reads and reuses host connections with
  bounded retries and no mutation replay. These mechanisms were preserved.
- Arbitrary project prose cannot safely be regenerated from compact excerpts.
  Full-target/hash/scope checks remain required. Approval or delivery cannot be
  inferred from successful collection, save, a calendar entry, or silence.
- Local file scanning costs I/O, not model input by itself. No additional growing
  metadata database, autonomous scheduler, semantic memory model, network probe
  or expensive cache layer was introduced merely to optimize small local reads.

## Evidence and limits

`python tests/benchmark_workflow.py` uses synthetic fixtures. Reference measurements:

- Default required rules: 23,897 to 9,854 characters, 58.8% smaller.
- Preparation context: 10,744 to 2,250 characters, 79.1% smaller. The fixture has
  20 tasks, three inbox items and unrelated profile/daily prose; extra pages are
  available explicitly, not silently treated as absent.
- Reviewed news: 52,780 to 4,807 characters, 90.9% smaller, preserving all 12
  selected stories, source links and the material warning. Candidate evidence
  remains available and is still reviewed before selection.

These measure model-visible characters, not billed tokens, actual latency, agent
quality or live coverage. Safety tests cover deterministic capture, setup errors,
duplicate stops, no provider/snapshot/context scans during preparation, hash
conflicts, exact deduplication, preserved completions/unrelated/fenced text,
partial task selection, source fidelity, explicit history and read-only calendar
storage. The existing provider/permission/revision/delivery tests still apply.

Use a new session after deployment to load the routed instructions. Personal
records and database schemas need no migration for this upgrade. Missing-calendar
reads now deliberately fail rather than initialize storage; authorize setup first.
