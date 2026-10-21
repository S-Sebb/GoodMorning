package me.love765.goodmorning;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * Finds newer APKs through the GoodMorning server, which reads the GitHub releases tagged
 * android-v{versionCode}. Checks run when the app opens and hourly from {@link UpdateJob}. A found
 * update is offered on the next launch, in the website's update pill, and, when notifications are
 * allowed, once as a notification.
 */
final class Updates {
    static final long DAY = 24 * 60 * 60 * 1000L;
    /** Releases come often while the app is in beta, so every launch checks unless one just did. */
    private static final long GAP = 10 * 60 * 1000L;

    /** A release newer than this build. */
    static final class Release {
        final int code;
        final String name;
        final String apk;

        Release(int code, String name, String apk) {
            this.code = code;
            this.name = name;
            this.apk = apk;
        }
    }

    private Updates() {}

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences("updates", Context.MODE_PRIVATE);
    }

    /** The saved newer release, unless the user chose Later within the last day and did not ask again. */
    static Release pending(Context context, boolean asked) {
        SharedPreferences prefs = prefs(context);
        int code = prefs.getInt("code", 0);
        boolean snoozed = System.currentTimeMillis() < prefs.getLong("snoozed", 0) + DAY;
        if (code <= BuildConfig.VERSION_CODE || (snoozed && !asked)) return null;
        return new Release(code, prefs.getString("name", ""), prefs.getString("apk", ""));
    }

    static void snooze(Context context) {
        prefs(context).edit().putLong("snoozed", System.currentTimeMillis()).apply();
    }

    static void checkInBackground(Context context) {
        Context app = context.getApplicationContext();
        UpdateJob.schedule(app);
        if (System.currentTimeMillis() < prefs(app).getLong("checked", 0) + GAP) return;
        new Thread(() -> check(app)).start();
    }

    static void check(Context context) {
        try {
            Release latest = latest(context);
            SharedPreferences prefs = prefs(context);
            SharedPreferences.Editor edit = prefs.edit().putLong("checked", System.currentTimeMillis());
            if (latest != null && latest.code > prefs.getInt("code", 0)) {
                edit.putInt("code", latest.code).putString("name", latest.name).putString("apk", latest.apk);
                notify(context, latest);
            }
            edit.apply();
        } catch (IOException | JSONException | RuntimeException ignored) {
            // Offline: the next launch or hourly check tries again.
        }
    }

    private static void notify(Context context, Release release) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (!manager.areNotificationsEnabled()) return;
        manager.createNotificationChannel(new NotificationChannel("updates",
                context.getString(R.string.update_channel), NotificationManager.IMPORTANCE_DEFAULT));
        PendingIntent open = PendingIntent.getActivity(context, 0, new Intent(context, UpdateActivity.class),
                PendingIntent.FLAG_IMMUTABLE);
        manager.notify(1, new Notification.Builder(context, "updates")
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(context.getString(R.string.update_title))
                .setContentText(context.getString(R.string.update_notification, release.name))
                .setContentIntent(open)
                .setAutoCancel(true)
                .build());
    }

    /** Asks the GoodMorning server, which reads this repository's releases, so phones need no GitHub API access. */
    private static Release latest(Context context) throws IOException, JSONException {
        String server = Server.get(context);
        if (server == null) return null;
        HttpURLConnection connection = (HttpURLConnection) new URL(server + "/api/app/release").openConnection();
        connection.setConnectTimeout(10000);
        connection.setReadTimeout(10000);
        try {
            if (connection.getResponseCode() != 200) throw new IOException("Release check failed");
            return newer(new JSONObject(Server.read(connection.getInputStream(), 1 << 16)), BuildConfig.VERSION_CODE);
        } finally {
            connection.disconnect();
        }
    }

    /** The server's newest release when it is above current and its APK comes from GitHub; otherwise null. */
    static Release newer(JSONObject release, int current) {
        int code = release.optInt("code");
        String apk = release.optString("apk");
        if (code <= current || !apk.startsWith("https://github.com/") || !apk.endsWith(".apk")) return null;
        String name = release.optString("name");
        return new Release(code, name.isEmpty() ? String.valueOf(code) : name, apk);
    }
}
