---
name: gn
description: Night secretary summary for /gn: ask what was completed, record actual project progress, remind tomorrow's approved schedule and pending ideas, and save the exact reply.
---

# Night summary

Trigger: `/gn`, or an explicit request for the GoodMorning night workflow.
Inputs: confirmed profile, current session, selected daily task lists, user-reported
progress, relevant project records, and approved calendar. Output: feedback and
progress records plus a clear night reply in the user's custom tone and a verbatim
snapshot. Apply that tone throughout, including questions and progress discussion;
clean formatting and clarity always take priority.

All paths below are relative to the GoodMorning package root. Read
`docs/core-rules.md` first (`docs/skill-rules.md` is the expanded reference). Use
`templates/gn.reply.template.md` and
`templates/daily.template.md`. Run commands from root; apply the shared
runtime/date rules. Use `question` for needed progress input or clarification;
confirmed completed-task choices may use multiple selection.
Apply the shared materiality gate: non-critical caveats, empty statuses and routine
bookkeeping stay internal; actionable blockers, conflicts and failed saves remain.
Use `docs/reply-voice.md`. Respond with the agreed personality to actual
effort, concerns and setbacks; make the evening conversation supportive, not a
performance report. Keep useful context within sections; use headings/rules,
appropriate lists and a timetable for tomorrow. Brief section takeaways and a warm
good-night closing are welcome; no long framing or pep talk.
Use the same layout discipline as gm: short greeting/date, Markdown headings and
horizontal rules, clear bullets or a task/status table, and tomorrow's timetable.
Bold only key outcomes/urgent issues. Keep warmth in useful content, optional brief
takeaways and the closing. Do not add routine weather/news, backlog or diagnostics.

## Steps

1. Run `workflow.py --secretary-dir RUNTIME --prepare gn` once for setup, dates,
   preferences, paths, daily tasks/hash and active inbox summaries. Do not repeat
   these reads. Handle duplicate
   or missed runs first. A duplicate names the previous session and stops without
   marking or overwriting its snapshot. When proceeding with a new summary,
   rename this conversation to `GoodNight DATE` in `secretary_language` per the shared title rule.
2. Read the selected day's must-do/nice-to-do lists. Ask what was completed,
   partially completed, blocked, or changed. If the user already provided this,
   ask only for remaining ambiguities. If no morning list exists, ask for the
   actual work and label the missing plan; do not invent it. Do not mark `/gn`
    while waiting for feedback.
    Follow the shared pending project-update workflow: ask outstanding clarification
    questions from saved updates alongside progress questions, reusing prior answers.
    Leave unanswered plan changes pending; they do not block a summary of otherwise
    confirmed progress. Do not apply them as confirmed goals, TODOs or completions.
   For a small task list, ask one compact question about actual outcomes and any
   extra work. A completion choice confirms that task only; partial/blocked work
   needs its actual details. Never turn implementation work by this agent, calendar
   presence or a successful gm run into the user's completed project work.
3. Use `daily.py --date DATE --amend --expect HASH` with selected task IDs and explicit
   `confirmed_completion:true` only for actual user-confirmed completions.
   Add concise `## feedback` and
   `## progress` sections; keep partial and blocked tasks open. Assess each
   relevant project's position against known goals/deadlines, stating uncertainty
   when evidence is insufficient. Recognize actual effort without exaggeration or
    judgment. Present reported completions, partial progress and blockers distinctly;
    a table is useful for several tasks, bullets for one. No inflated achievements
    or generic “completion not inferred” paragraphs. Keep source uncertainty internal
    unless it changes a reported outcome or needs a decision.
4. Update authorized project records from confirmed progress and set
   `last_update`. Write to work project files only within confirmed scope and the
   shared hash/confirmation rules; report unresolved write-back separately.
5. When Betterbird is the confirmed calendar source, first run
   `secretary_calendar.py --sync-betterbird --days 7 --timezone ZONE` to stage
   imports for review on every /gn run; never auto-approve unseen events. If the
   cache is locked, ask the user to close Betterbird and retry; otherwise continue
   with approved events. Then query the next local day's schedule with
   `secretary_calendar.py --from TOMORROW --days 1 --timezone ZONE --json --details`.
    Use preparation's inbox page; fetch further `inbox.py --list` filters/pages and
    `--show ID` only as needed for relevant current
    constraints; no raw inbox/history scan. Review flagged new details per
    `docs/inbox-pipeline.md`; do not silently omit reminders from later pages.
    Inspect preparation details, surface pending review, and remind about pending
    inbox ideas. Ask focused questions for pending clarification per the shared
    reminder rule; deferral leaves ideas pending without blocking the summary.
    Treat `kind: "todo"` entries as open task reminders, not automatic clarification
    questions. Mark them done only on user-confirmed completion.
    Do not treat unfinished tasks as new calendar appointments.
   Show date/time/timezone, event, place and prep in chronological rows. A clear
   calendar can be stated in one short planning-relevant line; do not manufacture
   events or pad it with empty rows. Omit empty reminder sections. Keep unfinished
   priorities separate from scheduled events and ask before assigning new dates.
6. Use the night template, ending in the user's tone and respecting the actual
   time (evening versus late night) or special instruction. Save feedback/progress
   and the exact final reply with `state.py --mark-gn --session NAME
   --answer-file PATH --json` (or stdin), using the selected date. Verify success,
   then present the reply. Saving is not evidence of delivery.

7. For chosen image delivery, follow `docs/image-delivery.md` after saving text.

## Errors and follow-up

Without user feedback, ask a considerate question rather than inventing a summary.
Unavailable schedule/project data stays explicitly unavailable. Do not silently
cancel, reschedule, roll over, or check off work. Apply shared event confirmation
and failure handling; ordinary amendments preserve the original snapshot.
