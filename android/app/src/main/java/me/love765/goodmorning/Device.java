package me.love765.goodmorning;

import android.content.Context;
import android.content.pm.PackageManager;

import com.google.androidbrowserhelper.trusted.TwaProviderPicker;

/** Which way this phone shows GoodMorning. */
final class Device {
    private Device() {}

    /**
     * Chrome's full-screen view and Web Push both depend on Google services: Chrome verifies the
     * site through a Google web service, and Chrome's pushes travel through Google's push service.
     * Without them the app uses its own WebView and checks for updates itself.
     */
    static boolean chromeMode(Context context) {
        PackageManager manager = context.getPackageManager();
        try {
            if (!manager.getApplicationInfo("com.google.android.gms", 0).enabled) return false;
        } catch (PackageManager.NameNotFoundException missing) {
            return false;
        }
        return TwaProviderPicker.pickProvider(manager).launchMode == TwaProviderPicker.LaunchMode.TRUSTED_WEB_ACTIVITY;
    }
}
