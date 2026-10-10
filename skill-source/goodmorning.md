---
name: goodmorning
description: Personal secretary for /gm morning briefings, /gn night summaries, /eureka idea capture, /todo task capture, and /secretary setup, project records, and calendar work.
---

# GoodMorning

The GoodMorning package root is this skill directory (`./`).
Resolve it to an absolute path before reading files or running helpers. All paths
in workflow files are relative to that package root, not the invoking project.

Read `docs/core-rules.md`, then only the requested workflow. The expanded
`docs/skill-rules.md` is for audits/edge cases, not a default read:

- `/gm`: `docs/workflows/gm.md`.
- `/gn`: `docs/workflows/gn.md`.
- `/eureka`: `docs/workflows/eureka.md`.
- `/todo`: `docs/workflows/todo.md`.
- `/secretary`, first-use setup, or general secretary work:
  `docs/workflows/secretary.md`.

Equivalent natural-language requests use the same workflows. Ask if the requested
workflow is unclear. Keep the current session and model; do not delegate.
`/eureka` and `/todo` are capture requests, not instructions to do the captured
work. Save, confirm, then stop. Supplied details do not authorize discussion or
execution; clarification requires an explicit request and is not execution consent.
Missing setup follows the secretary workflow without recursively loading a skill.
Inbox memory uses `scripts/inbox.py`: append without reading history, query only
active summaries/relevant IDs, and keep material current state—not a transcript.
Never append to legacy `inbox.md`. Read `docs/inbox-pipeline.md` for advanced updates/review.
New raw ideas/TODOs use `scripts/workflow.py --capture eureka|todo` directly; it
checks setup and saves without reading old context. Do not load the advanced inbox
guide for a simple capture. Briefings/general work use `--prepare KIND` once;
daily amendments use `scripts/daily.py`. See `docs/workflow-helpers.md` as needed.

Run helpers from the package root with explicit absolute storage paths. Runtime
records use an explicitly selected `SECRETARY_DIR`, otherwise
`~/.local/share/GoodMorning/secretary`. Cache files use an explicitly selected
`GM_CACHE_DIR`, otherwise `~/.cache/goodmorning`. Expand `~` before passing paths.
Always pass `--secretary-dir`, weather `--profile`, news/weather `--cache-dir`,
and calendar `--db` as applicable. Keep temporary files in the authorized runtime.
Never initialize records or caches inside the skill or the invoking project.
Installation does not authorize setup, provider access, or record mutations.
