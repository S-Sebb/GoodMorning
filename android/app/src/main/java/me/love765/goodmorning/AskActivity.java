package me.love765.goodmorning;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.text.TextUtils;
import android.view.Gravity;
import android.widget.ImageView;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.ImageButton;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;

/** A small dialog over the home screen for asking the secretary from the chat widget, with files as in the browser. */
public class AskActivity extends Activity {
    private static final int PICK = 1;
    /** Whether the user ticked or cleared "Start a new conversation" themselves. */
    private boolean chosen;
    private final List<Attachment> attachments = new ArrayList<>();
    private boolean sending;
    private Palette palette;
    /** One ID per draft, kept until it is sent, so sending it again after an unclear failure is not a second message. */
    private String draft;

    /**
     * The one send in flight. It outlives a dialog recreated by rotation or a dark-mode switch, which binds to it again
     * instead of offering Send for the same draft. Touched on the UI thread only.
     */
    private static final class Sending {
        final String draft;
        final List<Attachment> files;
        AskActivity screen;

        Sending(String draft, List<Attachment> files, AskActivity screen) {
            this.draft = draft;
            this.files = files;
            this.screen = screen;
        }
    }

    private static Sending inFlight;

    @Override
    protected void attachBaseContext(Context base) {
        super.attachBaseContext(Language.apply(base));
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        chosen = state != null && state.getBoolean("chosen");  // The checkbox itself comes back with the views.
        draft = state == null ? Attachment.newId() : state.getString("draft", Attachment.newId());
        if (state != null) {
            try {
                JSONArray saved = new JSONArray(state.getString("attachments", "[]"));
                for (int i = 0; i < saved.length(); i++) attachments.add(Attachment.from(saved.getJSONObject(i)));
            } catch (JSONException ignored) {
                // Written by onSaveInstanceState below, so always readable.
            }
        }
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
            fresh.setOnCheckedChangeListener((box, checked) -> conversation.setText(checked
                    ? getString(R.string.ask_starts_new) : getString(R.string.ask_continues, latest.optString("title"))));
            conversation.setText(getString(R.string.ask_continues, latest.optString("title")));
            // After 15 minutes away a settled conversation starts fresh, as in the browser, once the server confirms
            // it is still settled. It can still be continued, and the user's own choice stands.
            if (Sync.current(this, Sync.cached(this)) == null) {
                fresh.setOnClickListener(view -> chosen = true);
                Context app = getApplicationContext();
                new Thread(() -> {
                    JSONObject now = Sync.run(app) ? Sync.cached(app).optJSONObject("chat") : null;
                    boolean start = now != null && chat.equals(now.optString("id")) && Sync.current(app, Sync.cached(app)) == null;
                    runOnUiThread(() -> {
                        if (start && !chosen && !isFinishing()) fresh.setChecked(true);
                    });
                }).start();
            }
        }
        EditText text = findViewById(R.id.text);
        TextView status = findViewById(R.id.status);
        Button send = findViewById(R.id.send);
        findViewById(R.id.cancel).setOnClickListener(view -> finish());
        findViewById(R.id.attach).setOnClickListener(view -> startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE).setType("*/*").putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true), PICK));
        if (state != null) status.setText(state.getCharSequence("status"));
        if (inFlight != null && inFlight.draft.equals(draft)) {
            // Recreated while this draft is being sent: show that send rather than offering a second one.
            inFlight.screen = this;
            attachments.clear();
            attachments.addAll(inFlight.files);
            busy(true);
        } else {
            showAttachments();
        }
        send.setOnClickListener(view -> {
            String message = text.getText().toString().trim();
            if (message.isEmpty() && attachments.isEmpty()) return;
            status.setText("");
            Sending operation = inFlight = new Sending(draft, new ArrayList<>(attachments), this);
            busy(true);
            send(getApplicationContext(), token, operation, message, fresh.isChecked() ? null : chat);
        });
    }

    /** Uploads each file, then sends the message, on its own thread; the result goes to whichever dialog shows it then. */
    private static void send(Context app, String token, Sending operation, String message, String target) {
        new Thread(() -> {
            Context words = Language.apply(app);
            String error = null;
            String sent = target;
            try {
                // Each file goes up first, as in the browser; one already uploaded is not sent again on a retry.
                List<String> ids = new ArrayList<>();
                for (Attachment file : operation.files) {
                    if (!file.uploaded) {
                        Api.upload(app, token, file, open(app, file));
                        file.uploaded = true;
                    }
                    ids.add(file.id);
                }
                sent = Api.chat(app, token, operation.draft, message, target, ids).optString("chat", target);
            } catch (Attachment.Unreadable unreadable) {
                error = words.getString(R.string.ask_unreadable, unreadable.file.name);
            } catch (Api.Failure failure) {
                error = failure.status == 403 ? words.getString(R.string.ask_unlinked)
                        : failure.error.isEmpty() ? words.getString(R.string.ask_failed) : failure.error;
            } catch (IOException | JSONException offline) {
                error = words.getString(R.string.ask_failed);
            }
            String problem = error, conversation = sent;
            new Handler(Looper.getMainLooper()).post(() -> {
                inFlight = null;
                AskActivity screen = operation.screen;
                if (problem == null) {
                    Sync.markSent(app, conversation);
                    Toast.makeText(words, R.string.ask_sent, Toast.LENGTH_LONG).show();
                    if (screen != null) screen.finish();
                } else if (screen != null) {
                    // The message and its files stay, so the user can send again or remove a file first.
                    ((TextView) screen.findViewById(R.id.status)).setText(problem);
                    screen.busy(false);
                }
            });
        }).start();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (inFlight != null && inFlight.screen == this) inFlight.screen = null;
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        out.putBoolean("chosen", chosen);
        out.putString("draft", draft);
        TextView status = findViewById(R.id.status);
        if (status != null) out.putCharSequence("status", status.getText());
        JSONArray saved = new JSONArray();
        try {
            for (Attachment file : attachments) saved.put(file.json());
        } catch (JSONException ignored) {
            // Only strings and numbers.
        }
        out.putString("attachments", saved.toString());
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != PICK || result != RESULT_OK || data == null) return;
        List<Uri> picked = new ArrayList<>();
        if (data.getClipData() != null) {
            for (int i = 0; i < data.getClipData().getItemCount(); i++) picked.add(data.getClipData().getItemAt(i).getUri());
        } else if (data.getData() != null) {
            picked.add(data.getData());
        }
        Context app = getApplicationContext();
        new Thread(() -> {
            // Each file's name and size come from its app, which can be slow; the limits apply back on the UI thread.
            List<Object[]> found = new ArrayList<>();
            for (Uri uri : picked) {
                String name = uri.getLastPathSegment();
                long size = -1;
                try (Cursor row = app.getContentResolver().query(uri,
                        new String[] {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE}, null, null, null)) {
                    if (row != null && row.moveToFirst()) {
                        if (!row.isNull(0)) name = row.getString(0);
                        if (!row.isNull(1)) size = row.getLong(1);
                    }
                } catch (RuntimeException unreadable) {
                    // Reported below like a file without a size.
                }
                found.add(new Object[] {uri, name, size});
            }
            runOnUiThread(() -> add(found));
        }).start();
    }

    /** Picked files join the message with the browser's limits; when several can't, the first reason shows. */
    private void add(List<Object[]> found) {
        if (isFinishing() || isDestroyed()) return;
        String problem = null;
        for (Object[] file : found) {
            String name = (String) file[1];
            long size = (Long) file[2];
            String refused = size < 0 ? getString(R.string.ask_unreadable, Attachment.uploadName(name))  // An upload needs its exact size up front.
                    : size > Attachment.MAX_BYTES ? getString(R.string.ask_too_large)
                    : attachments.size() >= Attachment.MAX_FILES ? getString(R.string.ask_too_many) : null;
            if (refused == null) attachments.add(Attachment.picked(file[0].toString(), name, size));
            else if (problem == null) problem = refused;
        }
        ((TextView) findViewById(R.id.status)).setText(problem == null ? "" : problem);
        showAttachments();
    }

    private static InputStream open(Context app, Attachment file) throws Attachment.Unreadable {
        try {
            InputStream in = app.getContentResolver().openInputStream(Uri.parse(file.uri));
            if (in != null) return in;
        } catch (FileNotFoundException | SecurityException unreadable) {
            // Reported as below.
        }
        throw new Attachment.Unreadable(file);
    }

    /** While sending, the files and buttons wait, as in the browser. */
    private void busy(boolean now) {
        sending = now;
        for (int id : new int[] {R.id.send, R.id.attach}) {
            findViewById(id).setEnabled(!now);
            findViewById(id).setAlpha(now ? 0.45f : 1);  // The palette's custom backgrounds have no disabled look.
        }
        showAttachments();
    }

    /** One row per file, its name and size as the browser shows them, with × to remove it. */
    private void showAttachments() {
        LinearLayout list = findViewById(R.id.attachments);
        list.removeAllViews();
        float density = getResources().getDisplayMetrics().density;
        for (Attachment file : attachments) {
            LinearLayout row = new LinearLayout(this);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setBackground(rounded(palette.surface, palette.border, 14 * density, density));
            row.setPadding(Math.round(14 * density), 0, 0, 0);
            LinearLayout.LayoutParams place = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT);
            place.topMargin = Math.round(8 * density);
            TextView label = new TextView(this);
            label.setText(file.name + " · " + Attachment.size(file.size));
            label.setTextColor(palette.ink);
            label.setTextSize(14);
            label.setSingleLine(true);
            label.setEllipsize(TextUtils.TruncateAt.MIDDLE);
            row.addView(label, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
            Button remove = new Button(this, null, 0, android.R.style.Widget_Material_Button_Borderless);
            remove.setText("×");
            remove.setTextSize(18);
            remove.setTextColor(palette.muted);
            remove.setMinWidth(0);
            remove.setMinimumWidth(Math.round(48 * density));
            remove.setContentDescription(getString(R.string.ask_remove, file.name));
            remove.setEnabled(!sending);
            remove.setOnClickListener(view -> {
                attachments.remove(file);
                showAttachments();
            });
            row.addView(remove, new LinearLayout.LayoutParams(Math.round(48 * density), Math.round(48 * density)));
            list.addView(row, place);
        }
        // As in the browser: the limits note appears with the first file, and a long list scrolls (max-height 150px)
        // so Cancel and Send stay on screen.
        findViewById(R.id.upload_note).setVisibility(attachments.isEmpty() ? View.GONE : View.VISIBLE);
        list.measure(View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED),
                View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED));
        int most = Math.round(160 * density);
        View scroll = findViewById(R.id.attachments_scroll);
        scroll.getLayoutParams().height = list.getMeasuredHeight() > most ? most : ViewGroup.LayoutParams.WRAP_CONTENT;
        scroll.requestLayout();
    }

    /** The website's look in the account's day or night scheme, as in the chat widget. */
    private void style() {
        Palette p = palette = Palette.now(this);
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
        ((ImageButton) findViewById(R.id.attach)).setImageTintList(ColorStateList.valueOf(p.ink));
        ((TextView) findViewById(R.id.upload_note)).setTextColor(p.muted);
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
