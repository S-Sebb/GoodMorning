package me.love765.goodmorning;

import android.content.Intent;
import android.net.Uri;

import com.google.androidbrowserhelper.trusted.LauncherActivity;

/**
 * Opens the chosen server, after the server picker or a waiting update prompt: full screen in
 * Chrome where Google services exist, otherwise in the app's own WebView.
 */
public class Launcher extends LauncherActivity {
    @Override
    protected boolean shouldLaunchImmediately() {
        if (Server.get(this) == null) return open(new Intent(this, ServerActivity.class));
        if (Updates.pending(this) != null) return open(new Intent(this, UpdateActivity.class));
        Updates.checkInBackground(this);
        if (Sync.linked(this)) {
            Sync.schedule(this);
            Sync.inBackground(this);
        }
        if (!Device.chromeMode(this)) return open(new Intent(this, WebActivity.class).setData(getLaunchingUrl()));
        return true;
    }

    private boolean open(Intent screen) {
        startActivity(screen);
        finish();
        return false;
    }

    /** A page of the linked server (from a widget or notification), or /app, which reopens the last page. */
    @Override
    protected Uri getLaunchingUrl() {
        Uri data = getIntent().getData();
        return isTrustedIntentUrl(data) ? data : Uri.parse(Server.get(this) + "/app");
    }

    @Override
    protected boolean isTrustedIntentUrl(Uri uri) {
        Uri server = Uri.parse(Server.get(this));
        return uri != null && "https".equals(uri.getScheme()) && server.getAuthority().equals(uri.getAuthority());
    }
}
