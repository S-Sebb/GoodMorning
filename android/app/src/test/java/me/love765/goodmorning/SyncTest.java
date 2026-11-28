package me.love765.goodmorning;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
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

    private static final long MINUTE = 60_000L;
    private static final long NOW = 1_800_000_000_000L;

    private static JSONObject chat(String state) throws Exception {
        return new JSONObject().put("id", "a").put("state", state).put("active", (NOW - 60 * MINUTE) / 1000.0);
    }

    @Test
    public void aSettledConversationOpensFreshAfterFifteenMinutesAway() throws Exception {
        JSONObject chat = chat("idle");
        assertSame(chat, Sync.current(chat, NOW - 14 * MINUTE, 0, NOW));
        assertNull(Sync.current(chat, NOW - 15 * MINUTE, 0, NOW));
        assertEquals("/chat?mode=secretary", ConversationActivity.path(Sync.current(chat, NOW - 15 * MINUTE, 0, NOW)));
        assertEquals("/chat?id=a", ConversationActivity.path(Sync.current(chat, NOW - 14 * MINUTE, 0, NOW)));
        // A message written since, on any device, counts as being there.
        chat.put("active", (NOW - MINUTE) / 1000.0);
        assertSame(chat, Sync.current(chat, NOW - 60 * MINUTE, 0, NOW));
    }

    @Test
    public void anUnknownDepartureOrAReplySinceLeavingKeepsTheConversation() throws Exception {
        JSONObject chat = chat("idle");
        assertSame(chat, Sync.current(chat, 0, 0, NOW));
        // The reply came after the user left, so they haven't read it.
        assertSame(chat, Sync.current(chat, NOW - 60 * MINUTE, NOW - 30 * MINUTE, NOW));
        assertNull(Sync.current(chat, NOW - 60 * MINUTE, NOW - 61 * MINUTE, NOW));
    }

    @Test
    public void aReplyArrivesWhenTheConversationSettlesOrItsReplyChanges() throws Exception {
        JSONObject settled = chat("idle").put("reply_id", "m2");
        // Never seen before on this phone: unknown, not a new reply.
        assertFalse(Sync.replyArrived(null, settled));
        // Seen running, even if another conversation was the latest since.
        assertTrue(Sync.replyArrived(new JSONObject().put("state", "running").put("reply", "m1"), settled));
        // Seen settled with another reply, even if its text matches.
        assertTrue(Sync.replyArrived(new JSONObject().put("state", "idle").put("reply", "m1"), settled));
        assertFalse(Sync.replyArrived(new JSONObject().put("state", "idle").put("reply", "m2"), settled));
        assertFalse(Sync.replyArrived(new JSONObject().put("state", "idle").put("reply", "m1"), chat("running")));
    }

    @Test
    public void observationsAreBoundedByTheirTime() throws Exception {
        JSONObject seen = new JSONObject();
        for (int i = 0; i < 21; i++) Sync.bounded(seen, "c" + i, new JSONObject().put("at", 100 + i).put("state", "idle"));
        assertEquals(20, seen.length());
        assertFalse(seen.has("c0"));
    }

    @Test
    public void leavingAnotherConversationKeepsThisOnesDeparture() throws Exception {
        JSONObject times = Sync.bounded(new JSONObject(), "a", 1);
        Sync.bounded(times, "b", 2);
        assertEquals(1, times.getLong("a"));
        for (int i = 0; i < 25; i++) Sync.bounded(times, "c" + i, 10 + i);
        assertEquals(20, times.length());
        assertFalse(times.has("a"));
        assertTrue(times.has("c24"));
    }

    @Test
    public void runningWaitingAndUnreadConversationsStayAfterAnyTimeAway() throws Exception {
        for (String state : new String[] {"running", "waiting", "uncertain"}) {
            JSONObject chat = chat(state);
            assertSame(state, chat, Sync.current(chat, NOW - 600 * MINUTE, 0, NOW));
        }
        JSONObject unread = chat("idle").put("unread", true);
        assertSame(unread, Sync.current(unread, NOW - 600 * MINUTE, 0, NOW));
        assertNull(Sync.current(new JSONObject(), NOW, 0, NOW));
    }
}
