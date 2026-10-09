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

The repository root is `../../..` from this skill directory. Read
`../../../docs/skill-rules.md` first. Use
`../../../templates/gn.reply.template.md` and
`../../../templates/daily.template.md`. Run commands from root; apply the shared
runtime/date rules. Use `question` for needed progress input or clarification;
confirmed completed-task choices may use multiple selection.
Apply the shared materiality gate: non-critical caveats, empty statuses and routine
bookkeeping stay internal; actionable blockers, conflicts and failed saves remain.
Use `../../../docs/reply-voice.md`. Respond with the agreed personality to actual
effort, concerns and setbacks; make the evening conversation supportive, not a
performance report. Keep useful context within sections; use headings/rules,
appropriate lists and a timetable for tomorrow. Brief section takeaways and a warm
good-night closing are welcome; no long framing or pep talk.
Use the same layout discipline as gm: short greeting/date, Markdown headings and
horizontal rules, clear bullets or a task/status table, and tomorrow's timetable.
Bold only key outcomes/urgent issues. Keep warmth in useful content, optional brief
takeaways and the closing. Do not add routine weather/news, backlog or diagnostics.

## Steps

1. Check setup and run `python scripts/state.py --check --json`. Handle duplicate
   or missed runs first. A duplicate names the previous session and stops without
   marking or overwriting its snapshot. When proceeding with a new summary,
   rename this conversation to `GoodNight DATE` per the shared title rule.
2. Read the selected day's must-do/nice-to-do lists. Ask what was completed,
   partially completed, blocked, or changed. If the user already provided this,
   ask only for remaining ambiguities. If no morning list exists, ask for the
   actual work and label the missing plan; do not invent it. Do not mark `/gn`
   while waiting for feedback.
   For a small task list, ask one compact question about actual outcomes and any
   extra work. A completion choice confirms that task only; partial/blocked work
   needs its actual details. Never turn implementation work by this agent, calendar
   presence or a successful gm run into the user's completed project work.
3. Check only confirmed completed tasks. Add concise `## feedback` and
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
5. Query the next local day's schedule with
   `secretary_calendar.py --from TOMORROW --days 1 --timezone ZONE --json`.
   Inspect preparation details, surface pending review, and remind about pending
   inbox ideas. Do not treat unfinished tasks as new calendar appointments.
   Show date/time/timezone, event, place and prep in chronological rows. A clear
   calendar can be stated in one short planning-relevant line; do not manufacture
   events or pad it with empty rows. Omit empty reminder sections. Keep unfinished
   priorities separate from scheduled events and ask before assigning new dates.
6. Use the night template, ending in the user's tone and respecting the actual
   time (evening versus late night) or special instruction. Save feedback/progress
   and the exact final reply with `state.py --mark-gn --session NAME
   --answer-file PATH --json` (or stdin), using the selected date. Verify success,
   then present the reply. Saving is not evidence of delivery.

## Errors and follow-up

Without user feedback, ask a considerate question rather than inventing a summary.
Unavailable schedule/project data stays explicitly unavailable. Do not silently
cancel, reschedule, roll over, or check off work. Apply shared event confirmation
and failure handling; ordinary amendments preserve the original snapshot.
