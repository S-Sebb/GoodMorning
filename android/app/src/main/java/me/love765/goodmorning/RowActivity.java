package me.love765.goodmorning;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;

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
            new Thread(() -> Sync.tick(app, tap.getStringExtra("id"), tap.getStringExtra("date"),
                    tap.getIntExtra("revision", 0), tap.getBooleanExtra("done", true))).start();
        } else {
            startActivity(new Intent(this, Launcher.class).setData(tap.getData()).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        }
        finish();
    }
}
