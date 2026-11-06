# Secretary memory

The secretary keeps one short note about the user, the way a friend remembers
things as you keep talking, and uses it in every Secretary conversation, in
evening greetings and openings, morning openings and closings (only for something dated
today or tomorrow) and in the weekly letter's sign-off. The agent
rules are in `docs/workflows/secretary.md`, *Memory*; briefing use is in
`docs/browser-generation.md`.

## What it holds

One note in the secretary's words, written to the user in three parts: `life`
(their life, people, pets, home, work and interests), `likes` (how they like
things) and `lately` (what is going on for them now), plus `projects`: one entry
per project the user works on, at most 8, each at most 500 characters, saying what
it is, where it stands and what comes next. The whole note with its projects holds
at most 4,000 characters, about 1,200 tokens. The secretary writes what the user says
or plainly shows about themselves and patterns in their records, never its own
guesses about mood or personality, and keeps sensitive topics out unless the user
asks it to remember them. A `lately` item about something coming up keeps its date,
so briefings never speak of it as past and the evening tidy can drop it once it is
over. The note is never a permission, a setting or a source of facts for other
records.

## Projects

A project's name is its to-dos' `project` label, matched ignoring case and
spacing. A project starts in chat, or when a to-do first carries a new label: code
then adds an empty entry while memory is on and has room. Renaming a project in chat
(`task --rename-project`) renames its to-dos and its entry together. A finished
project's entry is dropped, with no archive; forgetting a project deletes its entry
only, and its to-dos keep their label. Dated milestones are allowed and drop out
once past. The morning and evening Tasks note may borrow an entry's wording, never
its facts. Projects used to be profile lines (`## Project roots`, a name and a
folder the secretary could not open), `projects/*.md` records and `projects.json`;
nothing reads them any more. `deploy/migrate_project_memory.py` moves them into
memory once per account and removes them after a backup (`SERVER-DATA-GUIDE.md`).

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
  agent adds what chats missed, updates project entries (to-do lines carry
  their project as `[project: NAME]`) and patterns that repeat on at least two
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

`RUNTIME/memory.json` holds `enabled`, `revision`, `note`, `projects` (a list
of `name`, `note` and `updated`; a file without it has none), `updated` (the
briefing day of the last change), `tidied` (when the evening tidy last read
chats) and `changes` (session and time only, no text). It lives in the account's
private runtime, inside that account's encrypted vault and readable only by its
own services. Every change goes through `src/goodmorning/records/memory.py`,
checks the revision, holds `memory.lock` and replaces the file atomically.

On About me, under **What I remember about you** (我记得的关于你的事), the user
reads the note part by part, then each project with its open to-dos, edits or
empties any part, edits or forgets one project, starts a new one through **Ask**
(chat), or switches memory off; no single button forgets the whole note. Unlike
other records, forgotten text is deleted, not cancelled; vault backups keep it
until they rotate out. Memory is on by default; when off, nothing is written,
tidied or used, and the note stays until the user empties it.
