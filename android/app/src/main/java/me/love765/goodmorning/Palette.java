package me.love765.goodmorning;

import android.content.Context;
import android.content.res.Configuration;
import android.graphics.Color;
import android.os.Build;
import android.widget.RemoteViews;

import org.json.JSONObject;

import java.util.HashMap;
import java.util.Map;

/**
 * The website's color schemes (assets/web/color-schemes.css), so widgets match the account's
 * chosen day and night look. Widgets follow the phone's dark mode: the day scheme in light mode,
 * the night scheme in dark mode.
 */
final class Palette {
    final int surface, ink, muted, accent, line, wash, paper, bubble, bubbleLine, border;

    private Palette(String surface, String ink, String muted, String accent, String line, String wash,
                    String paper, String bubble, String bubbleLine, String border) {
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
    }

    private static final Map<String, Palette> DAY = new HashMap<>();
    private static final Map<String, Palette> NIGHT = new HashMap<>();

    static {
        DAY.put("classic", new Palette("#fffefa", "#233c36", "#607169", "#35765b", "#d8dfd4", "#e8eee3", "#f4f2ec", "#fffefa", "#d8dfd4", "#c4cfc4"));
        DAY.put("warm", new Palette("#fffbf5", "#554032", "#7d6858", "#987052", "#e0cbb8", "#f1e4d4", "#fbf4e9", "#fffdf9", "#ead8c5", "#ceb29a"));
        DAY.put("morning-sky", new Palette("#fffdf7", "#293e50", "#304758", "#27465e", "#cfdae0", "#e5eef3", "#f3f8f9", "#fffdf7", "#cfdae0", "#9eb8c8"));
        DAY.put("first-light", new Palette("#fffaf5", "#48443c", "#594f43", "#784a30", "#e3d8c7", "#f4ebdc", "#f3ede2", "#fffaf5", "#e3d8c7", "#c6b798"));
        DAY.put("grass-block", new Palette("#fbf6e9", "#2d2620", "#5e5246", "#3f7f26", "#c9b997", "#f1e8d0", "#fbf6e9", "#fffdf6", "#ddd0ad", "#b9a77f"));
        DAY.put("picnic", new Palette("#fff7e8", "#4a2f22", "#73533f", "#b8445f", "#ecd0ae", "#fdeedb", "#fff7e8", "#fffbf2", "#ecd0ae", "#d4ad86"));
        NIGHT.put("classic", new Palette("#192638", "#edece7", "#b1bac8", "#d8bd8b", "#334156", "#223248", "#111c2a", "#192638", "#334156", "#4a5a72"));
        NIGHT.put("starry", new Palette("#111c32", "#eef2fb", "#b0bed6", "#b8c9f4", "#2d3d59", "#1b2a44", "#0d172b", "#16233d", "#2d3d59", "#526789"));
        NIGHT.put("city-lights", new Palette("#151b31", "#f2efe8", "#bdb9cb", "#f2c27b", "#2e3452", "#1d2442", "#0f1428", "#1a2139", "#2e3452", "#5a5f82"));
        NIGHT.put("midnight-violet", new Palette("#2a2b37", "#f8f8f2", "#b6bbd6", "#ff79c6", "#3d4052", "#33354a", "#24252f", "#2f303d", "#3d4052", "#6d6a9c"));
        NIGHT.put("grass-block", new Palette("#262b45", "#eef0f8", "#b9bfd9", "#ffd166", "#444b70", "#30365a", "#262b45", "#2c3150", "#3d4468", "#4a5280"));
        NIGHT.put("picnic", new Palette("#362a4c", "#f8eeff", "#d2c3e4", "#ffb3c7", "#54446e", "#403257", "#362a4c", "#3d3055", "#54446e", "#5f4b7d"));
    }

    /** The account's day and night schemes, or the website's defaults. */
    static Palette[] of(Context context) {
        JSONObject appearance = Sync.cached(context).optJSONObject("appearance");
        String day = appearance == null ? "" : appearance.optString("day");
        String night = appearance == null ? "" : appearance.optString("night");
        return new Palette[] {DAY.getOrDefault(day, DAY.get("morning-sky")), NIGHT.getOrDefault(night, NIGHT.get("starry"))};
    }

    /** A color picked from the day or night scheme, switched by the launcher on Android 12+. */
    interface Pick {
        int from(Palette palette);
    }

    static void color(Context context, RemoteViews views, Palette[] schemes, int id, String method, Pick pick) {
        pair(context, views, id, method, pick.from(schemes[0]), pick.from(schemes[1]));
    }

    /** A fixed day and night color, switched by the launcher on Android 12+. */
    static void pair(Context context, RemoteViews views, int id, String method, int day, int night) {
        if (Build.VERSION.SDK_INT >= 31) {
            views.setColorInt(id, method, day, night);
        } else {
            boolean dark = (context.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
            views.setInt(id, method, dark ? night : day);
        }
    }

    static void text(Context context, RemoteViews views, Palette[] schemes, int id, Pick pick) {
        color(context, views, schemes, id, "setTextColor", pick);
    }

    static void tint(Context context, RemoteViews views, Palette[] schemes, int id, Pick pick) {
        color(context, views, schemes, id, "setColorFilter", pick);
    }
}
