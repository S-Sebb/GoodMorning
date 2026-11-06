# Secretary memory

The secretary keeps one short note about the user, the way a friend remembers
things as you keep talking, and uses it in every Secretary conversation, in
evening greetings, morning openings and closings (only for something dated
today or tomorrow) and in the weekly letter's sign-off. The agent
rules are in `docs/workflows/secretary.md`, *Memory*; briefing use is in
`docs/browser-generation.md`.

## What it holds

One note in the secretary's words, written to the user in three parts: `life`
(their life, people, pets, home, work and interests), `likes` (how they like
things) and `lately` (what is going on for them now). The whole note holds at
most 2,000 characters, about 600 tokens. The secretary writes what the user says
or plainly shows about themselves and patterns in their records, never its own
guesses about mood or personality, and keeps sensitive topics out unless the user
asks it to remember them. A `lately` item about something coming up keeps its date,
so briefings never speak of it as past and the evening tidy can drop it once it is
over. The note is never a permission, a setting or a source of facts for other
records.

## How it grows

- **In chat**, the secretary rewrites the parts it changes before its reply ends
  (`memory --write`), merging and trimming instead of appending. The chat then
  shows a small “Jotted down a little note about you” marker that links to About me: the store keeps
  the last 30 writing sessions, and `src/goodmorning/web/chat_actions.py` shows
  the marker in that conversation only.
- **After an evening briefing is saved** (not a regeneration), the finish receipt
  carries the note, the user's own chat messages since the last tidy (at most
  40, 500 characters each, from `browser-chats/chats.json`; never the
  secretary's replies) and `activity`: the last 14 days of check-in answers and
  changes to to-dos, ideas and habits, one dated line each (newest 80). The
  agent adds what chats missed and patterns that repeat on at least two
  different days (“You usually plan your workouts on Mondays.”), drops `lately`
  items that are over and writes once. Marking a tidy does not change the
  note's revision; `memory.activity` in `src/goodmorning/records/memory.py`
  builds the lines.

Both use the same rules for what is worth remembering (`docs/workflows/secretary.md`,
*Memory*, step 2): lasting facts about the user's life and people, how they like
things, patterns across days, and what is going on for them now. A single to-do,
idea, appointment, habit, deadline or completion stays in its record; the note
keeps at most the goal or pattern behind it.

## Storage and privacy

`RUNTIME/memory.json` holds `enabled`, `revision`, `note`, `updated` (the
briefing day of the last change), `tidied` (when the evening tidy last read
chats) and `changes` (session and time only, no text). It lives in the account's
private runtime, inside that account's encrypted vault and readable only by its
own services. Every change goes through `src/goodmorning/records/memory.py`,
checks the revision, holds `memory.lock` and replaces the file atomically.

On About me, under **What I remember about you** (我记得的关于你的事), the user
reads the note part by part, edits any part, switches
memory off or uses **Forget everything**. Unlike other records, forgotten text is
deleted, not cancelled; vault backups keep it until they rotate out. Memory is on
by default; when off, nothing is written, tidied or used, and the note stays
until the user forgets it.
