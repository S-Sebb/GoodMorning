---
name: gn
description: Night secretary summary for /gn: ask what was completed, record actual project progress, remind tomorrow's approved schedule and pending ideas, and save the exact reply.
---

# Night summary

Trigger: `/gn`, or an explicit request for the GoodMorning night workflow.
Inputs: profile/session, tasks, reported progress, projects and approved calendar.
Output: JSON and feedback/progress records. Use the confirmed tone throughout;
clarity takes priority.

Paths are package-root relative. Read `docs/core-rules.md`; `docs/skill-rules.md` is for audits.
Use `docs/briefing-format.md`, `templates/daily.template.md` and the native authoring
guide `templates/gn.reply.template.md`. Run from root with shared runtime/date rules.
Use `question` for progress input or clarification;
confirmed completed-task choices may use multiple selection.
Apply the shared materiality gate: non-critical caveats, empty statuses and routine
bookkeeping stay internal; actionable blockers, conflicts and failed saves remain.
Use `docs/reply-voice.md`. Respond with the agreed personality to actual
effort, concerns and setbacks; make the evening conversation supportive, not a
performance report. Use helpful sections/lists and tomorrow's timetable. Brief takeaways and a warm
good-night closing are welcome; no long framing or pep talk.
Python commands below use `python scripts/goodmorning.py COMMAND`.
Use typed sections and tomorrow's timetable. The browser owns dates/typography.
No routine weather/news, backlog or diagnostics.

## Steps

Browser jobs: read `docs/browser-generation.md` before step 1. Initialize after its
decisions; publish Today from actual answers, then Still open, before tomorrow's work.

1. Browser jobs use the job helper's saved preparation and browser feedback; do
   not rerun preparation or repeat answered decisions. Other invocations run
   `workflow --secretary-dir RUNTIME --prepare gn` once for setup, dates,
   preferences, paths, daily tasks/hash and active inbox summaries. Do not repeat
   these reads. Handle duplicate
   or missed runs first. A duplicate names the previous session and stops without
    marking or overwriting its snapshot. Rename new runs to `GoodNight DATE` in
    the browser job's website language, or `secretary_language` for local use, per the shared title rule.
2. Read the selected day's must-do/nice-to-do lists. Ask what was completed,
   partially completed, blocked, or changed. If the user already provided this,
   ask only for remaining ambiguities. If no morning list exists, ask for the
   actual work and label the missing plan; do not invent it. Do not mark `/gn`
    while waiting for feedback.
    Follow the shared pending project-update workflow: ask outstanding clarification
    questions from saved updates alongside progress questions, reusing prior answers.
    Leave unanswered plan changes pending; they do not block a summary of otherwise
    confirmed progress. Do not apply them as confirmed goals, TODOs or completions.
    A completion choice confirms only that task; partial/blocked work needs actual
    details about actual outcomes. Work by this agent, calendar presence and gm
    success never establish user progress.
3. Browser feedback has already saved exact completions and factual feedback.
   Do not save/check off that input again. Additional progress amendments use
   `daily --date DATE --amend --expect HASH` with selected task IDs and explicit
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
   `python scripts/goodmorning.py calendar --sync-betterbird --days 7 --timezone ZONE` to stage
   imports for review on every /gn run; never auto-approve unseen events. If the
   cache is locked, ask the user to close Betterbird and retry; otherwise continue
   with approved events. Then query the next local day's schedule with
   `python scripts/goodmorning.py calendar --from TOMORROW --days 1 --timezone ZONE --json --details`.
    Use preparation's inbox page; fetch further `inbox --list` filters/pages and
    `--show ID` only as needed for relevant current
    constraints; no raw inbox/history scan. Review flagged new details per
    `docs/inbox-pipeline.md`; do not silently omit reminders from later pages.
    Inspect preparation details, surface pending review, and remind about pending
    inbox ideas. Ask focused questions for pending clarification per the shared
    reminder rule; deferral leaves ideas pending without blocking the summary.
     Treat `kind: "todo"` entries as open tasks, not automatic clarification
    questions. Mark them done only on user-confirmed completion.
    Do not treat unfinished tasks as new calendar appointments.
    Show date/time/timezone, event, place and prep in chronological rows. After
    timed events, append a typed `flexible` block for tomorrow's date-confirmed
    TODOs, agreed untimed work and applicable recurring tasks. This belongs in
    Tomorrow, not Notes, even when there are no appointments. A clear calendar
    means no timed appointments, not an empty/free day. Keep unknown appointment
    times explicit in agenda; never manufacture clock times. Unfinished work
    without an agreed tomorrow date stays in Still open; ask before assigning new
    dates. Unresolved ideas/background nudges stay in Notes; omit it when empty.
    Review relevant saved project records against confirmed progress. Include
    Must-do/Nice-to-do sections for actual outstanding work on projects:
    necessary/time-sensitive next actions versus optional improvements. Name each
    project, retain known priorities, dates and blockers, and omit either section
    if it has no supported tasks. Use typed `tasks` blocks, keeping partial/blocked
    work open. These are priorities, not automatic tomorrow assignments or consent
    to execute. Tomorrow contains only date-confirmed/agreed work, with identical
    titles when also shown in priorities; Still open summarizes unresolved status
    without repeating every task. No invented work or deadlines to fill sections.
6. End in the user's tone, respecting actual time or special instruction. Browser
   jobs use `job finish`; no separate state save is required. Otherwise save
    feedback/progress and the edition per `docs/briefing-format.md` with
     `state --mark-gn --session NAME --answer-file PATH --json`
     (or stdin), using the selected date.
      Verify success. Input must be native JSON. Saving is not delivery.

7. Return the browser link, not JSON/text. Do not attach image cards in chat.

## Errors and follow-up

Without user feedback, ask a considerate question rather than inventing a summary.
Unavailable schedule/project data stays explicitly unavailable. Do not silently
cancel, reschedule, roll over, or check off work. Apply shared event confirmation
and failure handling; ordinary amendments preserve the original snapshot.
