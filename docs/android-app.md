# Android app

`android/` is a small Trusted Web Activity (TWA) shell: Chrome shows the chosen
GoodMorning server full screen, without browser controls. The website does all
the work, so website deployments reach the app immediately. A new APK is needed
only when the shell changes: its screens, icon, name, permissions or the helper
library. The release APK is under 200 KB.

The app:

- asks for the server on first launch, prefilled with `https://gm.love765.me`.
  It accepts only an HTTPS origin whose `/.well-known/assetlinks.json` names
  `me.love765.goodmorning`. Long-pressing the icon offers "Change server" and
  Chrome's "Site Settings";
- opens `<server>/app`, which reopens the last page, or chat on the first visit
  (`docs/browser-delivery.md`, Installed app);
- shows website notifications as its own, through Chrome's notification
  delegation;
- offers home screen widgets once the phone is linked (below);
- updates itself from this repository's GitHub releases (below).

## Phones with and without Google services

Chrome's full-screen view needs Google services. Chrome verifies the site
through Google's Digital Asset Links service, which is blocked in mainland
China, and Chrome's Web Push travels through Google's FCM. `Device.chromeMode`
therefore uses Chrome only when Google Play services and a browser that
supports Trusted Web Activities are both present. Otherwise `WebActivity`
shows the server in the app's own WebView, which handles file uploads, back
navigation, external links in the browser, and edge-to-edge insets. Its user
agent includes `GoodMorningApp/<version>`, so the website still reopens the last
page and keeps notification settings visible. WebView has no Web Push, so on
these phones the linked app posts notifications itself (below).

## Linking and widgets

"Link this phone" (a launcher shortcut, or a tap on an unlinked widget) asks the
server for a pairing code. The owner enters it in Settings → Phone widgets, and
the app then claims its token (`docs/browser-delivery.md`, Phone widgets and app
linking). The token is encrypted with an AES key in the Android Keystore, and
unlinking in Settings makes the app forget it on its next check.

| Widget | Shows | Taps |
|---|---|---|
| Today's schedule | Today's events (time, until, place) and to-dos | Day schedule; refresh button |
| Week schedule | Seven days from today: events and to-do progress | That day's schedule |
| Secretary chat | Latest secretary conversation: title, state, start of the reply | Ask (dialog, may start paid model work), Open |

`Sync` reads `GET /api/app/sync` once per run and caches the answer for the
widgets. It runs when the app opens, after linking, from a widget's refresh
button, and every 15 minutes from a `JobScheduler` job that needs a network and
that Android batches with other work. A part the server cannot read keeps its
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

At launch (at most once a day) and from a daily `JobScheduler` job that runs
only when online, the app reads
`https://api.github.com/repos/S-Sebb/GoodMorning/releases?per_page=10`. It
looks for the highest non-draft, non-prerelease release tagged
`android-v<versionCode>` above its own code that has an `.apk` asset. When it
finds one:

- it posts one "Update available" notification, if notifications are allowed;
- the next cold launch, or a tap on the notification, shows Update / Later.
  Later waits a day.

Update first makes sure Android lets GoodMorning install apps; on the first
update it explains why and opens that setting. It then streams the APK into
Android's installer, which asks the user to confirm. On phones with Google Play
services, Play Protect may first offer to scan the sideloaded app. Nothing runs
in the background between checks.

## Releasing a new APK

Only when the owner asks. GitHub releases are public.

1. In a normal PR, raise `versionCode` by one and set `versionName` in
   `android/app/build.gradle`. The release title is shown to users as
   "GoodMorning <title> is ready", so use the `versionName` as the title.
2. After the merge, build from the primary checkout on an up-to-date `main` and
   publish:

   ```sh
   cd android && ./gradlew test assembleRelease
   cp app/build/outputs/apk/release/app-release.apk /tmp/opencode/GoodMorning-<versionName>.apk
   gh release create android-v<versionCode> /tmp/opencode/GoodMorning-<versionName>.apk \
     --title <versionName> --notes "<what changed, for users>"
   ```

Installed apps notice the release within a day. Website deployments use
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
