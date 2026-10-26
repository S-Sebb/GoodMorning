# Website security and account operations

The account-wide interface language and a linked phone's color schemes are
encrypted account metadata, not profile rewrites. Color schemes otherwise belong
to each device. Only the non-secret language, appearance and pre-login
day-palette cookies, and the HttpOnly linked-phone cookie, use the hosts' common
parent domain. Authentication
cookies remain host-only. Language and color changes require
the same origin and session CSRF checks, including the no-JavaScript form. HTML
uses `Referrer-Policy: same-origin` so native forms send a verifiable Origin;
external sites still receive no referrer. Language controls include a CSRF token,
so private HTML is never compressed. Shared translation assets contain no private
data and keep content-hashed, cacheable URLs.

The public website adds a security boundary to the local viewer; it is not an
OpenChamber UI proxy. It permits login, current-password changes, logout and
account-owned briefing viewing/generation/questions and secretary chats
(Initialize alone before setup; Secretary afterward; older To-do and Eureka chats stay replyable).
No web registration, account
creation, username edit, forgotten-password shortcut or arbitrary agent API exists.
Secretary chat also accepts private attachments up to 50 MB per file. Uploads
require a permanent authenticated account, the exact origin and session CSRF token.
Only opaque upload IDs and filenames are exposed; files stay in the owning
account's encrypted runtime. The gateway streams bytes without disk buffering,
and all ordinary JSON requests retain their 20,000-byte limit. NGINX's 50m ceiling
allows the binary upload route; it does not expand the other application limits.
The authenticated `/api/activity` summary includes only the caller's active,
queued or waiting work, status and original-page links, never prompts, question text, private
paths or another account's activity. Reads never advance the queue or change work
reservations. Each tab uses its host-only login; no activity is stored in browser
storage or shared authentication cookies.

The explicit `gm`, `gn`, and optional `sec` hosts share accounts, not login cookies.
The secretary host opens `/chat`; briefing hosts open their matching edition.
Incomplete profiles see an initialization link instead of a generation button,
even before a timezone exists. `/chat?mode=initialize` selects a new Initialize
draft without dispatching a model or resetting records. Direct generation also
refuses incomplete setup. Explicit host/origin allowlists and TLS certificates
must include all configured hosts; never use wildcard origin/cookie permissions.

## Notifications

Web Push uses VAPID (RFC 8292) and aes128gcm payload encryption (RFC 8291)
through the `cryptography` library, with no custom cryptography. The VAPID key,
each account's settings and its device subscriptions are encrypted account
metadata (`push-vapid`, `push:<account>`). Payloads are readable only by the
subscribed browser. The push service sees the endpoint, size and timing, not
the text. Subscriptions are accepted only for HTTPS endpoints on Google,
Mozilla, Apple and Microsoft push services, so a request can never make the
gateway contact another host. An account keeps at most ten devices. A device
belongs to the account that subscribed it last; signing out unsubscribes it.
Push services' 404 or 410 answers remove the subscription. The `/api/push`
routes require a permanent password, the exact origin and the session CSRF
token. Sending runs in background threads and never affects the work it
reports.

## App tokens

Android app tokens are random 256-bit values, stored only as SHA-256 hashes in
the encrypted account metadata (`app-links:<account>`). A token can only read
the app summary and send secretary chat messages. Each account keeps at most
ten linked phones, and any of them can be unlinked from Settings at once.
Linking needs both a code the signed-in owner types and a pairing secret only
the phone holds (`app-pair:<hash>`, ten minutes). App requests carry no cookies,
so they skip the Origin and CSRF checks. Pairing requests, claims, code entries
and failed tokens are rate-limited per address or account. The token travels in
a header, never in a URL.

## Encryption and trust

Use gocryptfs for encrypted filenames and authenticated content encryption, not
custom cryptography. Keep account SQLite/session/rate counters in a root-only
encrypted `accounts` volume. Give each immutable account ID a separate encrypted
volume and Linux UID. Its secretary records, caches, temporary inputs, agent HOME,
OpenCode database/WAL/transcripts, OpenChamber state/logs and runtime files all
belong there. Readable mounts are 0700; unmounted fallback directories are root-only
and empty. Never put personal data in the shared read-only source/engine package.
Production account operations fail closed when the encrypted mount is absent.

SSH administrators are trusted. Mount keys stay root-readable (0600), separately
from ciphertext. This protects ciphertext copies/backups, not a compromised root
server holding its keys. Back up ciphertext and recovery keys separately; test
restoration privately. Do not claim encryption hides live data from administrators
or from an AI provider processing the request. Legacy trial originals are retained
where they already were; this does not retroactively encrypt or delete them.

Use HTTPS/TLS 1.2+ publicly. The gateway listens only on a root:www-data Unix
socket; NGINX overwrites trusted host/proxy/IP headers. Backends remain loopback-only
and require an independent random gateway key and allowlisted HTTPS origin.
Each agent has its own authenticated OpenChamber/OpenCode runtime. Never reuse a
shared agent UID/HOME/database across accounts or expose its UI/API publicly.
`scripts/goodmorning.py runtime` launches per-account engines and renews only rejected/expired
bridge authentication, not uncertain model requests. Shared installed binaries are
read-only bind mounts, with a reader-group ACL on public libraries only. No extra
engine downloads or library copies per account. The example engine service points
to this host's installation; adapt and verify paths on another host.

The gateway reserves one agent request globally before dispatch, shared by chat
and briefing generation. Confirmed pending questions, permissions and browser
feedback release that slot without aborting their sessions or discarding forms.
Users can take their time; forms and account-local activity links survive reloads.
Replies reacquire the slot through the FIFO queue before reaching the original
session. Queued answers remain encrypted and do not expire while waiting for
other work. An in-flight reply retains its reservation until dispatch is confirmed;
unknown dispatches stay blocked for SSH reconciliation rather than launching
duplicates. A five-second background check also advances work without browser
traffic. This is a bounded single-agent pilot, not a tested multi-agent load
capacity claim.

The Unix gateway listener keeps a 64-connection backlog for simultaneous browser
assets while retaining its 16-worker cap. An accepted connection waits at most
20 seconds for a worker; sustained overload receives a non-cacheable HTTP 503
without dispatch. This connection queue is separate from the durable secretary
work queue. Authentication, request-size checks and NGINX login rate limits are
unchanged; no mutation is replayed automatically on overload.

Disable access/body logs and disk proxy buffering. Private responses/media use
`no-store`; only public fingerprinted assets cache durably. The one deliberate
exception is the offline briefing copy (`docs/browser-delivery.md`, Offline
reading): the service worker keeps the latest morning and evening edition in the
browser's cache storage, tagged with an opaque per-account owner tag. Copies carry
no session, CSRF or request token, and are deleted at sign-out and as soon as the
site answers for nobody or another account. A device that is offline cannot check
its session, so a copy stays readable there until that happens.

Unsaved evening check-in answers, including the free-text note, are the one
private text in `localStorage` (`goodmorningCheckin:<scope>:<form>`), so a reload
or a visit to another page keeps them. `<scope>` is the public, non-authorizing
namespace the gateway derives from each sign-in's CSRF token; it changes with
every sign-in and password change. Briefing pages delete answers from any other
scope, answers older than three days and answers once saved. `auth.js` deletes
all of them when Sign out is pressed (even if the server cannot be reached), on
every load of the sign-in page and after each sign-in or password change. A
session that ends without the device taking part (it expires, or a password
change elsewhere signs it out) leaves its answers in the browser profile until
GoodMorning next opens there online; that load reaches the sign-in page and deletes
them. No other sign-in can read them in the meantime.

Credentials never enter
URLs, browser storage, command arguments or report output. Services use no core
dumps and `MemorySwapMax=0` on cgroup v2: otherwise decrypted memory may enter
unencrypted swap. Apply the same controls to per-account engines and NGINX workers.
Existing host swap is not reformatted or disabled by this deployment.

## Accounts

Coding agents provisioning a hosted user must follow the root-level
[server user guide](../SERVER-USER-GUIDE.md), including private random temporary
password generation and the complete isolated-backend readiness gate.

Passwords use scrypt N=131072, r=8, p=1 and independent salts (128 MiB per check).
New temporary and permanent passwords require 6–32 characters inclusive, at least
one letter and one digit; symbols are optional and no uppercase is required.
Unicode letters/digits are supported; length counts Unicode characters rather
than UTF-16 units. This shorter minimum is an explicit owner preference; longer
passwords remain safer. Existing passwords continue to authenticate and can be
replaced without forcing a reset or losing records.
Persistent account/IP attempt limits precede checks. Session cookies are random,
host-only `__Host-` cookies with Secure, HttpOnly and SameSite=Strict. The database
stores token hashes, not cookies. Ordinary sessions expire after 30 minutes idle
or 12 hours absolute. The unchecked-by-default remember option lasts at most 60
days without idle expiry; it remembers a revocable login token, never password
text. Current-password replacement preserves that choice while revoking all old
tokens. SSH resets/admin changes also revoke tokens; logout revokes the current
token. Login rotates the
anonymous cookie. Every mutation also requires the exact HTTPS Origin and the
authenticated session's CSRF token. CSP blocks external scripts and framing.

The same account logs into gm and gn independently; no parent-domain cookie is
shared with unrelated sibling services. Temporary passwords can access only the
password-change page until replaced. Forgotten passwords require SSH recovery.

```sh
sudo python3 /opt/goodmorning/current/scripts/goodmorning.py admin \
  --account-mount /srv/goodmorning/live/accounts create USERNAME
sudo python3 /opt/goodmorning/current/scripts/goodmorning.py admin \
  --account-mount /srv/goodmorning/live/accounts reset USERNAME
sudo python3 /opt/goodmorning/current/scripts/goodmorning.py admin \
  --account-mount /srv/goodmorning/live/accounts rename USERNAME --new-name NEWNAME
```

These read temporary passwords interactively with getpass, never through chat,
argv or environment dumps. `list`, `disable` and `enable` are SSH-only too. Names
are normalized ASCII, 3–40 characters; storage uses the immutable random ID, so
rename/reset never moves or loses records. New accounts are not connected to any
existing user's data: provision a new encrypted volume/UID and isolated backend.

Account creation is only the login step, not a working secretary. `create` and
`enable` return exit status 1 when the backend is not ready; the login row is
retained, so do not repeat `create` or reset a password to fix provisioning.
An unprovisioned login shows a localized setup-pending page with retry, language,
password-change and sign-out controls. Private APIs return 503 without reserving
or queuing an agent request. Backend outages also show a readable page rather
than a raw JSON document; no exception details or private paths reach the browser.

All future hosted users use the server-default AI configuration. The root-owned
`server-defaults.json` (mode 0600) in the encrypted accounts mount holds only
`model` (a website model ID), `providerID`, and `credential` (a native OpenCode
key credential). Never display this file or copy it into public source. Account
creation refuses missing or unsafe defaults before asking for a password or
creating a login, and saves the configured default model for each new account.
Existing account preferences are not rewritten. Website requests automatically
route by website language (English: Muse Spark Contributor XHigh; Chinese:
DeepSeek V4.1 Flash High, paid tier). The provisioning default does not override this routing;
saved legacy model preferences remain intact but no longer select new requests.

Before handing over an account, finish this SSH-only checklist:

1. Initialize its new encrypted vault once, assign a dedicated Linux UID, and
   create private engine/viewer configuration with fresh gateway and bridge keys.
2. Use `goodmorning.security.briefing_admin.server_defaults(store)` over SSH to
   load the encrypted server policy. Configure the new engine's default model
   and variant from `goodmorning.web.models.MODELS[defaults['model']]`, then
   connect only `defaults['credential']` for `defaults['providerID']` through the
   owning engine's authenticated native `POST /api/credential` API. Never pass
   keys on the command line or log request/response bodies. Do not ask new users
   for separate AI credentials or copy provider configuration from another user.
   Never clone another account's HOME, database, profile, conversations, relay
   identity, authentication cookies or settings files.
3. Install account/viewer identity drop-ins and enable its vault, engine and
   viewer services. Verify their encrypted mount, non-root identity and independent
   loopback ports; register only that immutable account ID's viewer port and key.
4. Run the read-only readiness gate and require exit status 0:

   ```sh
   sudo /opt/goodmorning/python/bin/python -B /opt/goodmorning/current/scripts/goodmorning.py admin \
     --account-mount /srv/goodmorning/live/accounts check-backend USERNAME --gm-host gm.love765.me
   ```

   It requests Morning, Evening and Secretary HTML without dispatching models,
   issuing login tokens or advancing the global queue. This proves the pages
   respond, not that a paid model call or user initialization has completed.
5. Confirm the provider connection and the offered model IDs separately through
   the owning engine's authenticated API. Model discovery is asynchronous after
   connecting a provider; wait using bounded read-only checks rather than
   reinitializing the vault or replaying credential creation. Leave personal setup to the account
   owner; an empty profile is not a reason to copy someone else's profile.

If login rejects an SSH-set password, use the SSH-only `check USERNAME` action with
the same flags. It reads a hidden password and reports only whether it matches the
saved hash, without changing the password, issuing a session or clearing rate limits.
Never send the password in chat or add a public password-check route.

## Provisioning and validation

`python scripts/goodmorning.py vault --root /srv/goodmorning init accounts` initializes the auth
volume without printing keys. Start `goodmorning-vault@accounts.service`, create
an account, then `init ACCOUNT_ID` and `user ACCOUNT_ID`. Do not rerun init over
existing paths. `deploy/` contains reviewed NGINX and gateway/vault service templates;
install only after checking the host's existing paths and configuration.
Install the included Certbot deploy hook for renewal-time NGINX reloads; issuing
a certificate alone does not make running workers reload renewed files.

The encrypted `backends.json` registry maps account IDs only to `{port,key}`. Ports
must be independent loopback backends. Provision the backend key privately inside
the account volume and pass `python scripts/goodmorning.py serve --gateway-key-file KEY
--public-origin https://gm.love765.me`.
Run the backend as that account's Linux UID, never root. NGINX cannot choose a
backend from query strings/usernames. The gateway does not forward browser cookies
or credentials upstream; it substitutes session-owned CSRF for the reader.

Per-account services bind encrypted temporary directories over both `/tmp` and
`/var/tmp` in their private mount namespaces. Setting `TMPDIR` alone cannot protect
libraries that hard-code either path. Engine and viewer share only their own
account's temporary directory; the host and other users retain separate views.

Unit tests use synthetic accounts with explicitly reduced test-only password cost.
Production refuses that reduction and unencrypted storage. Before release test:
three distinct accounts; cross-account file/job/API denial; password recovery and
session revocation; encrypted unmount/remount; reboot/service recovery; actual
public-domain generation and mobile rendering. Passing unit tests alone is not a
security audit or proof of production readiness. Physical devices, third-party
penetration testing, key rotation and disaster recovery remain deployment work.
