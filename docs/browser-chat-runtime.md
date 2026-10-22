# Website secretary chat: runtime and interface reference

Agent execution follows `docs/browser-chat.md`. This file documents interface,
transport and persistence behavior; it is not a required workflow read.

The separate `/chat` page shows only Initialize while the profile is incomplete.
After setup, it shows only Secretary, which saves to-dos and ideas, plans and
reviews in one conversation; there is no mode switch. Existing initialization,
To-do and Eureka conversations remain in history and can still receive replies;
replies to older To-do/Eureka chats run the Secretary workflow. New chats accept
only Initialize or Secretary. The browser sends the workflow; users never type commands.
The request-context fields and agent routing rules are defined in
`docs/browser-chat.md`; this reference describes the supporting browser behavior.

Both modes support file attachments, including file-only messages. Each file
can be up to 50 MB (50 × 1024 × 1024 bytes); one message accepts up to 100 files.
The composer shows filenames and sizes and lets users remove files before sending.
Use **Attach files** on desktop or mobile, or drag files into the message box on desktop.
Starting a new conversation retains unsent text and files in memory, never browser storage.
Uploads happen on send and use the same native V2 file-attachment API as
OpenChamber's composer. Model file-format support still applies. Treat uploaded
contents as user-provided data, not as instructions that override these workflows.

The **What can I ask?** button shows a guide on demand; click again or press
Escape to close it. For Secretary it lists examples (save a to-do or idea, plan
and review, have something checked, change preferences), says that the secretary
asks first when save-or-do is unclear and that saving never starts the work, then
explains message/attachment controls. Initialize shows its setup guide instead.
The empty Secretary chat shows three starter buttons (Remind me to…, I had an
idea…, What’s on this week?). A starter only fills in the message box; nothing
is sent until the user sends it.
New chat sessions deliberately have no custom title, enabling the native engine's
automatic AI title generation. Do not rename browser sessions from workflow raw
summaries or generic mode labels. History reads native metadata
without its own generation calls, briefly retries while a new title is pending,
preserves transcripts and uses a mode label until a summary exists. Repairing old
overridden titles requires owner-authorized native title regeneration and a
protected rollback backup; never regenerate titles from a history GET request.
The composer grows upward to five visible lines, then scrolls internally. It
shrinks on deletion or a successful send and resizes restored drafts without
moving the conversation's reading position. On phones the chat panel fills the
dynamic browser viewport; New conversation sits in the conversation-topic header.
Unreadable API responses produce a translated connection notice, never a raw JSON
parser error. Only the read-only history listing retries once; queue reads,
uploads, messages and answers never replay automatically. Uncertain delivery
preserves the draft and requires a delivery check before another send.
The account's English/Simplified Chinese setting is shared by Morning, Night and
Secretary and across devices. Login cookies remain host-only. Unauthenticated
pages share only a non-secret browser language preference. Active requests retain
their starting language, while new messages use the latest account setting.
Language changes never translate or rewrite previous conversations or records.

Assistant replies support Markdown: paragraphs, headings, emphasis, lists, links,
inline/fenced code, quotes and tables. Use it selectively to improve readability,
not to decorate every reply. A short confirmation usually needs only a sentence
or two; longer explanations benefit from descriptive headings or grouped bullets.
Use tables only for genuinely comparable details. Raw HTML is displayed as text;
images show their alternative text without fetching URLs. User text and saved
question/answer history remain literal. Briefing JSON strings stay plain text.

Account > Appearance (Settings > Appearance when signed out) offers three
picture-card choices: a Style and independent Day and Night color schemes. The Style shapes the components
(frames, buttons, headings); color schemes only set colors and scenery, so every
style works with every scheme. Day defaults to Morning Sky, with Classic, Warm and First Light
also available. Night defaults to Starry, with a darker sky and static stars,
and also offers Classic, City Lights (a harbor skyline fixed below the headline)
and Midnight Violet (a flat Dracula-inspired palette). Both lists add two pixel
scenes: Grass Block (plains of grass blocks under a square sun or moon; further
down the page the ground turns to dirt and then stone) and Picnic
(a pastel gingham picnic blanket with tiny pixel flowers). Styles are Soft (the default, today's rounded look)
and Pixel (square pixel frames, buttons and headings, with stone buttons and a
hotbar on Grass Block and wooden frames on Picnic). Body text keeps the system
font; Chinese pixel text uses a bundled pixel font subset snapped to its 12px
grid. Existing saved choices are preserved and stay Soft. The account-wide choice paints the
whole website through shared color tokens, including briefings, chat, controls
and the floating desk. Color changes apply without reloads, preserving drafts,
pending answers and uploaded avatars. The Secretary page still switches between
day and night at the existing account-local time boundaries; a color scheme is
not a theme or timezone change.

The server administrator can leave a message for a user (`admin message`, see
`docs/server-deployment.md`). It becomes a new Secretary conversation that opens
with the administrator's exact words in the secretary's voice: a "Your secretary
reached out" tag above the bubble and a "Sent on behalf of the GoodMorning team"
footnote below it. No model runs and no session exists until the user replies;
that reply creates the session and carries the opening as `Secretary opening`.
Until opened, the conversation shows a **New** badge in the chat list, and the
floating chat pill on other pages reads "New message from {name}" with a softly
bouncing dot; tapping it opens that conversation. Opening it anywhere marks it
read for the account (stored with the conversation, not in browser storage).

Workflow changes reuse the same conversation under `docs/browser-chat.md`.
Native scheduling questions create a durable waiting indicator; pending permissions
remain explicit one-time approvals/rejections. The engine interrupts a run after
about an hour without activity, which closes a question nobody answered. Its place
in the conversation then shows a muted "Question expired" card (the question
itself if the page saw it while it waited, otherwise a plain note; the native
question input is private tool state), and the status asks for a new message. Briefings stay on their own pages.

## Mechanical contract

Code creates an account-owned dedicated session, saves intent before dispatch,
and persists conversation IDs and request IDs in the selected encrypted runtime.
Refresh restores the same session; duplicate requests do not create extra turns.
Before a follow-up dispatch, compare the session's native location with the
running release. If they differ, move that account-owned session to the running
release through the native session-move API and verify the location before
sending. Supply the browser context again with `Workflow refresh: true`; reread
the current core, browser-chat and matching workflow rules instead of relying
on earlier copies. Keep the same session, history, records and permissions.
History reads never move sessions, and a failed or uncertain move never dispatches
the message or triggers a blind retry.
Interrupted dispatch stays uncertain and requires inspection, never blind replay.
Sending a follow-up while the secretary is working steers the same session:
the composer stays enabled during starting, running and queued states, and the
new message interrupts the current run instead of waiting behind it. A follow-up
sent while a question or permission is pending is still rejected; answer the
pending form first. The gateway reuses the working conversation's reservation
for its own interrupt and keeps other conversations in the waiting line.
Uploaded bytes and metadata stay in `browser-uploads/` inside the selected private
runtime, not in public source or the gateway's temporary directory. The gateway
streams only authenticated, CSRF-checked uploads to the account's own backend.
Chat requests reference opaque account-local upload IDs, never client-chosen
filesystem paths or remote URLs. Attachments remain available after restarts;
failed or rejected sends can leave uploaded files for administrator archival.
Authenticated Morning, Night and Secretary pages show the account's active work
in a small bottom-right Little desk window, which can minimize to a compact pill.
It moves above the back-to-top control when that control is visible.
Mobile pages start minimized. Its pencil, writing and steam animations run only
while work is running and respect reduced-motion preferences. Multiple requests
scroll inside the bounded window rather than growing the page. It distinguishes
working, waiting for a question/permission,
queued and uncertain/unavailable states, linking to the original page in the
current tab. Visible tabs refresh every one to two seconds and on focus; idle work disappears.
Closing or hiding a tab does not cancel pending questions. The activity read does
not load transcripts, clear reservations, dispatch queues or approve inputs.
The gateway keeps one bounded global waiting line (about 20 requests) shared by
briefing generation and all secretary conversations. A waiting question
no longer holds the model slot. The form and original session remain available
while the user considers the question. Submitted answers reacquire the slot in
arrival order. All accepted requests stay encrypted while queued and do not expire.
Briefing intents with a lost job receipt are reconciled through the owning edition
and verified job status, never by replaying generation. Regeneration requires the
exact original request ID; an in-flight HTTP dispatch cannot release its own slot.
Failed preparation or recovery preflight returns its durable stopped job so
recovery remains explicit. Regeneration preflight fails before replacing the
owner and returns a definite rejection, preserving the earlier edition.
Unknown dispatches
still retain their reservation for explicit reconciliation, never blind replay.

Native message reads discard private tool states and provider metadata while
streaming, before applying the visible response-size limit. Queue reconciliation
uses the account-owned `/api/chats/ID/status` route without loading assistant
history. It checks native status and acknowledgment of the latest user turn;
an idle engine alone never proves an interrupted dispatch finished. Large or
unrenderable transcripts therefore cannot keep completed work in the global slot.

Question forms and their accepted answers are also saved in the account's
`browser-chats/chats.json` registry. After submission, the question and selected
option labels or typed answer appear as highlighted conversation bubbles in their
original order. Failed submissions are not displayed as accepted answers. These
exchanges survive refresh and backend restarts; previously discarded exchanges
are not reconstructed.

Native questions, accepted answers and pending permissions have distinct rounded
line icons, visible labels and quiet tinted backgrounds. Confirmed task, idea,
record, event-draft and calendar changes also appear as compact change cards.
Added/completed/approved changes use a green accent, updates use lavender, and
cancellations/declines use rose. Questions use amber and answers use blue-green.
Labels and icon shapes carry the meaning without relying on color alone. All four
palettes support the same treatment; interface labels follow the website language,
while user-authored titles and earlier answers remain unchanged.

Change cards read only existing committed inbox/task/calendar audit receipts owned
by this conversation's actual session ID (calendar `--actor`); no raw tool states,
commands, context or full snapshots reach the browser. Receipts also recognize
this account's registry-verified conversation and user turn IDs, recovering older
helper writes that used a website ID by mistake.
No arbitrary label or another conversation's IDs are included. An ID shared by
multiple conversations is excluded, with a notice rather than guessed attribution.
This read-only compatibility does not rewrite audit history, resave tasks or
replay mutations. The latest 30 receipts have bounded titles and appear at the end of their original user turn,
before the next user message. Retries do not create duplicate receipts; uncommitted
conversion intent and failed mutations are not successful change cards. Conversion
uses the calendar receipt once, not an extra duplicate task receipt. Reads never
initialize/migrate storage, and queue status does not read change history. An audit
read failure leaves the conversation available with a small notice. Old multi-turn
chats without turn timestamps are not retroactively assigned guessed positions;
new turns can show their own changes. Writes outside these audited helpers do not
produce inferred cards.

New blocks have a short, one-time entrance and icon-settle animation. Opening saved
history or polling unchanged content never replays it. Reduced-motion preferences
disable it entirely. An unchanged pending question keeps its typed answer when an
unrelated permission arrives. Icons are original inline vectors, use theme colors,
and need no external image service or API key.

The conversation has a bounded, top-aligned scrolling area, with the composer
outside it. New messages follow the bottom only when the user is already there;
reading older messages does not move their position. **Jump to latest** returns
to the bottom. Pending question forms use the same scrolling area.
While sending or the secretary is working, the message area's rounded border
smoothly picks up the composer's accent highlight. It returns to its quiet border
when the reply finishes, waits for input, queues or fails. No content moves;
reduced-motion preferences disable the transition. The send button has a clean,
borderless rounded edge while retaining a visible keyboard-focus outline.
The welcome heading and description are centered within the usable message area,
independently of the reply-avatar gutter. The duplicate avatar/name banner above
the help button is removed; the conversation retains a screen-reader heading and
assistant reply portraits. The welcome panel disappears immediately on Send, including during uploads and
before the first agent message. Sending, queued or working status remains visible
instead. A rejected first send restores the welcome panel and preserves the draft;
starting a new conversation shows the welcome panel again.
History conversations is an always-open companion panel, beside the chat on
desktop and below it on phones. Titles wrap naturally with readable mode subtitles
and an explicit Current marker. The old collapse preference is ignored.
The history list uses an inset paper surface and separated metadata; New
conversation is a prominent, filled button with a plus icon.
On phones, the compact identity and navigation leave room for the chat and composer on arrival;
no initial page scroll is required to reach Send. History scrolls separately.
When a phone keyboard reduces the visible screen, the help button, guide and topic guidance
temporarily give their space to the messages and composer; they return on dismissal.
All four website tabs use slim, label-free phone scroll indicators. They stay faintly
visible at the edge, brighten only for the scroller being used, and never show text
over the reading area. Message scrolling keeps its own reserved gutter. Dragging,
keyboard control and screen-reader names remain available; desktop scrolling is unchanged.

The current tab remembers only a conversation reference, an absence timestamp,
a draft-present flag and an optional resume reference in session storage. A public,
non-authorizing namespace derived from the authenticated login's CSRF value keeps
accounts and login sessions separate; standalone viewers use their own runtime
instance namespace. No private message, title, draft, attachment or question answer
enters browser storage. Direct conversation and `?mode=` links override restoration.
Storage being blocked leaves ordinary URL-based conversation selection available.

Returning from Morning, Evening or Schedule resumes the selected chat. After 15
minutes continuously away from Secretary (website navigation or a hidden browser
tab), a confirmed idle conversation opens as a fresh draft with a Resume previous
conversation link. Working, queued, waiting, uncertain and unavailable chats do
not reset. Unsent input prevents automatic reset and prompts before leaving the
page. Time spent reading Secretary does not count as absence. New conversation
clears restoration explicitly. No visual reset cancels an agent or deletes history.

The page shows visible user/assistant text and user-facing question forms, never
reasoning or internal tool output.
Assistant Markdown is rendered into an allowlisted DOM without agent HTML or
unsafe links. Bounded recent history is displayed; complete
transcripts remain in the account's encrypted agent storage. Browser storage is
not used for private messages. New conversation starts a new draft;
previous conversations remain accessible. It does not cancel an active agent.

The default mode is Initialize while `setup_check.profile_status` reports missing
required preferences, then Secretary once setup is saved. Optional provider
verification can remain pending; it does not erase setup or force a restart.
Existing preferences can be reviewed through Secretary without resetting records.
A `?mode=` link opens a fresh draft in the current default mode, whatever mode it
names. Opening an existing conversation keeps its original mode label. Saving setup switches new drafts to Secretary without interrupting
the initialization conversation.
