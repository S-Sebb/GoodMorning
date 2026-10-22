package me.love765.goodmorning;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * Event reminders as alarms on the phone, for phones without Web Push: they fire on time even
 * offline, and need no server contact at all once scheduled.
 */
public class Reminders extends BroadcastReceiver {
    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences("reminders", Context.MODE_PRIVATE);
    }

    private static PendingIntent alarm(Context context, String key, JSONObject event) {
        Intent intent = new Intent(context, Reminders.class).setAction(key);
        if (event != null) {
            intent.putExtra("subject", event.optString("subject")).putExtra("time", event.optString("time"))
                    .putExtra("location", event.optString("location"));
        }
        return PendingIntent.getBroadcast(context, key.hashCode(), intent,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    static void schedule(Context context, JSONObject data) {
        JSONArray events = data.optJSONArray("reminders");
        JSONObject settings = data.optJSONObject("settings");
        if (events == null || settings == null) return;
        AlarmManager alarms = context.getSystemService(AlarmManager.class);
        SharedPreferences prefs = prefs(context);
        Set<String> scheduled = Sync.strings(prefs, "scheduled");
        Set<String> fired = Sync.strings(prefs, "fired");
        List<String> wanted = new ArrayList<>();
        long now = System.currentTimeMillis();
        long lead = settings.optLong("lead", 15) * 60_000L;
        if (settings.optBoolean("events", true)) {
            for (int i = 0; i < events.length(); i++) {
                JSONObject event = events.optJSONObject(i);
                String key = event.optString("key");
                long starts = (long) (event.optDouble("starts") * 1000);
                if (key.isEmpty() || starts <= now || fired.contains(key)) continue;
                wanted.add(key);
                PendingIntent intent = alarm(context, key, event);
                long at = Math.max(starts - lead, now);
                if (Build.VERSION.SDK_INT < 31 || alarms.canScheduleExactAlarms()) alarms.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, intent);
                else alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, intent);
            }
        }
        for (String key : scheduled) {
            if (!wanted.contains(key)) alarms.cancel(alarm(context, key, null));  // Moved, deleted or switched off.
        }
        prefs.edit().putStringSet("scheduled", new java.util.HashSet<>(wanted)).apply();
    }

    static void cancelAll(Context context) {
        AlarmManager alarms = context.getSystemService(AlarmManager.class);
        for (String key : Sync.strings(prefs(context), "scheduled")) alarms.cancel(alarm(context, key, null));
        prefs(context).edit().clear().apply();
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        String key = intent.getAction();
        SharedPreferences prefs = prefs(context);
        Set<String> fired = Sync.strings(prefs, "fired");
        if (key == null || fired.contains(key)) return;
        fired.add(key);
        if (fired.size() > 200) fired.remove(fired.iterator().next());
        prefs.edit().putStringSet("fired", fired).apply();
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (!manager.areNotificationsEnabled()) return;
        context = Language.apply(context);
        manager.createNotificationChannel(new NotificationChannel("reminders",
                context.getString(R.string.channel_reminders), NotificationManager.IMPORTANCE_HIGH));
        String location = intent.getStringExtra("location");
        String body = location == null || location.isEmpty()
                ? context.getString(R.string.reminder_body, intent.getStringExtra("time"))
                : context.getString(R.string.reminder_body_place, intent.getStringExtra("time"), location);
        manager.notify(key, 2, new Notification.Builder(context, "reminders")
                .setSmallIcon(R.drawable.ic_notification)
                .setContentTitle(intent.getStringExtra("subject"))
                .setContentText(body)
                .setCategory(Notification.CATEGORY_REMINDER)
                .setContentIntent(Sync.open(context, "/schedule?view=day", key.hashCode()))
                .setAutoCancel(true)
                .build());
    }
}
