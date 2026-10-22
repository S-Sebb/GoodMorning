package me.love765.goodmorning;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.TextUtils;
import android.text.TextWatcher;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * The quick note writing screen. Every pause in typing keeps the note on the phone, and leaving
 * in any way keeps it too; there is no Save button. Sorting with the secretary is a separate,
 * explicit action that opens the conversation it starts.
 */
public class NoteActivity extends Activity {
    private static final long PAUSE = 300;

    private final Handler handler = new Handler(Looper.getMainLooper());
    /** Notes are written in order, off the main thread. */
    private final ExecutorService writer = Executors.newSingleThreadExecutor();
    private final Runnable keep = this::keep;
    private Palette palette;
    private EditText text;
    private String id;
    private long created;

    /** Opens a saved note. */
    static PendingIntent open(Context context, String note) {
        return pending(context, new Intent(context, NoteActivity.class).putExtra("note", note), "note:" + note);
    }

    /** Starts a new note. */
    static PendingIntent fresh(Context context) {
        return pending(context, new Intent(context, NoteActivity.class), "note:new");
    }

    /** Shows the notes and sorts them with the secretary at once. */
    static PendingIntent sort(Context context) {
        return pending(context, new Intent(context, NoteActivity.class).putExtra("sort", true), "note:sort");
    }

    private static PendingIntent pending(Context context, Intent intent, String key) {
        intent.setData(Uri.parse(key)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        return PendingIntent.getActivity(context, key.hashCode(), intent, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    @Override
    protected void attachBaseContext(Context base) {
        super.attachBaseContext(Language.apply(base));
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        setContentView(R.layout.note);
        palette = Palette.now(this);
        text = findViewById(R.id.text);
        style();
        findViewById(R.id.backdrop).setOnClickListener(view -> finish());
        findViewById(R.id.add).setOnClickListener(view -> show(null, true));
        findViewById(R.id.sort).setOnClickListener(view -> sort());
        text.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) {}
            @Override public void afterTextChanged(Editable s) {
                handler.removeCallbacks(keep);
                handler.postDelayed(keep, PAUSE);
            }
        });
        boolean sorting = state == null && getIntent().getBooleanExtra("sort", false);
        String note = state != null ? state.getString("note") : getIntent().getStringExtra("note");
        List<Notes.Note> notes = Notes.visible(this);
        // Sorting shows the newest note without the keyboard; everything else is ready for typing.
        show(note != null ? Notes.find(this, note) : sorting && !notes.isEmpty() ? notes.get(0) : null, !sorting);
        if (state != null) created = state.getLong("created", created);
        if (sorting) sort();
    }

    @Override
    protected void onSaveInstanceState(Bundle state) {
        super.onSaveInstanceState(state);
        state.putString("note", id);
        state.putLong("created", created);
    }

    @Override
    protected void onPause() {
        super.onPause();
        keep();
        // Send right away when online; otherwise the queued job sends it later.
        Context app = getApplicationContext();
        writer.execute(() -> {
            Widgets.updateAll(app);
            if (Notes.waiting(app)) Sync.run(app);
        });
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        writer.shutdown();
    }

    /** Keeps the text of the note on screen; an empty new note is never stored. */
    private void keep() {
        handler.removeCallbacks(keep);
        String current = id, words = text.getText().toString();
        long when = created;
        Context app = getApplicationContext();
        writer.execute(() -> {
            try {
                Notes.keep(app, current, words, when);
                handler.post(() -> {
                    state();
                    sortButton();
                });
            } catch (IOException failed) {
                handler.post(() -> message(getString(R.string.note_not_kept)));
            }
        });
        state();
    }

    /** Puts a note on the paper, or a blank one for a new note. */
    private void show(Notes.Note note, boolean typing) {
        if (id != null) keep();
        id = note == null ? Notes.newId() : note.id;
        created = note == null ? System.currentTimeMillis() : note.created;
        text.setText(note == null ? "" : note.text);
        text.setSelection(text.length());
        if (typing) {
            text.requestFocus();
            getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE | WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        } else {
            getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_HIDDEN | WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        }
        ((TextView) findViewById(R.id.label)).setText(Notes.when(this, created));
        writer.execute(() -> handler.post(this::list));
    }

    /** The chip under the note: where it is kept and how far sorting got; tapping it opens that conversation. */
    private void state() {
        TextView chip = findViewById(R.id.state);
        String words = text.getText().toString().trim();
        Notes.Note saved = Notes.find(this, id);
        if (words.isEmpty() || saved == null) {
            chip.setVisibility(View.GONE);
            return;
        }
        boolean edited = !saved.text.equals(words);
        chip.setVisibility(View.VISIBLE);
        chip.setText(edited ? getString(Sync.linked(this) ? R.string.note_state_local : R.string.note_state_unlinked) : Notes.status(this, saved));
        boolean needed = !edited && saved.sent && "question".equals(saved.state);
        chip.setTextColor(needed ? palette.accent : palette.muted);
        chip.setOnClickListener(saved.chat == null || edited ? null : view -> openChat(saved.chat));
    }

    /** Every other note, newest first, as a stack of tabs to switch to. */
    private void list() {
        LinearLayout list = findViewById(R.id.list);
        list.removeAllViews();
        float density = getResources().getDisplayMetrics().density;
        List<Notes.Note> notes = Notes.visible(this);
        int shown = 0;
        for (Notes.Note note : notes) {
            if (note.id.equals(id)) continue;
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.VERTICAL);
            int padding = Math.round(12 * density);
            row.setPadding(Math.round(14 * density), padding, padding, padding);
            row.setBackground(paper(shown % 2 == 0 ? palette.noteBehind : palette.noteBack, 3 * density, 3 * density));
            LinearLayout.LayoutParams spacing = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            spacing.bottomMargin = Math.round(6 * density);
            LinearLayout top = new LinearLayout(this);
            top.setGravity(Gravity.CENTER_VERTICAL);
            TextView title = new TextView(this);
            title.setText(note.text.split("\n", 2)[0]);
            title.setMaxLines(1);
            title.setEllipsize(TextUtils.TruncateAt.END);
            title.setTypeface(Typeface.create(Typeface.SERIF, Typeface.ITALIC));
            title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
            title.setTextColor(palette.ink);
            top.addView(title, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1));
            TextView time = new TextView(this);
            time.setText(Notes.shortWhen(this, note.created));
            time.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
            time.setTypeface(Typeface.DEFAULT_BOLD);
            time.setTextColor(palette.muted);
            time.setPadding(Math.round(8 * density), 0, 0, 0);
            top.addView(time);
            row.addView(top);
            TextView status = new TextView(this);
            status.setText(Notes.status(this, note));
            status.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
            status.setTextColor(note.sent && "question".equals(note.state) ? palette.accent : palette.muted);
            row.addView(status);
            row.setOnClickListener(view -> show(note, true));
            list.addView(row, spacing);
            shown++;
        }
        findViewById(R.id.earlier).setVisibility(shown == 0 ? View.GONE : View.VISIBLE);
        sortButton();
        state();
    }

    /** "Sort 3 notes with Aria", shown while notes wait to be sorted and the phone is linked. */
    private void sortButton() {
        int pending = Notes.pending(this);
        Button sort = findViewById(R.id.sort);
        sort.setVisibility(Sync.linked(this) && pending > 0 ? View.VISIBLE : View.GONE);
        sort.setText(getResources().getQuantityString(R.plurals.note_sort, Math.max(pending, 1), pending, Notes.name(this, false)));
    }

    /** Sends any waiting notes, starts the sorting conversation and opens it. */
    private void sort() {
        keep();
        Button button = findViewById(R.id.sort);
        button.setEnabled(false);
        message(getString(R.string.note_sorting, Notes.name(this, false)));
        Context app = getApplicationContext();
        writer.execute(() -> {
            String token = Api.token(app);
            String problem;
            String chat = null;
            int remaining = 0;
            try {
                if (token == null) throw new Api.Failure(403, "");
                Notes.sync(app, token);
                JSONObject answer = Api.sort(app, token);
                chat = answer.getString("chat");
                remaining = answer.optInt("remaining");
                Notes.sync(app, token);
                problem = null;
            } catch (Api.Failure failure) {
                problem = failure.status == 403 ? getString(R.string.ask_unlinked)
                        : failure.error.isEmpty() ? getString(R.string.note_sort_failed) : failure.error;
            } catch (IOException | JSONException offline) {
                problem = getString(R.string.note_sort_failed);
            }
            Widgets.updateAll(app);
            String failed = problem, opened = chat;
            int left = remaining;
            handler.post(() -> {
                button.setEnabled(true);
                list();
                if (failed != null) {
                    message(failed);
                    return;
                }
                if (left > 0) android.widget.Toast.makeText(app, getResources().getQuantityString(R.plurals.note_sort_remaining, left, left),
                        android.widget.Toast.LENGTH_LONG).show();
                openChat(opened);
            });
        });
    }

    private void openChat(String chat) {
        startActivity(new Intent(this, Launcher.class).setData(Uri.parse(Server.get(this) + "/chat?id=" + chat))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        finish();
    }

    private void message(String words) {
        TextView message = findViewById(R.id.message);
        message.setText(words);
        message.setVisibility(View.VISIBLE);
    }

    /** The account's colors; the note's paper comes from the scheme's warm color, as in the widget. */
    private void style() {
        float density = getResources().getDisplayMetrics().density;
        boolean pixel = Palette.pixel(this);
        float corner = pixel ? 0 : 3 * density;
        GradientDrawable sheet = paper(palette.note, corner, pixel ? 0 : 18 * density);
        findViewById(R.id.sheet).setBackground(sheet);
        findViewById(R.id.sheet).setElevation(8 * density);
        if (!pixel) findViewById(R.id.paper).setRotation(-1f);
        ImageView tape = findViewById(R.id.tape);
        tape.setImageResource(pixel ? R.drawable.note_tape_pixel : R.drawable.note_tape);
        tape.setColorFilter(palette.tape);
        tape.setImageAlpha(210);
        tape.setElevation(9 * density);
        text.setTextColor(palette.ink);
        text.setHintTextColor(palette.muted);
        TextView label = findViewById(R.id.label);
        label.setTextColor(palette.muted);
        if (pixel) label.setTypeface(getResources().getFont(R.font.silkscreen));
        ImageButton add = findViewById(R.id.add);
        GradientDrawable circle = new GradientDrawable();
        circle.setShape(pixel ? GradientDrawable.RECTANGLE : GradientDrawable.OVAL);
        circle.setColor(palette.ink);
        add.setBackground(circle);
        add.setColorFilter(palette.note);
        TextView chip = findViewById(R.id.state);
        chip.setBackground(paper(palette.surface, pixel ? 0 : 13 * density, pixel ? 0 : 13 * density));
        Button sort = findViewById(R.id.sort);
        sort.setBackground(paper(palette.note, pixel ? 0 : 23 * density, pixel ? 0 : 23 * density));
        sort.setTextColor(palette.ink);
        sort.setTypeface(Typeface.DEFAULT_BOLD);
    }

    /** A sticky note's paper: the given top corners, a softly curled bottom-right corner. */
    private static GradientDrawable paper(int color, float corner, float curl) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(color);
        shape.setCornerRadii(new float[] {corner, corner, corner, corner, curl, curl, corner, corner});
        return shape;
    }
}
