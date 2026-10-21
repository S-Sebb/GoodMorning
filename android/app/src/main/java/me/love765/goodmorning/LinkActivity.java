package me.love765.goodmorning;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Button;
import android.widget.TextView;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.security.GeneralSecurityException;

/**
 * Shows a code for the owner to enter in GoodMorning Settings, then collects this phone's app token.
 * Opened from the "Link this phone" shortcut and from unlinked widgets.
 */
public class LinkActivity extends Activity {
    private static final long POLL = 3000;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private TextView code;
    private TextView status;
    private Button again;
    private String secret;
    private boolean visible;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (Server.get(this) == null) {
            startActivity(new Intent(this, ServerActivity.class));
            finish();
            return;
        }
        setContentView(R.layout.link);
        code = findViewById(R.id.code);
        status = findViewById(R.id.status);
        again = findViewById(R.id.again);
        again.setOnClickListener(view -> pair());
        findViewById(R.id.open).setOnClickListener(view -> startActivity(new Intent(this, Launcher.class)));
        if (Sync.linked(this)) show(R.string.link_done, true);
        else pair();
    }

    private void show(int text, boolean offerNewCode) {
        status.setText(text);
        again.setVisibility(offerNewCode ? View.VISIBLE : View.GONE);
        if (offerNewCode) code.setText("");
    }

    private void pair() {
        secret = null;
        show(R.string.link_starting, false);
        String name = (Build.MANUFACTURER + " " + Build.MODEL).trim();
        new Thread(() -> {
            try {
                JSONObject pairing = Api.pair(this, name.length() > 60 ? name.substring(0, 60) : name);
                runOnUiThread(() -> {
                    secret = pairing.optString("secret");
                    code.setText(pairing.optString("code"));
                    show(R.string.link_waiting, false);
                    poll();
                });
            } catch (IOException | JSONException error) {
                runOnUiThread(() -> show(R.string.link_failed, true));
            }
        }).start();
    }

    private void poll() {
        handler.removeCallbacksAndMessages(null);
        if (secret != null && visible) handler.postDelayed(this::claim, POLL);
    }

    private void claim() {
        String current = secret;
        new Thread(() -> {
            int result;
            try {
                JSONObject answer = Api.claim(this, current);
                if (answer.has("token")) {
                    Api.saveToken(this, answer.getString("token"));
                    Sync.schedule(this);
                    Sync.run(this);
                    result = R.string.link_done;
                } else {
                    result = 0;
                }
            } catch (Api.Failure failure) {
                result = failure.status == 404 ? R.string.link_expired : 0;
            } catch (IOException | JSONException | GeneralSecurityException error) {
                result = 0;  // Offline for a moment: keep waiting while the code is valid.
            }
            int shown = result;
            runOnUiThread(() -> {
                if (!current.equals(secret)) return;
                if (shown == 0) {
                    poll();
                    return;
                }
                secret = null;
                show(shown, shown == R.string.link_expired);
                if (shown == R.string.link_done) {
                    code.setText("");
                    // Without Web Push the app posts notifications itself, which needs Android's permission.
                    if (Build.VERSION.SDK_INT >= 33 && !Device.chromeMode(this)) {
                        requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS}, 1);
                    }
                }
            });
        }).start();
    }

    @Override
    protected void onResume() {
        super.onResume();
        visible = true;
        poll();
    }

    @Override
    protected void onPause() {
        visible = false;
        handler.removeCallbacksAndMessages(null);
        super.onPause();
    }
}
