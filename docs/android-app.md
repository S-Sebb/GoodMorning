# Android app

`android/` is a small Trusted Web Activity (TWA) shell: Chrome shows the chosen
GoodMorning server full screen, without browser controls. The website does all
the work, so website deployments reach the app immediately. A new APK is needed
only when the shell changes: its screens, widgets, icon, name, permissions or
the helper library. The release APK is about 320 KB.

The app is in beta, like the website: versions start at 0.1, and its releases
are GitHub pre-releases.

The app:

- asks for the server on first launch, prefilled with `https://gm.love765.me`.
  It accepts only an HTTPS origin whose `/.well-known/assetlinks.json` names
  `me.love765.goodmorning`. Long-pressing the icon offers "Change server" and
  Chrome's "Site Settings";
- opens `<server>/app`, which reopens the last page, or chat on the first visit.
  Widgets and notifications open `/app?next=<page>`: the site signs the app in
  only through `/app` (`docs/browser-delivery.md`, Installed app);
- shows website notifications as its own, through Chrome's notification
  delegation. Chrome delegates only to an app that opens the site's links, so
  the app opens `https://gm.love765.me` links (verified App Links), through
  `/app?next=<page>`. A server chosen with "Change server" cannot be listed in
  the manifest, so its notifications stay Chrome's;
- offers home screen widgets once the phone is linked (below);
- updates itself from this repository's GitHub releases (below).

## Phones with and without Google services

Chrome's full-screen view needs Google services. Chrome verifies the site
through Google's Digital Asset Links service, which is blocked in mainland
China, and Chrome's Web Push travels through Google's FCM. The app therefore
uses Chrome itself (`com.android.chrome`), never the phone's default browser:
other browsers, such as some phone makers' own, may claim to support the
full-screen view yet open an ordinary tab with an address bar.

At each launch, when Google Play services and Chrome are both present,
`Launcher` asks Chrome to verify the site and waits up to six seconds, showing
the splash screen. Chrome answers from its cache after the first check. Only a
verified site opens in Chrome; otherwise, for example where Google's service is
unreachable, `WebActivity` shows the server in the app's own WebView, which handles file uploads, back
navigation, external links in the browser, and edge-to-edge insets. When a page
cannot load (no connection, or the server is down), it covers WebView's error page
with a can't-connect screen styled after the maintenance page, with Try again; it
also retries every 30 seconds while shown and on returning to the app. Chrome's
full-screen view shows Chrome's own offline page. Its user
agent includes `GoodMorningApp/<version>`, so the website still reopens the last
page and keeps notification settings visible. WebView has no Web Push, so on
these phones, and while Chrome cannot verify the site, the linked app posts
notifications itself (below), with the choices made in Settings on that phone.
The WebView's user agent names the phone's link (`GoodMorningLink/<id>`), and
each summary request says whether the app posts notifications itself, so
Account lists it among the devices with notifications. The WebView writes its cookies to disk whenever
the app leaves the screen, so a remembered sign-in survives closing it.

## Linking and widgets

"Link this phone" (a launcher shortcut, or a tap on an unlinked widget) asks the
server for a pairing code. The owner taps "Link in GoodMorning", which opens the
site with the code filled in to confirm, or copies the code ("Copy code") or types
it in Account → Linked phones on any device. The app then claims its token
(`docs/browser-delivery.md`, Linked phones and app linking). `Pairing` keeps the code until it expires, so the screen shows the
same code however often it opens. While a code waits, the app checks for its
token every three seconds, also with the screen closed, and again whenever the
app or the link screen opens. The token is encrypted with an AES key in the Android Keystore, and
unlinking in Settings makes the app forget it on its next check.

Widgets follow the website's look: serif headings, small uppercase labels, the
desk icons, the secretary's portrait and name, and the account's chosen day and
night color schemes (`Palette`, copied from `assets/web/color-schemes.css`),
switched with the phone's dark mode. On Android 12 and newer the launcher
switches them itself; older versions use the colors of the mode at drawing time.
Once the phone is linked, widgets, the screens they open and the app's own
notifications use the account's website language (`Language`), not the phone's;
a change reaches them with the next sync. The launcher's widget list and the
screens before linking follow the phone.

| Widget | Default size | Shows | Taps |
|---|---|---|---|
| Today's schedule | 4×4 | Today's events (time, until, place) and to-dos | Day schedule; refresh button |
| Week schedule | 4×5 | Seven days from today: events and to-do progress | That day's schedule |
| Secretary chat | 4×3 | Portrait and name, latest conversation title, its reply in a bubble, and a message box | Message box: Ask (dialog, may start paid model work); elsewhere: the conversation |
| Secretary | 1×1, fixed | The portrait alone, with an accent dot while a reply runs or waits for an answer | The latest conversation |
| Briefings | 4×5 | Today's morning or evening briefing in full, scrolling, with a Morning/Evening switch | The briefing page; Prepare button (starts generation at once, may start paid model work); refresh button |
| News | 4×4 | The news sections of today's morning briefing, one card per story: headline, a three-line summary and its publishers | The morning briefing at its first news section (`/gm.html?section=news`); Prepare button while it is missing |
| Weather | 4×2 | Temperature, rain and air headlines side by side, from the live forecast | The morning briefing's Weather section (`/gm.html?section=weather`); refresh button |
| Weather details | 4×5 | The three headlines, each beside its hourly chart | As Weather |
| Temperature, Rain, Air quality | 4×2 each | One headline above its hourly chart | As Weather |
| Quick note | 4×4 | The newest quick note as a taped sticky note, up to five earlier notes' first lines behind it (fewer when smaller), its state and a Sort pill | The note or a title: that note; +: a new note; Sort: sorts the notes with the secretary (paid model work) and opens that conversation |

Every widget but Secretary can be resized. Launchers hide a widget whose minimum size exceeds
their grid, so minimum sizes stay small and the defaults fit the common 4×5
grid. The Briefings widget shows the morning edition before 17:00 and the
evening edition from then on; a choice in the widget holds until the clock
passes the next switch.

The weather widgets read the server's 18-hour forecast frame (06:00–24:00, or
18:00 to noon after 18:00; `docs/weather-pipeline.md`). `WeatherFrame` works out
the headlines from the hours after now, so they move on between syncs;
`WeatherChart` draws each chart as two white layers (accent and muted) that the
widget tints, since the launcher switches day and night colors without
redrawing. Tiles keep the website's weather colors in both modes. A frame that
has run out shows the loading or unavailable message until the next sync.

### Quick notes

The Quick note widget, and the launcher shortcut of the same name, open
`NoteActivity`: the note over the dimmed (Android 12+: blurred) home screen, with
the keyboard up. There is no Save button. `Notes` keeps every note in
`notes.bin`, AES-GCM encrypted with its own Android Keystore key, 300 ms after
typing pauses and whenever the screen closes, so leaving in any way, or the app
being killed, keeps it. Only + starts a new note; the first line, cut with "…",
is its title. The paper takes the scheme's warm colour (mixed into near-black on
night schemes); Pixel style makes it square and upright, with stepped tape; the
writing screen's label also uses the pixel font, which widgets cannot load.

A note waits on the phone until the server confirms it (`POST /api/app/note`,
`docs/browser-delivery.md`). Each sync run sends waiting notes and then reads the
server's list; a `JobScheduler` job that needs a network sends them as soon as
the phone is online. A note written while linked belongs to that link: after
unlinking it stays on the phone as "Not sent" and never goes to another account.
One written unlinked goes to the next link. Unlinking forgets the sent copies,
which stay on the server.

Notes are never sorted automatically. "Sort N notes with NAME" appears while
notes are unsorted or edited since sorting; it sends any waiting notes, starts
the sorting conversation (`POST /api/app/notes/sort`) and opens it in the app.

`Sync` reads `GET /api/app/sync` once per run and caches the answer for the
widgets. It runs when the app opens, after linking, from a widget's refresh
button, and every 15 minutes from a `JobScheduler` job that needs a network and
that Android batches with other work. While a briefing is being prepared, an
extra job checks again after three minutes, then further apart, until it is
saved or stops. A part the server cannot read keeps its
last value. A 403 means the phone was unlinked: the app forgets its token and the
widgets show the link prompt.

On phones without Google services, the same run also:

- posts status notifications (briefing ready, needs your answer, reply
  finished) newer than its last check, so they arrive up to about 15 minutes
  late. The first check after linking only records where to start;
- schedules each timed event in the next 24 hours as an exact alarm at its
  start minus the account's lead time. Reminders fire on time even offline,
  each once; moved or deleted events lose their alarms on the next check.

Phones with Google services get these through Web Push instead, when turned on
in Settings, so nothing is shown twice.

No `android/` file is deployed to the server; the deployment archive keeps only
the top-level names in `deploy/deploy_native.py`.

## Toolchain and release key

Everything lives outside the repository, under `~/.local/share/goodmorning-android/`:

| Path | Contents |
|---|---|
| `toolchain/jdk` | Temurin JDK 21 |
| `toolchain/sdk` | Android SDK (platform 36, build tools, emulator, Android 36 Play Store image) |
| `release.keystore`, `keystore-password.txt` | Release signing key (alias `goodmorning`) and its password, mode 0600 |

The owner must back up the keystore and its password. Android installs an
update only when it carries the same signature, and every server's
`assetlinks.json` lists this key's SHA-256 fingerprint. Without the key,
existing installs cannot be updated: users would have to uninstall, and the
fingerprint would have to change. Never commit, print or upload the key or
its password.

```sh
export JAVA_HOME=~/.local/share/goodmorning-android/toolchain/jdk
export ANDROID_HOME=~/.local/share/goodmorning-android/toolchain/sdk
cd android
./gradlew test               # unit tests: address parsing and release selection
./gradlew assembleRelease    # app/build/outputs/apk/release/app-release.apk, signed
```

## Updates

The GoodMorning server reads
`https://api.github.com/repos/S-Sebb/GoodMorning/releases?per_page=10` at most
every ten minutes and answers `GET /api/app/release` with the highest published
release, pre-releases included, tagged `android-v<versionCode>` with a GitHub
`.apk` asset (`app_release.py`). Phones never need GitHub's API, only the APK
download.

The app asks its server at every launch (unless it asked in the last ten
minutes) and from an hourly `JobScheduler` job that runs only when online. When
it finds a higher build:

- it posts one "Update available" notification, if notifications are allowed;
- the next cold launch, or a tap on the notification, shows Update / Later.
  Later waits a day.

The website inside the app offers the same update. Each launch opens
`/app?app=<versionCode>`, and the server keeps that build in the
`GoodMorningApp` cookie. In the app, the website's update pill then reads
"App update" when `/api/app/release` is higher, opens the patch notes with
"GoodMorning app <version> is ready" once per release, and its Update app button
opens `goodmorning://update`, the app's own update screen (no Later delay
there). Website releases in the app read "Refresh" and say the app itself needs
no update, so they are never mistaken for an app update. Browsers keep the usual
wording.

Update first makes sure Android lets GoodMorning install apps; on the first
update it explains why and opens that setting. It then streams the APK into
Android's installer, which asks the user to confirm. On phones with Google Play
services, Play Protect may first offer to scan the sideloaded app.

Versions 0.1 and 0.2 still read GitHub directly, once a day; they find 0.3 that
way, and from 0.3 on updates come through the server.

## Releasing a new APK

Only when the owner asks. GitHub releases are public.

1. In a normal PR, raise `versionCode` by one and set `versionName` in
   `android/app/build.gradle`. The release title is shown to users as
   "GoodMorning <title> is ready", so use the `versionName` as the title.
   While the app is in beta, `versionName` stays below 1.0. Codes 1 and 2 were
   the withdrawn 1.0 and 1.1 releases; 0.1 is code 3.
2. After the merge, build from the primary checkout on an up-to-date `main` and
   publish:

   ```sh
   cd android && ./gradlew test assembleRelease
   cp app/build/outputs/apk/release/app-release.apk /tmp/opencode/GoodMorning-<versionName>.apk
   gh release create android-v<versionCode> /tmp/opencode/GoodMorning-<versionName>.apk \
     --prerelease --title <versionName> --notes "<what changed, for users>"
   ```

Installed apps from 0.3 on notice the release within about ten minutes of their next launch, or within the hour in the background (the server caches the list for up to ten minutes). Website deployments use
`deploy/<name>` tags, not releases, so the two never mix.

## Testing on the emulator

```sh
export ANDROID_AVD_HOME=~/.local/share/goodmorning-android/avd
$ANDROID_HOME/emulator/emulator -avd gmtest -no-window -no-audio -gpu swiftshader_indirect &
$ANDROID_HOME/platform-tools/adb install -r app/build/outputs/apk/release/app-release.apk
```

The `gmtest` image includes Chrome. To skip Chrome's first-run screens on the
emulator, write `_ --disable-fre --no-first-run --no-default-browser-check`
to `/data/local/tmp/chrome-command-line` and run
`adb shell am set-debug-app --persistent com.android.chrome`. Chrome verifies
the site through Google's Digital Asset Links service. A server that does not
serve the app's `assetlinks.json` opens with a browser address bar, and the
picker refuses it. To test the update flow without publishing a release, point
a temporary debug build's `RELEASES_URL` at a local feed. That needs a debug-only
`usesCleartextTraffic` manifest overlay; remove both afterwards.
