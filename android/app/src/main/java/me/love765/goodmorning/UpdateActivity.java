package me.love765.goodmorning;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.widget.ProgressBar;
import android.widget.Toast;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * Offers a newer APK, downloads it and hands it to Android's installer, which asks the user to
 * confirm. Android accepts it only when it is signed with this app's release key.
 */
public class UpdateActivity extends Activity {
    private AlertDialog dialog;
    private ProgressBar progress;
    private Updates.Release release;
    /** Opened from the website's update pill (goodmorning://update) rather than at launch. */
    private boolean asked;

    @Override
    protected void attachBaseContext(Context base) {
        super.attachBaseContext(Language.apply(base));
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (installed(getIntent())) return;
        asked = getIntent().getData() != null;
        release = Updates.pending(this, asked);
        if (release != null) {
            offer();
        } else if (!asked) {
            openSite();
        } else {
            // The website may know of a release before this phone's last check: check now.
            new Thread(() -> {
                Updates.check(this);
                runOnUiThread(() -> {
                    release = Updates.pending(this, true);
                    if (release != null) {
                        offer();
                    } else {
                        Toast.makeText(this, R.string.update_current, Toast.LENGTH_SHORT).show();
                        finish();
                    }
                });
            }).start();
        }
    }

    private void offer() {
        dialog = new AlertDialog.Builder(this, R.style.Dialog)
                .setTitle(R.string.update_title)
                .setMessage(getString(R.string.update_message, release.name))
                .setPositiveButton(R.string.update_install, (d, which) -> start())
                .setNegativeButton(R.string.update_later, (d, which) -> later())
                .setCancelable(false)
                .show();
    }

    /** Later waits a day at launch; from the website it simply returns there. */
    private void later() {
        if (!asked) Updates.snooze(this);
        openSite();
    }

    /** Android allows installing only after the user lets this app install apps, once. */
    private void start() {
        if (getPackageManager().canRequestPackageInstalls()) {
            download();
            return;
        }
        dialog = new AlertDialog.Builder(this, R.style.Dialog)
                .setTitle(R.string.update_title)
                .setMessage(R.string.update_permission)
                .setPositiveButton(R.string.update_continue, (d, which) -> startActivityForResult(
                        new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getPackageName())), 1))
                .setNegativeButton(R.string.update_later, (d, which) -> later())
                .setCancelable(false)
                .show();
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (getPackageManager().canRequestPackageInstalls()) download();
        else failed();
    }

    private void download() {
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setPadding(64, 32, 64, 0);
        dialog = new AlertDialog.Builder(this, R.style.Dialog)
                .setTitle(R.string.update_downloading)
                .setView(progress)
                .setCancelable(false)
                .show();
        new Thread(() -> {
            try {
                install();
            } catch (IOException | RuntimeException error) {
                runOnUiThread(this::failed);
            }
        }).start();
    }

    /** Streams the APK straight into an installer session, so it never lands in shared storage. */
    private void install() throws IOException {
        PackageInstaller installer = getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        params.setAppPackageName(getPackageName());
        int id = installer.createSession(params);
        try (PackageInstaller.Session session = installer.openSession(id)) {
            HttpURLConnection connection = (HttpURLConnection) new URL(release.apk).openConnection();
            connection.setConnectTimeout(15000);
            connection.setReadTimeout(30000);
            try {
                if (connection.getResponseCode() != 200) throw new IOException("Download failed");
                long size = connection.getContentLengthLong();
                try (InputStream in = connection.getInputStream(); OutputStream out = session.openWrite("update.apk", 0, size)) {
                    byte[] buffer = new byte[65536];
                    long done = 0;
                    for (int n; (n = in.read(buffer)) != -1; ) {
                        out.write(buffer, 0, n);
                        done += n;
                        if (size > 0) {
                            int percent = (int) (done * 100 / size);
                            runOnUiThread(() -> progress.setProgress(percent));
                        }
                    }
                    session.fsync(out);
                }
            } finally {
                connection.disconnect();
            }
            Intent result = new Intent(this, UpdateActivity.class).setAction("installed");
            PendingIntent callback = PendingIntent.getActivity(this, 0, result,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_MUTABLE);
            session.commit(callback.getIntentSender());
        } catch (IOException | RuntimeException error) {
            installer.abandonSession(id);
            throw error;
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        installed(intent);
    }

    /** Handles the installer's answer; returns false for any other intent. */
    @SuppressWarnings("deprecation") // The typed getParcelableExtra needs API 33.
    private boolean installed(Intent intent) {
        if (!"installed".equals(intent.getAction())) return false;
        int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            // Android's own confirmation screen, including "allow installs from this app" the first time.
            startActivity((Intent) intent.getParcelableExtra(Intent.EXTRA_INTENT));
        } else if (status != PackageInstaller.STATUS_SUCCESS) {
            failed();
        }
        return true;
    }

    private void failed() {
        if (isFinishing()) return;
        if (dialog != null) dialog.dismiss();
        Updates.snooze(this);
        dialog = new AlertDialog.Builder(this, R.style.Dialog)
                .setMessage(R.string.update_failed)
                .setPositiveButton(R.string.update_continue, (d, which) -> openSite())
                .setCancelable(false)
                .show();
    }

    /** Back to GoodMorning: the website below when it asked for this screen, otherwise a fresh launch. */
    private void openSite() {
        if (!asked) startActivity(Launcher.start(this));
        finish();
    }
}
