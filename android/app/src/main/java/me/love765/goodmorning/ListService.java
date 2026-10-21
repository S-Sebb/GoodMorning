package me.love765.goodmorning;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.widget.RemoteViews;
import android.widget.RemoteViewsService;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** Rows for the Today and Week widgets, built from the cached summary. */
public class ListService extends RemoteViewsService {
    @Override
    public RemoteViewsFactory onGetViewFactory(Intent intent) {
        return new Rows(getApplicationContext(), intent.getStringExtra("kind"));
    }

    private static final class Rows implements RemoteViewsFactory {
        private final Context context;
        private final String kind;
        private final List<RemoteViews> rows = new ArrayList<>();

        Rows(Context context, String kind) {
            this.context = context;
            this.kind = kind;
        }

        @Override
        public void onDataSetChanged() {
            rows.clear();
            JSONObject schedule = Sync.cached(context).optJSONObject("schedule");
            JSONArray days = schedule == null ? null : schedule.optJSONArray("days");
            if (days == null) return;
            boolean today = "today".equals(kind);
            for (int offset = 0; offset < (today ? Math.min(1, days.length()) : days.length()); offset++) {
                JSONObject day = days.optJSONObject(offset);
                JSONArray events = day.optJSONArray("events");
                JSONArray tasks = day.optJSONArray("tasks");
                String page = "/schedule?view=day&day=" + offset;
                if (!today) {
                    RemoteViews header = new RemoteViews(context.getPackageName(), R.layout.widget_day);
                    header.setTextViewText(R.id.day, offset == 0 ? context.getString(R.string.widget_today_title, Widgets.day(day.optString("date"), true))
                            : Widgets.day(day.optString("date"), true));
                    header.setOnClickFillInIntent(R.id.day, fill(page));
                    rows.add(header);
                }
                for (int i = 0; i < events.length(); i++) {
                    JSONObject event = events.optJSONObject(i);
                    String time = event.optBoolean("tbc") ? context.getString(R.string.widget_tbc)
                            : event.optBoolean("all_day") ? context.getString(R.string.widget_all_day)
                            : event.optString("time").isEmpty() ? "…" : event.optString("time");
                    String detail = event.optString("location");
                    if (!event.optString("end").isEmpty()) {
                        detail = context.getString(R.string.widget_until, event.optString("end")) + (detail.isEmpty() ? "" : " · " + detail);
                    }
                    rows.add(row(time, event.optString("subject"), detail, page));
                }
                if (today) {
                    for (int i = 0; i < tasks.length(); i++) {
                        JSONObject task = tasks.optJSONObject(i);
                        rows.add(row(task.optBoolean("done") ? "✓" : "○", task.optString("text"), "", page));
                    }
                } else if (tasks.length() > 0) {
                    int done = 0;
                    for (int i = 0; i < tasks.length(); i++) if (tasks.optJSONObject(i).optBoolean("done")) done++;
                    rows.add(row("", context.getString(R.string.widget_tasks, done, tasks.length()), "", page));
                } else if (events.length() == 0) {
                    rows.add(row("", context.getString(R.string.widget_free), "", page));
                }
            }
        }

        private RemoteViews row(String time, String text, String detail, String page) {
            RemoteViews row = new RemoteViews(context.getPackageName(), R.layout.widget_item);
            row.setTextViewText(R.id.time, time);
            row.setTextViewText(R.id.text, text);
            row.setTextViewText(R.id.detail, detail);
            row.setViewVisibility(R.id.detail, detail.isEmpty() ? android.view.View.GONE : android.view.View.VISIBLE);
            row.setOnClickFillInIntent(R.id.item, fill(page));
            return row;
        }

        private Intent fill(String page) {
            return new Intent().setData(Uri.parse(Server.get(context) + page));
        }

        @Override public void onCreate() {}
        @Override public void onDestroy() { rows.clear(); }
        @Override public int getCount() { return rows.size(); }
        @Override public RemoteViews getViewAt(int position) { return rows.get(position); }
        @Override public RemoteViews getLoadingView() { return null; }
        @Override public int getViewTypeCount() { return 2; }
        @Override public long getItemId(int position) { return position; }
        @Override public boolean hasStableIds() { return false; }
    }
}
