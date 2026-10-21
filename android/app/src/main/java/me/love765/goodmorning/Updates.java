package me.love765.goodmorning;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Finds newer APKs among the GitHub releases tagged android-v{versionCode}. Checks run when the
 * app opens (at most once a day) and from {@link UpdateJob}. A found update is offered on the next
 * launch and, when notifications are allowed, announced once as a notification.
 */
final class Updates {
    static final long DAY = 24 * 60 * 60 * 1000L;
    private static final Pattern TAG = Pattern.compile("android-v(\\d+)");

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

    /** The saved newer release, unless the user chose Later within the last day. */
    static Release pending(Context context) {
        SharedPreferences prefs = prefs(context);
        int code = prefs.getInt("code", 0);
        if (code <= BuildConfig.VERSION_CODE || System.currentTimeMillis() < prefs.getLong("snoozed", 0) + DAY) return null;
        return new Release(code, prefs.getString("name", ""), prefs.getString("apk", ""));
    }

    static void snooze(Context context) {
        prefs(context).edit().putLong("snoozed", System.currentTimeMillis()).apply();
    }

    static void checkInBackground(Context context) {
        Context app = context.getApplicationContext();
        UpdateJob.schedule(app);
        if (System.currentTimeMillis() < prefs(app).getLong("checked", 0) + DAY) return;
        new Thread(() -> check(app)).start();
    }

    static void check(Context context) {
        try {
            Release latest = latest();
            SharedPreferences prefs = prefs(context);
            SharedPreferences.Editor edit = prefs.edit().putLong("checked", System.currentTimeMillis());
            if (latest != null && latest.code > prefs.getInt("code", 0)) {
                edit.putInt("code", latest.code).putString("name", latest.name).putString("apk", latest.apk);
                notify(context, latest);
            }
            edit.apply();
        } catch (IOException | JSONException | RuntimeException ignored) {
            // Offline or rate limited: the next launch or daily check tries again.
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

    private static Release latest() throws IOException, JSONException {
        HttpURLConnection connection = (HttpURLConnection) new URL(BuildConfig.RELEASES_URL).openConnection();
        connection.setConnectTimeout(10000);
        connection.setReadTimeout(10000);
        connection.setRequestProperty("Accept", "application/vnd.github+json");
        JSONArray releases;
        try {
            if (connection.getResponseCode() != 200) throw new IOException("Release check failed");
            releases = new JSONArray(Server.read(connection.getInputStream(), 1 << 20));
        } finally {
            connection.disconnect();
        }
        return newest(releases, BuildConfig.VERSION_CODE);
    }

    /** The highest android-v{code} release above current that has an APK, or null. */
    static Release newest(JSONArray releases, int current) throws JSONException {
        Release best = null;
        for (int i = 0; i < releases.length(); i++) {
            JSONObject release = releases.getJSONObject(i);
            Matcher tag = TAG.matcher(release.optString("tag_name"));
            if (release.optBoolean("draft") || release.optBoolean("prerelease") || !tag.matches()) continue;
            int code = Integer.parseInt(tag.group(1));
            if (code <= current || (best != null && code <= best.code)) continue;
            JSONArray assets = release.getJSONArray("assets");
            for (int j = 0; j < assets.length(); j++) {
                String url = assets.getJSONObject(j).optString("browser_download_url");
                if (url.endsWith(".apk")) {
                    String name = release.optString("name");
                    best = new Release(code, name.isEmpty() ? tag.group() : name, url);
                    break;
                }
            }
        }
        return best;
    }
}
