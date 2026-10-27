package me.love765.goodmorning;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.widget.Toast;

/**
 * A tap on a Today widget row, with no screen of its own. The ○/✓ of a to-do the server marks tickable ticks it;
 * anywhere else opens the row's page. It is not exported, so no other app can tick to-dos through it.
 */
public class RowActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        Intent tap = getIntent();
        if (tap.hasExtra("id")) {
            Context app = getApplicationContext();
            new Thread(() -> {
                if (!Sync.tick(app, tap.getStringExtra("id"), tap.getStringExtra("date"),
                        tap.getIntExtra("revision", 0), tap.getBooleanExtra("done", true))) {
                    // Android 13 and newer hide it when this app's notifications are off.
                    new Handler(Looper.getMainLooper()).post(() ->
                            Toast.makeText(Language.apply(app), R.string.widget_tick_failed, Toast.LENGTH_LONG).show());
                }
                Sync.run(app);  // The rest of the schedule, or after a failure what the server holds now.
            }).start();
        } else {
            startActivity(new Intent(this, Launcher.class).setData(tap.getData()).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        }
        finish();
    }
}
