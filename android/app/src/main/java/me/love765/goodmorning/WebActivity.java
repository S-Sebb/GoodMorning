package me.love765.goodmorning;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Insets;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.webkit.CookieManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.window.OnBackInvokedDispatcher;

/**
 * GoodMorning in the app's own WebView, for phones without Google services, where Chrome's
 * verified full-screen view is unavailable. Pages of the linked server stay here; other links open
 * in the phone's browser.
 */
public class WebActivity extends Activity {
    private static final int FILES = 1;
    private WebView web;
    private ValueCallback<Uri[]> chooser;
    private String agent;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        web = new WebView(this);
        // A WebView ignores its own padding, so system bars and the keyboard pad a container instead.
        FrameLayout frame = new FrameLayout(this);
        frame.addView(web);
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
        else web.loadUrl(target(getIntent()));
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
    }

    /** WebView writes cookies to disk only now and then; closing the app soon after signing in would lose them. */
    @Override
    protected void onPause() {
        CookieManager.getInstance().flush();
        super.onPause();
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    protected void onDestroy() {
        web.destroy();
        super.onDestroy();
    }
}
