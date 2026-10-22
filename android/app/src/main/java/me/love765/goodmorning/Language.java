package me.love765.goodmorning;

import android.content.Context;
import android.content.res.Configuration;

import java.util.Locale;

/**
 * The account's website language, which the app's own text follows once the phone is linked;
 * before that, and for the launcher's widget list, the phone's language.
 */
final class Language {
    private Language() {}

    /** A context whose resources, dates and capitals use the account's language. */
    static Context apply(Context context) {
        String code = Sync.cached(context).optString("language");
        if (code.isEmpty()) return context;
        Configuration config = new Configuration(context.getResources().getConfiguration());
        config.setLocale(Locale.forLanguageTag(code));
        return context.createConfigurationContext(config);
    }

    static Locale of(Context context) {
        return context.getResources().getConfiguration().getLocales().get(0);
    }
}
