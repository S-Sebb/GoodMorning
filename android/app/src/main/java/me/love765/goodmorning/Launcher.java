package me.love765.goodmorning;

import android.content.Intent;
import android.net.Uri;

import com.google.androidbrowserhelper.trusted.LauncherActivity;

/** Opens the chosen server full screen, after the server picker or a waiting update prompt. */
public class Launcher extends LauncherActivity {
    @Override
    protected boolean shouldLaunchImmediately() {
        if (Server.get(this) == null) return open(ServerActivity.class);
        if (Updates.pending(this) != null) return open(UpdateActivity.class);
        Updates.checkInBackground(this);
        return true;
    }

    private boolean open(Class<?> screen) {
        startActivity(new Intent(this, screen));
        finish();
        return false;
    }

    /** The server's /app route reopens the last page, or chat on the first visit. */
    @Override
    protected Uri getLaunchingUrl() {
        return Uri.parse(Server.get(this) + "/app");
    }
}
