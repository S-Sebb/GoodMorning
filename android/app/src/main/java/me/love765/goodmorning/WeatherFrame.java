package me.love765.goodmorning;

import org.json.JSONArray;
import org.json.JSONObject;

import java.time.Duration;
import java.time.LocalDateTime;

/**
 * The server's 18-hour weather frame (src/goodmorning/weather.py, forecast_frame): 06:00–24:00, or
 * 18:00 to noon for late reads. Headlines use only the hours after now, as the website does.
 */
final class WeatherFrame {
    static final int HOURS = 18;
    static final int WET = 50;
    /** Upper bounds of the US AQI levels: good, moderate, sensitive groups, unhealthy, very unhealthy. */
    static final int[] AQI_LIMITS = {50, 100, 150, 200, 300};

    enum Rain { DRY, DRY_UNTIL, EASING, THROUGH }

    final LocalDateTime start;
    final double[] temp = new double[HOURS];
    final int[] rain = new int[HOURS];
    /** Null when the server had no hourly air quality. */
    final int[] air;
    /** Sunrise and sunset as hours from the start; true marks a sunrise. */
    final double[] sun;
    final boolean[] sunrise;
    final double[][] night;
    final boolean snow;

    private WeatherFrame(JSONObject frame) throws Exception {
        start = LocalDateTime.parse(frame.getString("start"));
        if (start.getMinute() != 0 || (start.getHour() != 6 && start.getHour() != 18)) throw new IllegalArgumentException("start");
        JSONArray hours = frame.getJSONArray("hours");
        if (hours.length() != HOURS) throw new IllegalArgumentException("hours");
        boolean hasAir = !hours.getJSONArray(0).isNull(2);
        air = hasAir ? new int[HOURS] : null;
        for (int i = 0; i < HOURS; i++) {
            JSONArray row = hours.getJSONArray(i);
            temp[i] = row.getDouble(0);
            rain[i] = row.getInt(1);
            if (hasAir) air[i] = row.getInt(2);
        }
        JSONArray marks = frame.getJSONArray("sun");
        sun = new double[marks.length()];
        sunrise = new boolean[marks.length()];
        for (int i = 0; i < marks.length(); i++) {
            sunrise[i] = "sunrise".equals(marks.getJSONArray(i).getString(0));
            sun[i] = marks.getJSONArray(i).getDouble(1);
        }
        JSONArray spans = frame.getJSONArray("night");
        night = new double[spans.length()][];
        for (int i = 0; i < spans.length(); i++) night[i] = new double[] {spans.getJSONArray(i).getDouble(0), spans.getJSONArray(i).getDouble(1)};
        snow = frame.getBoolean("snow");
    }

    /** The frame, or null when it is missing or not in the expected shape. */
    static WeatherFrame parse(JSONObject frame) {
        try {
            return frame == null ? null : new WeatherFrame(frame);
        } catch (Exception unreadable) {
            return null;
        }
    }

    boolean late() {
        return start.getHour() == 18;
    }

    /** Frame hours already gone at this moment, or -1 once the whole frame has passed. */
    int past(LocalDateTime now) {
        long hours = Duration.between(start, now).toHours();
        return hours >= HOURS ? -1 : (int) Math.max(hours, 0);
    }

    /** "07:36" for a frame offset in hours; the end of the day frame reads 24:00. */
    String clock(double offset) {
        long minutes = start.getHour() * 60L + Math.round(offset * 60);
        if (minutes == 24 * 60 && offset == HOURS) return "24:00";
        return String.format("%02d:%02d", (minutes / 60) % 24, minutes % 60);
    }

    int high(int past) {
        int value = Integer.MIN_VALUE;
        for (int i = past; i < HOURS; i++) value = Math.max(value, (int) Math.round(temp[i]));
        return value;
    }

    int low(int past) {
        int value = Integer.MAX_VALUE;
        for (int i = past; i < HOURS; i++) value = Math.min(value, (int) Math.round(temp[i]));
        return value;
    }

    int rainPeak(int past) {
        int value = 0;
        for (int i = past; i < HOURS; i++) value = Math.max(value, rain[i]);
        return value;
    }

    Rain rainState(int past) {
        int first = rainChange(past, true);
        if (first < 0) return Rain.DRY;
        if (first > past) return Rain.DRY_UNTIL;
        return rainChange(past, false) < 0 ? Rain.THROUGH : Rain.EASING;
    }

    /** The first hour from `past` that is wet (or dry), as a frame offset; -1 if none. */
    int rainChange(int past, boolean wet) {
        for (int i = past; i < HOURS; i++) if ((rain[i] >= WET) == wet) return i;
        return -1;
    }

    int airLow(int past) {
        int value = Integer.MAX_VALUE;
        for (int i = past; i < HOURS; i++) value = Math.min(value, air[i]);
        return value;
    }

    int airHigh(int past) {
        int value = 0;
        for (int i = past; i < HOURS; i++) value = Math.max(value, air[i]);
        return value;
    }

    /** 0 good … 5 hazardous, from the worst hour ahead. */
    int airLevel(int past) {
        int high = airHigh(past);
        int level = 0;
        while (level < AQI_LIMITS.length && high > AQI_LIMITS[level]) level++;
        return level;
    }
}
