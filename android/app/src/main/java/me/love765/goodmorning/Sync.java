package me.love765.goodmorning;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.FileInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;

/** Reads the app summary from the server and keeps the widgets, status notifications and event reminders up to date. */
final class Sync {
    static final int JOB = 2;
    /** Extra checks while the account's work runs, so its notification and widgets follow soon after it ends. */
    static final int SOON = 3;
    private static final long PERIOD = 15 * 60 * 1000L;
    private static final long[] SOON_DELAYS = {30_000L, 60_000L, 120_000L, 240_000L};
    private static final Object LOCK = new Object();

    private Sync() {}

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences("sync", Context.MODE_PRIVATE);
    }

    private static File cache(Context context) {
        return new File(context.getFilesDir(), "sync.json");
    }

    /** The last summary the server sent, or an empty object. */
    static JSONObject cached(Context context) {
        try (FileInputStream in = new FileInputStream(cache(context))) {
            return new JSONObject(Server.read(in, 4 << 20));
        } catch (IOException | JSONException missing) {
            return new JSONObject();
        }
    }

    static boolean linked(Context context) {
        return Api.token(context) != null;
    }

    static void inBackground(Context context) {
        Context app = context.getApplicationContext();
        new Thread(() -> run(app)).start();
    }

    /** Runs every fifteen minutes while the phone is linked; Android batches it with other work. */
    static void schedule(Context context) {
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        if (!linked(context)) {
            scheduler.cancel(JOB);
            return;
        }
        if (scheduler.getPendingJob(JOB) != null) return;
        scheduler.schedule(new JobInfo.Builder(JOB, new ComponentName(context, SyncJob.class))
                .setPeriodic(PERIOD)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPersisted(true)
                .build());
    }

    static void run(Context context) {
        synchronized (LOCK) {
            String token = Api.token(context);
            if (token == null) {
                forget(context);
                return;
            }
            SharedPreferences prefs = prefs(context);
            long cursor = prefs.getLong("cursor", -1);
            JSONObject data;
            try {
                data = Api.sync(context, token, Math.max(cursor, 0));
            } catch (Api.Failure failure) {
                if (failure.status == 403) {
                    Api.forget(context);  // Unlinked in Settings: show the link prompt again.
                    forget(context);
                }
                return;
            } catch (IOException | JSONException offline) {
                return;  // The widgets keep showing the last summary.
            }
            try {
                JSONObject previous = cached(context);
                for (String part : new String[] {"schedule", "reminders", "chat", "briefings", "weather"}) {
                    if (data.isNull(part) && previous.has(part)) data.put(part, previous.get(part));
                }
                JSONArray notifications = (JSONArray) data.remove("notifications");
                data.put("synced", System.currentTimeMillis());
                write(context, data);
                long newest = Math.max(cursor, 0);
                for (int i = 0; i < notifications.length(); i++) newest = Math.max(newest, notifications.getJSONObject(i).getLong("seq"));
                // The first summary after linking only sets the starting point; old news stays quiet.
                if (cursor >= 0) post(context, notifications, cursor);
                Reminders.schedule(context, data);
                prefs.edit().putLong("cursor", newest).apply();
                if (busy(context)) soon(context, !prefs.contains("soon"));  // New work starts again at 30 seconds.
                else prefs.edit().remove("soon").apply();
                portrait(context, token, data.optJSONObject("secretary"));
            } catch (IOException | JSONException unreadable) {
                return;
            }
            try {
                Notes.sync(context, token);
            } catch (IOException | JSONException offline) {
                // Waiting notes stay on the phone; the next run sends them.
            }
            Widgets.updateAll(context);
        }
    }

    /** Keeps a small copy of an uploaded portrait for the chat widget; built-in ones ship with the app. */
    private static void portrait(Context context, String token, JSONObject secretary) {
        String path = secretary == null || secretary.isNull("image") ? "" : secretary.optString("image");
        SharedPreferences prefs = prefs(context);
        if (path.isEmpty() || path.equals(prefs.getString("portrait", ""))) return;
        try {
            byte[] data = Api.portrait(context, token, path);
            android.graphics.Bitmap image = android.graphics.BitmapFactory.decodeByteArray(data, 0, data.length);
            if (image == null) return;
            // A round crop, like the built-in portraits and the website's portrait badge.
            int side = Math.min(image.getWidth(), image.getHeight());
            android.graphics.Bitmap square = android.graphics.Bitmap.createBitmap(image, (image.getWidth() - side) / 2, (image.getHeight() - side) / 2, side, side);
            android.graphics.Bitmap small = android.graphics.Bitmap.createBitmap(128, 128, android.graphics.Bitmap.Config.ARGB_8888);
            android.graphics.Paint paint = new android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG);
            paint.setShader(new android.graphics.BitmapShader(android.graphics.Bitmap.createScaledBitmap(square, 128, 128, true),
                    android.graphics.Shader.TileMode.CLAMP, android.graphics.Shader.TileMode.CLAMP));
            new android.graphics.Canvas(small).drawCircle(64, 64, 64, paint);
            try (FileOutputStream out = new FileOutputStream(new File(context.getFilesDir(), "portrait.png"))) {
                small.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, out);
            }
            prefs.edit().putString("portrait", path).apply();
        } catch (IOException offline) {
            // The built-in portrait shows until the next check.
        }
    }

    static void forget(Context context) {
        cache(context).delete();
        new File(context.getFilesDir(), "portrait.png").delete();
        prefs(context).edit().clear().apply();
        context.getSystemService(JobScheduler.class).cancel(JOB);
        context.getSystemService(JobScheduler.class).cancel(SOON);
        context.getSystemService(JobScheduler.class).cancel(Notes.JOB);
        Notes.forgetSent(context);
        Reminders.cancelAll(context);
        Widgets.updateAll(context);
    }

    /** Whether the account's work runs, or a briefing of today is being prepared, by the last summary. */
    static boolean busy(Context context) {
        JSONObject data = cached(context);
        if (data.optBoolean("busy")) return true;
        JSONObject briefings = data.optJSONObject("briefings");
        JSONObject editions = briefings == null ? null : briefings.optJSONObject("editions");
        if (editions == null) return false;
        for (String kind : new String[] {"gm", "gn"}) {
            JSONObject edition = editions.optJSONObject(kind);
            if (edition != null && "working".equals(edition.optString("state"))) return true;
        }
        return false;
    }

    /**
     * Checks again soon: after 30 seconds, then one, two and every four minutes while the work lasts.
     * again replaces a waiting check, as when it just ran or new work started; otherwise it is kept.
     */
    static void soon(Context context, boolean again) {
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        if (!again && scheduler.getPendingJob(SOON) != null) return;
        SharedPreferences prefs = prefs(context);
        int step = prefs.getInt("soon", 0);
        prefs.edit().putInt("soon", step + 1).apply();
        scheduler.schedule(new JobInfo.Builder(SOON, new ComponentName(context, SyncJob.class))
                .setMinimumLatency(SOON_DELAYS[Math.min(step, SOON_DELAYS.length - 1)])
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .build());
    }

    /** The briefings widgets' Generate button: shows the edition as being prepared at once, then asks the server. */
    static void generate(Context context, String kind) {
        String token = Api.token(context);
        if (token == null) return;
        briefingState(context, kind, "working");
        try {
            Api.generate(context, token, kind);
        } catch (IOException | JSONException failed) {
            // Offline, or the server's queue is full: the widget offers the button again.
            briefingState(context, kind, "failed");
            return;
        }
        run(context);
    }

    private static void briefingState(Context context, String kind, String state) {
        try {
            JSONObject data = cached(context);
            JSONObject edition = data.getJSONObject("briefings").getJSONObject("editions").getJSONObject(kind);
            edition.put("state", state);
            write(context, data);
        } catch (IOException | JSONException ignored) {
            // No summary yet; the next one shows the state either way.
        }
        Widgets.updateAll(context);
    }

    /** Marks the latest conversation as waiting for its reply until the next summary arrives, which comes soon. */
    static void markSent(Context context, String chat) {
        prefs(context).edit().remove("soon").apply();
        soon(context, true);
        try {
            JSONObject data = cached(context);
            JSONObject summary = data.optJSONObject("chat");
            if (summary == null || !summary.optString("id").equals(chat)) summary = new JSONObject().put("id", chat == null ? "" : chat);
            data.put("chat", summary.put("state", "running").put("reply", ""));
            write(context, data);
        } catch (IOException | JSONException ignored) {
            // The next summary corrects the widget either way.
        }
        Widgets.updateAll(context);
    }

    private static void write(Context context, JSONObject data) throws IOException {
        File temporary = new File(context.getFilesDir(), "sync.json.tmp");
        try (FileOutputStream out = new FileOutputStream(temporary)) {
            out.write(data.toString().getBytes(StandardCharsets.UTF_8));
        }
        if (!temporary.renameTo(cache(context))) throw new IOException("Could not save the summary");
    }

    private static void post(Context context, JSONArray notifications, long cursor) throws JSONException {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (!manager.areNotificationsEnabled()) return;
        context = Language.apply(context);
        manager.createNotificationChannel(new NotificationChannel("status",
                context.getString(R.string.channel_status), NotificationManager.IMPORTANCE_DEFAULT));
        for (int i = 0; i < notifications.length(); i++) {
            JSONObject item = notifications.getJSONObject(i);
            if (item.getLong("seq") <= cursor) continue;
            manager.notify(item.optString("tag"), 1, new Notification.Builder(context, "status")
                    .setSmallIcon(R.drawable.ic_notification)
                    .setContentTitle(item.optString("title"))
                    .setContentText(item.optString("body"))
                    .setStyle(new Notification.BigTextStyle().bigText(item.optString("body")))
                    .setContentIntent(open(context, item.optString("url"), (int) item.getLong("seq")))
                    .setAutoCancel(true)
                    .build());
        }
    }

    /** Opens a page of the linked server in the app. */
    static PendingIntent open(Context context, String path, int request) {
        Intent intent = new Intent(context, Launcher.class)
                .setData(Uri.parse(Server.get(context) + (path.startsWith("/") ? path : "/app")))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        return PendingIntent.getActivity(context, request, intent, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    static Set<String> strings(SharedPreferences prefs, String key) {
        return new HashSet<>(prefs.getStringSet(key, new HashSet<>()));
    }
}
