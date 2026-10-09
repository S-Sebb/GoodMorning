---
name: eureka
description: Fast idea capture for /eureka: save the user's raw idea as pending, offer clarification now or later, and organize only confirmed meaning into authorized project records.
---

# Idea capture

Trigger: `/eureka`, or an explicit request to capture an idea in GoodMorning.
Inputs: the user's raw idea, confirmed runtime/timezone, optional project alias,
and their choice to clarify now or later. Output: a saved pending idea first;
confirmed organization only after clarification and successful writes.

The repository root is `../../..` from this skill directory. Read
`../../../docs/skill-rules.md` first. Use
`../../../templates/eureka.reply.template.md`. Run commands from root and resolve
the shared runtime directory. Use `question` for now/later and needed clarification
or confirmation. Do not fetch weather/news or scan all projects.
Apply the shared materiality gate: no non-critical disclaimers or unrelated
diagnostic narration; show the actual capture outcome and useful next step.
Use `../../../docs/reply-voice.md`: quick capture can still sound interested and
personal. Reflect the idea within useful content, without extra framing. Use lists
when clarification benefits from them, not forced tables or decorative bold.
Brief grounded interest or a warm closing is optional, not mandatory padding.

## Steps

1. Check setup without delaying capture with unrelated questions. If setup is
   missing, retain the idea in the conversation, load `secretary` for setup, and
   say it is not saved yet. If no idea was supplied, ask for it; do not create an
   empty entry.
2. Append one pending entry to the existing inbox without replacing other ideas:
   `- YYYY-MM-DD HH:MM TIMEZONE | RAW_IDEA | pending | PROJECT`.
   Use the real local timestamp and an optional confirmed project. Preserve raw
   wording; for multiline text, encode the raw string as JSON on that single
   line so line breaks/quotes are reversible. Never persist credentials: ask for
   a redacted idea instead. Verify the write before saying "Saved". If this same
   user turn was already captured, point to its entry rather than appending again.
3. Apply the user's customised tone throughout the confirmation, questions, and
   reminders, while prioritizing clean formatting and clarity. Confirm what was
   saved in a natural reply using the template. Make it
   easy to choose whether to clarify now or later, without pressure or exaggerated
   praise. If the idea implies a dated event, offer calendar confirmation under
   the shared rules; capturing an idea does not authorize adding an appointment.
4. Later: leave it pending. State the reminder rule: today's `/gn`, otherwise the
   next `/gm`, repeated until confirmed and organized. Do not install a scheduler.
5. Now: ask focused questions until goal, intended project, constraints, and next
   action are clear. Quote back the clarified meaning for confirmation. Read only
   relevant project records/instructions. Write the confirmed idea into authorized
   records and/or work files, updating `last_update` and preserving unrelated work.
6. Change that inbox entry to `confirmed` only after the user confirms and the
   agreed organization succeeds. If any required write is unresolved, keep it
   pending and describe what remains. Rebuild the state index after record changes
   with `state.py --rebuild --json`; never mark gm/gn for idea capture.

## Errors

Failed capture means "not saved", not "saved for later". Ask about ambiguous
project matches instead of guessing. Respect write conflicts/unknown outcomes;
never duplicate a possibly successful remote write or delete the original idea.
