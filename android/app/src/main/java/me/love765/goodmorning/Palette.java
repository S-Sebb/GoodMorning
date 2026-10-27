package me.love765.goodmorning;

import android.content.Context;
import android.graphics.Color;
import android.widget.RemoteViews;

import org.json.JSONObject;

import java.time.LocalTime;
import java.util.HashMap;
import java.util.Map;

/**
 * The website's color schemes (assets/web/color-schemes.css), so widgets match the day and night
 * look chosen on this phone (the account's earlier choice until the phone chooses its own). Like the website,
 * they follow the clock rather than the phone's dark mode: the day scheme from 06:00, the night scheme from 18:00.
 */
final class Palette {
    final int surface, ink, muted, accent, line, wash, paper, bubble, bubbleLine, border, warm;
    /** A quick note's paper and the deeper shades of the notes stacked behind it, from the scheme's warm color. */
    final int note, noteBehind, noteBack, tape;

    private Palette(String surface, String ink, String muted, String accent, String line, String wash,
                    String paper, String bubble, String bubbleLine, String border, String warm) {
        this.surface = Color.parseColor(surface);
        this.ink = Color.parseColor(ink);
        this.muted = Color.parseColor(muted);
        this.accent = Color.parseColor(accent);
        this.line = Color.parseColor(line);
        this.wash = Color.parseColor(wash);
        this.paper = Color.parseColor(paper);
        this.bubble = Color.parseColor(bubble);
        this.bubbleLine = Color.parseColor(bubbleLine);
        this.border = Color.parseColor(border);
        this.warm = Color.parseColor(warm);
        // On dark schemes the warm color goes into near-black, not the bluish surface, which would turn it grey.
        boolean dark = Color.luminance(this.surface) < 0.3;
        int base = dark ? Color.rgb(24, 22, 20) : this.surface;
        this.note = mix(base, this.warm, dark ? 0.26f : 0.34f);
        this.noteBehind = mix(base, this.warm, dark ? 0.33f : 0.46f);
        this.noteBack = mix(base, this.warm, dark ? 0.40f : 0.58f);
        this.tape = mix(this.surface, this.accent, dark ? 0.45f : 0.3f);
    }

    private static int mix(int from, int to, float share) {
        return Color.rgb(Math.round(Color.red(from) + (Color.red(to) - Color.red(from)) * share),
                Math.round(Color.green(from) + (Color.green(to) - Color.green(from)) * share),
                Math.round(Color.blue(from) + (Color.blue(to) - Color.blue(from)) * share));
    }

    private static final Map<String, Palette> DAY = new HashMap<>();
    private static final Map<String, Palette> NIGHT = new HashMap<>();

    static {
        DAY.put("classic", new Palette("#fffefa", "#233c36", "#607169", "#35765b", "#d8dfd4", "#e8eee3", "#f4f2ec", "#fffefa", "#d8dfd4", "#c4cfc4", "#d8b471"));
        DAY.put("warm", new Palette("#fffbf5", "#554032", "#7d6858", "#987052", "#e0cbb8", "#f1e4d4", "#fbf4e9", "#fffdf9", "#ead8c5", "#ceb29a", "#d8b471"));
        DAY.put("morning-sky", new Palette("#fffdf7", "#293e50", "#304758", "#27465e", "#cfdae0", "#e5eef3", "#f3f8f9", "#fffdf7", "#cfdae0", "#9eb8c8", "#d3af64"));
        DAY.put("first-light", new Palette("#fffaf5", "#48443c", "#594f43", "#784a30", "#e3d8c7", "#f4ebdc", "#f3ede2", "#fffaf5", "#e3d8c7", "#c6b798", "#c69c55"));
        DAY.put("grass-block", new Palette("#fbf6e9", "#2d2620", "#5e5246", "#3f7f26", "#c9b997", "#f1e8d0", "#fbf6e9", "#fffdf6", "#ddd0ad", "#b9a77f", "#e0a93a"));
        DAY.put("picnic", new Palette("#fff7e8", "#4a2f22", "#73533f", "#b8445f", "#ecd0ae", "#fdeedb", "#fff7e8", "#fffbf2", "#ecd0ae", "#d4ad86", "#f0b443"));
        NIGHT.put("classic", new Palette("#192638", "#edece7", "#b1bac8", "#d8bd8b", "#334156", "#223248", "#111c2a", "#192638", "#334156", "#4a5a72", "#d8bd8b"));
        NIGHT.put("starry", new Palette("#111c32", "#eef2fb", "#b0bed6", "#b8c9f4", "#2d3d59", "#1b2a44", "#0d172b", "#16233d", "#2d3d59", "#526789", "#d8c493"));
        NIGHT.put("city-lights", new Palette("#151b31", "#f2efe8", "#bdb9cb", "#f2c27b", "#2e3452", "#1d2442", "#0f1428", "#1a2139", "#2e3452", "#5a5f82", "#f2c27b"));
        NIGHT.put("midnight-violet", new Palette("#2a2b37", "#f8f8f2", "#b6bbd6", "#ff79c6", "#3d4052", "#33354a", "#24252f", "#2f303d", "#3d4052", "#6d6a9c", "#ffb86c"));
        NIGHT.put("grass-block", new Palette("#262b45", "#eef0f8", "#b9bfd9", "#ffd166", "#444b70", "#30365a", "#262b45", "#2c3150", "#3d4468", "#4a5280", "#ffd166"));
        NIGHT.put("picnic", new Palette("#362a4c", "#f8eeff", "#d2c3e4", "#ffb3c7", "#54446e", "#403257", "#362a4c", "#3d3055", "#54446e", "#5f4b7d", "#ffd38a"));
    }

    /** This phone's day and night schemes, or the website's defaults. */
    static Palette[] of(Context context) {
        JSONObject appearance = Sync.cached(context).optJSONObject("appearance");
        String day = appearance == null ? "" : appearance.optString("day");
        String night = appearance == null ? "" : appearance.optString("night");
        return new Palette[] {DAY.getOrDefault(day, DAY.get("morning-sky")), NIGHT.getOrDefault(night, NIGHT.get("starry"))};
    }

    /** Whether this phone uses the website's Pixel style. */
    static boolean pixel(Context context) {
        JSONObject appearance = Sync.cached(context).optJSONObject("appearance");
        return appearance != null && "pixel".equals(appearance.optString("style"));
    }

    /** The hours of the day scheme, as in src/goodmorning/web/chat_theme.py. */
    static final int DAY_STARTS = 6, NIGHT_STARTS = 18;

    static boolean night() {
        int hour = LocalTime.now().getHour();
        return hour < DAY_STARTS || hour >= NIGHT_STARTS;
    }

    /** The day or night scheme for the time now. */
    static Palette now(Context context) {
        return of(context)[night() ? 1 : 0];
    }

    /** A color picked from the day or night scheme. */
    interface Pick {
        int from(Palette palette);
    }

    static void color(RemoteViews views, Palette[] schemes, int id, String method, Pick pick) {
        pair(views, id, method, pick.from(schemes[0]), pick.from(schemes[1]));
    }

    /** A fixed day and night color; widgets are redrawn when the scheme switches. */
    static void pair(RemoteViews views, int id, String method, int day, int night) {
        views.setInt(id, method, night() ? night : day);
    }

    static void text(RemoteViews views, Palette[] schemes, int id, Pick pick) {
        color(views, schemes, id, "setTextColor", pick);
    }

    static void tint(RemoteViews views, Palette[] schemes, int id, Pick pick) {
        color(views, schemes, id, "setColorFilter", pick);
    }
}
