package me.love765.goodmorning;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;

import androidx.browser.customtabs.CustomTabsCallback;
import androidx.browser.customtabs.CustomTabsClient;
import androidx.browser.customtabs.CustomTabsService;
import androidx.browser.customtabs.CustomTabsServiceConnection;
import androidx.browser.customtabs.CustomTabsSession;

import com.google.androidbrowserhelper.trusted.LauncherActivity;
import com.google.androidbrowserhelper.trusted.SessionStore;
import com.google.androidbrowserhelper.trusted.SharedPreferencesTokenStore;
import com.google.androidbrowserhelper.trusted.TwaLauncher;

/**
 * Opens the chosen server, after the server picker or a waiting update prompt: full screen in
 * Chrome once Chrome has verified the site, otherwise in the app's own WebView.
 */
public class Launcher extends LauncherActivity {
    /** Chrome answers at once from its cache; a first check goes to Google's verification service. */
    private static final long VERIFY_TIMEOUT = 6000;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private CustomTabsServiceConnection connection;
    private boolean decided;

    @Override
    protected boolean shouldLaunchImmediately() {
        if (Server.get(this) == null) return open(new Intent(this, ServerActivity.class));
        if (Updates.pending(this, false) != null) return open(new Intent(this, UpdateActivity.class));
        Updates.checkInBackground(this);
        Pairing.claimInBackground(this);
        if (Sync.linked(this)) {
            Sync.schedule(this);
            Sync.inBackground(this);
        }
        if (!Device.chromeAvailable(this)) return open(new Intent(this, WebActivity.class).setData(getLaunchingUrl()));
        verify();
        return false;
    }

    /**
     * Without verification Chrome would show the site with an address bar, as where Google's
     * verification service is unreachable; the app's own WebView then shows it full screen instead.
     */
    private void verify() {
        setContentView(R.layout.splash);
        handler.postDelayed(() -> decide(false), VERIFY_TIMEOUT);
        connection = new CustomTabsServiceConnection() {
            @Override
            public void onCustomTabsServiceConnected(ComponentName name, CustomTabsClient client) {
                client.warmup(0);  // Chrome refuses to verify for a client that has not warmed it up.
                CustomTabsSession session = client.newSession(new CustomTabsCallback() {
                    @Override
                    public void onRelationshipValidationResult(int relation, Uri origin, boolean result, Bundle extras) {
                        handler.post(() -> decide(result));
                    }
                });
                if (session == null || !session.validateRelationship(CustomTabsService.RELATION_HANDLE_ALL_URLS, Uri.parse(Server.get(Launcher.this)), null)) {
                    handler.post(() -> decide(false));
                }
            }

            @Override
            public void onServiceDisconnected(ComponentName name) {
                handler.post(() -> decide(false));
            }
        };
        if (!CustomTabsClient.bindCustomTabsService(this, Device.CHROME, connection)) {
            connection = null;
            decide(false);
        }
    }

    private void decide(boolean verified) {
        if (decided || isFinishing()) return;
        decided = true;
        handler.removeCallbacksAndMessages(null);
        if (connection != null) unbindService(connection);
        connection = null;
        Device.verified(this, verified);
        if (verified) launchTwa();
        else open(new Intent(this, WebActivity.class).setData(getLaunchingUrl()));
    }

    /**
     * Opens GoodMorning from the app's own screens. The helper library restarts a launcher that is
     * not opened as a new task, and that restart would land on the closing screen and show nothing.
     */
    static Intent start(Context context) {
        return new Intent(context, Launcher.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
    }

    /** Chrome itself, even when another browser is the phone's default. */
    @Override
    protected TwaLauncher createTwaLauncher() {
        return new TwaLauncher(this, Device.CHROME, SessionStore.makeSessionId(getTaskId()), new SharedPreferencesTokenStore(this));
    }

    private boolean open(Intent screen) {
        startActivity(screen);
        finish();
        return false;
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        if (connection != null) unbindService(connection);
        connection = null;
        super.onDestroy();
    }

    /**
     * /app, which reopens the last page or the page a widget or notification asked for. The site
     * signs the app in only through /app: Chrome holds back the login cookie when another app opens
     * a page directly.
     */
    @Override
    protected Uri getLaunchingUrl() {
        Uri data = getIntent().getData();
        // The build number lets the website offer this app's own updates.
        Uri.Builder app = Uri.parse(Server.get(this) + "/app").buildUpon().appendQueryParameter("app", String.valueOf(BuildConfig.VERSION_CODE));
        // The phone's link, so the colors chosen in the app also reach its widgets.
        String link = Sync.linked(this) ? Sync.cached(this).optString("device") : "";
        if (link.matches("[a-f0-9]{16}")) app.appendQueryParameter("link", link);
        if (isTrustedIntentUrl(data) && !"/app".equals(data.getPath())) {
            app.appendQueryParameter("next", data.getEncodedPath() + (data.getEncodedQuery() == null ? "" : "?" + data.getEncodedQuery()));
        }
        return app.build();
    }

    @Override
    protected boolean isTrustedIntentUrl(Uri uri) {
        Uri server = Uri.parse(Server.get(this));
        return uri != null && "https".equals(uri.getScheme()) && server.getAuthority().equals(uri.getAuthority());
    }
}
