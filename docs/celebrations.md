# Celebrations

On a special day the briefing opens with one **Something to celebrate** card.
Celebrations are always on; there is no setting to turn them off. Code
(`src/goodmorning/records/celebrations.py`) finds them from saved records when a
briefing job is prepared, and the page words every fact in the website language.

## What is celebrated

- **Birthday:** the profile's optional `birthday: "MM-DD"` (month and day only;
  no year or age). On non-leap years, 29 February is celebrated on 28 February.
  An empty or unreadable value shows nothing. Setup asks for it (optional),
  and the user can set or clear it in chat or on the About me page, under What
  you call each other. Other people's birthdays stay calendar occasions
  (`docs/item-taxonomy.md`).
- **Festivals:** a festive public holiday in the regions the user follows
  (`holiday_countries`, `docs/calendar-pipeline.md`): New Year's Day, Spring
  Festival, Dragon Boat Festival, Mid-Autumn Festival, National Day, Labor Day
  and Christmas Day, keyed by the holiday's `key` in `FESTIVALS`. Other public
  holidays, make-up workdays and the rest of a break get no card; a festival
  with several days off under one name (National Day) is greeted on its first
  day. The line names the countries that have it off.
- **GoodMorning anniversaries:** 100 days after the first saved briefing, then
  every year on its date. The first briefing is the earliest
  `daily/DATE.gm|gn.json|md` edition, so no start date is stored.
- **Finished-task milestones:** 100, 250, 500 and 1,000 tasks done, then every
  1,000, counted as the weekly letter counts finished work (confirmed
  completions only). Each milestone shows once, on the first briefing after it
  is reached; the highest one reached is shown and smaller ones passed with it
  never show. `celebrations.json` in the runtime keeps the day each one first
  showed, so regenerating that day's briefing shows it again.

## Where it shows

The card is the first section of the morning briefing. The evening briefing
carries it only when no morning briefing was saved that day. Several
celebrations on one day share the card. Nothing is shown in chat, on the
Schedule page or as a notification.

## Wording

Code writes each headline and factual line (“Happy Mid-Autumn Festival! 🌕” /
“Today is a public holiday in China.”) and never
uses the user's name. The secretary writes one short wish in the saved tone,
speaking as itself (“I”, never “we” or the GoodMorning team); code signs it with
`secretary_name` when one is saved.

## The briefing step

The plan's first position is `celebration`. Its receipt lists `celebrations`
(each `headline` and `line`, already worded) and asks for
`{"position":0,"celebration":{"wish":"…"}}`. Code builds the section
`["celebration",[["celebration",items,wish,secretary_name]]]`, records any
milestone as shown, and never lets the step be skipped.
