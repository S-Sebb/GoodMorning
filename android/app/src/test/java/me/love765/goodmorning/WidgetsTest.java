package me.love765.goodmorning;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

import java.time.LocalDateTime;

public class WidgetsTest {
    @Test
    public void theBriefingsWidgetsEveningLastsUntilFourInTheMorning() {
        assertEquals("2026-10-30am", Widgets.period(LocalDateTime.parse("2026-10-30T16:59")));
        assertEquals("2026-10-30pm", Widgets.period(LocalDateTime.parse("2026-10-30T23:00")));
        assertEquals("2026-10-30pm", Widgets.period(LocalDateTime.parse("2026-10-31T03:59")));
        assertEquals("2026-10-31am", Widgets.period(LocalDateTime.parse("2026-10-31T04:00")));
    }
}
