package me.love765.goodmorning;

import android.app.Activity;
import android.appwidget.AppWidgetManager;
import android.content.ComponentName;
import android.os.Bundle;

/**
 * Debug builds only, for tests/android: `am start -n me.love765.goodmorning/.TestHooks` with
 * `--es pin Chat` (ask the launcher to place that widget), `--es departed <chat> --ei ago <minutes>`
 * (the user left that conversation so long ago; `--ei replied_ago <minutes>` its last reply came so long ago) and `--ez sync true` (fetch the summary, redraw the widgets).
 */
public class TestHooks extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        String pin = getIntent().getStringExtra("pin");
        if (pin != null) {
            getSystemService(AppWidgetManager.class).requestPinAppWidget(
                    new ComponentName(this, Widgets.class.getName() + "$" + pin), null, null);
        }
        String departed = getIntent().getStringExtra("departed");
        if (departed != null) {
            Sync.departed(this, departed, System.currentTimeMillis() - getIntent().getIntExtra("ago", 0) * 60_000L);
            if (getIntent().hasExtra("replied_ago")) {
                Sync.repliedAt(this, departed, System.currentTimeMillis() - getIntent().getIntExtra("replied_ago", 0) * 60_000L);
            }
        }
        if (getIntent().getBooleanExtra("sync", false)) Sync.inBackground(this);
        finish();
    }
}
