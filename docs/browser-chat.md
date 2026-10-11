# Website secretary conversations

The separate `/chat` page has four modes: Initialize, Secretary, To-do and Eureka.
The browser sends the selected workflow; users never need to type commands.
The first message supplies only the workflow, browser conversation ID, selected
runtime, website language, and user text. Every later turn also supplies its
website language. Keep the configured model and current session. Never
delegate. Read `docs/core-rules.md` and the matching workflow, as for local use.

- **Initialize** (`/initialize`): follow `docs/workflows/secretary.md` and
  `docs/initialization.md`. Ask for the secretary's display name first
  (`secretary_name`, optional, 1-30 characters); allow skipping and reuse the
  saved spelling for self-reference and website greetings. Use the supplied website language; never ask for a
  separate agent/reply language. Show it as controlled by the website switch.
  Leave any existing local `secretary_language` field unchanged. For an existing
  profile, review **all other** preferences in small related groups,
  showing current values and offering to retain them. Ask only once per setting;
  preserve answers already confirmed in this conversation. Change only explicitly
  confirmed values. Never reset briefings, tasks, ideas, calendar records or access
  permissions. This is profile setup, not account registration or password recovery.
- **Secretary** (`/secretary`): normal authorized secretary work. Follow existing
  storage, calendar, project-access and confirmation rules. Setup failures are not
  permission to repair integrations or develop code.
- **To-do** (`/todo`) and **Eureka** (`/eureka`): capture only. Save using the existing
  fast helper, confirm the actual save and stop. A capture is not execution consent.
  Pass `--website-language CODE` to `workflow --capture` and preparation helpers.
  Use the same flag for `setup` readiness checks. It supplies reply language
  without writing a profile field or guessing from country/user text.

The page explains the four modes: Secretary discusses and plans, To-do records a
task, Eureka records an idea, and Initialize sets up or reviews preferences.
The account's English/Simplified Chinese setting is shared by Morning, Night and
Secretary and across devices. Login cookies remain host-only. Unauthenticated
pages share only a non-secret browser language preference. Active requests retain
their starting language, while new messages use the latest account setting.
Language changes never translate or rewrite previous conversations or records.

Conversation continuations stay within the selected mode. If the user wants
another mode, direct them to the mode switch. Briefing generation remains on the
Morning/Evening pages; never generate `/gm` or `/gn` inside these conversations.

Use browser-supported question fields for missing answers, especially setup:
strings, dates, booleans, numbers and choice lists with real options/custom text.
If a plain conversational question is sufficient, ask and wait for the next user
reply. Never invent consent or answer your own questions. Permission requests
remain explicit one-time approvals or rejections. Do not ask for passwords, keys,
pairing credentials or protected joining links in chat.

## Mechanical contract

Code creates an account-owned dedicated session, saves intent before dispatch,
and persists conversation IDs and request IDs in the selected encrypted runtime.
Refresh restores the same session; duplicate requests do not create extra turns.
Interrupted dispatch stays uncertain and requires inspection, never blind replay.
The gateway keeps one bounded global waiting line (about 20 requests) shared by
briefing generation and all secretary conversations. A waiting question retains
its reservation until the owning session becomes idle, and queued requests wait
behind it in arrival order without concurrent dispatch.

The page reads only visible user/assistant text, never reasoning or tool output.
Text is rendered without agent HTML. Bounded recent history is displayed; complete
transcripts remain in the account's encrypted agent storage. Browser storage is
not used for private messages. Switching modes starts a new draft conversation;
previous conversations remain accessible. It does not cancel an active agent.

The default mode is Initialize while `setup_check.profile_status` reports missing
required preferences, then Secretary once setup is saved. Optional provider
verification can remain pending; it does not erase setup or force a restart.
Existing setup can always be reviewed again through Initialize.
