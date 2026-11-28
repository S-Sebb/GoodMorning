package me.love765.goodmorning;

import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.UUID;

/**
 * The widgets' ticks, kept on the phone until the server confirms them, so a tap shows at once and survives
 * being offline. Per to-do and day it holds the state and revision the server last confirmed and the taps
 * still to send. A tap not sent yet and its opposite cancel out; the rest go out one at a time, in order,
 * each with the revision the previous answer gave, and keep their retry key until the server confirms them.
 * Every widget reads the summary with these applied ({@link Sync#cached}), so they never disagree.
 */
final class Ticks {
    static final int JOB = 5;
    /** How long a tick's Undo shows; the list keeps its order until then. */
    static final long UNDO = 5000;
    /** How long a refused tap's message stays in the widget. */
    private static final long NOTE = 10 * 60_000L;
    private static final Object STATE = new Object();
    private static final Object SENDING = new Object();

    private Ticks() {}

    // The rules, on the saved state alone, so tests need no phone.

    static String key(String id, String date) {
        return id + "|" + date;
    }

    private static JSONObject items(JSONObject state) throws JSONException {
        JSONObject items = state.optJSONObject("items");
        if (items == null) state.put("items", items = new JSONObject());
        return items;
    }

    /** What the item shows: its last waiting tap, or what the server confirmed. */
    static boolean shown(JSONObject item) {
        JSONArray taps = item.optJSONArray("taps");
        return taps != null && taps.length() > 0 ? taps.optJSONObject(taps.length() - 1).optBoolean("done") : item.optBoolean("done");
    }

    /**
     * One tap on a row of the summary (with these ticks applied): flips it, and holds the list's order for
     * the Undo unless quiet (Undo itself). Returns whether the row now shows done.
     */
    static boolean tap(JSONObject state, JSONObject task, String date, String retry, long now, boolean quiet) throws JSONException {
        String key = key(task.getString("id"), date);
        JSONObject item = items(state).optJSONObject(key);
        boolean before = item == null ? task.optBoolean("done") : shown(item);
        if (item == null) {
            item = new JSONObject().put("id", task.getString("id")).put("date", date).put("text", task.optString("text"))
                    .put("revision", task.optInt("revision")).put("done", task.optBoolean("done")).put("taps", new JSONArray());
            items(state).put(key, item);
        }
        JSONArray taps = item.getJSONArray("taps");
        JSONObject last = taps.length() > 0 ? taps.getJSONObject(taps.length() - 1) : null;
        // A tap that may have reached the server is resolved by its retry first, so only unsent ones cancel.
        if (last != null && !last.optBoolean("sent")) taps.remove(taps.length() - 1);
        else taps.put(new JSONObject().put("done", !before).put("key", retry));
        state.remove("note");
        if (quiet) {
            state.remove("undo");
        } else {
            JSONObject undo = undo(state, now);
            JSONObject frozen = undo == null ? new JSONObject() : undo.getJSONObject("frozen");
            if (!frozen.has(key)) frozen.put(key, before);  // Where the row stood before this Undo began.
            state.put("undo", new JSONObject().put("key", key).put("until", now + UNDO).put("frozen", frozen));
        }
        return !before;
    }

    /** The Undo showing now, or null. */
    static JSONObject undo(JSONObject state, long now) {
        JSONObject undo = state.optJSONObject("undo");
        return undo != null && undo.optLong("until") > now ? undo : null;
    }

    /** The next tap to send, marked as sent so it is no longer cancelled; null when none waits. */
    static JSONObject next(JSONObject state) throws JSONException {
        JSONObject items = items(state);
        for (Iterator<String> keys = items.keys(); keys.hasNext(); ) {
            String key = keys.next();
            JSONObject item = items.getJSONObject(key);
            JSONArray taps = item.getJSONArray("taps");
            if (taps.length() == 0) continue;
            JSONObject tap = taps.getJSONObject(0).put("sent", true);
            return new JSONObject().put("key", key).put("body", new JSONObject().put("id", item.getString("id"))
                    .put("date", item.getString("date")).put("revision", item.getInt("revision"))
                    .put("done", tap.getBoolean("done")).put("key", tap.getString("key")));
        }
        return null;
    }

    /** The server saved the first waiting tap: the next one goes out with its new revision. */
    static void confirmed(JSONObject state, String key, JSONObject saved) throws JSONException {
        JSONObject item = items(state).optJSONObject(key);
        if (item == null) return;
        item.getJSONArray("taps").remove(0);
        item.put("done", saved.getBoolean("done")).put("revision", saved.getInt("revision"));
    }

    /** The server refused the first waiting tap: the row goes back to how it was before it, with the server's reason. */
    static void refused(JSONObject state, String key, String reason, long now) throws JSONException {
        JSONObject item = items(state).optJSONObject(key);
        if (item == null) return;
        item.put("taps", new JSONArray());
        state.put("note", new JSONObject().put("text", "“" + item.optString("text") + "”: " + reason).put("until", now + NOTE));
        JSONObject undo = state.optJSONObject("undo");
        if (undo != null && key.equals(undo.optString("key"))) state.remove("undo");
    }

    /** The refused tap's message while it still shows, or "". */
    static String note(JSONObject state, long now) {
        JSONObject note = state.optJSONObject("note");
        return note != null && note.optLong("until") > now ? note.optString("text") : "";
    }

    /** Whether a tap waits because the server could not be reached. */
    static boolean offline(JSONObject state) {
        if (!state.optBoolean("offline")) return false;
        JSONObject items = state.optJSONObject("items");
        for (Iterator<String> keys = items == null ? null : items.keys(); keys != null && keys.hasNext(); ) {
            if (items.optJSONObject(keys.next()).optJSONArray("taps").length() > 0) return true;
        }
        return false;
    }

    /** The summary as the widgets show it: each item's mark and latest revision, and "waiting" on rows not sent while offline. */
    static JSONObject apply(JSONObject data, JSONObject state) {
        JSONObject items = state.optJSONObject("items");
        boolean offline = state.optBoolean("offline");
        for (Iterator<String> keys = items == null ? null : items.keys(); keys != null && keys.hasNext(); ) {
            JSONObject item = items.optJSONObject(keys.next());
            JSONObject task = row(data, item.optString("id"), item.optString("date"));
            if (task == null) continue;
            try {
                task.put("done", shown(item)).put("revision", item.optInt("revision"))
                        .put("waiting", offline && item.optJSONArray("taps").length() > 0);
            } catch (JSONException ignored) {
                // Booleans and numbers always fit.
            }
        }
        return data;
    }

    /** Drops settled items once a summary carries their revision or no longer has the row. */
    static void prune(JSONObject state, JSONObject data) throws JSONException {
        JSONObject items = items(state);
        List<String> settled = new ArrayList<>();
        for (Iterator<String> keys = items.keys(); keys.hasNext(); ) {
            String key = keys.next();
            JSONObject item = items.getJSONObject(key);
            if (item.getJSONArray("taps").length() > 0) continue;
            JSONObject task = row(data, item.getString("id"), item.getString("date"));
            if (task == null || task.optInt("revision") >= item.getInt("revision")) settled.add(key);
        }
        for (String key : settled) items.remove(key);
    }

    static JSONObject row(JSONObject data, String id, String date) {
        JSONObject schedule = data.optJSONObject("schedule");
        JSONArray days = schedule == null ? null : schedule.optJSONArray("days");
        for (int i = 0; days != null && i < days.length(); i++) {
            JSONObject day = days.optJSONObject(i);
            if (!date.equals(day.optString("date"))) continue;
            JSONArray tasks = day.optJSONArray("tasks");
            for (int j = 0; tasks != null && j < tasks.length(); j++) {
                if (id.equals(tasks.optJSONObject(j).optString("id"))) return tasks.optJSONObject(j);
            }
        }
        return null;
    }

    /** A row the widgets may tick: a planned to-do or habit, not a deadline, on the account's today or earlier. */
    static boolean tickable(JSONObject task, String date, String today) {
        return !task.optString("id").isEmpty() && !"deadline".equals(task.optString("kind")) && date.compareTo(today) <= 0;
    }

    /** A day's checklist, as the Today widget shows it. */
    static final class Checklist {
        final String date;
        /** Rows by where they stand: open first, then under "Done · N". */
        final List<JSONObject> open = new ArrayList<>(), done = new ArrayList<>();
        /** Rows that count, without optional ones, and how many of them are done. */
        int total, finished;

        Checklist(String date) {
            this.date = date;
        }

        boolean allDone() {
            return total > 0 && finished == total && open.isEmpty();
        }
    }

    /**
     * Routines first, then other to-dos, each in the schedule's order; events, deadlines and stopped habits
     * stay out. While an Undo shows, rows ticked since it began stay where they were.
     */
    static Checklist checklist(JSONObject day, JSONObject state, long now) {
        Checklist list = new Checklist(day.optString("date"));
        JSONObject undo = undo(state, now);
        JSONObject frozen = undo == null ? new JSONObject() : undo.optJSONObject("frozen");
        JSONArray tasks = day.optJSONArray("tasks");
        for (boolean routines : new boolean[] {true, false}) {
            for (int i = 0; tasks != null && i < tasks.length(); i++) {
                JSONObject task = tasks.optJSONObject(i);
                if (task.optString("id").isEmpty() || "deadline".equals(task.optString("kind"))
                        || "routine".equals(task.optString("kind")) != routines) continue;
                String key = key(task.optString("id"), list.date);
                boolean placed = frozen.has(key) ? frozen.optBoolean(key) : task.optBoolean("done");
                (placed ? list.done : list.open).add(task);
                if (task.optBoolean("optional")) continue;
                list.total++;
                if (task.optBoolean("done")) list.finished++;
            }
        }
        return list;
    }

    // The saved state and the network.

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences("ticks", Context.MODE_PRIVATE);
    }

    static JSONObject load(Context context) {
        synchronized (STATE) {
            try {
                return new JSONObject(prefs(context).getString("state", "{}"));
            } catch (JSONException unreadable) {
                return new JSONObject();
            }
        }
    }

    private static void save(Context context, JSONObject state) {
        prefs(context).edit().putString("state", state.toString()).commit();
    }

    static void forget(Context context) {
        synchronized (STATE) {
            prefs(context).edit().clear().commit();
        }
        context.getSystemService(JobScheduler.class).cancel(JOB);
    }

    /** A tap from a widget on that to-do of that day; ignored when the summary no longer has it. */
    static void tap(Context context, String id, String date, boolean quiet) {
        synchronized (STATE) {
            JSONObject task = row(Sync.cached(context), id, date);
            if (task == null) return;
            JSONObject state = load(context);
            try {
                tap(state, task, date, UUID.randomUUID().toString(), System.currentTimeMillis(), quiet);
            } catch (JSONException ignored) {
                return;  // Strings, booleans and numbers always fit.
            }
            save(context, state);
        }
    }

    /** After a new summary: forgets what it already shows. */
    static void settle(Context context, JSONObject data) {
        synchronized (STATE) {
            JSONObject state = load(context);
            try {
                prune(state, data);
            } catch (JSONException ignored) {
                return;
            }
            save(context, state);
        }
    }

    /**
     * Sends the waiting taps one at a time and redraws the widgets after each answer. Unreachable, it stops and
     * tries again once the phone has a network. Returns the last refusal's message, or null.
     */
    static String send(Context context) {
        String token = Api.token(context);
        if (token == null) return null;
        String refusal = null;
        synchronized (SENDING) {
            while (true) {
                JSONObject next;
                synchronized (STATE) {
                    JSONObject state = load(context);
                    try {
                        next = next(state);
                    } catch (JSONException unreadable) {
                        next = null;
                    }
                    if (next == null) {
                        if (state.remove("offline") != null | state.remove("tries") != null) save(context, state);
                        break;
                    }
                    save(context, state);
                }
                String key = next.optString("key");
                try {
                    JSONObject saved = Api.tick(context, token, next.getJSONObject("body"));
                    synchronized (STATE) {
                        JSONObject state = load(context);
                        confirmed(state, key, saved);
                        state.remove("offline");
                        state.remove("tries");
                        save(context, state);
                    }
                } catch (Api.Failure failure) {
                    if (failure.status == 403 || failure.status == 429 || failure.status >= 500) {
                        waitForServer(context);  // Unlinked (the sync shows the prompt) or busy: the tap waits.
                        break;
                    }
                    String reason = failure.status == 409 && !failure.error.isEmpty() ? failure.error
                            : Language.apply(context).getString(R.string.widget_tick_failed);
                    synchronized (STATE) {
                        JSONObject state = load(context);
                        try {
                            refused(state, key, reason, System.currentTimeMillis());
                        } catch (JSONException ignored) {
                            // Strings always fit.
                        }
                        save(context, state);
                    }
                    refusal = reason;
                } catch (IOException | JSONException offline) {
                    waitForServer(context);
                    break;
                } finally {
                    Widgets.updateAll(context);
                }
            }
        }
        return refusal;
    }

    /** Marks the taps as waiting and tries again once there is a network: after 30 seconds, doubling up to 15 minutes. */
    private static void waitForServer(Context context) {
        int tries;
        synchronized (STATE) {
            JSONObject state = load(context);
            tries = state.optInt("tries");
            try {
                state.put("offline", true).put("tries", tries + 1);
            } catch (JSONException ignored) {
                // Booleans and numbers always fit.
            }
            save(context, state);
        }
        context.getSystemService(JobScheduler.class).schedule(new JobInfo.Builder(JOB, new ComponentName(context, SyncJob.class))
                .setMinimumLatency(Math.min(15 * 60_000L, 30_000L << Math.min(tries, 5)))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPersisted(true)
                .build());
    }
}
