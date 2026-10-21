package me.love765.goodmorning;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.os.Bundle;
import android.text.format.DateFormat;
import android.view.View;
import android.widget.RemoteViews;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.Locale;

/** Home screen widgets drawn from the last summary the app received; see {@link Sync}. */
public abstract class Widgets extends AppWidgetProvider {
    private static final String REFRESH = "me.love765.goodmorning.REFRESH";
    private static final String EDITION = "me.love765.goodmorning.EDITION";
    private static final String GENERATE = "me.love765.goodmorning.GENERATE";
    /** Before this hour the briefings widget opens on the morning edition, from it on the evening one. */
    private static final int EVENING = 17;

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

    /** The latest secretary conversation, with the composer that opens Ask. */
    public static class Chat extends Widgets {
        @Override
        RemoteViews draw(Context context, int id) {
            // As many whole reply lines as the widget's height holds, so text never stops mid-line.
            // Portrait phones report their height as the maximum; small widgets drop the title.
            Bundle size = AppWidgetManager.getInstance(context).getAppWidgetOptions(id);
            int height = size.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 180);
            boolean compact = height < 190;
            int lines = Math.max(1, Math.min(12, (height - (compact ? 150 : 176)) / 18));
            RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_chat);
            views.setInt(R.id.reply, "setMaxLines", lines);
            views.setViewVisibility(R.id.title, compact ? View.GONE : View.VISIBLE);
            Palette[] schemes = Palette.of(context);
            card(context, views, schemes, p -> p.border, p -> p.paper);
            Palette.tint(context, views, schemes, R.id.portrait_ring, p -> p.wash);
            Palette.tint(context, views, schemes, R.id.bubble_border, p -> p.bubbleLine);
            Palette.tint(context, views, schemes, R.id.bubble_fill, p -> p.bubble);
            Palette.tint(context, views, schemes, R.id.field_border, p -> p.border);
            Palette.tint(context, views, schemes, R.id.field_fill, p -> p.surface);
            Palette.tint(context, views, schemes, R.id.send_circle, p -> p.ink);
            Palette.tint(context, views, schemes, R.id.send_icon, p -> p.surface);
            Palette.text(context, views, schemes, R.id.label, p -> p.muted);
            Palette.text(context, views, schemes, R.id.name, p -> p.ink);
            Palette.text(context, views, schemes, R.id.title, p -> p.ink);
            Palette.text(context, views, schemes, R.id.state, p -> p.accent);
            Palette.text(context, views, schemes, R.id.reply, p -> p.ink);
            Palette.text(context, views, schemes, R.id.placeholder, p -> p.muted);

            JSONObject data = Sync.cached(context);
            JSONObject secretary = data.optJSONObject("secretary");
            String name = secretary == null || secretary.optString("name").isEmpty() || secretary.isNull("name")
                    ? context.getString(R.string.chat_name_default) : secretary.optString("name");
            views.setTextViewText(R.id.label, context.getString(R.string.chat_label).toUpperCase(Locale.getDefault()));
            views.setTextViewText(R.id.name, name);
            portrait(context, views, secretary);
            views.setTextViewText(R.id.placeholder, context.getString(R.string.chat_placeholder, name));
            if (!Sync.linked(context)) {
                views.setTextViewText(R.id.title, "");
                views.setTextViewText(R.id.state, "");
                views.setTextViewText(R.id.reply, context.getString(R.string.widget_link));
                views.setViewVisibility(R.id.composer, View.GONE);
                views.setOnClickPendingIntent(R.id.root, screen(context, LinkActivity.class));
                return views;
            }
            JSONObject chat = data.optJSONObject("chat");
            String identifier = chat == null ? "" : chat.optString("id");
            String state = chat == null ? "" : chat.optString("state");
            String reply = chat == null ? "" : chat.optString("reply");
            views.setTextViewText(R.id.title, chat == null ? "" : chat.optString("title"));
            views.setTextViewText(R.id.state, "running".equals(state) ? context.getString(R.string.chat_working, name)
                    : "waiting".equals(state) ? context.getString(R.string.chat_waiting, name) : "");
            views.setViewVisibility(R.id.state, "running".equals(state) || "waiting".equals(state) ? View.VISIBLE : View.GONE);
            views.setTextViewText(R.id.reply, reply.isEmpty() && !"running".equals(state) ? context.getString(R.string.chat_empty, name) : reply);
            views.setViewVisibility(R.id.composer, View.VISIBLE);
            String page = identifier.isEmpty() ? "/chat" : "/chat?id=" + identifier;
            views.setOnClickPendingIntent(R.id.root, Sync.open(context, page, 1000 + id));
            views.setOnClickPendingIntent(R.id.composer, screen(context, AskActivity.class));
            return views;
        }
    }

    /** Today's morning or evening briefing, switched in the widget. */
    public static class Briefing extends Widgets {
        @Override
        RemoteViews draw(Context context, int id) {
            return briefing(context, id, edition(context, id), false);
        }
    }

    /** The news sections of today's morning briefing. */
    public static class News extends Widgets {
        @Override
        RemoteViews draw(Context context, int id) {
            return briefing(context, id, "gm", true);
        }
    }

    abstract RemoteViews draw(Context context, int id);

    @Override
    public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        for (int id : ids) manager.updateAppWidget(id, draw(context, id));
        manager.notifyAppWidgetViewDataChanged(ids, R.id.list);
    }

    @Override
    public void onAppWidgetOptionsChanged(Context context, AppWidgetManager manager, int id, Bundle options) {
        manager.updateAppWidget(id, draw(context, id));  // Resized: fit the content again.
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        super.onReceive(context, intent);
        String action = intent.getAction();
        if (EDITION.equals(action)) {
            int id = intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, 0);
            choose(context, id, intent.getStringExtra("edition"));
            AppWidgetManager manager = AppWidgetManager.getInstance(context);
            manager.updateAppWidget(id, draw(context, id));
            manager.notifyAppWidgetViewDataChanged(id, R.id.list);
            return;
        }
        if (!REFRESH.equals(action) && !GENERATE.equals(action)) return;
        PendingResult pending = goAsync();
        new Thread(() -> {
            try {
                if (GENERATE.equals(action)) Sync.generate(context.getApplicationContext(), intent.getStringExtra("edition"));
                else Sync.run(context.getApplicationContext());
            } finally {
                pending.finish();
            }
        }).start();
    }

    /** Redraws every widget of every kind, for example after a new summary. */
    static void updateAll(Context context) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        for (Widgets kind : new Widgets[] {new Today(), new Week(), new Chat(), new Briefing(), new News()}) {
            int[] ids = manager.getAppWidgetIds(new ComponentName(context, kind.getClass()));
            if (ids.length > 0) kind.onUpdate(context, manager, ids);
        }
    }

    private static SharedPreferences choices(Context context) {
        return context.getSharedPreferences("widgets", Context.MODE_PRIVATE);
    }

    /** Morning or evening by the clock; a choice in the widget holds until the clock passes the next switch. */
    static String edition(Context context, int id) {
        SharedPreferences prefs = choices(context);
        String chosen = prefs.getString("edition" + id, null);
        boolean evening = LocalTime.now().getHour() >= EVENING;
        return chosen != null && prefs.getString("period" + id, "").equals(period()) ? chosen : evening ? "gn" : "gm";
    }

    private static void choose(Context context, int id, String edition) {
        choices(context).edit().putString("edition" + id, "gn".equals(edition) ? "gn" : "gm").putString("period" + id, period()).apply();
    }

    private static String period() {
        return LocalDate.now() + (LocalTime.now().getHour() >= EVENING ? "pm" : "am");
    }

    /** A broadcast to this widget's provider; the data keeps each widget's and edition's intents apart. */
    private PendingIntent action(Context context, String action, int id, String edition) {
        Intent intent = new Intent(context, getClass()).setAction(action).setData(Uri.parse("widget:" + id + "/" + edition))
                .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id).putExtra("edition", edition);
        return PendingIntent.getBroadcast(context, id, intent, PendingIntent.FLAG_IMMUTABLE);
    }

    private static PendingIntent screen(Context context, Class<?> activity) {
        return PendingIntent.getActivity(context, activity.getName().hashCode(),
                new Intent(context, activity).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE);
    }

    /** The rounded card with its 1dp border, both in the account's colors. */
    static void card(Context context, RemoteViews views, Palette[] schemes, Palette.Pick border, Palette.Pick fill) {
        Palette.tint(context, views, schemes, R.id.card_border, border);
        Palette.tint(context, views, schemes, R.id.card_fill, fill);
    }

    /** The account's portrait: a built-in secretary, or the uploaded one once the app has it. */
    private static void portrait(Context context, RemoteViews views, JSONObject secretary) {
        String avatar = secretary == null ? "f1" : secretary.optString("avatar", "f1");
        File custom = new File(context.getFilesDir(), "portrait.png");
        if ("custom".equals(avatar) && custom.exists()) {
            Bitmap image = BitmapFactory.decodeFile(custom.getPath());
            if (image != null) {
                views.setImageViewBitmap(R.id.portrait, image);
                return;
            }
        }
        int resource = "f2".equals(avatar) ? R.drawable.portrait_f2 : "m1".equals(avatar) ? R.drawable.portrait_m1
                : "m2".equals(avatar) ? R.drawable.portrait_m2 : R.drawable.portrait_f1;
        views.setImageViewResource(R.id.portrait, resource);
    }

    static String day(String date, String skeleton) {
        String pattern = DateFormat.getBestDateTimePattern(Locale.getDefault(), skeleton);
        return LocalDate.parse(date).format(DateTimeFormatter.ofPattern(pattern, Locale.getDefault()));
    }

    RemoteViews list(Context context, int id, String kind) {
        boolean today = "today".equals(kind);
        RemoteViews views = new RemoteViews(context.getPackageName(), today ? R.layout.widget_today : R.layout.widget_week);
        Palette[] schemes = Palette.of(context);
        card(context, views, schemes, p -> p.line, p -> p.surface);
        Palette.tint(context, views, schemes, R.id.rule, p -> p.line);
        Palette.tint(context, views, schemes, R.id.refresh, p -> p.muted);
        Palette.text(context, views, schemes, R.id.label, p -> p.muted);
        Palette.text(context, views, schemes, R.id.title, p -> p.ink);
        Palette.text(context, views, schemes, R.id.empty, p -> p.muted);
        Palette.text(context, views, schemes, R.id.link, p -> p.ink);
        views.setContentDescription(R.id.refresh, context.getString(R.string.widget_refresh));

        JSONObject schedule = Sync.cached(context).optJSONObject("schedule");
        JSONArray days = schedule == null ? null : schedule.optJSONArray("days");
        views.setTextViewText(R.id.label, context.getString(today ? R.string.widget_label_today : R.string.widget_label_week)
                .toUpperCase(Locale.getDefault()));
        String title = context.getString(today ? R.string.widget_today_name : R.string.widget_week_name);
        if (days != null && days.length() > 0) {
            String first = days.optJSONObject(0).optString("date");
            title = today ? day(first, "EEEEMMMMd")
                    : context.getString(R.string.widget_week_range, day(first, "MMMd"), day(days.optJSONObject(days.length() - 1).optString("date"), "MMMd"));
        }
        views.setTextViewText(R.id.title, title);
        boolean linked = Sync.linked(context);
        views.setViewVisibility(R.id.list, linked ? View.VISIBLE : View.GONE);
        views.setViewVisibility(R.id.refresh, linked ? View.VISIBLE : View.GONE);
        views.setViewVisibility(R.id.link, linked ? View.GONE : View.VISIBLE);
        views.setTextViewText(R.id.link, context.getString(R.string.widget_link));
        if (!linked) {
            views.setOnClickPendingIntent(R.id.root, screen(context, LinkActivity.class));
            return views;
        }
        Intent service = new Intent(context, ListService.class).putExtra("kind", kind)
                .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id);
        service.setData(Uri.parse(service.toUri(Intent.URI_INTENT_SCHEME)));  // One adapter per widget.
        views.setRemoteAdapter(R.id.list, service);
        views.setTextViewText(R.id.empty, context.getString(schedule == null ? R.string.widget_loading
                : today ? R.string.widget_empty_today : R.string.widget_empty_week));
        views.setEmptyView(R.id.list, R.id.empty);
        String page = today ? "/schedule?view=day" : "/schedule";
        views.setOnClickPendingIntent(R.id.title, Sync.open(context, page, 3000 + id));
        // Rows fill in their own page; the template must stay mutable for that.
        Intent template = new Intent(context, Launcher.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        views.setPendingIntentTemplate(R.id.list, PendingIntent.getActivity(context, 4000 + id, template,
                PendingIntent.FLAG_MUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        Intent refresh = new Intent(context, getClass()).setAction(REFRESH);
        views.setOnClickPendingIntent(R.id.refresh, PendingIntent.getBroadcast(context, 5000 + id, refresh, PendingIntent.FLAG_IMMUTABLE));
        return views;
    }

    RemoteViews briefing(Context context, int id, String kind, boolean news) {
        boolean morning = "gm".equals(kind);
        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_briefing);
        Palette[] schemes = Palette.of(context);
        card(context, views, schemes, p -> p.line, p -> p.surface);
        Palette.tint(context, views, schemes, R.id.rule, p -> p.line);
        Palette.tint(context, views, schemes, R.id.refresh, p -> p.muted);
        Palette.tint(context, views, schemes, R.id.icon, p -> p.accent);
        Palette.text(context, views, schemes, R.id.label, p -> p.muted);
        Palette.text(context, views, schemes, R.id.title, p -> p.ink);
        Palette.text(context, views, schemes, R.id.empty_text, p -> p.muted);
        Palette.tint(context, views, schemes, R.id.generate_fill, p -> p.ink);
        Palette.text(context, views, schemes, R.id.generate_text, p -> p.surface);
        views.setContentDescription(R.id.refresh, context.getString(R.string.widget_refresh));
        views.setImageViewResource(R.id.icon, news ? R.drawable.ic_news : morning ? R.drawable.ic_morning : R.drawable.ic_evening);
        views.setTextViewText(R.id.label, context.getString(news ? R.string.news_label : morning ? R.string.briefing_label_gm : R.string.briefing_label_gn)
                .toUpperCase(Locale.getDefault()));
        JSONObject briefings = Sync.cached(context).optJSONObject("briefings");
        String date = briefings == null ? "" : briefings.optString("date");
        views.setTextViewText(R.id.title, date.isEmpty() ? context.getString(news ? R.string.widget_news_name : R.string.widget_briefing_name)
                : day(date, "EEEEMMMMd"));
        // The chosen edition is a filled pill, as in the website's edition switch.
        views.setViewVisibility(R.id.editions, news ? View.GONE : View.VISIBLE);
        for (String option : new String[] {"gm", "gn"}) {
            boolean chosen = option.equals(kind);
            int fill = "gm".equals(option) ? R.id.pick_gm_fill : R.id.pick_gn_fill;
            int text = "gm".equals(option) ? R.id.pick_gm_text : R.id.pick_gn_text;
            Palette.tint(context, views, schemes, fill, chosen ? (p -> p.ink) : (p -> p.wash));
            Palette.text(context, views, schemes, text, chosen ? (p -> p.surface) : (p -> p.ink));
            views.setTextViewText(text, context.getString("gm".equals(option) ? R.string.briefing_morning : R.string.briefing_evening));
            views.setOnClickPendingIntent("gm".equals(option) ? R.id.pick_gm : R.id.pick_gn, action(context, EDITION, id, option));
        }
        boolean linked = Sync.linked(context);
        views.setViewVisibility(R.id.refresh, linked ? View.VISIBLE : View.GONE);
        if (!linked) {
            views.setViewVisibility(R.id.list, View.GONE);
            views.setViewVisibility(R.id.empty, View.VISIBLE);
            views.setViewVisibility(R.id.generate, View.GONE);
            views.setTextViewText(R.id.empty_text, context.getString(R.string.widget_link));
            views.setOnClickPendingIntent(R.id.root, screen(context, LinkActivity.class));
            return views;
        }
        JSONObject editions = briefings == null ? null : briefings.optJSONObject("editions");
        JSONObject edition = editions == null ? null : editions.optJSONObject(kind);
        String state = edition == null ? "" : edition.optString("state");
        int message = edition == null ? R.string.briefing_loading
                : "ready".equals(state) ? R.string.news_none
                : "missing".equals(state) ? (news ? R.string.news_missing : morning ? R.string.briefing_missing_gm : R.string.briefing_missing_gn)
                : "waiting".equals(state) ? R.string.briefing_waiting
                : "stopped".equals(state) ? R.string.briefing_stopped
                : "failed".equals(state) ? R.string.briefing_failed : R.string.briefing_working;
        views.setTextViewText(R.id.empty_text, context.getString(message));
        boolean offer = "missing".equals(state) || "failed".equals(state);
        views.setViewVisibility(R.id.generate, offer ? View.VISIBLE : View.GONE);
        views.setTextViewText(R.id.generate_text, context.getString(morning ? R.string.briefing_generate_gm : R.string.briefing_generate_gn));
        views.setOnClickPendingIntent(R.id.generate, action(context, GENERATE, id, kind));
        Intent service = new Intent(context, ListService.class).putExtra("kind", news ? "news" : "briefing")
                .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id);
        service.setData(Uri.parse(service.toUri(Intent.URI_INTENT_SCHEME)));  // One adapter per widget.
        views.setRemoteAdapter(R.id.list, service);
        views.setEmptyView(R.id.list, R.id.empty);
        String page = "/" + kind + ".html" + (news ? "?section=news" : "");
        views.setOnClickPendingIntent(R.id.header, Sync.open(context, page, 3000 + id));
        views.setOnClickPendingIntent(R.id.empty, Sync.open(context, page, 6000 + id));
        Intent template = new Intent(context, Launcher.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        views.setPendingIntentTemplate(R.id.list, PendingIntent.getActivity(context, 4000 + id, template,
                PendingIntent.FLAG_MUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        views.setOnClickPendingIntent(R.id.refresh, action(context, REFRESH, id, kind));
        return views;
    }
}
