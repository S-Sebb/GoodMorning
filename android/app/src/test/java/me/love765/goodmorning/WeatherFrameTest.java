package me.love765.goodmorning;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

import java.time.LocalDateTime;

public class WeatherFrameTest {
    /** Rain at 06:00 (gone by 10:00) and from 21:00; temperature rises by a degree every four hours. */
    private static JSONObject frame(String start, Integer air) throws Exception {
        JSONArray hours = new JSONArray();
        for (int i = 0; i < WeatherFrame.HOURS; i++) {
            hours.put(new JSONArray().put(10 + i / 4.0).put(i == 0 || i >= 15 ? 80 : 5).put(air == null ? JSONObject.NULL : air + i % 3));
        }
        return new JSONObject().put("start", start).put("past", 0).put("hours", hours)
                .put("sun", new JSONArray().put(new JSONArray().put("sunrise").put(1.6)).put(new JSONArray().put("sunset").put(11.88)))
                .put("night", new JSONArray()).put("snow", false).put("links", new JSONObject());
    }

    @Test
    public void headlinesCountOnlyTheHoursAhead() throws Exception {
        WeatherFrame day = WeatherFrame.parse(frame("2026-10-22T06:00", 30));
        int past = day.past(LocalDateTime.parse("2026-10-22T10:20"));
        assertEquals(4, past);
        assertEquals(WeatherFrame.Rain.DRY_UNTIL, day.rainState(past));
        assertEquals("21:00", day.clock(day.rainChange(past, true)));
        assertEquals(80, day.rainPeak(past));
        assertEquals(14, day.high(past));
        assertEquals(11, day.low(past));
        assertEquals(0, day.airLevel(past));
        assertEquals("07:36", day.clock(1.6));
        assertEquals("24:00", day.clock(WeatherFrame.HOURS));
        assertEquals(WeatherFrame.Rain.EASING, day.rainState(0));
    }

    @Test
    public void lateFramesRunPastMidnightAndExpire() throws Exception {
        WeatherFrame late = WeatherFrame.parse(frame("2026-10-22T18:00", null));
        assertEquals("00:00", late.clock(6));
        assertEquals("12:00", late.clock(WeatherFrame.HOURS));
        assertEquals(WeatherFrame.Rain.THROUGH, late.rainState(16));
        assertNull(late.air);
        assertEquals(-1, late.past(LocalDateTime.parse("2026-10-23T12:00")));
        assertNull(WeatherFrame.parse(frame("2026-10-22T07:00", 30)));
        assertNull(WeatherFrame.parse(null));
    }
}
