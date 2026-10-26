# Android app

`android/` is a small shell around the phone's system WebView, which shows the
chosen GoodMorning server full screen. It uses no Chrome, Google Play services
or other libraries, so it works the same on phones without Google services, as
in mainland China. The website does all the work, so website deployments reach
the app immediately. A new APK is needed only when the shell changes: its
screens, widgets, icon, name or permissions. The release APK is about 340 KB.

The app is in beta, like the website: versions start at 0.1, and its releases
are GitHub pre-releases.

The app:

- asks for the server on first launch, prefilled with `https://gm.love765.me`.
  It accepts only an HTTPS origin whose `/.well-known/assetlinks.json` names
  `me.love765.goodmorning`. Long-pressing the icon offers "Change server";
- opens `<server>/app`, which reopens the last page, or chat on the first visit.
  Widgets and notifications open `/app?next=<page>`: the site signs the app in
  only through `/app` (`docs/browser-delivery.md`, Installed app);
- opens `https://gm.love765.me` links (verified App Links), through
  `/app?next=<page>`. A server chosen with "Change server" cannot be listed in
  the manifest;
- posts notifications itself once the phone is linked (below);
- offers home screen widgets once the phone is linked (below);
- updates itself from this repository's GitHub releases (below).

## The WebView

`WebActivity` shows the server in the app's own WebView, which handles file
uploads, back navigation, external links in the browser, and edge-to-edge insets.
When a page cannot load (no connection, or the server is down), it covers
WebView's error page with a can't-connect screen styled after the maintenance
page, with Try again; it also retries every 30 seconds while shown and on
returning to the app. Once the WebView has opened the signed-in site, its service
worker keeps the latest morning and evening briefings, and without a connection
the WebView shows those with an offline notice instead
(`docs/browser-delivery.md`, Offline reading). The can't-connect screen then
appears only when no copy is kept yet. This needs no app change: widgets keep
using `Sync`'s cache. Its user agent includes `GoodMorningApp/<version>`, so the
website reopens the last page and shows notification settings. WebView has no
Web Push, so the linked app posts notifications itself (below), with the choices
made in Settings on that phone. The user agent names the phone's link
(`GoodMorningLink/<id>`), and each summary request says that the app posts
notifications itself, so Account lists it among the devices with notifications.
The WebView writes its cookies to disk whenever the app leaves the screen, so a
remembered sign-in survives closing it.

Versions before 0.8 opened the site in Chrome's full-screen view (a Trusted Web
Activity) when Chrome could verify it through Google, and in the WebView
otherwise. A phone that last opened in Chrome kept its sign-in, colors and Web
Push subscription there. After the update:

- a linked phone signs the WebView in once with its app token
  (`POST /api/app/signin`), unless the WebView already has a sign-in; an
  unlinked one signs in by hand. A failure from being offline tries again at the
  next launch;
- the site gives the WebView the colors saved for the phone's link;
- the server removes the Chrome subscription and keeps its choices for the
  phone (`docs/browser-delivery.md`, Notifications);
- the launcher drops Chrome's "Site Settings" shortcut.

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
desk icons, the secretary's portrait and name, and the day and night color
schemes chosen on this phone (`Palette`, copied from `assets/web/color-schemes.css`),
switched with the phone's dark mode. On Android 12 and newer the launcher
switches them itself; older versions use the colors of the mode at drawing time.
The app opens the site at `/app?link=<id>`, so colors chosen in the app are
saved for its link (`docs/browser-delivery.md`, Settings and Account) and reach
the widgets when the app leaves the screen. Until the phone chooses colors,
widgets use the account's earlier choice.

The launcher's widget list shows each widget's `widget_preview_*` layout: the
real layout filled with a sample Thursday, in the default Morning Sky and Starry
schemes, switched with dark mode. Their hourly charts are `WeatherChart` layers
saved as `drawable-nodpi/preview_chart_*` (axis layers with period names also in
`drawable-zh-rCN-nodpi`). A change to a widget's look needs the same change in
its preview.
Once the phone is linked, widgets, the screens they open and the app's own
notifications use the account's website language (`Language`), not the phone's;
a change reaches them with the next sync. The launcher's widget list and the
screens before linking follow the phone.

| Widget | Default size | Shows | Taps |
|---|---|---|---|
| Today's schedule | 4×4 | Today's events (time, until, place) and to-dos | ○/✓ of a to-do: ticks it done or back (below); elsewhere: day schedule; refresh button |
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
grid. The Briefings widget shows the morning edition from 04:00 and the
evening edition from 17:00 until 04:00, like the website's briefing day; a
choice in the widget holds until the clock passes the next switch.

The weather widgets read the server's 18-hour forecast frame (06:00–24:00, or
18:00 to noon after 18:00; `docs/weather-pipeline.md`). `WeatherFrame` works out
the headlines from the hours after now, so they move on between syncs;
`WeatherChart` draws each chart as two white layers (accent and muted) that the
widget tints, since the launcher switches day and night colors without
redrawing. Tiles keep the website's weather colors in both modes. A frame that
has run out shows the loading or unavailable message until the next sync.

### Ticking to-dos

In the Today's schedule widget, a tap on a to-do's ○ or ✓ ticks it done or back,
as on the Schedule page (`docs/weekly-schedule.md`, Ticking to-dos): a one-off
task is finished as a whole, a recurring task or habit only for today, and ✓
restores exactly the state before. Only rows the server marks `tickable` (planned
to-dos and habits) tick; the rest of the row, other rows and events open the day
schedule. The tap goes to `RowActivity`, which has no window and is not exported,
so the home screen stays as it is and no other app can tick through it. It sends
`POST /api/app/schedule/tick` with the app token and nothing is saved on the phone
first: the mark changes when the server answers, and a sync follows. When the save
fails (offline, or the to-do changed), the mark stays and a toast says
"Couldn’t save. Open GoodMorning to try again."

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
widgets. It runs when the app opens or leaves the screen, after linking, from a
widget's refresh button, and every 15 minutes from a `JobScheduler` job that
needs a network and that Android batches with other work. While the account's
work runs or waits in the queue (`busy`), or a briefing is being prepared, an
extra job checks again after 30 seconds, then one, two and every four minutes
until it ends. A message sent from the chat widget starts these checks at once.
Android's battery saving (Doze) and some phone makers' background limits can
hold them back until the phone wakes. A part the server cannot read keeps its
last value. A 403 means the phone was unlinked: the app forgets its token and the
widgets show the link prompt.

The same run also:

- posts status notifications (briefing ready, needs your answer, reply
  finished, briefing not prepared yet) newer than its last check, usually within a few minutes. The first
  check after linking only records where to start;
- schedules each timed event in the next 24 hours as an exact alarm at its
  start minus the account's lead time. Reminders fire on time even offline,
  each once; moved or deleted events lose their alarms on the next check.

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

The server picker refuses a server that does not serve the app's
`assetlinks.json`. To test the update flow without publishing a release, point
a temporary debug build's `RELEASES_URL` at a local feed. That needs a debug-only
`usesCleartextTraffic` manifest overlay; remove both afterwards.
