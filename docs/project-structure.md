# Project structure

Application code belongs in `src/goodmorning/`, not in the command directory.
`scripts/goodmorning.py` adds that source directory to Python's import path and
dispatches one selected command. It works without installation, including when
the public files are copied into an agent's skill directory. Imports are
package-qualified.

## Ownership

| Directory | Responsibility |
|---|---|
| `src/goodmorning/briefings/` | Native JSON, incremental publication, images, and browser rendering |
| `src/goodmorning/web/` | HTTP viewer, secretary chat, and shared resources |
| `src/goodmorning/security/` | Accounts, gateway, encrypted volumes, and isolated launchers |
| `src/goodmorning/records/` | Daily records, inbox, state, and workflow preparation |
| `src/goodmorning/news/` | Collection, editorial selection, reports, and bundled source configuration |
| `src/goodmorning/calendar/` | Calendar storage, recurrence, and confirmed changes |
| `assets/web/` | Browser assets; no generated pages or private user data |
| `integrations/opencode/` | OpenCode plugins the website engine loads |
| `vendor/` | Unmodified third-party source and notices |
| `scripts/` | One small command entry point only |
| `requirements/` | Optional dependency lists |
| `tests/` | Unit contracts, shared fixtures, `browser/` checks, and `benchmarks/` |
| `deploy/` | Public service and HTTPS configuration |
| `android/` | Android app shell, released as an APK and never deployed to the server (`docs/android-app.md`) |

Keep personal runtimes, logs, reports, generated screenshots, caches, backups,
and credentials outside the source tree.

## Commands

Use `python scripts/goodmorning.py --help` to list commands and append
`--help` after a command for its existing options. For example:

```sh
python scripts/goodmorning.py job --secretary-dir RUNTIME --job JOB prepare
python scripts/goodmorning.py serve --secretary-dir RUNTIME
```

Update commands, workflow documents, and service templates together. Verify the
copied release before switching its pointer. Retain the previous release and
never replay an uncertain generation while changing public code.
