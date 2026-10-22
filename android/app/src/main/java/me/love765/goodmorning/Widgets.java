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
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.time.format.TextStyle;

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
            views.setTextViewText(R.id.label, context.getString(R.string.chat_label).toUpperCase(Language.of(context)));
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
            String state = chat == null ? "" : chat.optString("state");
            String reply = chat == null ? "" : chat.optString("reply");
            views.setTextViewText(R.id.title, chat == null ? "" : chat.optString("title"));
            views.setTextViewText(R.id.state, "running".equals(state) ? context.getString(R.string.chat_working, name)
                    : "waiting".equals(state) ? context.getString(R.string.chat_waiting, name) : "");
            views.setViewVisibility(R.id.state, "running".equals(state) || "waiting".equals(state) ? View.VISIBLE : View.GONE);
            views.setTextViewText(R.id.reply, reply.isEmpty() && !"running".equals(state) ? context.getString(R.string.chat_empty, name) : reply);
            views.setViewVisibility(R.id.composer, View.VISIBLE);
            views.setOnClickPendingIntent(R.id.root, Sync.open(context, conversation(chat), 1000 + id));
            views.setOnClickPendingIntent(R.id.composer, screen(context, AskActivity.class));
            return views;
        }
    }

    /** Just the secretary's portrait, with a dot while a reply runs or waits; opens the latest conversation. */
    public static class Portrait extends Widgets {
        @Override
        RemoteViews draw(Context context, int id) {
            RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_portrait);
            Palette[] schemes = Palette.of(context);
            Palette.tint(context, views, schemes, R.id.portrait_ring, p -> p.wash);
            Palette.tint(context, views, schemes, R.id.dot_ring, p -> p.surface);
            Palette.tint(context, views, schemes, R.id.dot_fill, p -> p.accent);

            JSONObject data = Sync.cached(context);
            JSONObject secretary = data.optJSONObject("secretary");
            String name = secretary == null || secretary.optString("name").isEmpty() || secretary.isNull("name")
                    ? context.getString(R.string.chat_name_default) : secretary.optString("name");
            portrait(context, views, secretary);
            if (!Sync.linked(context)) {
                views.setViewVisibility(R.id.dot, View.GONE);
                views.setContentDescription(R.id.root, context.getString(R.string.widget_link));
                views.setOnClickPendingIntent(R.id.root, screen(context, LinkActivity.class));
                return views;
            }
            JSONObject chat = data.optJSONObject("chat");
            String state = chat == null ? "" : chat.optString("state");
            boolean busy = "running".equals(state) || "waiting".equals(state);
            views.setViewVisibility(R.id.dot, busy ? View.VISIBLE : View.GONE);
            views.setContentDescription(R.id.root, "running".equals(state) ? context.getString(R.string.chat_working, name)
                    : "waiting".equals(state) ? context.getString(R.string.chat_waiting, name)
                    : context.getString(R.string.portrait_open, name));
            views.setOnClickPendingIntent(R.id.root, Sync.open(context, conversation(chat), 1000 + id));
            return views;
        }
    }

    /** The chat page at the latest conversation, if there is one. */
    private static String conversation(JSONObject chat) {
        String identifier = chat == null ? "" : chat.optString("id");
        return identifier.isEmpty() ? "/chat" : "/chat?id=" + identifier;
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

    /** Temperature, rain and air headlines side by side. */
    public static class Weather extends Widgets {
        @Override
        RemoteViews draw(Context context, int id) {
            return weather(context, id, null, false, size(context, id));
        }
    }

    /** The three weather tiles with their hourly charts. */
    public static class WeatherFull extends Widgets {
        @Override
        RemoteViews draw(Context context, int id) {
            return weather(context, id, null, true, size(context, id));
        }
    }

    public static class Temperature extends Widgets {
        @Override
        RemoteViews draw(Context context, int id) {
            return weather(context, id, WeatherChart.Kind.TEMPERATURE, true, size(context, id));
        }
    }

    public static class Rain extends Widgets {
        @Override
        RemoteViews draw(Context context, int id) {
            return weather(context, id, WeatherChart.Kind.RAIN, true, size(context, id));
        }
    }

    public static class Air extends Widgets {
        @Override
        RemoteViews draw(Context context, int id) {
            return weather(context, id, WeatherChart.Kind.AIR, true, size(context, id));
        }
    }

    /** The newest quick note as a sticky note, with up to five earlier notes peeking out behind it. */
    public static class QuickNote extends Widgets {
        private static final int[][] TABS = {
                {R.id.tab1, R.id.tab1_fill, R.id.tab1_title, R.id.tab1_time}, {R.id.tab2, R.id.tab2_fill, R.id.tab2_title, R.id.tab2_time},
                {R.id.tab3, R.id.tab3_fill, R.id.tab3_title, R.id.tab3_time}, {R.id.tab4, R.id.tab4_fill, R.id.tab4_title, R.id.tab4_time},
                {R.id.tab5, R.id.tab5_fill, R.id.tab5_title, R.id.tab5_time}};

        @Override
        RemoteViews draw(Context context, int id) {
            boolean pixel = Palette.pixel(context);
            RemoteViews views = new RemoteViews(context.getPackageName(), pixel ? R.layout.widget_note_pixel : R.layout.widget_note);
            Palette[] schemes = Palette.of(context);
            views.setImageViewResource(R.id.note_fill, pixel ? R.drawable.note_square : R.drawable.note_paper);
            views.setImageViewResource(R.id.note_shadow, pixel ? R.drawable.note_square : R.drawable.note_shadow);
            views.setImageViewResource(R.id.tape, pixel ? R.drawable.note_tape_pixel : R.drawable.note_tape);
            if (pixel) {
                Palette.tint(context, views, schemes, R.id.note_shadow, p -> p.border);
                for (int shape : new int[] {R.id.add_fill, R.id.chip_fill, R.id.sort_fill}) views.setImageViewResource(shape, R.drawable.note_square);
            }
            Palette.tint(context, views, schemes, R.id.note_fill, p -> p.note);
            Palette.tint(context, views, schemes, R.id.tape, p -> p.tape);
            views.setInt(R.id.tape, "setImageAlpha", 210);
            Palette.tint(context, views, schemes, R.id.add_fill, p -> p.ink);
            Palette.tint(context, views, schemes, R.id.add_icon, p -> p.note);
            Palette.tint(context, views, schemes, R.id.chip_fill, p -> p.surface);
            Palette.tint(context, views, schemes, R.id.sort_fill, p -> p.ink);
            Palette.text(context, views, schemes, R.id.sort_text, p -> p.note);
            Palette.text(context, views, schemes, R.id.label, p -> p.muted);
            views.setContentDescription(R.id.add, context.getString(R.string.note_new));
            views.setOnClickPendingIntent(R.id.add, NoteActivity.fresh(context));
            portrait(context, views, Sync.cached(context).optJSONObject("secretary"));

            // Each earlier title takes 24dp; the front note keeps room for at least three lines.
            int height = AppWidgetManager.getInstance(context).getAppWidgetOptions(id).getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 280);
            int fit = Math.max(0, Math.min(TABS.length, (height - 200) / 24));
            java.util.List<Notes.Note> notes = Notes.visible(context);
            boolean stacked = fit > 0 && notes.size() > 1;
            views.setViewVisibility(R.id.tabs, stacked ? View.VISIBLE : View.GONE);
            views.setViewVisibility(R.id.tape, stacked ? View.GONE : View.VISIBLE);  // It would cover the nearest title.
            for (int i = 0; i < TABS.length; i++) {
                int[] tab = TABS[i];
                Notes.Note earlier = i + 1 < notes.size() && i < fit ? notes.get(i + 1) : null;
                views.setViewVisibility(tab[0], earlier == null ? View.GONE : View.VISIBLE);
                if (earlier == null) continue;
                views.setImageViewResource(tab[1], pixel ? R.drawable.note_square : R.drawable.note_tab);
                Palette.tint(context, views, schemes, tab[1], i % 2 == 0 ? (p -> p.noteBehind) : (p -> p.noteBack));
                Palette.text(context, views, schemes, tab[2], p -> p.ink);
                Palette.text(context, views, schemes, tab[3], p -> p.muted);
                views.setTextViewText(tab[2], earlier.text.split("\n", 2)[0]);
                views.setTextViewText(tab[3], Notes.shortWhen(context, earlier.created));
                views.setOnClickPendingIntent(tab[0], NoteActivity.open(context, earlier.id));
            }
            Notes.Note front = notes.isEmpty() ? null : notes.get(0);
            String label = front == null ? context.getString(R.string.note_label) : Notes.when(context, front.created);
            views.setTextViewText(R.id.label, label.toUpperCase(Language.of(context)));
            views.setTextViewText(R.id.text, front == null ? context.getString(R.string.note_empty) : front.text);
            Palette.text(context, views, schemes, R.id.text, front == null ? (p -> p.muted) : (p -> p.ink));
            views.setInt(R.id.text, "setMaxLines", Math.max(2, (height - fit * 24 - 150) / 22));
            views.setViewVisibility(R.id.status, front == null ? View.GONE : View.VISIBLE);
            views.setOnClickPendingIntent(R.id.note, front == null ? NoteActivity.fresh(context) : NoteActivity.open(context, front.id));
            if (front != null) {
                views.setTextViewText(R.id.chip_text, Notes.status(context, front));
                boolean needed = "question".equals(front.state) && front.sent;
                Palette.text(context, views, schemes, R.id.chip_text, needed ? (p -> p.accent) : (p -> p.muted));
            }
            int pending = Notes.pending(context);
            boolean sort = Sync.linked(context) && pending > 0;
            views.setViewVisibility(R.id.sort, sort ? View.VISIBLE : View.GONE);
            if (sort) {
                views.setTextViewText(R.id.sort_text, context.getResources().getQuantityString(R.plurals.note_sort, pending, pending, Notes.name(context, false)));
                views.setOnClickPendingIntent(R.id.sort, NoteActivity.sort(context));
            }
            return views;
        }
    }

    abstract RemoteViews draw(Context context, int id);

    @Override
    public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        for (int id : ids) manager.updateAppWidget(id, draw(Language.apply(context), id));
        manager.notifyAppWidgetViewDataChanged(ids, R.id.list);
    }

    @Override
    public void onAppWidgetOptionsChanged(Context context, AppWidgetManager manager, int id, Bundle options) {
        manager.updateAppWidget(id, draw(Language.apply(context), id));  // Resized: fit the content again.
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        super.onReceive(context, intent);
        String action = intent.getAction();
        if (EDITION.equals(action)) {
            int id = intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, 0);
            choose(context, id, intent.getStringExtra("edition"));
            AppWidgetManager manager = AppWidgetManager.getInstance(context);
            manager.updateAppWidget(id, draw(Language.apply(context), id));
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
        for (Widgets kind : new Widgets[] {new Today(), new Week(), new Chat(), new Portrait(), new Briefing(), new News(),
                new Weather(), new WeatherFull(), new Temperature(), new Rain(), new Air(), new QuickNote()}) {
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

    /** The rounded card with its 1dp border, both in this phone's colors. */
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

    static String day(Context context, String date, String skeleton) {
        String pattern = DateFormat.getBestDateTimePattern(Language.of(context), skeleton);
        return LocalDate.parse(date).format(DateTimeFormatter.ofPattern(pattern, Language.of(context)));
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
                .toUpperCase(Language.of(context)));
        String title = context.getString(today ? R.string.widget_today_name : R.string.widget_week_name);
        if (days != null && days.length() > 0) {
            String first = days.optJSONObject(0).optString("date");
            title = today ? day(context, first, "EEEEMMMMd")
                    : context.getString(R.string.widget_week_range, day(context, first, "MMMd"), day(context, days.optJSONObject(days.length() - 1).optString("date"), "MMMd"));
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
                .toUpperCase(Language.of(context)));
        JSONObject briefings = Sync.cached(context).optJSONObject("briefings");
        String date = briefings == null ? "" : briefings.optString("date");
        views.setTextViewText(R.id.title, date.isEmpty() ? context.getString(news ? R.string.widget_news_name : R.string.widget_briefing_name)
                : day(context, date, "EEEEMMMMd"));
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

    /** The website's weather tile colors (briefing.css): {accent, fill} by day, then by night. */
    private static int[] tileColors(WeatherChart.Kind kind) {
        switch (kind) {
            case TEMPERATURE: return new int[] {0xFF316D97, 0xFFEDF4F8, 0xFFA2CDE9, 0xFF203345};
            case RAIN: return new int[] {0xFF706392, 0xFFF1EEF8, 0xFFC8B9EA, 0xFF2B2B43};
            default: return new int[] {0xFF387559, 0xFFEDF5EE, 0xFFAED4B7, 0xFF23392F};
        }
    }

    /**
     * The weather widgets: all three topics or one, as headline columns or tiles with hourly charts.
     * Headlines count only the hours from now, as the briefing page does.
     */
    RemoteViews weather(Context context, int id, WeatherChart.Kind only, boolean charts, int[] size) {
        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_weather);
        Palette[] schemes = Palette.of(context);
        card(context, views, schemes, p -> p.line, p -> p.surface);
        Palette.tint(context, views, schemes, R.id.icon, p -> p.accent);
        Palette.tint(context, views, schemes, R.id.refresh, p -> p.muted);
        Palette.text(context, views, schemes, R.id.label, p -> p.muted);
        Palette.text(context, views, schemes, R.id.title, p -> p.ink);
        Palette.text(context, views, schemes, R.id.message, p -> p.muted);
        views.setContentDescription(R.id.refresh, context.getString(R.string.widget_refresh));
        views.setViewVisibility(R.id.header, only == null ? View.VISIBLE : View.GONE);
        views.setViewVisibility(R.id.label, charts ? View.VISIBLE : View.GONE);  // The compact widget keeps one header line.
        views.setTextViewText(R.id.label, context.getString(R.string.weather_label).toUpperCase(Language.of(context)));
        JSONObject data = Sync.cached(context).optJSONObject("weather");
        String city = data == null ? "" : data.optString("city");
        views.setTextViewText(R.id.title, city.isEmpty() ? context.getString(R.string.widget_weather_name) : city);
        views.removeAllViews(R.id.tiles);
        views.removeAllViews(R.id.columns);
        boolean linked = Sync.linked(context);
        views.setViewVisibility(R.id.refresh, linked ? View.VISIBLE : View.GONE);
        if (!linked) {
            message(views, context.getString(R.string.widget_link));
            views.setOnClickPendingIntent(R.id.root, screen(context, LinkActivity.class));
            return views;
        }
        views.setOnClickPendingIntent(R.id.root, Sync.open(context, "/gm.html?section=weather", 7000 + id));
        views.setOnClickPendingIntent(R.id.refresh, action(context, REFRESH, id, "weather"));
        WeatherFrame frame = WeatherFrame.parse(data == null ? null : data.optJSONObject("frame"));
        int past = frame == null ? -1 : frame.past(LocalDateTime.now());
        if (past < 0 || (only == WeatherChart.Kind.AIR && frame.air == null)) {
            message(views, context.getString(data == null ? R.string.weather_loading : R.string.weather_unavailable));
            return views;
        }
        views.setViewVisibility(R.id.message, View.GONE);
        int width = size[0], height = size[1];
        int topics = frame.air == null ? 2 : 3;
        // A single topic stacks its chart under the headline; the details widget puts each chart beside it.
        // What is left after the text decides the chart's size; too little hides it.
        int chartWidth = only != null ? width - 44 : (width - 48) * 3 / 5;
        int chart = only != null ? Math.min(180, height - 112) : Math.min(120, (height - 82) / topics - 20);
        float density = context.getResources().getDisplayMetrics().density;
        for (WeatherChart.Kind kind : WeatherChart.Kind.values()) {
            if ((only != null && kind != only) || (kind == WeatherChart.Kind.AIR && frame.air == null)) continue;
            RemoteViews tile = new RemoteViews(context.getPackageName(), !charts ? R.layout.widget_weather_brief
                    : only != null ? R.layout.widget_weather_tile : R.layout.widget_weather_row);
            int[] colors = tileColors(kind);
            if (only != null) {
                // A single topic is the whole card, in its tile color.
                Palette.pair(context, views, R.id.card_fill, "setColorFilter", colors[1], colors[3]);
                tile.setViewVisibility(R.id.tile_fill, View.GONE);
            }
            Palette.pair(context, tile, R.id.tile_fill, "setColorFilter", colors[1], colors[3]);
            tile.setViewVisibility(R.id.tile_label, charts ? View.VISIBLE : View.GONE);  // Columns rely on their icons.
            Palette.pair(context, tile, R.id.tile_icon, "setColorFilter", colors[0], colors[2]);
            for (int text : new int[] {R.id.tile_label, R.id.tile_main, R.id.tile_sub}) {
                Palette.pair(context, tile, text, "setTextColor", colors[0], colors[2]);
            }
            tile.setImageViewResource(R.id.tile_icon, kind == WeatherChart.Kind.TEMPERATURE ? R.drawable.ic_thermometer
                    : kind == WeatherChart.Kind.RAIN ? R.drawable.ic_rain : R.drawable.ic_leaf);
            tile.setTextViewText(R.id.tile_label, context.getString(kind == WeatherChart.Kind.TEMPERATURE ? R.string.weather_temperature
                    : kind == WeatherChart.Kind.RAIN ? R.string.weather_precipitation : R.string.weather_air).toUpperCase(Language.of(context)));
            String[] headline = headline(context, frame, kind, past);
            tile.setTextViewText(R.id.tile_main, headline[0]);
            tile.setTextViewText(R.id.tile_sub, headline[1]);
            if (charts) {
                tile.setViewVisibility(R.id.tile_chart, chart >= 56 ? View.VISIBLE : View.GONE);
                if (chart >= 56) {
                    Bitmap[] layers = new WeatherChart(frame, kind, past, density, chartWidth >= 240 ? periods(context, frame) : null)
                            .draw(Math.round(chartWidth * density), Math.round(chart * density));
                    tile.setImageViewBitmap(R.id.chart_accent, layers[0]);
                    tile.setImageViewBitmap(R.id.chart_muted, layers[1]);
                    Palette.pair(context, tile, R.id.chart_accent, "setColorFilter", colors[0], colors[2]);
                    Palette.color(context, tile, schemes, R.id.chart_muted, "setColorFilter", p -> p.muted);
                }
            }
            views.addView(charts ? R.id.tiles : R.id.columns, tile);
        }
        return views;
    }

    /** The widget's portrait width and height in dp; the defaults match a 4×4 cell area. */
    private static int[] size(Context context, int id) {
        Bundle options = AppWidgetManager.getInstance(context).getAppWidgetOptions(id);
        return new int[] {options.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 250),
                options.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 250)};
    }

    private static void message(RemoteViews views, String text) {
        views.setViewVisibility(R.id.message, View.VISIBLE);
        views.setTextViewText(R.id.message, text);
    }

    private static String[] periods(Context context, WeatherFrame frame) {
        if (!frame.late()) {
            return new String[] {context.getString(R.string.weather_this_morning), context.getString(R.string.weather_this_afternoon),
                    context.getString(R.string.weather_this_evening)};
        }
        String day = frame.start.plusDays(1).getDayOfWeek().getDisplayName(TextStyle.SHORT, Language.of(context));
        return new String[] {context.getString(R.string.weather_this_evening), context.getString(R.string.weather_overnight),
                context.getString(R.string.weather_day_morning, day)};
    }

    /** The tile's big headline and the line under it. */
    static String[] headline(Context context, WeatherFrame frame, WeatherChart.Kind kind, int past) {
        if (kind == WeatherChart.Kind.TEMPERATURE) {
            return new String[] {frame.high(past) + "°", context.getString(R.string.weather_high_low, frame.low(past))};
        }
        if (kind == WeatherChart.Kind.AIR) {
            int low = frame.airLow(past), high = frame.airHigh(past);
            String span = low == high ? String.valueOf(low) : low + "–" + high;
            int[] levels = {R.string.weather_aqi_good, R.string.weather_aqi_moderate, R.string.weather_aqi_sensitive,
                    R.string.weather_aqi_unhealthy, R.string.weather_aqi_very_unhealthy, R.string.weather_aqi_hazardous};
            return new String[] {context.getString(levels[frame.airLevel(past)]),
                    context.getString(frame.late() ? R.string.weather_aqi_night : R.string.weather_aqi_day, span)};
        }
        int peak = frame.rainPeak(past);
        boolean snow = frame.snow;
        switch (frame.rainState(past)) {
            case DRY:
                return new String[] {context.getString(R.string.weather_dry),
                        context.getString(snow ? R.string.weather_snow_chance : R.string.weather_rain_chance, peak)};
            case DRY_UNTIL:
                return new String[] {context.getString(R.string.weather_dry_until, frame.clock(frame.rainChange(past, true))),
                        context.getString(snow ? R.string.weather_then_snow : R.string.weather_then_rain, peak)};
            case EASING:
                return new String[] {context.getString(snow ? R.string.weather_snow_likely : R.string.weather_rain_likely),
                        context.getString(R.string.weather_easing, frame.clock(frame.rainChange(past, false)), peak)};
            default:
                return new String[] {context.getString(snow ? R.string.weather_snow_likely : R.string.weather_rain_likely),
                        context.getString(R.string.weather_through, frame.clock(WeatherFrame.HOURS), peak)};
        }
    }
}
