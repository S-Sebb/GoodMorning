package me.love765.goodmorning;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.security.GeneralSecurityException;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * A pairing code waiting for the owner to enter it in GoodMorning Settings. It is saved until it
 * expires, so the same code stays on screen however often "Link this phone" opens, and the app
 * collects its token in the background while the owner types the code into the website.
 */
final class Pairing {
    private static final long POLL = 3000;
    private static final AtomicBoolean POLLING = new AtomicBoolean();
    private static final Object LOCK = new Object();

    enum Result { LINKED, WAITING, EXPIRED }

    private Pairing() {}

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences("pairing", Context.MODE_PRIVATE);
    }

    /** The code to show, while it is valid for the current server; otherwise null. */
    static String code(Context context) {
        SharedPreferences prefs = prefs(context);
        boolean valid = System.currentTimeMillis() < prefs.getLong("expires", 0)
                && String.valueOf(Server.get(context)).equals(prefs.getString("server", null));
        return valid ? prefs.getString("code", null) : null;
    }

    /** Asks the server for a new code, replacing any earlier one. */
    static String start(Context context) throws IOException, JSONException {
        String name = (Build.MANUFACTURER + " " + Build.MODEL).trim();
        JSONObject pairing = Api.pair(context, name.length() > 60 ? name.substring(0, 60) : name);
        // A little early, so the app never shows a code the server has just expired.
        long expires = System.currentTimeMillis() + (pairing.optLong("expires", 600) - 15) * 1000;
        prefs(context).edit().putString("code", pairing.getString("code")).putString("secret", pairing.getString("secret"))
                .putString("server", Server.get(context)).putLong("expires", expires).apply();
        return pairing.getString("code");
    }

    static Result claim(Context context) {
        synchronized (LOCK) {
            if (code(context) == null) return Sync.linked(context) ? Result.LINKED : Result.EXPIRED;
            try {
                JSONObject answer = Api.claim(context, prefs(context).getString("secret", ""));
                if (!answer.has("token")) return Result.WAITING;
                Api.saveToken(context, answer.getString("token"));
                prefs(context).edit().clear().apply();
            } catch (Api.Failure failure) {
                if (failure.status != 404) return Result.WAITING;
                prefs(context).edit().clear().apply();
                return Result.EXPIRED;
            } catch (IOException | JSONException | GeneralSecurityException offline) {
                return Result.WAITING;  // Offline for a moment: keep waiting while the code is valid.
            }
        }
        Sync.schedule(context);
        Sync.run(context);
        return Result.LINKED;
    }

    /** Checks every few seconds until the code is used or expires; one check at a time. */
    static void claimInBackground(Context context) {
        Context app = context.getApplicationContext();
        if (code(app) == null || !POLLING.compareAndSet(false, true)) return;
        new Thread(() -> {
            try {
                while (claim(app) == Result.WAITING) Thread.sleep(POLL);
            } catch (InterruptedException ignored) {
                // The process is ending; the next launch checks again.
            } finally {
                POLLING.set(false);
            }
        }).start();
    }
}
