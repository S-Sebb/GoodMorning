package me.love765.goodmorning;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.widget.ImageView;
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
    protected void attachBaseContext(Context base) {
        super.attachBaseContext(Language.apply(base));
    }

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
        getWindow().setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
        style();
        JSONObject latest = Sync.cached(this).optJSONObject("chat");
        String chat = latest == null || latest.optString("id").isEmpty() ? null : latest.optString("id");
        TextView conversation = findViewById(R.id.conversation);
        JSONObject secretary = Sync.cached(this).optJSONObject("secretary");
        String name = secretary == null || secretary.isNull("name") || secretary.optString("name").isEmpty()
                ? getString(R.string.chat_name_default) : secretary.optString("name");
        ((TextView) findViewById(R.id.heading)).setText(getString(R.string.ask_heading, name));
        portrait(secretary);
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

    /** The website's look in the account's day or night scheme, as in the chat widget. */
    private void style() {
        Palette p = Palette.now(this);
        float density = getResources().getDisplayMetrics().density;
        findViewById(R.id.card).setBackground(rounded(p.paper, p.border, 24 * density, density));
        findViewById(R.id.text).setBackground(rounded(p.surface, p.border, 16 * density, density));
        ((EditText) findViewById(R.id.text)).setTextColor(p.ink);
        ((EditText) findViewById(R.id.text)).setHintTextColor(p.muted);
        ((TextView) findViewById(R.id.label)).setTextColor(p.muted);
        ((TextView) findViewById(R.id.heading)).setTextColor(p.ink);
        ((TextView) findViewById(R.id.conversation)).setTextColor(p.muted);
        CheckBox fresh = findViewById(R.id.fresh);
        fresh.setTextColor(p.ink);
        fresh.setButtonTintList(ColorStateList.valueOf(p.accent));
        Button send = findViewById(R.id.send);
        send.setBackground(rounded(p.ink, p.ink, 22 * density, density));
        send.setTextColor(p.surface);
        ((Button) findViewById(R.id.cancel)).setTextColor(p.muted);
        findViewById(R.id.portrait).setBackground(circle(p.wash));
    }

    private static GradientDrawable rounded(int fill, int stroke, float radius, float density) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(fill);
        shape.setStroke(Math.round(density), stroke);
        shape.setCornerRadius(radius);
        return shape;
    }

    private static GradientDrawable circle(int fill) {
        GradientDrawable shape = new GradientDrawable();
        shape.setShape(GradientDrawable.OVAL);
        shape.setColor(fill);
        return shape;
    }

    private void portrait(JSONObject secretary) {
        String avatar = secretary == null ? "f1" : secretary.optString("avatar", "f1");
        ImageView view = findViewById(R.id.portrait);
        java.io.File custom = new java.io.File(getFilesDir(), "portrait.png");
        Bitmap image = "custom".equals(avatar) && custom.exists() ? BitmapFactory.decodeFile(custom.getPath()) : null;
        if (image != null) view.setImageBitmap(image);
        else view.setImageResource("f2".equals(avatar) ? R.drawable.portrait_f2 : "m1".equals(avatar) ? R.drawable.portrait_m1
                : "m2".equals(avatar) ? R.drawable.portrait_m2 : R.drawable.portrait_f1);
    }
}
