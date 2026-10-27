package me.love765.goodmorning;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

public class SyncTest {
    private static JSONObject summary() throws Exception {
        JSONArray tasks = new JSONArray()
                .put(new JSONObject().put("text", "Pick up a parcel").put("done", false).put("tickable", true).put("id", "task_a").put("revision", 2))
                .put(new JSONObject().put("text", "Stretch").put("done", false).put("tickable", true).put("id", "cu_b").put("revision", 5))
                .put(new JSONObject().put("text", "Report due").put("done", false).put("tickable", false));
        JSONArray days = new JSONArray()
                .put(new JSONObject().put("date", "2026-10-26").put("events", new JSONArray()).put("tasks", tasks))
                .put(new JSONObject().put("date", "2026-10-27").put("events", new JSONArray()).put("tasks", new JSONArray()));
        return new JSONObject().put("schedule", new JSONObject().put("days", days));
    }

    private static JSONObject task(JSONObject data, int index) throws Exception {
        return data.getJSONObject("schedule").getJSONArray("days").getJSONObject(0).getJSONArray("tasks").getJSONObject(index);
    }

    @Test
    public void aTickShowsTheServersAnswerOnThatRowOnly() throws Exception {
        JSONObject saved = new JSONObject().put("saved", true).put("id", "task_a").put("date", "2026-10-26").put("done", true).put("revision", 3);
        JSONObject data = Sync.ticked(summary(), saved);
        assertTrue(task(data, 0).getBoolean("done"));
        assertEquals(3, task(data, 0).getInt("revision"));
        assertFalse(task(data, 1).getBoolean("done"));
        assertEquals(5, task(data, 1).getInt("revision"));
        assertFalse(task(data, 2).has("revision"));
    }

    @Test
    public void anAnswerForAnotherDayChangesNothing() throws Exception {
        // The summary already moved past midnight while the tick was on its way.
        JSONObject saved = new JSONObject().put("saved", true).put("id", "task_a").put("date", "2026-10-25").put("done", true).put("revision", 3);
        assertEquals(summary().toString(), Sync.ticked(summary(), saved).toString());
    }
}
