# Website secretary conversations

The separate `/chat` page has four modes: Initialize, Secretary, To-do and Eureka.
The browser sends the selected workflow; users never need to type commands.
The first message supplies only the workflow, browser conversation ID, selected
runtime, and user text. Keep the configured model and current session. Never
delegate. Read `docs/core-rules.md` and the matching workflow, as for local use.

- **Initialize** (`/initialize`): follow `docs/workflows/secretary.md` and
  `docs/initialization.md`. For a new profile, ask reply language alone first.
  For an existing profile, review **all** preferences in small related groups,
  showing current values and offering to retain them. Ask only once per setting;
  preserve answers already confirmed in this conversation. Change only explicitly
  confirmed values. Never reset briefings, tasks, ideas, calendar records or access
  permissions. This is profile setup, not account registration or password recovery.
- **Secretary** (`/secretary`): normal authorized secretary work. Follow existing
  storage, calendar, project-access and confirmation rules. Setup failures are not
  permission to repair integrations or develop code.
- **To-do** (`/todo`) and **Eureka** (`/eureka`): capture only. Save using the existing
  fast helper, confirm the actual save and stop. A capture is not execution consent.

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
The gateway shares the global agent reservation with briefing generation. A
waiting question retains its reservation until the owning session becomes idle.

The page reads only visible user/assistant text, never reasoning or tool output.
Text is rendered without agent HTML. Bounded recent history is displayed; complete
transcripts remain in the account's encrypted agent storage. Browser storage is
not used for private messages. Switching modes starts a new draft conversation;
previous conversations remain accessible. It does not cancel an active agent.

The default mode is Initialize while `setup_check.profile_status` reports missing
required preferences, then Secretary once setup is saved. Optional provider
verification can remain pending; it does not erase setup or force a restart.
Existing setup can always be reviewed again through Initialize.
