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
OpenChamber session using the user's configured defaults. Duplicate clicks reuse
the durable date/edition job. Uncertain dispatches are never replayed blindly.
Questions and permissions belong only to that session; the viewer is not an
arbitrary session browser or API proxy. Permissions require explicit one-time
approval or rejection. Host, Origin, body limits and a server-generated request
token protect mutations.

Browser authoring follows `docs/browser-generation.md`: prepare once, initialize
the plan, then collect and publish one new section at a time. Code owns the
cumulative document, visible checklist synchronization and final save. Published
sections remain readable and unchanged while later sections are prepared.
Only the next unresolved section animates; questions and permissions pause it.
Progress counts resolved sections, not elapsed time or model claims.

Refresh restores the same job, preview and questions without launching another
session. Status updates preserve answer drafts. Only new section patches transfer
after a checkpoint changes. A matching final save marks completion; unfinished
or failed previews never imply a completed run, task or news acknowledgement.

`/chat` is separate. Its four modes are Initialize, Secretary, To-do and Eureka.
Initialize reviews all saved preferences without resetting records. Mode drafts
and previous conversations remain available; refresh resumes the selected chat.
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

CSS, JavaScript, fonts and icons are shared, fingerprinted assets with immutable
caching, conditional requests and HEAD support. Private HTML, JSON, questions and
API responses remain `no-store`. Pages containing generation request tokens are
not compressed. Images use private browser caching.

Viewer caches are capped at 14 editions / 16 MiB, 128 images / 4 MiB and 128
thumbnails / 2 MiB. These do not bound total process memory or retained history.
Viewing checks only the selected day and seven-day navigation window. There is no
automatic deletion policy for private records, preferences, images or job recovery.

Reduced motion is respected; saved content and source links remain readable
without JavaScript. Restart for renderer/backend changes; saved JSON and image
manifest changes refresh without a restart.

## Validation and evidence

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
