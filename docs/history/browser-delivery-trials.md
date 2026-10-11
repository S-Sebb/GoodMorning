# Historical browser-delivery trials

This preserves earlier trial evidence and instructions as recorded. It is not
current usage guidance. See `../browser-delivery.md` for the native-only interface.

Browser tabs use a sun for GoodMorning, a moon for GoodNight, and a notebook for
Secretary. SVG originals and 32px PNG fallbacks live in `assets/web/icons/`.
The same icons appear on each hostname's login/password page and on saved,
unfinished, missing, and initialization pages. Only these public, fixed assets
are available before login; private pages and APIs retain their authentication.

This private viewer renders saved `/gm` and `/gn` editions as real HTML, not image
attachments. Each heading stays with its content. Text can be selected, source
links are clickable, and saved data remains available. New editions use one
validated native JSON document; old Markdown stays readable and downloadable. Morning and
evening have distinct palettes, full-width content, a right-hand section minimap,
responsive tables, a reading progress bar and restrained scroll-entry motion. Reduced-motion preferences are
respected; content, navigation and tables also work without JavaScript.

## Live seven-day viewer

Use the live server for current-day routing, archive browsing and optional generation:

```sh
python scripts/goodmorning.py serve \
  --secretary-dir /home/YOU/.local/share/GoodMorning/secretary \
  --openchamber-url http://127.0.0.1:YOUR_OPENCHAMBER_PORT --port 8765
```

The OpenChamber origin is explicit and machine-specific, never hard-coded. Omit
it for browse-only mode. Protected OpenChamber installations can supply
`GM_OPENCHAMBER_TOKEN` server-side; it is never sent to page JavaScript. The bridge
does not read pairing stores or copy browser login cookies. Remote deployment and
authentication are **not** enabled by this local prototype.

`/gm.html` and `/gn.html` always mean the current briefing day. All users' day
boundaries are implemented in project source, at 04:00 in their profile timezone,
including DST. The page rechecks on return/focus and each visible minute, preserving
morning versus evening. `/d/YYYY-MM-DD/gm.html` (or gn) pins a selected date. The
top seven-day selector shows saved versus missing editions; archive visits never
launch a model. Past missing editions are read-only. Today's missing edition offers
an explicit preparation button, not automatic generation merely from visiting.

That button creates one dedicated **OpenChamber** session with its configured user
defaults (including model/agent/variant), rather than hard-coding this developer's
model. Duplicate clicks reuse a durable date/edition job. Questions and permission
requests are scoped to that session; the bridge cannot browse arbitrary sessions
or act as a general API proxy. Browser approvals are explicit, one-time or declined;
existing upstream permission policies remain authoritative. Origins, Host headers,
JSON body limits and a server-generated CSRF capability guard mutation endpoints.
One live bridge owns each runtime, including across processes.

New generation jobs publish validated sections **top-down**, while later sections
keep individual loading placeholders. Weather, news, calendar and task placeholders
use small themed animations; only the next section animates, and it pauses for real
questions/permissions. Completed sections appear within the normal 2.5-second polling
interval without a whole-page refresh. Progress counts resolved sections, not time
or tokens; already-running old jobs retain their reported stage bar.

The page clearly labels this as an unfinished preview. Published sections stay
unchanged and readable during later questions or interruptions. Refresh restores
the same job/preview and status updates preserve answer drafts. Only new resolved
sections are transferred after a checkpoint changes; shared assets/images retain
their existing caches. One bounded checkpoint is overwritten per job and removed
only after a matching completed save is verified. Failed previews are preserved.
No completed run, task completion or news acknowledgement is inferred from previews.
Uncertain dispatches never blindly replay; inspect their session in OpenChamber.
Briefing pages have no general chat or scheduler. Restricted secretary
conversations live separately at `/chat`.

## Secretary mode switch

The separate chat page offers Initialize, Secretary, To-do and Eureka through an
accessible four-way switch; users never type commands. Before required profile
settings are saved, Initialize is the default. Afterwards, new conversations
default to Secretary. Initialize remains available to review all preferences,
changing only explicitly confirmed values without resetting saved records.

Switching modes opens a new draft while preserving previous conversations and
per-mode drafts in memory. Refresh resumes the selected conversation. Questions
and one-time permissions use the same widgets as briefings; visible agent text is
rendered safely without executable HTML. No private text enters browser storage.
See `docs/browser-chat.md` for the agent and durable-dispatch contract.

The mode-switch experiment passed at 320/390/768/1440 px with a synthetic agent:
setup, default transition, answers, permissions, same-session refresh, keyboard
selection, draft preservation, and switching during a delayed status response.
Authentication controls passed three local layouts and six public-domain login
checks. Three fresh encrypted synthetic accounts passed real HTTPS remembered
login/password replacement and account-scoped chat/briefing denial. The latest
suite passed 464 Python and 26 Node tests. These checks made zero model calls;
real-agent website setup/chat, physical devices, load and recovery remain unproven.

The section experiment uses `tests/browser/stream.py PRIVATE_ARTIFACT_DIRECTORY`
with an isolated mock agent and production publication/save helpers. It compares
the previous all-at-once behavior (no readable section before the final snapshot)
against a first completed section that is readable while later sections remain
unresolved. It checks question/permission handling, paused animations, unchanged
published DOM nodes, incremental payloads, refresh recovery, optional-section
skips, interruption, matching final saves and transient-preview cleanup. There
are no model calls. This tests the delivery protocol, not whether a real agent
follows the new writing order, improves total generation time, or costs fewer tokens.
Publication adds tool calls; minimal draft patches avoid re-emitting prior content.
The full Python suite passes 405 tests. Six streaming browser cases cover morning
and evening at 1440, 390 and 320 pixels, including reduced motion during generation
and preview recovery while the mock secretary is unavailable. The three-width older
generation round-trip, 42 native future editions and saved-page polish checks also
pass. Screenshots were inspected; these are Chromium checks, not physical Android/iOS
tests. The installed global skill copy has not been redeployed.

Normal workflows now author v1 browser-native JSON (`docs/briefing-format.md`).
It contains each edition's natural greeting/opening, explicit component data and
useful section notes, including Nice-to-do, without Markdown/presentation copies.
Old Markdown snapshots and source-bound presentation remain unchanged and readable;
missing legacy presentation falls back to
their original greeting, not an invented AI summary. Known bookkeeping IDs are
hidden in visible prose, while original Markdown and citation destinations remain
intact. The date no longer repeats across the greeting and artwork. The moon is
unchanged; the sun is a simpler flat illustration. A small “Today” badge marks
the current briefing day even while another date is selected. Back-to-top is
high-contrast and centered between the section's right border and the usable
viewport edge, accounting for wide layouts and safe areas. Its gutter is reserved
so it cannot cover content. A footer fallback is visible only without JavaScript.

Whole sections now enter together: their title, body and border share a noticeable
800ms fade from 14% opacity. Text is never translated or scaled during this
entrance, so it stays on its final pixel grid instead of snapping as motion ends.
An unanimated outer frame
drives intersection detection to prevent self-triggering flicker; re-entering a
section can replay the entrance. Reduced motion disables it and nothing is hidden
without JavaScript. Weather, news, agenda and task cards have gentle desktop hover
color/border/shadow feedback again, without movement, pointer cursors or fake actions.

The live viewer refreshes saved-source/presentation changes without restarting.
Restart for Python renderer/backend code changes. Public article image retrieval
remains an explicit offline-build option, never an implicit page-view request.

Validation: 386 Python tests, 16 Chromium layout/interaction cases, and a separate
three-viewport mock generation round-trip cover questions, permission replies,
refresh recovery, archive pinning and edition-preserving rollover. No paid model
was launched during these tests. Subsequent real-agent pilot results are recorded below.
The actual local OpenChamber control endpoint was checked read-only for user defaults.
Nine additional WebKitGTK reading/navigation checks passed; these are not physical
iOS Safari tests. Mock question/generation interactions were tested in Chromium.

A matched 180-frame desktop scroll experiment (median of three runs per variant)
reduced layout recalculations from 98 with size animations to 14 with transforms.
Total measured browser work changed only slightly (0.268s versus 0.257s); this is
not proof that every source of lag is fixed, nor a physical-phone frame-rate claim.
Run `tests/browser/performance.py` with optional Playwright against the live preview.
`tests/browser/generation.py PRIVATE_ARTIFACT_DIRECTORY` exercises the isolated
fake-agent flow without contacting any model or touching personal records.
`tests/browser/polish.py --artifacts PRIVATE_DIRECTORY` checks whole-panel fading,
unchanged glyph rectangles during the entrance and final settling frames,
restored hover feedback, the Today badge, and exact button centering at 320, 390,
1440 and 1920 pixels in both editions. Its private screenshots were inspected.

## Loading, reuse and long-term storage

Live viewing no longer creates `browser/DATE/` exports. New canonical content is one
native JSON document; legacy Markdown/presentation remain supported. HTML renders on demand.
The requested edition is compiled independently, so a damaged sibling edition
cannot break a readable one. Native fields render directly, without Markdown or
prose-layout inference. Legacy Markdown is parsed once per compilation and reused
for section conversion and citation lookup. Existing exports/screenshots are left
untouched; removing them needs separate confirmation. Explicit static exports are
still supported for offline use, but are not the long-term live-viewing strategy.

CSS, JavaScript, the font and its licence are shared, content-fingerprinted assets.
They use immutable browser caching, ETags, conditional requests and HEAD support.
Text assets and saved HTML/Markdown use negotiated gzip; `gzip;q=0` is respected.
The full Lora font is served as **91,464-byte WOFF2**, versus **221,232-byte TTF**,
with all 889 glyphs and 778 Unicode mappings preserved. Its preload reuses the same
URL as CSS. The original TTF is retained once in source for reproducibility, not
served or copied into future exports.

Personal HTML, saved JSON/Markdown, agent questions and API responses remain
`no-store`. Read-only saved pages do not contain the generation CSRF capability.
Generation pages that do contain it are not compressed. Only package assets get
public cache directives; public-publisher image bytes use private browser caching.
This is still a loopback prototype, not remote authentication or a production CDN.

Future explicit `--fetch-images` operations store normalized WebP images once in
`browser-images/objects/SHA256.webp`, with a URL-indexed SQLite catalog and small
per-date manifests. Repeated URLs reuse verified originals without network fetches;
different URLs producing identical bytes share an object. Legacy date caches stay
readable and are only imported into the pool during explicit image-cache work.
Nothing is fetched from publishers while visiting the page. Unique image originals
and required records still grow with history; there is no destructive retention
policy or promise of constant total storage.

To populate previews without creating an offline webpage export, use
`briefing_web.py --secretary-dir RUNTIME --date DATE --fetch-images --images-only`.
This writes only the image cache/catalog/manifests; ordinary page views never fetch.

Live image URLs are shared across dates. Responsive previews offer an in-memory
320×240-bounded derivative and the original, accounting for image aspect ratio,
displayed crop and screen density. Large/high-density displays can retain the
original. Small derivatives are never saved on disk, are bounded by a separate
cache, and use a versioned recipe URL (`thumb-v1`; bump when changing the recipe).
Optional Pillow absence retains the original-image path.

Server caches are capped at 14 edition entries / 16 MiB, 128 original images /
4 MiB and 128 small derivatives / 2 MiB. These are byte-cache limits, not a claim
that process RSS or transient decode buffers cannot exceed 22 MiB. Viewing a day
checks only that day and the seven-day navigation window, not all saved history.
Private job/session recovery records are retained independently.

Measured in local desktop Chromium: adaptive images reduced cold transfer from
624,261 to **309,965 bytes** against the full-size-image variant. On subsequent
morning/evening switches, shared CSS/JS/font traffic was **zero bytes**; the night
page transferred 4,376 bytes and the next morning visit 10,608 bytes including
headers/API requests. Navigation load events were about 166 ms cold and 18–26 ms
warm in that run. These are local measurements, not remote-network or phone-speed
guarantees. The older day's duplicated export occupied approximately 856 KB; new
live renders create no such per-day exports.

## Future conversion validation

Legacy conversion splits parsed Markdown, not raw `##` lines, so fenced/indented code and
quoted headings cannot become fake navigation. Formatted headings, setext headings,
common task-heading variants, lower-case timetable headers, nested lists, tables,
all citation links and unknown sections remain readable. Unfamiliar or missing
section structure uses a generic Briefing layout rather than failing. Missing or
malformed optional image manifests/presentation fall back without fabricating data.
Original UTF-8, CRLF and BOM bytes remain unchanged and downloadable. The normal
source-size limit remains 150,000 bytes; this is not an unbounded-input parser.

`tests/test_briefing_scaling.py` covers 18 varied source shapes, 100 deterministic
optional-section combinations, original byte preservation, resource reuse, image
deduplication, HTTP negotiation and damaged-sibling isolation. A 4,000-original
fixture rendered 160 editions across 80 changing dates without adding export files
or exceeding cache bounds. `tests/browser/future.py PRIVATE_DIRECTORY` passed
42 synthetic 2034 morning/evening browser cases at desktop, 390px and 320px widths,
including an 80-section navigation strip, with no overflow or page errors.

These validate conversion and resource behavior, not the factual accuracy or
future instruction-following of an AI writer. They launch no agents or providers.
Real-agent pilot results are recorded below; physical-device validation remains separate.
`tests/browser/loading.py` measures actual transfer/cache reuse in a real Chromium
context; it does not infer cache effectiveness merely from response headers.

## Native-format experiment and validation

`tests/benchmarks/briefing_format.py` compares equal substantive content in 12
English/Chinese morning/evening fixtures, with 2/8/16 stories/tasks/events. It
compares Markdown plus authored presentation, named-field JSON, compact typed JSON,
and YAML using two real tokenizers. Native v1 uses compact tuples only for repeated
rows/blocks, readable type tags, and optional explicit translated/custom labels.

Authored compact JSON used **3.61% fewer o200k tokens** and **3.53% fewer cl100k
tokens** than the Markdown/presentation baseline. Ordinary named JSON and YAML
used more. Saved UTF-8 briefing bytes, including the legacy presentation source
hash, fell from 41,236 to **39,776 bytes (3.54%)**. These are small format savings,
not reductions in image storage, full history or total agent cost. Schema guidance
costs 1,611 o200k input tokens; instructions, tool envelopes and tool round trips
are excluded from authored-output counts. Tokenizers are proxies for other models.

Seven paired local parse/validate/render batches alternated test order after warmup.
Median compilation fell from **4.716 ms to 2.593 ms per edition (about 45% less)**.
This excludes filesystem/network/cache work and does not promise a comparable
reduction in page-load time. Native rendering identifies components from explicit
types, never English headings or punctuation; unrecognized versions/fields,
malformed rows, missing news citations and unsafe URLs are rejected before marking.
Every accepted fixture retains its facts, all citation URLs, separate notes and
closing. JSON escapes do not bypass the existing boilerplate lint. Validation is
structural, not a check of factual accuracy or evidence of user consent.

`tests/test_briefing_document.py` exercises malformed input, inert HTML strings,
translated labels/flags, headline dashes, multiple same-type section notes, exact
task statuses, source-size limits, canonical pointers, duplicate saves, damaged
source handling, cached images and Markdown-free rendering. A 2,000-native-record
fixture rendered 160 editions across 80 days without adding exports or exceeding
cache bounds. Existing 4,000-Markdown-record tests remain intact.

`tests/browser/future.py PRIVATE_DIRECTORY --native` passed 42 synthetic future
cases at 1440/390/320px, including an 80-section strip, with no overflow/page errors.
`tests/browser/generation.py PRIVATE_DIRECTORY --native` passed mocked generation,
refresh recovery, real question/permission reply shapes, read-only archives and
edition-preserving rollover at three widths, producing JSON without a Markdown copy.
No real agent was launched: future AI authoring error rates, actual model billing
and physical-device behavior remain unmeasured. Old records were not migrated,
rewritten or deleted. The copied global skill must receive the public source update
through the documented deployment process; browser dispatch reads this checkout.

## Real-agent pilot: 2026-10-11

An isolated remote trial used a verified copy of this source and approved private
record copies with `opencode-go/muse-spark-1.3-contributor`, variant `xhigh`, from
the server's configured defaults. Original records were unchanged. The viewer and
agent runtime remained loopback-only; this did not deploy public domains. Live
project access, calendar synchronization, publisher-image fetching and news
acknowledgement were excluded.

The morning job published six complete sections top-down, then saved one native
JSON document of 7,772 bytes without a Markdown briefing, presentation sidecar or
daily HTML export. At 2.5-second observation intervals, the first readable section
appeared about **45.6 seconds after the final consent answer**, and the completed
briefing about **205.6 seconds after that answer**. These exclude an earlier human
decision/recovery pause and are not click-to-completion measurements. They show a
readable section before the final save in this run, not faster total generation
than an unmeasured real-agent all-at-once baseline.

Sampled combined agent/viewer service memory peaked at **846.1 MiB**, with at least
**2,317.5 MiB** of host RAM available. Concurrent local NGINX probes all returned
HTTP 200, with median 8.14 ms and maximum 103.32 ms. These short-run samples are not
continuous peak tracking, production-site load testing or a capacity guarantee.
The session API reported 100,816 input, 17,786 output, 16,191 reasoning and
4,131,347 cache-read tokens across 68 assistant messages. These counters should not
be summed blindly; reasoning may overlap output. Its reported cost of approximately
$0.02514 is not a verified billing charge or a model-cost comparison.

Chromium rendered the actual saved edition at 390, 768 and 1,440 pixels without
horizontal overflow or JavaScript errors. All six headings and ten citation links
were present; the previous missing day remained read-only. Images correctly used
unavailable placeholders because fetching was excluded. Physical Android/iOS,
real-image retrieval and public authentication/routing remain untested here.

The trial also exposed limitations: the missed-run question repeated after an
explicit answer, and an older question tool receipt remained marked running after
the job was ready, though no form remained pending. Editorial review found
unsupported assumptions about availability and imprecise timetable commentary.
Successful validation and publication do not establish factual or editorial
correctness. The saved edition was retained, not rewritten to conceal these findings.

The sequential evening job paused all sections at its actual progress form. The
user explicitly reported no completed listed tasks and no other updates. Those
answers were relayed through the existing browser form. The first section appeared
about **44.1 seconds after the answer**, and the saved briefing about **89.1 seconds
after the answer**, again sampled every 2.5 seconds. Four sections published in
order; the native snapshot is 4,651 bytes. No task was marked complete. The morning
snapshot remained byte-identical, and both job checkpoints were removed only after
their verified final saves. Evening service memory peaked at **856.8 MiB**, with
at least **2,306.7 MiB** of host RAM available. NGINX probes were all HTTP 200,
median 7.84 ms and maximum 34.94 ms.

The evening session API reported 122,039 input, 8,520 output, 12,136 reasoning and
1,447,373 cache-read tokens across 31 assistant messages, and approximately $0.01923
reported cost. These retain the same counter/billing caveats as the morning run.
The saved four-section edition passed Chromium checks at the same three widths.
All 87 packaged source-file hashes and all 18 immutable baseline-record hashes
still matched after both trials. Python bytecode caches were additional source-tree
files, not source changes. The active secretary tree occupied approximately 1.00 MB,
including the news database, caches and retained draft inputs; the two native
snapshots together occupy 12,423 bytes. This excludes OpenCode session storage,
immutable baseline/source copies and observation logs, and is not a growth forecast.

Record validation found a separate correctness gap: **five tasks displayed in the
morning plan were not added to the daily checklist**. The evening writer recovered
them from the saved morning snapshot, but that does not make the daily record
consistent. Its only checklist entry remained unchecked. Also, morning tooling
recovered from a rejected out-of-runtime draft path and a news-result field error;
the evening audit found no failed tools. These findings require follow-up before
production readiness is claimed. No saved trial edition or original record was
repaired as part of measurement, and no public deployment occurred.

## Section scroll navigation

The left catalog has been removed. A narrow, fixed strip on the right contains
one segment per section. Segment lengths reflect section heights, and the current
section and reading progress update as the page scrolls. It supplements the native
browser scrollbar rather than replacing ordinary scrolling or pinch zoom.

- Mouse hover or keyboard focus opens a themed preview with the section heading
  and a short excerpt from its actual content. Click a segment or preview to jump.
- On touch screens, tap a segment once to preview, then tap it again (or its
  preview card) to jump. Targets are at least 44 CSS pixels high and wide. Tap
  outside or press Escape to dismiss. Keyboard activation remains a single action.
- Previews stay within the viewport, including small landscape screens. They do
  not load images or make network calls. The original-text link is in the briefing
  toolbar immediately before the content, not the footer.
- Without JavaScript, section anchors still navigate directly. Hover/focus previews
  remain available for pointer/keyboard users; the two-step touch enhancement is
  not required to read or navigate the page.
- Safe-area insets keep controls away from notches/home indicators. Dynamic viewport
  height is used where supported, with a `vh` fallback for older browsers. No zoom
  limit is set. Short screens let the strip scroll internally rather than shrink
  touch targets. The active indicator follows that internal scrolling.

## Polished motion

The user selected restrained rather than cinematic movement. The page now has:

- Brief, lightly staggered title entrances and gently eased section arrivals.
- A moving soft glow behind the active navigation segment. It smoothly moves and
  adopts the new segment's height without animating layout size. Fills stay consistent.
- A short slide/scale transition for preview cards and soft hover responses on
  links, edition buttons and component surfaces. Read-only cards keep normal cursors
  and do not move or mutate data. The active section gets a subtle
  border and number-badge emphasis.
- A lightly smoothed top reading-progress line and a maximum 9.5-pixel sun/moon
  drift tied to scrolling. Decorative drift is disabled on touch devices and
  stops updating when the hero is offscreen.

Saved briefings have no endless animations, autoplay effects, extra libraries, custom scroll
physics or hidden-until-JavaScript content. Normal browser scrolling and pinch zoom
remain unchanged. Reduced-motion preferences disable the new animations,
transitions and decorative transforms, including when the preference changes
while the page is open. Reading-progress values and section navigation still work.

The cursor's section geometry is cached during measurement, not read repeatedly
on each scroll event. This keeps decorative work small; it is not a claim of a
measured frame rate on physical phones.

## Encrypted public-domain pilot — 2026-10-11

The public viewer now uses the separate [website security boundary](website-security.md).
Both configured domains have a valid HTTPS certificate and require password login.
Accounts and their browser sessions live in an encrypted root-only volume. Each
user has an independent encrypted record/agent volume and Linux identity, not a
shared agent HOME. The website cannot register users, rename them or bypass
current-password checks; recovery remains SSH-admin-only.

The new workflow has code-owned preflight and section assembly. Dispatch is three
lines; the model reads saved preparation/feedback, publishes one section per call,
and finishes through the job helper. Explicit night selections are saved once;
visible morning task titles enter the checklist unchecked. Focused tests cover
interrupted feedback receipts, conflicting edits, final-marker recovery and
preservation of existing completed/unrelated tasks. Temporary cumulative input is
removed only after a confirmed final save.

Validation is distinct from the earlier real-agent pilot:

- **432 Python tests** and **26 Node tests** passed locally. This includes account,
  password, session, routing, ownership and workflow contracts.
- Three new synthetic encrypted accounts passed real public-HTTPS login, forced
  password replacement, old-token revocation, private record rendering, cross-account
  web/job/file denial, CSRF rejection and no web username changes. Their services
  stopped and accounts were disabled; encrypted evidence remains preserved.
- Encrypted unmount/remount retained the synthetic data; missing-mount and
  plaintext-fallback writes were refused. A unique synthetic plaintext marker did
  not occur in that account's ciphertext files. This is a focused check, not an
  independent cryptographic or penetration audit.
- Both login pages passed actual Chromium checks at **390, 768 and 1,440 px**, with
  no horizontal overflow or page errors, host-only Secure/HttpOnly/Strict cookies,
  and HTTP 401 for private APIs before login. These are emulated sizes, not physical
  Android/iOS or Safari tests.
- Running per-account engine/viewer mount namespaces confirmed that hard-coded
  `/tmp` and `/var/tmp` paths resolve to encrypted storage. Both services have
  `MemorySwapMax=0`; NGINX and the gateway do too.
- All **33** restored settings still matched in a read-only check. Original pilot
  source **87 files**, immutable baseline **18 files**, and the original morning
  edition hash were reverified unchanged. No original trial was repaired/replayed.

These security/browser checks made **zero model calls**. The fresh real-agent
public-domain briefing trial has not started: the owner must issue a temporary
password over SSH and replace it in the browser first. Production transfer,
reboot testing, recovery-key/backup restoration, load testing and physical-device
validation remain incomplete. The original overlapping-question cause remains
unresolved. Legacy private trial originals retain their existing storage; this
deployment does not retroactively move, encrypt or delete that evidence.

## Static build / frozen experiment

Native JSON rendering uses the standard library. Python-Markdown is needed only
for old Markdown editions; Pillow is used only for the optional publisher
thumbnail cache. Existing secretary helpers do not need these browser dependencies.
No npm dependencies, runtime CDN requests or image-generation service are used.
Commentary uses the bundled, self-hosted Lora italic font under its included
SIL Open Font License; no browser request goes to Google Fonts.

```sh
python -m pip install -r requirements/browser.txt
python scripts/goodmorning.py web \
  --secretary-dir /home/YOU/.local/share/GoodMorning/secretary \
  --date 2026-10-10 --serve --port 8765
```

Open `http://127.0.0.1:8765/`. Morning is `gm.html`; evening is `gn.html`.
Only saved editions get navigation links. If neither exists, rendering fails
instead of fabricating a briefing. Date is explicit: use the profile-local date.
The example runtime path must be replaced with your selected absolute path.

Without `--serve`, the command only builds files. Output defaults to
`RUNTIME/browser/DATE/`; `--output` selects a separate, private artifact directory.
Rerun the command after a saved source changes. The running server serves a frozen
build, not live records. Existing generated files are rebuilt; use a dedicated
output folder. Do not put personal output in a Git checkout or public web root.

The renderer never fetches weather/news reports, changes tasks, updates inbox records,
marks a workflow or acknowledges news. It reads the two selected snapshots and
the optional checked image cache. Article image retrieval requires `--fetch-images`.
Browser testing is not fact-checking their contents. Explicit card delivery is
separate; new browser workflows save native JSON without a presentation sidecar.

## Privacy and limitations

- The preview binds only to `127.0.0.1`, rejects unrelated Host/Origin headers,
  and serves an explicit generated-file allowlist, not the private runtime.
- Raw HTML is displayed as text. Markdown output is restricted to formatting
  tags and HTTP(S) citation links. No remote assets load automatically; clicking
  a citation intentionally opens its publisher.
- Generated directories/files use private permissions when created. The HTTP
  responses disable caching and include a restrictive content security policy.
- The local preview alone is not an authenticated web service. Other local processes/users able to
  reach the port can read it. Stop the preview when finished. Do not tunnel it or
  bind it publicly as a substitute for authentication.
- Source ordering, facts and estimates are retained. Known bookkeeping identifiers
  are omitted from visible prose, not removed from saved Markdown or link targets.
- The static builder is read-only. The opt-in live bridge above can start a workflow
  and relay questions/permissions; it has no general chat, scheduler or automatic
  news-delivery acknowledgement.
- Publishing a file is not evidence the user read it. News acknowledgement needs
  a separate, explicit delivery mechanism; never acknowledge on build/upload.

## Rich in-section layouts and publisher thumbnails

The section overhaul follows information patterns studied in
[Apple Weather](https://support.apple.com/guide/iphone/check-the-weather-iph1ac0b35f/ios),
[Google Calendar](https://workspace.google.com/products/calendar/),
[BBC News](https://www.bbc.com/news) and
[the Guardian](https://www.theguardian.com/international), without copying their branding.

- Weather uses individual metric tiles with local vector icons. Prominent values
  come from the saved text, not a fresh forecast. Cool temperature, dry/rain/snow
  precipitation, AQI and explicit warning headings have appropriate icon treatments.
  Icons are decorative; full values, units, caveats and advice remain readable.
- Recognized schedule tables become date-grouped agendas. Time, event, location,
  preparation and any extra columns are retained. Wide screens place location and
  preparation side by side; phones stack them without horizontal scrolling.
  Unrecognized tables keep their original accessible table layout. Nothing is
  added to a calendar, and no duration, date or completion is inferred.
- News is grouped by the saved categories. Each story separates its headline,
  complete summary, source and publisher preview. The grid becomes a single
  column on narrower screens. Photographs are never substituted from another
  story; unavailable previews get a labeled topic illustration.
- Tasks and reminders use distinct cards, with existing checkbox states and
  clearly separated lead/detail text where the source permits it. These are
  read-only displays, not functional task-completion controls.

Publisher image retrieval is explicitly opt-in:

```sh
python scripts/goodmorning.py web \
  --secretary-dir /home/YOU/.local/share/GoodMorning/secretary \
  --date 2026-10-10 --fetch-images
```

The helper requests the selected news citations' public Open Graph/Twitter image
metadata, then caches decoded, resized WebP previews under
`RUNTIME/browser-images/DATE/`. It uses no browser login, cookies or authorization
headers. HTTPS destinations and every redirect must resolve to public addresses;
the TLS connection is pinned to a validated address with hostname verification.
Private/local addresses, credentials in URLs and non-HTTPS redirects are refused.
Requests have bounded reads/socket budgets, four workers and at most 32 unique
citations per date. DNS resolution uses the system resolver. Failures are recorded
and rendered as illustrations, not retried automatically or used to bypass access
controls. Existing successful/failure receipts are reused on repeated invocation.

Normal builds and page views are offline with respect to publishers: they read
the checked cache and serve normalized raster bytes from an explicit `media/`
allowlist. The browser's existing self-only image policy remains intact. Image
hashes, file names, size, raster signatures and symlinks are checked before serving.
Original article/image URLs and publisher-provided alt text stay in the private
cache receipt. This private prototype does not establish redistribution rights;
check publisher/image terms before deploying thumbnails publicly.

For the authorized 2026-10-10 experiment, all 16 publisher previews were cached,
using 499,372 bytes in total. Saved briefing wording and citation destinations were
preserved. Desktop and phone detail screenshots were inspected; the desktop agenda
was then made more compact by grouping its location/preparation columns. Test
artifacts live privately under `RUNTIME/browser/2026-10-10/section-overhaul-checks/`.
The full Python suite passes 314 tests. All 16 Chromium desktop/mobile cases
pass with cached images decoding successfully, intact section navigation, no
page-wide overflow, preserved bottom fills, reduced-motion and no-JavaScript
support. Exact scroll-fill checks use a fresh document after interaction checks
so an unfinished native keyboard scroll cannot interfere with test-only jumps.

## TCSFrontEnd / NGINX deployment

The authorized encrypted trial above supersedes the initial deployment proposal.
NGINX terminates HTTPS and forwards only to the Unix-socket gateway. The gateway
authenticates users and selects their independent loopback briefing backend; that
backend controls only its account's authenticated OpenChamber engine. Shared source
and binaries are read-only, outside the web root. There are no daily HTML exports
or unrestricted OpenCode API routes. Deployment/account operations and trust
boundaries are maintained in `docs/website-security.md` and `deploy/`.

`/gm` and `/gn` remain plain workflow prompts, not assumed registered commands.
Questions and permissions belong to their actual dedicated sessions. Reconnects
reconcile durable state rather than replay unknown prompts. Pairing does not grant
new website/credential-copy permissions. The owner separately authorized the
isolated record copy and the remote model credential; live calendar/project access
remains disabled. No production record transfer has occurred.

References: [OpenCode V2 client](https://opencode.ai/v2/docs/build/client),
[HTTP API](https://opencode.ai/v2/docs/api),
[skill deployment](deployment.md).

## Validation

```sh
python -m unittest discover -s tests -p test_briefing_web.py -v
```

Focused tests cover source preservation, inline ordering, both editions, absent
editions, accessible table wrappers, checkbox labels, raw-HTML/link sanitization,
input/path restrictions, Python 3.9 grammar and the private HTTP allowlist.
Unit tests use synthetic fixtures; real snapshots remain outside Git. The optional
`tests/browser/briefing.py` accepts a running private viewer and requires an already
installed Playwright package and its browser engine. It is not part of the
standard-library test suite and installs nothing automatically:

```sh
python tests/browser/briefing.py --url http://127.0.0.1:8765 --browser chromium
# When a Playwright WebKit browser is available:
python tests/browser/briefing.py --url http://127.0.0.1:8765 --browser webkit
```

An optional `--artifacts PRIVATE_DIRECTORY` saves screenshots and a metrics report.
Those screenshots contain the actual briefing; keep them outside the checkout.

### Local experiment: 2026-10-10

The existing real morning snapshot was reused unchanged. A real evening snapshot
was generated after the user explicitly chose to leave progress unreported; no
tasks were marked complete. Neither snapshot was uploaded remotely.

Against the chat screenshot's detached attachment previews, Chrome 150 displayed
all six morning sections and all four evening sections with their content directly
under the correct headings. All 16 morning citations were clickable. Checks at
1440×1000 and 390×844 found no page-wide horizontal overflow; the schedule table
scrolls within its own region on mobile. Section links and reading progress worked.
Reduced-motion disabled smooth scrolling and entry animation. Mobile content and
table scrolling also worked with JavaScript disabled. No application JavaScript
errors were observed. These checks establish local rendering, not remote hosting,
provider correctness, accessibility certification or browser-driven invocation.

The full Python suite passed 304 tests; card-plugin/project Node tests passed 36.
Private screenshots and the browser-check report are in the selected runtime's
`browser/2026-10-10/`, not the repository. OpenChamber's browser panel initially
reported display-only, so automated layout checks used a separate temporary
headless Chrome profile through its built-in debugging protocol. After reopening,
the panel became controllable; its page snapshot and an actual Morning-to-Evening
click also verified the viewer in OpenChamber. The temporary headless browser was
closed after validation; the loopback viewer stays available for inspection while
its preview process is running.

### Full-width / mobile navigation follow-up

The full-width layout and segmented navigation passed 16 Chromium cases: both
editions on desktop, Pixel 7 emulation, iPhone SE/13 viewport-and-touch emulation,
320×568 portrait, 844×390 and 568×320 landscape, and 768×1024 tablet. Checks included
all segment previews, keyboard/Escape behavior, first-tap preview without navigation,
second-tap or preview-card navigation, 44-pixel targets, active-section tracking,
within-viewport preview bounds and no page-wide horizontal overflow. Reduced-motion
and no-JavaScript checks also passed. Screenshots were inspected after preview
transitions finished, rather than accepting partially transparent animation frames.

The installed WebKitGTK 2.54.0 engine passed nine additional cases covering both
editions at phone and landscape sizes and the evening edition on desktop. Those
checked full-width content, preview bounds, keyboard focus, section anchors, CSS
grid/clamp/safe-area support and the two-step JavaScript handler using synthetic
clicks with touch mode forced. This is independent WebKit-engine coverage, **not
physical iOS Safari testing**. Chromium with an iPhone user agent is likewise not
Safari. No browser package was installed for these checks.

The Python suite now passes 305 tests. Follow-up screenshots/reports are private
under `RUNTIME/browser/2026-10-10/scroll-map-checks/`. Before treating mobile support
as release-certified, open both editions on a real iPhone/iPad in Safari and an
Android phone in Chrome. Check pinch zoom, browser-toolbar expansion, notch/home
indicator spacing, orientation changes and touch navigation. That device check
requires a separately authorized private delivery path; the local server is
intentionally not reachable from another device.

### Bottom-of-page segment regression

A user screenshot exposed a fill inconsistency that the initial preview/navigation
checks missed. Reproduction at 1440×1000 selected the final (sixth) morning segment
at the page bottom while leaving the fifth at `0.4273743016759777` fill. The
bottom-of-page active-section override and the per-section fill calculation used
different rules when short final sections could not reach the viewport reading line.

The fix makes all fills complete at the bottom, all segments before the active
section complete, and later segments empty. The browser suite now checks these
invariants at section midpoints, just before the bottom and at the bottom for
both editions across all 16 Chromium cases. Independent WebKit checks also verify
complete bottom fills. Cropped before/after minimap screenshots were inspected,
including desktop, phone and short-landscape views, rather than checking only
hover previews. Private regression images remain in `scroll-map-checks/`.

### Motion validation

All 16 Chromium cases passed after the motion changes, including the earlier
bottom-fill regression, intermediate scroll states, cursor alignment, preview
navigation and mobile bounds. At settled states, there were zero running browser
animations. Reduced-motion checks covered static transitions, disabled drift and
changing the preference while the page was open. No-JavaScript navigation also
passed. Nine WebKitGTK cases independently checked final cursor alignment, bottom
fills and zero running animations after finishing their finite transitions.

Actual navigation-transition frames were captured at 0%, 25% and 100% of its
duration and visually inspected, alongside settled desktop/phone screenshots.
The cursor moved continuously from top `293` to `336.796875` CSS pixels and grew
from `31.796875` to `157.578125` pixels to match the longer news segment. The
quarter-duration frame lay between both endpoints. This demonstrates the intended
motion locally; physical Android/iOS performance still needs device validation.
Private frame images and the comparison sheet are in `scroll-map-checks/`.

### Active-segment edge refinement

The separate outlined cursor created a visible double edge around the active bar.
It now uses a low-opacity blurred glow, while the active bar has a transparent
border so its rounded fill forms one clean edge. Movement, previews and keyboard
focus indicators are retained. Before/after minimap crops were inspected in both
editions on desktop and phone; hover/touch preview checks and all 16 Chromium
cases passed. Regression assertions require no cursor border and no visible
active-bar border. Private crops are in `navigation-edge-checks/`.

### Earlier static-preview refinement (historical)

The header tagline is “A personal secretary just for you.” Sun/moon artwork uses
local vector illustrations with the date in a separate caption underneath, so
the caption cannot cover the illustration. They are decorative edition motifs,
not actual astronomical phases or forecasts.

The original Markdown link sits in a dedicated toolbar before the sections.
The floating “Back to top” control appears after leaving the top and uses the
browser's normal smooth scrolling, or immediate scrolling in reduced-motion mode.
Its 44-pixel target occupies the reserved right gutter; section navigation reserves
vertical space above it, including on short landscape screens. A footer link
remains available without JavaScript. Neither control changes records or
acknowledges news delivery.

Closing section commentary uses one shared Lora italic callout style. Main weather
values, schedule data and progress reports keep their readable body font.
Explicit national-news category codes get small local SVG country flags; world
news retains its globe. Flags have accessible country names and do not infer
new article classifications.

Read-only task, schedule and news-card surfaces no longer change on hover. Their
existing information is already visible, and clicks cannot modify records.
Actual links, edition switches, navigation previews and back-to-top retain
interactive feedback. Checkbox states remain displays of the saved source only.

When only `/gm` exists, Morning is available and Evening shows “Not yet” without
a clickable link; the reverse works for an evening-only snapshot. A direct URL
to a missing edition returns a styled, explanatory 404 with a link to the available
edition, not a fabricated briefing. The viewer still serves a frozen build: after
`/gn` is saved, rebuild/re-publish the viewer to enable its switch. Viewing an
unavailable edition does not invoke a model or mark a workflow.

These refinements pass 317 Python tests and all 16 Chromium layout/interaction
cases, including back-to-top clicks, reserved-space overlap checks, internal strip
scrolling, desktop artwork/caption separation, reduced motion and no JavaScript.
