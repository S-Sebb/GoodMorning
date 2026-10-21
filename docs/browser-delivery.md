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
  --secretary-dir /home/YOU/.local/share/GoodMorning/secretary \
  --openchamber-url http://127.0.0.1:YOUR_OPENCHAMBER_PORT --port 8765
```

The OpenChamber origin is explicit and machine-specific. Omit it for read-only
browsing. `GM_OPENCHAMBER_TOKEN`, when required, stays server-side. The bridge
never copies browser cookies or pairing credentials. Local serving is loopback
only; public HTTPS deployment requires `docs/website-security.md`.

`/gm.html` and `/gn.html` select the current briefing day. The day changes at
04:00 in the saved timezone, including daylight-saving changes. A seven-day
selector shows saved and missing editions. `/d/DATE/gm.html` and `/d/DATE/gn.html`
pin an archive date. Archive visits never launch a model; missing past editions
remain read-only. The page rechecks the day on focus and each visible minute,
preserving the selected edition and pinned archives.

Saved data is available at `/d/DATE/gm.json` or `/d/DATE/gn.json`. Invalid formats
remain untouched and are not reported ready. Internal bookkeeping IDs are hidden
in visible text, without changing saved data or citation destinations.

## Explicit generation and chat

Today's missing edition offers a preparation button. It creates a dedicated
OpenChamber session using automatic website-language routing: English uses
Muse Spark 1.3 Contributor XHigh; Chinese uses DeepSeek V4.1 Flash High (paid tier).
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
or failed previews never imply a completed run, task or news acknowledgement.

`/chat` is separate: Initialize before setup, then Secretary for everything,
including to-dos and ideas. Initialize reviews all saved preferences without
resetting records. Drafts and previous conversations remain available; refresh resumes the selected chat.
No private text is placed in persistent browser storage. See `docs/browser-chat.md`.

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
while a mutation is being sent and asks before discarding unsent drafts. No
draft is persisted in browser storage. Public auth/update assets are
fingerprinted, immutable and precompressed; their unversioned aliases revalidate.
Tabs opened before this feature was installed need one manual refresh first.

Chat history reads bounded native V2 pages of at most 200 raw records, retaining
the latest 100 visible messages. This avoids OpenChamber 2.2's fourfold prefetch
overflow. Pending input and uncertain delivery still retain the global busy flag.

## Installed app

Private pages link a web app manifest, so Android Chrome can install the site,
and the Android app opens it in full screen. `/.well-known/assetlinks.json`
vouches for the app package `me.love765.goodmorning` and its release-key
fingerprint. Every server running this source serves it, so the app can connect
to any of them. The app starts at `/app`. Inside the installed app, `app.js`
saves the current page path in the `GoodMorningAppPage` cookie, and `/app`
redirects to that path when it is a page route, otherwise to `/chat`. Sign-in
inside the app also continues to `/app`. The cookie holds only a path, never
page content.

## Notifications

Settings has a Notifications section on the hosted website, shown in browsers
that support Web Push. Turning it on for a device asks for permission, then
registers `/sw.js` and subscribes that device. Turning it off, or signing out,
unsubscribes the device and unregisters the worker. The worker has no fetch
handler, so page loads never start it; it runs only to show a notification or
open one. The four switches and the reminder lead time (5, 10, 15, 30 or 60
minutes; 15 by default) belong to the account and apply to all its devices.

| Switch | Sent when |
|---|---|
| A briefing is ready | A reserved briefing job becomes ready, or stops without finishing |
| My secretary needs my answer | A briefing or chat waits for a question or permission; the text shows the first question or the requested action |
| A chat reply is finished | A chat turn becomes idle; the text is the start of the reply |
| An event is about to start | A timed calendar event starts within the lead time; all-day and unconfirmed (TBC) events are skipped |

The gateway notices the first three in its five-second reservation check
(`reconcile_ticket`); each transition is announced once. For reminders, it reads
`/api/reminders` from each opted-in account's own backend every five minutes.
That endpoint lists the timed events starting in the next three hours. Each
reminder is sent once per event start. While a GoodMorning window is focused,
the worker shows only reminders, because the page already shows everything
else. Notification text uses the account's website language. A tap opens the
related chat, briefing or day schedule. In the Android app, Chrome shows them
as the app's own notifications.

## Session organization

Each website conversation and each briefing owns exactly one OpenChamber
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
node --test tests/test_projects.mjs
python tests/browser/generation.py PRIVATE_ARTIFACT_DIRECTORY
python tests/browser/stream.py PRIVATE_ARTIFACT_DIRECTORY
python tests/browser/future.py PRIVATE_ARTIFACT_DIRECTORY
```

Browser checks require Playwright. They test layout, questions, permission replies,
pause/resume, archive pinning, rollover and incremental publication, not real-agent
quality or physical-phone behavior. Historical measurements and pilot limitations
are preserved in `docs/history/browser-delivery-trials.md`; its obsolete commands
are evidence, not supported interfaces. The opt-in public security trial also
restores a stopped synthetic account from an independent ciphertext/key backup.
Load, physical iOS/Android, machine reboot and real-account disaster recovery need
separate owner-authorized trials; synthetic restoration does not prove those.
