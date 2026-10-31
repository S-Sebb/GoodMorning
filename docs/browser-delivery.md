# Browser briefings

GoodMorning and GoodNight use validated native JSON only. The viewer renders
selectable HTML with clickable citations, typed weather/news/agenda/task sections,
a section minimap and reading progress. It never exports dated webpages or reads
Markdown briefings and presentation sidecars. Profiles, projects and daily work
records still use Markdown; inbox and calendar storage use SQLite.

Browser tabs use sun, moon and notebook icons for Morning, Night and Secretary.
SVG originals and 32px PNG fallbacks are in `assets/web/icons/`. Login, password,
initialization, missing, unfinished and saved pages use the corresponding icon.
Only fixed public assets are available without authentication.

## Local viewer

```sh
python scripts/goodmorning.py serve \
  --secretary-dir /home/YOU/.local/share/GoodMorning/secretary --port 8765
```

The local viewer is for read-only browsing of saved records; generation and chat
run only on the hosted website, where each account has its own engine. Local
serving is loopback only; public HTTPS deployment requires `docs/website-security.md`.

`/gm` and `/gn` select the current briefing day. The day changes at
04:00 in the saved timezone, including daylight-saving changes. A seven-day
selector shows saved and missing editions. `/d/DATE/gm` and `/d/DATE/gn`
pin an archive date. The earlier `.html` addresses of these pages and of the
offline copies answer with a permanent redirect (308) to the clean address,
keeping the query, so bookmarks, installed apps and old notifications still work. Archive visits never launch a model; missing past editions
remain read-only. The page rechecks the day on focus and each visible minute,
preserving the selected edition and pinned archives.

Saved data is available at `/d/DATE/gm.json` or `/d/DATE/gn.json`. Invalid formats
remain untouched and are not reported ready. Internal bookkeeping IDs are hidden
in visible text, without changing saved data or citation destinations.

## Explicit generation and chat

Today's missing edition offers a preparation button. It creates a dedicated
OpenCode session using automatic website-language routing: English and Chinese
both use DeepSeek V4.1 Flash High (paid tier).
There is no manual model selector. The model is pinned per briefing job and per
chat turn before any prompt is sent. Duplicate clicks reuse
the durable date/edition job. Uncertain dispatches are never replayed blindly.
Questions and permissions belong only to that session; the viewer is not an
arbitrary session browser or API proxy. Permissions require explicit one-time
approval or rejection. Host, Origin, body limits and a server-generated request
token protect mutations.

Browser authoring follows the job receipts (`docs/browser-generation.md`): prepare once, initialize
the plan, then collect and publish one new section at a time. Code owns the
cumulative document, visible checklist synchronization and final save. Published
sections remain readable and unchanged while later sections are prepared.
Only the next unresolved section animates; questions and permissions pause it.
Progress counts resolved sections, not elapsed time or model claims.

Refresh restores the same job, preview and questions without launching another
session. Status updates preserve answer drafts. Only new section patches transfer
after a checkpoint changes. A matching final save marks completion; unfinished
or failed previews never imply a completed run or task.

`/chat` is separate: Initialize before setup, then Secretary for everything,
including to-dos and ideas. Initialize reviews all saved preferences without
resetting records. Drafts and previous conversations remain available; refresh resumes the selected chat.
Chat places no private text in persistent browser storage. See `docs/browser-chat.md`.

## Images, resources and storage

Native rendering uses the Python standard library. Pillow supports optional
publisher previews. Image requests need explicit authorization and never run
merely because a page is viewed. To cache previews for a saved edition:

```sh
python scripts/goodmorning.py web --secretary-dir RUNTIME --date DATE --fetch-images
```

This writes image objects, manifests and the URL catalog only. Successful images
are checked and deduplicated; failures retain honest placeholders and retry after
one hour. Private-network destinations, credentials, oversized payloads and unsafe
redirects are refused. Responsive thumbnails stay in bounded memory, not on disk.

The article page's first `og:image` (else `twitter:image`) is preferred. When the
page has none or refuses the request, the image the news feed itself named for
that article (`media:content`, image enclosure, `media:thumbnail`, or an inline
`<img>` other than a tracking pixel) is used instead, read from the news archive.
A host that stalls or answers 403/429 is not asked again in the same run.
Requests send a browser User-Agent because NPR and CBC stall all others; they
still carry no cookies. Non-ASCII article URLs are percent-encoded and GBK pages
are decoded by their declared charset. Pages without any preview metadata, such
as chinanews.com.cn and solidot.org, and plain-HTTP articles keep placeholders.

CSS, JavaScript, fonts and icons are shared, fingerprinted assets with immutable
caching, conditional requests and HEAD support. Private HTML, JSON, questions and
API responses remain `no-store`. Pages containing generation request tokens are
not compressed. Images use private browser caching.

Viewer caches are capped at 14 editions / 16 MiB, 128 images / 4 MiB and 128
thumbnails / 2 MiB. These do not bound total process memory or retained history.
Saved assembled pages have a separate 14-page / 8 MiB memory cache. File identity,
mtime, ctime, image manifests, week availability, language, and archive selection
invalidate it immediately. The gateway caches final HTML in 32 entries / 8 MiB,
bound to account, host, path, language, session CSRF, and backend content. Every
request is authenticated before lookup; private responses remain `no-store`.
Viewing checks only the selected day and seven-day navigation window. There is no
automatic deletion policy for private records, preferences, images or job recovery.

Reduced motion is respected; saved content and source links remain readable
without JavaScript. Restart for renderer/backend changes; saved JSON and image
manifest changes refresh without a restart.

Open tabs check a public release fingerprint on load, focus and each visible
minute. The fingerprint detects changed deployments; a separate readable
`0.minor.patch` version identifies each beta release. `/api/release` supplies
the current version and the complete bilingual history from
`assets/web/patch-notes.json`. Each release uses category headings and real bullet
lists in both languages; older open tabs receive a plain-text summary derived
from the same categorized data.

Signed-in accounts automatically see the patch-note dialog for each version
until dismissed, including on first visits and ordinary refreshes. Dismissals
are stored per account in the encrypted account database and shared across
hosts and devices, not in browser storage. The private local viewer stores the
same preference in its isolated runtime's `release-seen.json`. Guests can open
the public history manually; automatic display starts after sign-in, when the
site can identify the person. `/api/release/seen` is private and `no-store`;
its writes require authentication, same-origin requests and CSRF protection.

A persistent blue upward-arrow button opens the dialog when the page has an
available update. It becomes a checkmark when the page is current and still
opens history. The dialog has a version sidebar, an Update button for stale
pages, and a Dismiss button. Dismissing keeps the arrow available. Reading old
notes does not install old code. Update never reloads automatically, pauses
while a mutation is being sent and asks before discarding unsent drafts. Of those
drafts, only evening check-in answers are kept in browser storage; see
`docs/website-security.md`. Public auth/update assets are
fingerprinted, immutable and precompressed; their unversioned aliases revalidate.
Tabs opened before this feature was installed need one manual refresh first.

Chat history reads bounded native V2 pages of at most 200 raw records, retaining
the latest 100 visible messages (more on request, up to 1,000) and reporting
whether earlier ones exist, so a long chat never loads its whole history. Pending input and uncertain delivery still retain the global busy flag.

## Installed app

Private pages link a web app manifest, so a browser can install the site. The
Android app shows it in its own WebView. `/.well-known/assetlinks.json` vouches
for the app package `me.love765.goodmorning` and its release-key fingerprint:
the app's server picker accepts only a server that serves it, and Android opens
the default server's links in the app. Every server running this source serves
it, so the app can connect to any of them. The app starts at `/app`, and pages it opens for widgets and
notifications go through `/app?next=<page>`. Inside the installed app, `app.js`
saves the current page path in the `GoodMorningAppPage` cookie, and `/app`
redirects to `next` when it is a page route, otherwise to that saved path when it
is one, otherwise to `/chat`. Sign-in inside the app also continues to `/app`. The
cookie holds only a path, never page content. The app also adds `app=<build>`,
which `/app` keeps in the `GoodMorningApp` cookie so the update pill can offer
the app's own updates (`docs/android-app.md`, Updates).

Browsers withhold `SameSite=Strict` cookies, the login cookie included, when
another app opens a page, as Chrome did for app versions before 0.8. Without a login cookie, `/app` therefore answers with a
page that refreshes once to `/app?b=1`: that same-site step sends the cookie, so a
remembered sign-in survives closing the app. Only a request that still has no
session after this step goes to `/login`.

## Offline reading

Signed-in pages register `/sw.js` (`app.js`), in browsers and in the Android
app's WebView. After each page load the worker refreshes two read-only copies,
`/offline/gm` and `/offline/gn`: the latest saved morning and evening
edition of the seven-day window, with the stylesheets, scripts, icons and images
they name and the fonts and pictures those stylesheets name. An unchanged copy costs a 304 (the gateway's ETag). A copy has no
request token, form, chat, week picker or account control, and the gateway adds
none. While the newest edition awaits its check after regeneration the backend
answers 503 and the device keeps its copy; with nothing saved that week it
answers 404 and the device drops it.

Page loads go to the network first. Only when that fails, or the server answers
502, 503 or 504 (NGINX while the gateway is stopped, a deployment pause, an
unavailable secretary), does the worker answer with a copy: the requested edition
on briefing pages, otherwise the morning from 04:00 until 17:00 in the account's
timezone and the evening otherwise, or whichever it has. Each copy names that
timezone and its edition's day. The copy starts with "You’re offline · showing
the version from HH:MM", or "GoodMorning can’t be reached right now · …" when the
server answered, giving the time the edition was saved in the account's timezone.
The date is added unless the edition is the account's current briefing day (the
04:00 rollover in the account's timezone; the device's timezone and date play no
part). A Try again link reloads the page. Edition links switch between the two
copies. With no copy the failure shows as before: the error page, or the Android
app's can't-connect screen. Online, other requests are untouched; when the page
loads fail, the copies' own files come from the cache too.

The copies belong to one account. The gateway tags them with an opaque owner tag
(`X-GoodMorning-Owner`, a hash of the account ID), and the worker keeps them in a
cache named after it. Signing out deletes that cache (`auth.js`). The worker
deletes it too when a refresh is redirected to sign-in or the password page, is
refused, or answers for another account, so a session that ended without
signing out is forgotten the next time the device is online. Until then the copy
stays readable offline. Nothing from `/api/` or the sign-in pages is kept.

## Settings and Account

Signed in, the two top menus split by scope. **Settings** holds what belongs to
this device: its appearance and, where they can work (a browser with Web Push,
or the Android app), its notifications. **Account** holds what follows the owner
everywhere: website language, linked phones, devices with notifications, Change
password and Sign out. Without a sign-in (the sign-in page, a local viewer)
language stays in Settings too.

Appearance (style, day and night color schemes) lives in the
`GoodMorningAppearance` cookie (`style.day.night`, one year, shared by the
hosts' common parent domain like the language cookie), so every browser keeps its
own. A device without that cookie uses the account's earlier saved choice, from
when appearance followed the account; nothing writes that choice any more.
Signed out, a device without the cookie falls back to the older
`GoodMorningDayScheme` cookie, then to the defaults. A local install keeps one
choice in its runtime (`website-color-schemes.json`).

The Android app opens `/app?link=<id>` once linked. If that link belongs to the
signed-in account, the site sets the HttpOnly `GoodMorningLink` cookie and copies
this device's appearance to the link, or, when this view has not chosen colors
yet but the link has, gives the view the link's colors; later appearance changes on that device
update the link too, and `/api/app/sync` returns it so the phone's widgets match.
A link that has none yet gets the account's earlier choice.
Inside the linked app (its user agent names the link), Settings also shows the
widget theme: by the clock (the default), with the phone's dark mode, or always
day or night (`POST /api/app/widgets`). It is kept on the link and returned as
`appearance.widgets` in `/api/app/sync`; see `docs/android-app.md`.

## Notifications

Settings → Notifications belongs to the device it is shown on. In a browser,
turning it on asks for permission and subscribes that browser, through the
service worker (`/sw.js`, see Offline reading), under a name such as "Firefox on
Linux". Turning it off, or signing out, unsubscribes it. Each
device keeps its own switches, event reminder lead time (5, 10, 15, 30 or 60
minutes; 15 by default) and briefing reminder times (07:00 and 21:00 by default). Devices that subscribed before choices moved to devices
start from the account-wide choices saved then.

In the Android app, the app posts notifications itself: usually within a few
minutes, while the account's work runs (`busy` below), or within about 15
minutes otherwise. The app names its link in its
user agent (`GoodMorningLink/<id>`, from app 0.2), so Settings there edits that
linked phone's choices, and the phone's summary returns only those kinds.

Account → Devices with notifications lists every subscribed browser and every
linked phone that posts its own notifications, each with Turn off, so a lost or
unused device can be stopped from anywhere. Subscription endpoints stay on the
server; pages see only a short name derived from them.

| Switch | Sent when |
|---|---|
| A briefing is ready | A reserved briefing job becomes ready, or stops without finishing |
| My secretary needs my answer | A briefing or chat waits for a question or permission; the text shows the first question or the requested action |
| A chat reply is finished | A chat turn becomes idle; the text is the start of the reply |
| An event is about to start | A timed calendar event starts within the lead time; all-day and unconfirmed (TBC) events are skipped |
| Remind me to prepare a briefing: Morning / Evening briefing | At the device's time, today's edition is not prepared, queued or being prepared |

The gateway notices the first three in its five-second reservation check
(`reconcile_ticket`); each transition is announced once. For reminders, it reads
`/api/reminders` from each opted-in account's own backend every five minutes.
That endpoint lists the timed events starting in the next three hours. Each
device gets each reminder once, at its own lead time.

Briefing reminders read `/api/briefing-reminders` (today's briefing day, which
editions exist, and the reminder lines) from the account's backend every five
minutes, and once more just before sending. Each device gets each edition's
reminder at most once per briefing day, within an hour of its time; a time
before 04:00 belongs to the night after that day. The gateway only reaches these
routes itself: browsers get 403. The text is one of three lines per edition the
secretary writes in the saved tone and website language
(`web/briefing_reminders.py`, kept in the runtime's `reminder-lines.json`),
rotated by day. A changed tone, user name or website language asks for new lines
through the shared model line, like any other model work; until they are saved,
or for six hours after a failed attempt, built-in lines remind instead. The
reminder shares the ready notification's tag, so a briefing prepared later
replaces it.

While a GoodMorning window is focused,
the worker shows only event and briefing reminders, because the page already shows everything
else. Notification text uses the account's website language. A tap opens the
related chat, briefing or day schedule.

Android app versions before 0.8 used Chrome where they could, and subscribed
Chrome to Web Push there. Such a subscription, made inside the app, records the
phone's link (from the `GoodMorningLink` cookie; `app.js` subscribes again to add
it). When that phone's app first reports that it posts notifications itself,
the gateway removes the subscription so nothing arrives twice, and the phone
keeps its choices (`web_push.retire`). A subscription made before this tagging
is recognized by its name, "GoodMorning app on Android".

## Linked phones and app linking

Android widgets and app-side notifications use a separate, revocable app
token, never the website's login cookie. To link a phone:

1. The app calls `POST /api/app/pair` with the phone's name. It receives a code
   (like `ABCD-2345`) to show, and a pairing secret that it keeps.
2. The signed-in owner enters that code in Account → Linked phones
   (`POST /api/app/link`). The box adds the dash after four characters and
   cleans up pasted codes. On the phone being linked, "Link in GoodMorning"
   opens the site at `/chat?link=<code>`, which opens Account with the code
   filled in for the owner to confirm.
3. The app polls `GET /api/app/pair` with its secret and receives its token
   exactly once. It keeps the code and secret until they expire, so closing
   and reopening "Link this phone" shows the same code, and it keeps polling
   in the background while the owner types the code into the website.

Codes expire after ten minutes, and nothing secret travels in a URL. Settings
lists linked phones; Unlink revokes one immediately.

With its token (`X-GoodMorning-App` header) the app can call:

- `GET /api/app/sync?after=N`: everything the widgets and background check
  need, in one request. It returns this phone's notification settings and
  color schemes (`appearance`), the account's website language, seven
  plain days of schedule from today (`/api/app-schedule` on the account's
  backend), timed events in the next 24 hours for on-phone reminders, a summary
  of the latest secretary conversation, today's two briefings
  (`/api/app-briefings`), the forecast frame for the account's city
  (`/api/app-weather`: `{city, frame}`, or `{error}`, read like the briefing's
  weather with its 30-minute cache), status notifications newer than `N`, and
  `busy`: whether the account's work runs or waits in the queue. A saved
  briefing comes as plain rows in reading order, without hidden record IDs; an
  unsaved one only as `missing`, `working` (also while queued), `waiting` (a
  question first) or `stopped`. If one part cannot be read, that part is
  `null`; the rest still updates.
- `POST /api/app/chat` with `{text}` or `{text, chat}`: starts a secretary
  conversation or continues one through the normal queue. It may start paid
  model work.
- `POST /api/app/generate` with `{kind}` (`gm` or `gn`): prepares today's
  morning or evening briefing through the normal queue, like the website's
  button. It may start paid model work.
- `POST /api/app/schedule/tick` with `{id, date, revision, done, key}`: ticks a
  to-do or habit done, or back, exactly like a tap on the Schedule page. No
  model runs. The full contract is in `docs/weekly-schedule.md`
  ([Ticking to-dos](weekly-schedule.md#ticking-to-dos)).
- `POST /api/app/note` with `{id, text, created}`: saves one quick note word for
  word in the account's `quick-notes.sqlite` (`src/goodmorning/web/quick_notes.py`).
  The phone names the note (32 hex characters), so a retried save never makes a
  copy; `created` is when it was first written, in milliseconds. Empty text
  deletes it. No model runs.
- `GET /api/app/notes`: the newest 100 notes, each `unsorted`, `sorting`,
  `question` (its sorting conversation waits for an answer), `sorted`, `changed`
  (edited since it was sorted) or `check` (that conversation's delivery is
  uncertain), with the count still to sort.
- `POST /api/app/notes/sort` with `{}`: starts a new Secretary conversation
  through the normal queue with the unsorted and changed notes that fit one
  message (`Quick notes to sort`, handled by `docs/workflows/secretary.md`), then
  marks them with that conversation and the words it received. Returns `{chat,
  remaining}`, or 409 when nothing waits. It starts paid model work.

- `POST /api/app/signin` with `{}`: a remembered website sign-in as a
  `Set-Cookie` value (`{cookie}`), for the app's WebView. Only a phone that
  moved there from Chrome asks, once, as its sign-in stayed in Chrome
  (`docs/android-app.md`). Ten requests per account in 15 minutes.

The status notifications that Web Push sends are also kept, as the latest
thirty, for accounts with a linked phone. Linked phones read them in their
background check.

## Session organization

Each website conversation and each briefing owns exactly one OpenCode
session. Follow-up messages reuse that session; only a new conversation or a
new briefing date creates another one. Briefing sessions are titled
`GoodMorning · <briefing> · <date>`. Chat sessions start without a custom title,
so the native engine automatically generates an AI summary. Assigning a custom
mode label at creation disables that automatic generation.

Local registries stay bounded without deleting engine history:

```sh
python scripts/goodmorning.py sessions --secretary-dir RUNTIME --list
python scripts/goodmorning.py sessions --secretary-dir RUNTIME --prune-jobs --jobs-older-than-days 14
python scripts/goodmorning.py sessions --secretary-dir RUNTIME --archive-chats --keep 200 --older-than-days 90
```

Reports are dry runs unless `--apply` is passed. Pruning drops only terminal
job entries older than the window plus their transient preview/context files;
saved editions are never touched. Archival moves only idle chats to a preserved
local archive; active, waiting, running, uncertain, or unavailable chats are
retained. Engine sessions are never deleted by these commands; use the engine
dashboard and the registry's owned-session IDs to review unreferenced sessions.

## Validation and evidence

On narrow mobile screens, the floating Sections button opens a native modal
bottom sheet containing only currently visible briefing sections. Selecting an
anchor closes it and focuses the destination; Escape, its close button and an
outside tap dismiss it. It marks the current reading section and updates during
section publication and website-language changes. The desktop minimap and
top-of-briefing native anchor list remain available; the latter also works without
JavaScript. Navigation never changes saved briefing data or dispatches model work.

Use isolated synthetic runtimes. These commands make no model calls:

```sh
python -m unittest discover -s tests -q
node --test tests/test_parked_reasoning.mjs
python tests/browser/generation.py PRIVATE_ARTIFACT_DIRECTORY
python tests/browser/stream.py PRIVATE_ARTIFACT_DIRECTORY
python tests/browser/future.py PRIVATE_ARTIFACT_DIRECTORY
```

Browser checks require Playwright. They test layout, questions, permission replies,
pause/resume, archive pinning, rollover and incremental publication, not real-agent
quality or physical-phone behavior. The opt-in public security trial also
restores a stopped synthetic account from an independent ciphertext/key backup.
Load, physical iOS/Android, machine reboot and real-account disaster recovery need
separate owner-authorized trials; synthetic restoration does not prove those.
