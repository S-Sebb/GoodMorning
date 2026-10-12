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
- `/initialize`, `/secretary`, first-use setup, or general secretary work:
  `docs/workflows/secretary.md`.

Equivalent natural-language requests use the same workflows. Ask if the requested
workflow is unclear. Keep the current session and model; do not delegate.
New gm/gn editions are browser-native: read `docs/briefing-format.md`, author one
validated v1 JSON document, and save with `scripts/goodmorning.py state`. Do not
generate Markdown/presentation copies, image cards or HTML exports. Only native
JSON briefings are supported. Preserve private records and initialized preferences.
Browser jobs follow `docs/browser-generation.md` and `scripts/goodmorning.py job`: prepare
from saved browser context, publish only the next section, then finish. Code owns
the cumulative document, task synchronization and final save. Never count previews
as completed runs or repeat saved browser decisions/progress questions.
Schedule/Tomorrow holds appointments and important day commitments, with typed
`flexible` rows for eligible untimed work. Project steps / Optional project steps
hold ongoing project progress, excluding scheduled actions. Follow task selection
and section ownership in `docs/briefing-format.md`; show only confirmed current
wording, not superseded daily history. Each action has one section owner.
Never equate no appointments with a free day or bury dated plans in reminders.
Website conversations marked `Browser chat` follow `docs/browser-chat.md`.
Stay flexible: an explicit request for another mode's work automatically follows
that workflow in the same conversation. Do not require a manual mode switch or
special command. Reuse saved context and preserve permissions and confirmations;
browser briefings still belong on the Morning/Evening pages.
`/eureka` and `/todo` are capture requests, not instructions to do the captured
work. By default, save, confirm, then stop. Supplied details do not authorize discussion or
execution; clarification requires an explicit request and is not execution consent.
Missing setup follows the secretary workflow without recursively loading a skill.
Inbox memory uses `scripts/goodmorning.py inbox`: append without reading history, query only
active summaries/relevant IDs, and keep material current state—not a transcript.
Only SQLite inbox storage is supported. Read `docs/inbox-pipeline.md` for advanced updates/review.
New raw ideas/TODOs use `scripts/goodmorning.py workflow --capture eureka|todo` directly; it
checks setup and saves without reading old context. Do not load the advanced inbox
guide for a simple capture. Briefings/general work use `--prepare KIND` once;
daily amendments use `scripts/goodmorning.py daily`. See `docs/workflow-helpers.md` as needed.

Run helpers from the package root with explicit absolute storage paths. Runtime
records use an explicitly selected `SECRETARY_DIR`, otherwise
`~/.local/share/GoodMorning/secretary`. Cache files use an explicitly selected
`GM_CACHE_DIR`, otherwise `~/.cache/goodmorning`. Expand `~` before passing paths.
Always pass `--secretary-dir`, weather `--profile`, news/weather `--cache-dir`,
and calendar `--db` as applicable. Keep temporary files in the authorized runtime.
Never initialize records or caches inside the skill or the invoking project.
Installation does not authorize setup, provider access, or record mutations.
