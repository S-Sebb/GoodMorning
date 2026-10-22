# Daily history template

Use only for an authorized daily history/run record, never during setup. New live
tasks/occurrences belong in `inbox.sqlite` through `task`; native v2 editions do
not copy displayed actions into Markdown. Follow `docs/item-taxonomy.md`.

One file per day: `daily/YYYY-MM-DD.md`. Fixed section headings are case-insensitive.
Store concise factual lines here; native `.gm.json`/`.gn.json` holds briefing content.

```text
# YYYY-MM-DD

- gm: no
- gn: no
```

Only a verified save changes a run line to:
`- gm: yes (session NAME) | answer: daily/YYYY-MM-DD.gm.json`
or its gn equivalent. Preserve machine-readable session/pointer parts.

Add `weather`, `news`, `schedule`, `feedback` or `progress` sections only for actual
authorized content. Do not infer successful retrieval from a heading. Use actual
news publication dates, not the greeting date.

## Existing legacy checklists

Preserve `must-do`, `nice-to-do`, `flexible`, checked boxes, run lines and unrelated
edits. They are historical compatibility records, not live task state or source
of new work. Never infer completion, reset existing completions, automatically
roll over work or silently merge title-similar actions. Reconciliation/migration
needs owner approval under `docs/item-taxonomy.md`.

Use `python scripts/goodmorning.py daily --show` and
`daily --date DATE --amend --expect HASH` with the selected runtime for routine
history amendments; see `docs/workflow-helpers.md`. Do not rebuild entire files from
excerpts. Keep original briefing snapshots unchanged during ordinary amendments;
full replacement requires explicit authorization and browser-owned jobs use Regenerate.
