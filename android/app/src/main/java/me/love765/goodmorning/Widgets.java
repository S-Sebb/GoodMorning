package me.love765.goodmorning;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.text.format.DateFormat;
import android.view.View;
import android.widget.RemoteViews;

import org.json.JSONObject;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.Locale;

/** Home screen widgets drawn from the last summary the app received; see {@link Sync}. */
public abstract class Widgets extends AppWidgetProvider {
    private static final String REFRESH = "me.love765.goodmorning.REFRESH";

    /** Today's events and to-dos. */
    public static class Today extends Widgets {
        @Override
        RemoteViews draw(Context context, int id) {
            return super.list(context, id, "today");
        }
    }

    /** Seven days from today. */
    public static class Week extends Widgets {
        @Override
        RemoteViews draw(Context context, int id) {
            return super.list(context, id, "week");
        }
    }

    /** The latest secretary conversation, with Ask and Open. */
    public static class Chat extends Widgets {
        @Override
        RemoteViews draw(Context context, int id) {
            RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_chat);
            // Text from layouts follows the launcher's language; the app's own language must be set here.
            views.setTextViewText(R.id.open, context.getString(R.string.chat_open));
            views.setTextViewText(R.id.ask, context.getString(R.string.chat_ask));
            if (!Sync.linked(context)) {
                views.setTextViewText(R.id.title, context.getString(R.string.widget_chat_name));
                views.setTextViewText(R.id.state, "");
                views.setTextViewText(R.id.reply, context.getString(R.string.widget_link));
                views.setViewVisibility(R.id.actions, View.GONE);
                views.setOnClickPendingIntent(R.id.root, screen(context, LinkActivity.class));
                return views;
            }
            JSONObject chat = Sync.cached(context).optJSONObject("chat");
            String identifier = chat == null ? "" : chat.optString("id");
            String reply = chat == null ? "" : chat.optString("reply");
            String state = chat == null ? "" : chat.optString("state");
            views.setTextViewText(R.id.title, chat == null || chat.optString("title").isEmpty()
                    ? context.getString(R.string.chat_title_default) : chat.optString("title"));
            views.setTextViewText(R.id.state, "running".equals(state) ? context.getString(R.string.chat_working)
                    : "waiting".equals(state) ? context.getString(R.string.chat_waiting) : "");
            views.setTextViewText(R.id.reply, reply.isEmpty() && !"running".equals(state) ? context.getString(R.string.chat_empty) : reply);
            views.setViewVisibility(R.id.actions, View.VISIBLE);
            String page = identifier.isEmpty() ? "/chat" : "/chat?id=" + identifier;
            views.setOnClickPendingIntent(R.id.root, Sync.open(context, page, 1000 + id));
            views.setOnClickPendingIntent(R.id.open, Sync.open(context, page, 2000 + id));
            views.setOnClickPendingIntent(R.id.ask, screen(context, AskActivity.class));
            return views;
        }
    }

    abstract RemoteViews draw(Context context, int id);

    @Override
    public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        for (int id : ids) manager.updateAppWidget(id, draw(context, id));
        manager.notifyAppWidgetViewDataChanged(ids, R.id.list);
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        super.onReceive(context, intent);
        if (!REFRESH.equals(intent.getAction())) return;
        PendingResult pending = goAsync();
        new Thread(() -> {
            try {
                Sync.run(context.getApplicationContext());
            } finally {
                pending.finish();
            }
        }).start();
    }

    /** Redraws every widget of every kind, for example after a new summary. */
    static void updateAll(Context context) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        for (Widgets kind : new Widgets[] {new Today(), new Week(), new Chat()}) {
            int[] ids = manager.getAppWidgetIds(new ComponentName(context, kind.getClass()));
            if (ids.length > 0) kind.onUpdate(context, manager, ids);
        }
    }

    private static PendingIntent screen(Context context, Class<?> activity) {
        return PendingIntent.getActivity(context, activity.getName().hashCode(),
                new Intent(context, activity).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE);
    }

    static String day(String date, boolean weekday) {
        String pattern = DateFormat.getBestDateTimePattern(Locale.getDefault(), weekday ? "EEEMMMd" : "MMMd");
        return LocalDate.parse(date).format(DateTimeFormatter.ofPattern(pattern, Locale.getDefault()));
    }

    RemoteViews list(Context context, int id, String kind) {
        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_list);
        views.setTextViewText(R.id.link, context.getString(R.string.widget_link));
        views.setContentDescription(R.id.refresh, context.getString(R.string.widget_refresh));
        boolean linked = Sync.linked(context);
        JSONObject schedule = Sync.cached(context).optJSONObject("schedule");
        String today = schedule == null ? "" : schedule.optString("today");
        views.setTextViewText(R.id.title, "today".equals(kind)
                ? (today.isEmpty() ? context.getString(R.string.widget_today_name) : context.getString(R.string.widget_today_title, day(today, true)))
                : context.getString(R.string.widget_week_name));
        views.setViewVisibility(R.id.list, linked ? View.VISIBLE : View.GONE);
        views.setViewVisibility(R.id.refresh, linked ? View.VISIBLE : View.GONE);
        views.setViewVisibility(R.id.link, linked ? View.GONE : View.VISIBLE);
        views.setViewVisibility(R.id.empty, View.GONE);
        if (!linked) {
            views.setOnClickPendingIntent(R.id.root, screen(context, LinkActivity.class));
            return views;
        }
        Intent service = new Intent(context, ListService.class).putExtra("kind", kind)
                .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id);
        service.setData(Uri.parse(service.toUri(Intent.URI_INTENT_SCHEME)));  // One adapter per widget.
        views.setRemoteAdapter(R.id.list, service);
        views.setTextViewText(R.id.empty, context.getString(schedule == null ? R.string.widget_loading
                : "today".equals(kind) ? R.string.widget_empty_today : R.string.widget_empty_week));
        views.setEmptyView(R.id.list, R.id.empty);
        String page = "today".equals(kind) ? "/schedule?view=day" : "/schedule";
        views.setOnClickPendingIntent(R.id.title, Sync.open(context, page, 3000 + id));
        // Rows fill in their own page; the template must stay mutable for that.
        Intent template = new Intent(context, Launcher.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        views.setPendingIntentTemplate(R.id.list, PendingIntent.getActivity(context, 4000 + id, template,
                PendingIntent.FLAG_MUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        Intent refresh = new Intent(context, getClass()).setAction(REFRESH);
        views.setOnClickPendingIntent(R.id.refresh, PendingIntent.getBroadcast(context, 5000 + id, refresh, PendingIntent.FLAG_IMMUTABLE));
        return views;
    }
}
