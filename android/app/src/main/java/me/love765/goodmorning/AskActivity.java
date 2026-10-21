package me.love765.goodmorning;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;

/** A small dialog over the home screen for asking the secretary from the chat widget. */
public class AskActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        String token = Api.token(this);
        if (token == null) {
            startActivity(new Intent(this, LinkActivity.class));
            finish();
            return;
        }
        setContentView(R.layout.ask);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE);
        JSONObject latest = Sync.cached(this).optJSONObject("chat");
        String chat = latest == null || latest.optString("id").isEmpty() ? null : latest.optString("id");
        TextView conversation = findViewById(R.id.conversation);
        CheckBox fresh = findViewById(R.id.fresh);
        if (chat == null) {
            conversation.setText(R.string.ask_starts_new);
            fresh.setVisibility(View.GONE);
        } else {
            conversation.setText(getString(R.string.ask_continues, latest.optString("title")));
            fresh.setOnCheckedChangeListener((box, checked) -> conversation.setText(checked
                    ? getString(R.string.ask_starts_new) : getString(R.string.ask_continues, latest.optString("title"))));
        }
        EditText text = findViewById(R.id.text);
        TextView status = findViewById(R.id.status);
        Button send = findViewById(R.id.send);
        findViewById(R.id.cancel).setOnClickListener(view -> finish());
        send.setOnClickListener(view -> {
            String message = text.getText().toString().trim();
            if (message.isEmpty()) return;
            String target = fresh.isChecked() ? null : chat;
            send.setEnabled(false);
            status.setText("");
            new Thread(() -> {
                String error;
                String sent = target;
                try {
                    JSONObject answer = Api.chat(this, token, message, target);
                    sent = answer.optString("chat", target);
                    error = null;
                } catch (Api.Failure failure) {
                    error = failure.status == 403 ? getString(R.string.ask_unlinked)
                            : failure.error.isEmpty() ? getString(R.string.ask_failed) : failure.error;
                } catch (IOException | JSONException offline) {
                    error = getString(R.string.ask_failed);
                }
                String problem = error, conversationId = sent;
                runOnUiThread(() -> {
                    if (problem != null) {
                        status.setText(problem);
                        send.setEnabled(true);
                        return;
                    }
                    Sync.markSent(this, conversationId);
                    Toast.makeText(this, R.string.ask_sent, Toast.LENGTH_LONG).show();
                    finish();
                });
            }).start();
        });
    }
}
