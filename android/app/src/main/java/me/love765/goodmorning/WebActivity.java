package me.love765.goodmorning;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Insets;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.window.OnBackInvokedDispatcher;

import org.json.JSONException;

import java.io.IOException;

/** GoodMorning in the app's own WebView. Pages of the chosen server stay here; other links open in the phone's browser. */
public class WebActivity extends Activity {
    private static final int FILES = 1;
    private WebView web;
    private ValueCallback<Uri[]> chooser;
    private String agent;
    /** Covers the WebView's own error page while the server can't be reached. */
    private View offline;
    private Button retry;
    private String failed;
    private boolean broken;
    private final Handler later = new Handler(Looper.getMainLooper());
    private final Runnable again = this::retry;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        web = new WebView(this);
        // A WebView ignores its own padding, so system bars and the keyboard pad a container instead.
        FrameLayout frame = new FrameLayout(this);
        frame.addView(web);
        offline = getLayoutInflater().inflate(R.layout.offline, frame, false);
        frame.addView(offline);
        retry = offline.findViewById(R.id.retry);
        retry.setOnClickListener(view -> retry());
        setContentView(frame);
        if (Build.VERSION.SDK_INT >= 30) {
            frame.setOnApplyWindowInsetsListener((view, insets) -> {
                Insets bars = insets.getInsets(android.view.WindowInsets.Type.systemBars() | android.view.WindowInsets.Type.ime());
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
                return insets;
            });
        }
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        agent = settings.getUserAgentString() + " GoodMorningApp/" + BuildConfig.VERSION_NAME;
        name();
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (own(request.getUrl())) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, request.getUrl()));
                } catch (ActivityNotFoundException ignored) {
                    // Nothing can open this link; stay on the current page.
                }
                return true;
            }

            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                broken = false;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (!request.isForMainFrame()) return;
                broken = true;
                failed = request.getUrl().toString();
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (broken) offline();
                else {
                    later.removeCallbacks(again);
                    offline.setVisibility(View.GONE);
                }
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (chooser != null) chooser.onReceiveValue(null);
                chooser = callback;
                try {
                    startActivityForResult(params.createIntent(), FILES);
                } catch (ActivityNotFoundException missing) {
                    chooser = null;
                    return false;
                }
                return true;
            }
        });
        if (Build.VERSION.SDK_INT >= 33) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::back);
        }
        if (state != null) web.restoreState(state);
        else load(target(getIntent()));
    }

    /**
     * Versions before 0.8 showed the site in Chrome where they could, so the sign-in stayed in Chrome.
     * A linked phone signs in here once instead; an unlinked one signs in by hand.
     */
    private void load(String url) {
        SharedPreferences app = getSharedPreferences("app", MODE_PRIVATE);
        String token = Api.token(this);
        if (!app.getBoolean("verified", false) || token == null) {
            app.edit().remove("verified").apply();
            web.loadUrl(url);
            return;
        }
        new Thread(() -> {
            String cookie = null;
            try {
                cookie = Api.signin(this, token).getString("cookie");
                app.edit().remove("verified").apply();
            } catch (IOException | JSONException failed) {
                // Offline, busy or under maintenance: tries again at the next launch.
                if (failed instanceof Api.Failure && ((Api.Failure) failed).status < 500 && ((Api.Failure) failed).status != 429) {
                    app.edit().remove("verified").apply();
                }
            }
            String found = cookie;
            runOnUiThread(() -> {
                if (isDestroyed()) return;
                String server = Server.get(this), had = CookieManager.getInstance().getCookie(server);
                // A sign-in made here earlier, for example while Chrome could not verify the site, stays.
                if (found != null && (had == null || !("; " + had).contains("; " + found.substring(0, found.indexOf('=') + 1)))) {
                    CookieManager.getInstance().setCookie(server, found);
                }
                web.loadUrl(url);
            });
        }).start();
    }

    /**
     * Lets the website recognize the app, for example to reopen the last page, and, once linked,
     * which linked phone this is, so its Settings show this phone's notification choices.
     */
    private void name() {
        String link = Sync.cached(this).optString("device");
        web.getSettings().setUserAgentString(agent + (link.matches("[a-f0-9]{16}") ? " GoodMorningLink/" + link : ""));
    }

    private boolean own(Uri uri) {
        Uri server = Uri.parse(Server.get(this));
        return uri != null && "https".equals(uri.getScheme()) && server.getAuthority().equals(uri.getAuthority());
    }

    private String target(Intent intent) {
        Uri data = intent.getData();
        return own(data) ? data.toString() : Server.get(this) + "/app";
    }

    private void offline() {
        offline.setVisibility(View.VISIBLE);
        retry.setEnabled(true);
        retry.setText(R.string.offline_retry);
        later.removeCallbacks(again);
        later.postDelayed(again, 30_000);
    }

    private void retry() {
        later.removeCallbacks(again);
        retry.setEnabled(false);
        retry.setText(R.string.offline_retrying);
        web.loadUrl(failed);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (intent.getData() != null) web.loadUrl(target(intent));
    }

    private void back() {
        if (web.canGoBack()) web.goBack();
        else finish();
    }

    @Override
    @SuppressWarnings("deprecation")
    @android.annotation.SuppressLint("GestureBackNavigation") // Only Android 12 and older; newer use back().
    public void onBackPressed() {
        back();
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == FILES && chooser != null) {
            chooser.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data));
            chooser = null;
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        name();  // Linking may have finished since; the next page load names this phone.
        if (offline.getVisibility() == View.VISIBLE) retry();  // The connection may be back.
    }

    /** WebView writes cookies to disk only now and then; closing the app soon after signing in would lose them. */
    @Override
    protected void onPause() {
        CookieManager.getInstance().flush();
        later.removeCallbacks(again);
        super.onPause();
    }

    /** Colors chosen in the app reach the widgets as soon as the app leaves the screen. */
    @Override
    protected void onStop() {
        if (!isChangingConfigurations() && Sync.linked(this)) Sync.inBackground(this);
        super.onStop();
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    protected void onDestroy() {
        later.removeCallbacks(again);
        web.destroy();
        super.onDestroy();
    }
}
