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

import java.io.IOException;

/**
 * Shows a code for the owner to enter in GoodMorning Settings; {@link Pairing} collects this
 * phone's app token. Opened from the "Link this phone" shortcut and from unlinked widgets.
 */
public class LinkActivity extends Activity {
    private static final long REFRESH = 1000;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private TextView code;
    private TextView status;
    private Button again;
    private boolean visible;
    private boolean starting;
    private boolean failed;
    private boolean waiting;

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
        findViewById(R.id.open).setOnClickListener(view -> startActivity(Launcher.start(this)));
        // The code from an earlier visit stays valid; a new one would make the entered code useless.
        if (!Sync.linked(this) && Pairing.code(this) == null) pair();
    }

    private void pair() {
        starting = true;
        failed = false;
        show();
        new Thread(() -> {
            boolean started;
            try {
                Pairing.start(this);
                started = true;
            } catch (IOException | JSONException error) {
                started = false;
            }
            boolean ok = started;
            runOnUiThread(() -> {
                starting = false;
                failed = !ok;
                Pairing.claimInBackground(this);
                show();
            });
        }).start();
    }

    /** Follows the saved code: waiting, linked or expired. */
    private void show() {
        handler.removeCallbacksAndMessages(null);
        String current = Pairing.code(this);
        boolean linked = Sync.linked(this);
        if (linked && waiting) linked();  // The code on screen was just used.
        waiting = !starting && !linked && current != null;
        code.setText(waiting ? current : "");
        status.setText(starting ? R.string.link_starting : linked ? R.string.link_done : failed ? R.string.link_failed
                : waiting ? R.string.link_waiting : R.string.link_expired);
        again.setVisibility(starting || linked || waiting ? View.GONE : View.VISIBLE);
        if (visible && (starting || waiting)) handler.postDelayed(this::show, REFRESH);
    }

    /** Without Web Push the app posts notifications itself, which needs Android's permission. */
    private void linked() {
        if (Build.VERSION.SDK_INT >= 33 && !Device.chromeMode(this)) {
            requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS}, 1);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        visible = true;
        Pairing.claimInBackground(this);
        show();
    }

    @Override
    protected void onPause() {
        visible = false;
        handler.removeCallbacksAndMessages(null);
        super.onPause();
    }
}
