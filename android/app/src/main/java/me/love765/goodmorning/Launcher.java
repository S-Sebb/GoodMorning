package me.love765.goodmorning;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ShortcutManager;
import android.net.Uri;
import android.os.Bundle;

/** Opens the chosen server in the app's own WebView, after the server picker or a waiting update prompt. */
public class Launcher extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        // Versions that used Chrome added a "Site Settings" shortcut that no longer works.
        getSystemService(ShortcutManager.class).removeAllDynamicShortcuts();
        if (Server.get(this) == null) open(new Intent(this, ServerActivity.class));
        else if (Updates.pending(this, false) != null) open(new Intent(this, UpdateActivity.class));
        else {
            Updates.checkInBackground(this);
            Pairing.claimInBackground(this);
            if (Sync.linked(this)) {
                Sync.schedule(this);
                Sync.inBackground(this);
            }
            open(new Intent(this, WebActivity.class).setData(launchingUrl()));
        }
    }

    /** Opens GoodMorning from the app's own screens. */
    static Intent start(Context context) {
        return new Intent(context, Launcher.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
    }

    private void open(Intent screen) {
        startActivity(screen);
        finish();
    }

    /** /app, which reopens the last page or the page a widget, notification or link asked for. */
    private Uri launchingUrl() {
        Uri data = getIntent().getData();
        Uri server = Uri.parse(Server.get(this));
        // The build number lets the website offer this app's own updates.
        Uri.Builder app = server.buildUpon().path("/app").appendQueryParameter("app", String.valueOf(BuildConfig.VERSION_CODE));
        // The phone's link, so the colors chosen in the app also reach its widgets.
        String link = Sync.linked(this) ? Sync.cached(this).optString("device") : "";
        if (link.matches("[a-f0-9]{16}")) app.appendQueryParameter("link", link);
        if (data != null && "https".equals(data.getScheme()) && server.getAuthority().equals(data.getAuthority()) && !"/app".equals(data.getPath())) {
            app.appendQueryParameter("next", data.getEncodedPath() + (data.getEncodedQuery() == null ? "" : "?" + data.getEncodedQuery()));
        }
        return app.build();
    }
}
