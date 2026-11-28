package me.love765.goodmorning;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;

import org.json.JSONObject;

/**
 * A tap on a chat widget, with no screen of its own: opens the conversation the widget continues, decided now
 * rather than when the widget was drawn. Before starting fresh it checks the conversation's state with the
 * server, as the browser does, and keeps the conversation when that check fails.
 */
public class ConversationActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        Context app = getApplicationContext();
        JSONObject cached = Sync.cached(app).optJSONObject("chat");
        JSONObject chat = Sync.current(app, Sync.cached(app));
        if (chat != null || cached == null || cached.optString("id").isEmpty()) {
            open(chat);
            return;
        }
        new Thread(() -> {
            JSONObject checked = Sync.run(app) ? Sync.current(app, Sync.cached(app)) : cached;
            runOnUiThread(() -> open(checked));
        }).start();
    }

    private void open(JSONObject chat) {
        startActivity(new Intent(this, Launcher.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                .setData(Uri.parse(Server.get(this) + path(chat))));
        finish();
    }

    /** A fresh conversation skips the chat page's saved workspace, which could reopen the old one. */
    static String path(JSONObject chat) {
        return chat == null ? "/chat?mode=secretary" : "/chat?id=" + chat.optString("id");
    }
}
