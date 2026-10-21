package me.love765.goodmorning;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;

import androidx.browser.customtabs.CustomTabsService;

/** Which way this phone shows GoodMorning. */
final class Device {
    static final String CHROME = "com.android.chrome";

    private Device() {}

    /**
     * Chrome's full-screen view and Web Push both depend on Google services: Chrome verifies the
     * site through a Google web service, and Chrome's pushes travel through Google's push service.
     * Only Chrome itself is used: other browsers, such as some phone makers' own, may claim the
     * full-screen view but open an ordinary tab instead.
     */
    static boolean chromeAvailable(Context context) {
        PackageManager manager = context.getPackageManager();
        try {
            if (!manager.getApplicationInfo("com.google.android.gms", 0).enabled || !manager.getApplicationInfo(CHROME, 0).enabled) return false;
        } catch (PackageManager.NameNotFoundException missing) {
            return false;
        }
        return !manager.queryIntentServices(new Intent(CustomTabsService.ACTION_CUSTOM_TABS_CONNECTION).setPackage(CHROME), 0).isEmpty();
    }

    /**
     * Whether the app opened in Chrome's full-screen view at its last launch. Where Chrome cannot
     * reach Google's verification service, the app uses its own WebView and checks for
     * notifications itself.
     */
    static boolean chromeMode(Context context) {
        return chromeAvailable(context) && context.getSharedPreferences("app", Context.MODE_PRIVATE).getBoolean("verified", true);
    }

    static void verified(Context context, boolean verified) {
        context.getSharedPreferences("app", Context.MODE_PRIVATE).edit().putBoolean("verified", verified).apply();
    }
}
