# Secretary memory

The secretary keeps one short note about the user, the way a friend remembers
things as you keep talking, and uses it in every Secretary conversation, in
briefing greetings and closings and in the weekly letter's sign-off. The agent
rules are in `docs/workflows/secretary.md`, *Memory*; briefing use is in
`docs/browser-generation.md`.

## What it holds

One note in the secretary's words, written to the user in three parts: `life`
(their life, people, pets, home, work and interests), `likes` (how they like
things) and `lately` (what is going on for them now). The whole note holds at
most 2,000 characters, about 600 tokens. The secretary writes what the user says
or plainly shows about themselves, never its own guesses about mood or
personality, and keeps sensitive topics out unless the user asks it to remember
them. The note is never a permission, a setting or a source of facts for other
records.

## How it grows

- **In chat**, the secretary rewrites the parts it changes before its reply ends
  (`memory --write`), merging and trimming instead of appending. The chat then
  shows a small “Jotted down a little note about you” marker that links to About me: the store keeps
  the last 30 writing sessions, and `src/goodmorning/web/chat_actions.py` shows
  the marker in that conversation only.
- **After an evening briefing is saved** (not a regeneration), the finish receipt
  carries the note and the user's own chat messages since the last tidy (at most
  40, 500 characters each, from `browser-chats/chats.json`; never the
  secretary's replies). The agent adds what chats missed, takes in tonight's
  check-in answers, drops `lately` items that are over and writes once. Marking
  a tidy does not change the note's revision.

## Storage and privacy

`RUNTIME/memory.json` holds `enabled`, `revision`, `note`, `updated` (the
briefing day of the last change), `tidied` (when the evening tidy last read
chats) and `changes` (session and time only, no text). It lives in the account's
private runtime, inside that account's encrypted vault and readable only by its
own services. Every change goes through `src/goodmorning/records/memory.py`,
checks the revision, holds `memory.lock` and replaces the file atomically.

On About me the user reads the note part by part, edits any part, switches
memory off or uses **Forget everything**. Unlike other records, forgotten text is
deleted, not cancelled; vault backups keep it until they rotate out. Memory is on
by default; when off, nothing is written, tidied or used, and the note stays
until the user forgets it.
