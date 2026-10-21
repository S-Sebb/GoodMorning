package me.love765.goodmorning;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.style.StrikethroughSpan;
import android.view.View;
import android.widget.RemoteViews;
import android.widget.RemoteViewsService;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** Rows for the Today and Week widgets, built from the cached summary in the account's colors. */
public class ListService extends RemoteViewsService {
    @Override
    public RemoteViewsFactory onGetViewFactory(Intent intent) {
        return new Rows(getApplicationContext(), intent.getStringExtra("kind"));
    }

    private static final class Rows implements RemoteViewsFactory {
        private static final int[][] SLOTS = {
                {R.id.event1, R.id.bar1, R.id.time1, R.id.text1},
                {R.id.event2, R.id.bar2, R.id.time2, R.id.text2},
                {R.id.event3, R.id.bar3, R.id.time3, R.id.text3}};
        private final Context context;
        private final String kind;
        private final List<RemoteViews> rows = new ArrayList<>();
        private Palette[] schemes;

        Rows(Context context, String kind) {
            this.context = context;
            this.kind = kind;
        }

        @Override
        public void onDataSetChanged() {
            rows.clear();
            schemes = Palette.of(context);
            JSONObject schedule = Sync.cached(context).optJSONObject("schedule");
            JSONArray days = schedule == null ? null : schedule.optJSONArray("days");
            if (days == null || days.length() == 0) return;
            if ("today".equals(kind)) today(days.optJSONObject(0));
            else for (int offset = 0; offset < days.length(); offset++) day(days.optJSONObject(offset), offset);
        }

        private void today(JSONObject day) {
            JSONArray events = day.optJSONArray("events");
            JSONArray tasks = day.optJSONArray("tasks");
            String page = "/schedule?view=day";
            if (events.length() == 0 && tasks.length() == 0) return;  // The empty view says so.
            for (int i = 0; i < events.length(); i++) {
                JSONObject event = events.optJSONObject(i);
                RemoteViews row = view(R.layout.row_event, page);
                Palette.tint(context, row, schemes, R.id.bar, event.optBoolean("tbc") ? (p -> p.line) : (p -> p.accent));
                Palette.text(context, row, schemes, R.id.time, p -> p.accent);
                Palette.text(context, row, schemes, R.id.text, p -> p.ink);
                Palette.text(context, row, schemes, R.id.detail, p -> p.muted);
                row.setTextViewText(R.id.time, time(event));
                row.setTextViewText(R.id.text, event.optString("subject"));
                String detail = detail(event);
                row.setTextViewText(R.id.detail, detail);
                row.setViewVisibility(R.id.detail, detail.isEmpty() ? View.GONE : View.VISIBLE);
                rows.add(row);
            }
            if (tasks.length() > 0) rows.add(section(R.drawable.desk_secretary, R.string.section_todos, page));
            for (int i = 0; i < tasks.length(); i++) {
                JSONObject task = tasks.optJSONObject(i);
                boolean done = task.optBoolean("done");
                RemoteViews row = view(R.layout.row_todo, page);
                Palette.text(context, row, schemes, R.id.mark, p -> p.accent);
                Palette.text(context, row, schemes, R.id.text, done ? (p -> p.muted) : (p -> p.ink));
                row.setTextViewText(R.id.mark, done ? "✓" : "○");
                SpannableString text = new SpannableString(task.optString("text"));
                if (done) text.setSpan(new StrikethroughSpan(), 0, text.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                row.setTextViewText(R.id.text, text);
                rows.add(row);
            }
        }

        private void day(JSONObject day, int offset) {
            String page = "/schedule?view=day&day=" + offset;
            RemoteViews row = view(R.layout.row_day, page);
            String date = day.optString("date");
            row.setViewVisibility(R.id.divider, offset == 0 ? View.GONE : View.VISIBLE);
            Palette.tint(context, row, schemes, R.id.divider, p -> p.line);
            // Today's date sits in a filled circle, as in the website's week header.
            Palette.tint(context, row, schemes, R.id.circle, offset == 0 ? (p -> p.ink) : (p -> p.surface));
            Palette.text(context, row, schemes, R.id.number, offset == 0 ? (p -> p.surface) : (p -> p.ink));
            Palette.text(context, row, schemes, R.id.weekday, offset == 0 ? (p -> p.ink) : (p -> p.muted));
            Palette.text(context, row, schemes, R.id.note, p -> p.muted);
            row.setTextViewText(R.id.weekday, Widgets.day(date, "EEE").toUpperCase(Locale.getDefault()));
            row.setTextViewText(R.id.number, String.valueOf(Integer.parseInt(date.substring(8))));
            JSONArray events = day.optJSONArray("events");
            JSONArray tasks = day.optJSONArray("tasks");
            for (int i = 0; i < SLOTS.length; i++) {
                int[] slot = SLOTS[i];
                JSONObject event = events.optJSONObject(i);
                row.setViewVisibility(slot[0], event == null ? View.GONE : View.VISIBLE);
                if (event == null) continue;
                Palette.tint(context, row, schemes, slot[1], event.optBoolean("tbc") ? (p -> p.line) : (p -> p.accent));
                Palette.text(context, row, schemes, slot[2], p -> p.accent);
                Palette.text(context, row, schemes, slot[3], p -> p.ink);
                row.setTextViewText(slot[2], time(event));
                row.setTextViewText(slot[3], event.optString("subject"));
            }
            List<String> notes = new ArrayList<>();
            if (events.length() > SLOTS.length) notes.add(context.getString(R.string.widget_more, events.length() - SLOTS.length));
            if (tasks.length() > 0) {
                int done = 0;
                for (int i = 0; i < tasks.length(); i++) if (tasks.optJSONObject(i).optBoolean("done")) done++;
                notes.add(context.getString(R.string.widget_tasks, done, tasks.length()));
            }
            if (events.length() == 0 && tasks.length() == 0) notes.add(context.getString(R.string.widget_free));
            row.setTextViewText(R.id.note, String.join(" · ", notes));
            row.setViewVisibility(R.id.note, notes.isEmpty() ? View.GONE : View.VISIBLE);
            rows.add(row);
        }

        private RemoteViews section(int icon, int label, String page) {
            RemoteViews row = view(R.layout.row_section, page);
            row.setImageViewResource(R.id.icon, icon);
            row.setTextViewText(R.id.text, context.getString(label));
            Palette.text(context, row, schemes, R.id.text, p -> p.muted);
            return row;
        }

        private RemoteViews view(int layout, String page) {
            RemoteViews row = new RemoteViews(context.getPackageName(), layout);
            row.setOnClickFillInIntent(R.id.row, new Intent().setData(Uri.parse(Server.get(context) + page)));
            return row;
        }

        private String time(JSONObject event) {
            if (event.optBoolean("tbc")) return context.getString(R.string.widget_tbc);
            if (event.optBoolean("all_day")) return context.getString(R.string.widget_all_day);
            return event.optString("time").isEmpty() ? "…" : event.optString("time");
        }

        private String detail(JSONObject event) {
            String place = event.optString("location");
            if (event.optString("end").isEmpty()) return place;
            String until = context.getString(R.string.widget_until, event.optString("end"));
            return place.isEmpty() ? until : until + " · " + place;
        }

        @Override public void onCreate() {}
        @Override public void onDestroy() { rows.clear(); }
        @Override public int getCount() { return rows.size(); }
        @Override public RemoteViews getViewAt(int position) { return rows.get(position); }
        @Override public RemoteViews getLoadingView() { return null; }
        @Override public int getViewTypeCount() { return 4; }
        @Override public long getItemId(int position) { return position; }
        @Override public boolean hasStableIds() { return false; }
    }
}
