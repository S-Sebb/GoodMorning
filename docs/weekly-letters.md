# Weekly letters

A weekly letter looks back on one Monday–Sunday week. Preparing Sunday's
evening briefing writes it; nothing runs on its own. The **Letters** tab at
`/letters` opens the newest saved letter, whenever it was written, and
`/letters/WEEK` (the week's Monday) opens one week's. Beside the letter (above
it on phones) a wheel lists every saved week, newest first: scrolling, tapping
or the arrow keys turn it, and the week left in the middle opens in place
(`assets/web/letters.js`); without scripts the wheel is a list of links.
Letters are a memory book: once saved, a letter never changes, even when its
records change later or the briefing is regenerated.

## Contents

Code (`src/goodmorning/records/letters.py`) builds every list from saved
records. The secretary writes only a short opening and a one-line sign-off from
those lists, in the job's website language and saved tone. When a week has
nothing finished, no habits and no ideas, code writes the opening (“This week’s
letter is a short one.”) so a quiet week is never judged, and the secretary
writes only the sign-off.

- **What you finished:** task occurrences confirmed done that week, plus one-off
  tasks whose done confirmation falls in the week (account timezone). Grouped by
  project in the order they were finished; repeats show a count. Nudges, errands
  and reference notes never appear.
- **Habits:** habits with at least one confirmed completion that week: times this
  week and the number of weeks in a row with at least one completion (shown from
  2). A habit with a quiet week is left out; a broken run is never mentioned.
- **Ideas you saved:** ideas captured that week.
- **Coming up next week:** appointments (once, on their start day), confirmed
  appointments with time to be confirmed, hard deadlines, and how many planned
  tasks the week holds. Habit projections are left out. A failed calendar or
  task read is noted, never shown as an empty week.

Empty parts are left out. Saved files are `letters/WEEK.json` in the runtime.

## Sunday's evening briefing

On a Sunday briefing day (04:00 rollover), the evening plan ends with a
**Weekly letter** position unless the profile sets `weekly_letter: "false"`; the
secretary changes it when the user asks to stop or resume. The position's read
(`letter --week WEEK`) returns the lists, or `saved: true` when the letter
exists; for a short week it also returns the code-written `opening`.
Publishing `{"position":N,"letter":{"opening":"…","signoff":"…"}}`, or
`{"position":N,"letter":{"signoff":"…"}}` for a short week, saves the letter, then code publishes the card: a short notice, the counts and
an **Open letter** link. With a saved letter, or when records could not be read,
the agent publishes `{"position":N}`; the card then reuses the saved letter or
says this week's letter could not be written. The position is never skipped,
and the card never links to a letter that was not saved.
