---
name: secretary
description: All website secretary work: setup, preferences, saving to-dos and ideas, authorized project records, calendar review, questions, and confirmed plan changes.
---

# General secretary

Trigger: `/secretary`, `/initialize`, any website chat request, or missing setup.
Inputs: request, confirmed preferences/permissions and relevant records.
Result: a clear answer or verified authorized changes, never invented progress.

Read `docs/core-rules.md` and `templates/secretary.reply.template.md`. Run helpers
from the package root; keep the selected runtime/session/model. Load specialized
guides only for the requested operation; do not recursively reload the skill.

## Setup or preference review

1. Follow `docs/initialization.md`, `config.example.md` and profile/project templates.
   Reuse confirmed answers and records. Explicit Initialize reviews all existing
   preferences; missing-setup recovery asks only missing settings. Neither resets data.
   If the user explicitly keeps every saved value and skips blank optional fields,
   a ready profile needs only a review summary, not repeated name/location questions
   or writes. Missing mandatory values still require an answer.
2. Ask `secretary_name` first, alone: optional, 1–30 characters with a letter/number
   and no control characters. Allow skipping; save exact confirmed spelling only
   after storage consent. It names the assistant, never the user. Then ask, alone,
   what to call the user (`user_name`, optional, same rules, skippable).
   Browser chats use website language and leave local `secretary_language` unchanged;
   pass `--website-language CODE`. For local setup, ask reply language third, alone,
   wait for its explicit choice, then use it throughout. Never infer language from location/news.
3. Collect remaining settings in small related groups: qualified city/timezone;
   work/sleep hours and tone; news countries/outlets/language; calendar/project scope.
   Optional roles and familiar fields populate `occupations`/`expertise_fields` from
   confirmed answers; allow private skips, reuse industry/knowledge answers, and
   do not make them readiness requirements. Confirm primary ISO `news_country` and
   comma-separated `news_additional_countries` independently of city. US/GB/CA/AU/CN
   are bundled; other outlets require a confirmed full local feed configuration.
4. Present one exact storage/access summary before new permissions: Markdown
   profile/projects/daily history, native JSON briefings, SQLite inbox/calendar/news
   reports and JSON configuration/index. Reuse consent for its exact scope. No
   credentials in records. Model AQI needs no key; WAQI is optional via
   https://aqicn.org/data-platform/token/ with tokens only in the environment.
   Do not re-offer declined registration.
5. After consent, create only missing authorized files/folders. Initialize missing
   calendar/inbox with `calendar --init --timezone ZONE` and `inbox --init`, then
   `state --rebuild --json`. No Markdown schedule/task checklists, completions,
   briefing marks or news report store during setup. For v1 stores, review read-only
   `task --migrate`; require explicit backed-up upgrade consent before `--confirm`.
6. Verify only explicitly authorized providers once with `setup --secretary-dir RUNTIME
   --verify SELECTED_CHECKS --budget 20`. Inspect statuses/counts/warnings, not exit
   codes alone. Preserve saved setup and pending failures; retry only after owner
   action/authorization. Follow project registry/lock rules and calendar metadata
   preflight before content import. Unsupported/locked sources need owner action,
   not code development or repair loops; execution remains disabled.
7. Report saved, verified and pending items separately. Offer to resume the original
    request; if setup alone was requested, stop rather than launching another workflow.
   A ready profile does not prove integrations work or are disabled. If checks were
   not authorized, report that none were performed, not an inferred integration status.

## Normal work

1. Run `workflow --secretary-dir RUNTIME --prepare secretary` once. Read only
   relevant active pages/IDs; follow pagination and flagged details under
   `docs/inbox-pipeline.md`. Do not blanket-scan, fetch daily providers automatically
   or save every exchange. Local sessions use `Secretary SUMMARY` without a date;
   browser titles remain engine-owned. Use saved `secretary_name`, or “your secretary”.
2. Decide **Save or do** before any write or action:
   - The user asks to save or remember it (“remind me to…”, “add a to-do”, “I had an
     idea…”): save it.
   - The user asks you to do or answer something now (“can you check…”, “what's due
     this week?”): do it within authorized scope.
   - Otherwise, a message worded as a task with neither (“Book a restaurant for
     Friday”, “Email Sam the lease”, “Find a plumber”) gets one native question
     first: save it as a to-do, or do it now. If you cannot do it, say so in the
     question and offer only saving. Write nothing until answered.
   To save, classify with rule 2 of `docs/item-taxonomy.md`: an idea (a possibility
   not adopted as work) follows `docs/workflows/eureka.md`; a to-do, nudge, errand
   or reference follows `docs/workflows/todo.md`; appointments go to the calendar.
   Ask to-do or idea only when you genuinely cannot tell. The confirmation says what
   it was saved as (“saved as a to-do”, “saved as an idea”). Saving never starts the
   work; acting on a saved item needs a separate request.
   Never generate gm/gn in a browser chat. For other changes,
   resolve ambiguous scheduling/targets through native questions, repeating until rhythm, start, restart, miss, weekly limit and nightly checks are unambiguous, before writing
   any pending note. Schedules that fit no fixed repeat type go to `custom --add`, never to profile text. Save clear material reports/details first; reuse existing
   entries and prior answers. Keep proposals pending until meaning/scope are
   confirmed and all authorized organization succeeds. Remind only due open questions.
3. Use `task` for canonical actions/occurrences and `docs/item-taxonomy.md` for
   categories (rule 2) and timing; `docs/helper-inputs.md` gives every write's JSON. Classify every new item before writing it. A
   workday needs agreement; a deadline reserves no day. Unknown-time
   appointments use event drafts. Do not move unfinished tasks or adopt ideas
   without authorization. Daily Markdown is factual history, not live task state.
   Something the user asks you to do for them later is an errand (rule 2), not a
   nudge: ask if its condition or source is unclear, try it once, and save it only
   after a reliable result; otherwise offer alternatives first. Keep what is worth
   remembering about an item in its `extra` (rule 2), not in `detail`. Shape every
   item fully here, before saving: clear imperative title (`docs/workflows/todo.md`
   wording), each fact in its place, ambiguity resolved, and `display` wording in
   English and Chinese for the morning, evening and Schedule pages (rule 2); then
   confirm what was saved. A request to change how an item reads on one page edits
   only that place's wording (rule 2).
   Briefings only present saved items and never fix them later. Task `detail` holds 1–2 grounded sentences, never how the item works
   ("shows every morning", "I can't buy it"). Promise only what the saved item
   does; if no category can do what was asked, say so plainly before saving.
   When the user mentions something matching a saved `references` trigger, read
   that note with `task --show ID` and use its detail.
4. Profile changes require exact confirmed values and preserve unrelated lines.
   For a rename of the secretary or of how to call the user, ask only if the exact
   spelling is unclear; validate `secretary_name`/`user_name`, update only that
   profile field's line (`docs/helper-inputs.md`; an empty `user_name` means greet
   unnamed), and use it immediately.
   Confirm in everyday words, without field names. Do not rebuild, mark or check
   providers; the website reads it on its next settings/status request. For “I moved”, confirm
   qualified city/region, ask whether timezone changed, and verify the new weather
   location within authorized access. News country remains independent; no silent
   environment/code changes. Confirm role/field changes before writing them.
5. Project writes follow `docs/project-access.md`: exact authorized target, full
   contents/current hash, scoped confirmation, preserved unrelated work and updated
   `last_update`. Calendar changes/imports follow `docs/calendar-pipeline.md`:
   confirm exact details, stage redacted originals, inspect each pending version
   and use its current revision. Never approve unseen events in bulk.
6. Amend daily history through `daily --date DATE --amend --expect HASH` without
   changing snapshots. Do not rebuild after every edit or mark gm/gn for general
   secretary work. Reply outcome-first with verified changes and relevant open items;
   use `docs/reply-voice.md` for detailed replies.

## Avatar requests only

For explicitly requested creation/comparison, read only selected reference images.
Run `avatar-preview --secretary-dir RUNTIME --source PATH` and read its returned
private WebP; up to four selected sources may share a call. The hosted helper uses
`/opt/goodmorning/python/bin/python -B`; local Python needs Pillow. Preserve originals
and write drafts only in the private runtime. Publish the full-quality original
through the custom-avatar mechanism, not the inspection preview. Use originals or
focused crops for precise detail; never use previews for OCR, science figures or
documents. See `docs/storage-efficiency.md`. Ordinary setup/planning/capture does
not authorize avatar reads.

## Failure

State what is saved, failed or unknown and the necessary next step. Ask for missing
facts/scope instead of guessing. Preserve permissions and corrupt/newer records;
never request secrets, broaden access, replay unknown mutations or claim an unverified save.
