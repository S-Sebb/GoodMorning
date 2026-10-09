# custom_schedule.md (user-local, git-ignored)

**Legacy migration reference only.** New calendars use
`secretary/calendar.sqlite`. Do not copy this template during init or edit
Markdown to change the active schedule. Talk to the secretary instead.
See `docs/calendar-pipeline.md` for migration and current commands.

Old user-set special dates. One event per line, accepted by `--migrate-md`.

Format:

```text
- YYYY-MM-DD HH:MM-HH:MM | Title | Place | Notes
```

Rules:

- Date required. End time optional (default +1h).
- `Title` required. `Place` and `Notes` optional but recommended.
- Lines starting with `#` are comments. Blank lines ignored.
- Keep one line per item, no extra prose (low token cost).

Example (fake data, replace with your own):

```text
- 2026-10-10 09:30-10:30 | TA RSM338 | RSM338 | Bring slides, whiteboard markers
- 2026-10-11 11:00-12:00 | Group meeting | Room 301 / Teams link | Send slides by 22:00 day before
- 2026-10-12 18:00-19:00 | Gym | Gym | Rest day if ill
```
