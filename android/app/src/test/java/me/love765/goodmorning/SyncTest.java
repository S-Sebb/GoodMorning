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
                .put(new JSONObject().put("text", "Pick up a parcel").put("done", false).put("kind", "todo").put("id", "task_a").put("revision", 2))
                .put(new JSONObject().put("text", "Stretch").put("done", false).put("kind", "routine").put("id", "cu_b").put("revision", 5))
                .put(new JSONObject().put("text", "Report due").put("done", false).put("kind", "deadline"));
        JSONArray tomorrow = new JSONArray()
                .put(new JSONObject().put("text", "Stretch").put("done", false).put("kind", "routine").put("id", "cu_b").put("revision", 5));
        JSONArray days = new JSONArray()
                .put(new JSONObject().put("date", "2026-10-13").put("events", new JSONArray()).put("tasks", tasks))
                .put(new JSONObject().put("date", "2026-10-14").put("events", new JSONArray()).put("tasks", tomorrow));
        return new JSONObject().put("schedule", new JSONObject().put("timezone", "Europe/London").put("days", days));
    }

    private static JSONObject task(JSONObject data, int index) throws Exception {
        return data.getJSONObject("schedule").getJSONArray("days").getJSONObject(0).getJSONArray("tasks").getJSONObject(index);
    }

    private static final String TODAY = "2026-10-13";
    private static final String A = Ticks.key("task_a", TODAY);

    @Test
    public void waitingTapsCancelOutAndGoOutInOrderWithTheLatestRevision() throws Exception {
        JSONObject state = new JSONObject();
        JSONObject data = summary();
        // An unsent tap and its opposite cancel out: nothing goes out.
        Ticks.tap(state, task(data, 0), TODAY, "key-one-0000000000", 0, false);
        Ticks.tap(state, task(Ticks.apply(summary(), state), 0), TODAY, "key-two-0000000000", 0, false);
        assertNull(Ticks.next(state));
        assertFalse(task(Ticks.apply(summary(), state), 0).getBoolean("done"));

        assertTrue(Ticks.tap(state, task(Ticks.apply(summary(), state), 0), TODAY, "key-three-00000000", 0, false));
        JSONObject first = Ticks.next(state);
        JSONObject body = first.getJSONObject("body");
        assertEquals("task_a", body.getString("id"));
        assertEquals(TODAY, body.getString("date"));
        assertTrue(body.getBoolean("done"));
        assertEquals(2, body.getInt("revision"));
        assertEquals("key-three-00000000", body.getString("key"));
        // Once it may have reached the server, the opposite tap waits behind it instead of cancelling it.
        assertFalse(Ticks.tap(state, task(Ticks.apply(summary(), state), 0), TODAY, "key-four-000000000", 0, false));
        assertEquals("key-three-00000000", Ticks.next(state).getJSONObject("body").getString("key"));  // Retried with its key.
        Ticks.confirmed(state, A, new JSONObject().put("done", true).put("revision", 3));
        JSONObject second = Ticks.next(state).getJSONObject("body");
        assertFalse(second.getBoolean("done"));
        assertEquals(3, second.getInt("revision"));
        assertEquals("key-four-000000000", second.getString("key"));
        Ticks.confirmed(state, A, new JSONObject().put("done", false).put("revision", 4));
        assertNull(Ticks.next(state));
        assertEquals(4, task(Ticks.apply(summary(), state), 0).getInt("revision"));
    }

    @Test
    public void aRefusedTapPutsTheRowBackWithTheServersReason() throws Exception {
        JSONObject state = new JSONObject();
        Ticks.tap(state, task(summary(), 0), TODAY, "key-one-0000000000", 0, false);
        Ticks.next(state);
        Ticks.tap(state, task(Ticks.apply(summary(), state), 0), TODAY, "key-two-0000000000", 0, false);
        Ticks.refused(state, A, "This task changed.", 0);
        assertNull(Ticks.next(state));
        assertFalse(task(Ticks.apply(summary(), state), 0).getBoolean("done"));
        assertEquals("“Pick up a parcel”: This task changed.", Ticks.note(state, 1));
        assertNull(Ticks.undo(state, 1));
    }

    @Test
    public void aConfirmedRevisionHoldsUntilASummaryCarriesIt() throws Exception {
        JSONObject state = new JSONObject();
        Ticks.tap(state, task(summary(), 0), TODAY, "key-one-0000000000", 0, true);
        Ticks.next(state);
        Ticks.confirmed(state, A, new JSONObject().put("done", true).put("revision", 3));
        Ticks.prune(state, summary());  // A summary fetched before the save still has revision 2.
        assertEquals(3, task(Ticks.apply(summary(), state), 0).getInt("revision"));
        JSONObject fresh = summary();
        task(fresh, 0).put("done", true).put("revision", 3);
        Ticks.prune(state, fresh);
        assertEquals(0, state.getJSONObject("items").length());
    }

    @Test
    public void rowsStayPutUntilTheUndoEndsAndRoutinesComeFirst() throws Exception {
        JSONObject state = new JSONObject();
        Ticks.tap(state, task(summary(), 0), TODAY, "key-one-0000000000", 1000, false);
        JSONObject day = Ticks.apply(summary(), state).getJSONObject("schedule").getJSONArray("days").getJSONObject(0);
        Ticks.Checklist during = Ticks.checklist(day, state, 1000 + Ticks.UNDO - 1);
        assertEquals("cu_b", during.open.get(0).getString("id"));
        assertEquals("task_a", during.open.get(1).getString("id"));  // Done, but still where it was tapped.
        assertEquals(1, during.finished);
        assertEquals(2, during.total);  // The deadline is not part of the list.
        Ticks.Checklist after = Ticks.checklist(day, state, 1000 + Ticks.UNDO);
        assertEquals(1, after.open.size());
        assertEquals("task_a", after.done.get(0).getString("id"));
    }

    @Test
    public void theDayTurnsAtFourInTheAccountsTimezoneFromTheCachedNextDay() throws Exception {
        JSONObject data = summary();
        // 03:59 in London (BST) on the 14th is still the 13th, like the website's briefing day.
        JSONObject late = Sync.today(data, java.time.Instant.parse("2026-10-14T02:59:00Z"));
        assertEquals(TODAY, late.getString("date"));
        JSONObject next = Sync.today(data, java.time.Instant.parse("2026-10-14T03:00:00Z"));
        assertEquals("2026-10-14", next.getString("date"));
        JSONObject stretch = next.getJSONArray("tasks").getJSONObject(0);
        assertTrue(Ticks.tickable(stretch, "2026-10-14", "2026-10-14"));
        assertFalse(Ticks.tickable(stretch, "2026-10-14", TODAY));  // The next day only once it has begun.
        assertNull(Sync.today(data, java.time.Instant.parse("2026-10-16T12:00:00Z")));  // Beyond the cache.
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
