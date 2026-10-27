# Weekly letters

A weekly letter looks back on one Monday–Sunday week of 04:00 days: the week
ends at 04:00 on Monday, like the briefing day. Every week gets exactly one
letter, written when a briefing is prepared or the Letters tab is opened;
nothing runs on its own. The **Letters** tab at
`/letters` opens the newest saved letter, whenever it was written, and
`/letters/WEEK` (the week's Monday) opens one week's. Beside the letter (above
it on phones) a wheel lists every saved week, newest first: scrolling, tapping
or the arrow keys turn it, and the week left in the middle opens in place
(`assets/web/letters.js`); without scripts the wheel is a list of links.
Letters are a memory book. A letter written before its week ends (Sunday
evening) is completed once from records the first time a briefing is prepared
or the Letters tab is opened after the week ended, so anything finished or
saved later that Sunday night is in it; its opening and sign-off stay as
written. After that a letter never changes, even when its records change later
or the briefing is regenerated. The briefing card keeps the counts it showed.

## Contents

Code (`src/goodmorning/records/letters.py`) builds every list from saved
records. The secretary writes only a short opening and a sign-off from those
lists, in the job's website language and saved tone. The opening may add one
thing from next week; the sign-off is about two short sentences: a brief
summary of what was finished, kept and saved, then a warm wish. It never
mentions next week. A plan from next week stays the user's own: the letter
never says what the secretary, or the two of them together, will do later. When
a week has nothing finished, no habits and no ideas, code writes the opening
(“This week’s letter is a short one.”) so a quiet week is never judged, and the
secretary writes only the sign-off: a warm wish that names nothing.

- **What you finished:** task occurrences confirmed done that week, plus one-off
  tasks whose done confirmation falls in the week (account timezone, 04:00 days). Grouped by
  project in the order they were finished; repeats show a count. Nudges, errands
  and reference notes never appear.
- **Habits:** habits with at least one confirmed completion that week: times this
  week and the number of weeks in a row with at least one completion (shown from
  2). A habit with a quiet week is left out; a broken run is never mentioned.
- **Ideas you saved:** ideas captured that week (04:00 days).
- **Coming up next week:** appointments (once, on their start day), confirmed
  appointments with time to be confirmed, hard deadlines, and how many planned
  tasks the week holds. Habit projections are left out. A failed calendar or
  task read is noted, never shown as an empty week.

Empty parts are left out. Saved files are `letters/WEEK.json` in the runtime;
`open: true` marks a letter whose week had not ended when it was written.

## The briefing that carries it

Unless the profile sets `weekly_letter: "false"` (the secretary changes it when
the user asks to stop or resume), a briefing plan ends with a **Weekly letter**
position:

- on a Sunday briefing day (04:00 rollover), the evening plan, for this week;
- otherwise, either edition, for last week when it ended without a letter (for
  example, Sunday's evening briefing was skipped or its records could not be
  read). The card then says last week's letter is in the book. Weeks before the
  account's first briefing record, and weeks while letters were off, are not
  missed.

The position's read
(`letter --week WEEK`) returns the lists, or `saved: true` when the letter
exists; for a short week it also returns the code-written `opening`.
Publishing `{"position":N,"letter":{"opening":"…","signoff":"…"}}`, or
`{"position":N,"letter":{"signoff":"…"}}` for a short week, saves the letter, then code publishes the card: a short notice, the counts and
an **Open letter** link. With a saved letter, or when records could not be read,
the agent publishes `{"position":N}`; the card then reuses the saved letter or
says the letter could not be written. The position is never skipped,
and the card never links to a letter that was not saved.

## Older missed weeks

From the first saved letter on, no week is left without one. When a briefing is
prepared or the Letters tab is opened, code writes the letter for each missed
week older than last week (last week waits for the next briefing), with its own
opening (“Here’s a look back at this week.”, or the short-week opening) and
sign-off (“Until the next letter.”). Weeks while letters were off are skipped:
code notes the latest week it saw them off in `letters/.off`.
