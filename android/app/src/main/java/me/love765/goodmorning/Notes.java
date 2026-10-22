package me.love765.goodmorning;

import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.text.format.DateFormat;
import android.text.format.DateUtils;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.UUID;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Quick notes on this phone, encrypted with a key that never leaves it. A note is kept here from the
 * first keystroke; `sent` says the server has its current text. A note waiting to be sent belongs to
 * the link it was written under (or to the next link, when written unlinked) and never goes to
 * another account.
 */
final class Notes {
    static final int MAX_TEXT = 3000;
    /** Sends waiting notes as soon as the phone is online. */
    static final int JOB = 4;
    private static final String KEY = "goodmorning-notes";
    private static final Object LOCK = new Object();

    private Notes() {}

    static final class Note {
        String id, text, link, state, chat;
        long created;
        boolean sent;

        JSONObject json() throws JSONException {
            return new JSONObject().put("id", id).put("text", text).put("link", link).put("state", state)
                    .put("chat", chat == null ? JSONObject.NULL : chat).put("created", created).put("sent", sent);
        }

        static Note of(JSONObject item) {
            Note note = new Note();
            note.id = item.optString("id");
            note.text = item.optString("text");
            note.link = item.optString("link");
            note.state = item.optString("state", "unsorted");
            note.chat = item.isNull("chat") ? null : item.optString("chat", null);
            note.created = item.optLong("created");
            note.sent = item.optBoolean("sent");
            return note;
        }

        /** Waiting here: bound to this phone's current link, to none yet, or to a link that was removed. */
        boolean stranded(Context context) {
            return !sent && !link.isEmpty() && !link.equals(device(context));
        }

        /** Waits for the user to sort it: never sorted, or edited since. */
        boolean pending() {
            return !sent || "unsorted".equals(state) || "changed".equals(state);
        }
    }

    private static File file(Context context) {
        return new File(context.getFilesDir(), "notes.bin");
    }

    /** This phone's link, as the server named it in the last summary; empty when unlinked. */
    static String device(Context context) {
        return Sync.linked(context) ? Sync.cached(context).optString("device") : "";
    }

    /** Every note, newest first. */
    static List<Note> all(Context context) {
        synchronized (LOCK) {
            List<Note> notes = new ArrayList<>();
            try {
                JSONArray items = new JSONArray(read(context));
                for (int i = 0; i < items.length(); i++) notes.add(Note.of(items.getJSONObject(i)));
            } catch (JSONException | IOException | GeneralSecurityException missing) {
                // No notes yet.
            }
            notes.sort((a, b) -> Long.compare(b.created, a.created));
            return notes;
        }
    }

    /** Notes with text, newest first. */
    static List<Note> visible(Context context) {
        List<Note> notes = new ArrayList<>();
        for (Note note : all(context)) if (!note.text.isEmpty()) notes.add(note);
        return notes;
    }

    /** What a note's chip says: where it is kept and how far sorting got. */
    static String status(Context context, Note note) {
        if (!note.sent) {
            if (note.stranded(context)) return context.getString(R.string.note_state_stranded);
            return context.getString(Sync.linked(context) ? R.string.note_state_local : R.string.note_state_unlinked);
        }
        String name = name(context, true);
        switch (note.state) {
            case "sorting": return context.getString(R.string.note_state_sorting, name);
            case "question": return context.getString(R.string.note_state_question, name);
            case "sorted": return context.getString(R.string.note_state_sorted);
            case "changed": return context.getString(R.string.note_state_changed);
            case "check": return context.getString(R.string.note_state_check);
            default: return context.getString(R.string.note_state_unsorted);
        }
    }

    /** The secretary's saved name, or "Your secretary" at the start of a sentence and "your secretary" inside one. */
    static String name(Context context, boolean start) {
        JSONObject secretary = Sync.cached(context).optJSONObject("secretary");
        String name = secretary == null || secretary.isNull("name") ? "" : secretary.optString("name");
        return !name.isEmpty() ? name : context.getString(start ? R.string.chat_name_default : R.string.note_name_default);
    }

    /** When a note was written: "Today · 14:05", "Yesterday · 09:12" or "21 Oct · 18:30". */
    static String when(Context context, long created) {
        return context.getString(R.string.note_when, day(context, created), DateFormat.getTimeFormat(context).format(new Date(created)));
    }

    /** An earlier note's tab: the time for today's notes, otherwise the day. */
    static String shortWhen(Context context, long created) {
        return DateUtils.isToday(created) ? DateFormat.getTimeFormat(context).format(new Date(created)) : day(context, created);
    }

    private static String day(Context context, long created) {
        if (DateUtils.isToday(created)) return context.getString(R.string.note_today);
        if (DateUtils.isToday(created + DateUtils.DAY_IN_MILLIS)) return context.getString(R.string.note_yesterday);
        java.util.Locale locale = Language.of(context);
        return new java.text.SimpleDateFormat(DateFormat.getBestDateTimePattern(locale, "MMMd"), locale).format(new Date(created));
    }

    static Note find(Context context, String id) {
        for (Note note : all(context)) if (note.id.equals(id)) return note;
        return null;
    }

    /** Keeps the note's text at once; an empty note is removed here and, once sent, on the server too. */
    static void keep(Context context, String id, String text, long created) throws IOException {
        synchronized (LOCK) {
            List<Note> notes = all(context);
            Note note = null;
            for (Note item : notes) if (item.id.equals(id)) note = item;
            String trimmed = text.trim();
            if (note == null) {
                if (trimmed.isEmpty()) return;
                note = new Note();
                note.id = id;
                note.created = created;
                note.link = device(context);
                note.state = "unsorted";
                notes.add(note);
            } else if (note.text.equals(trimmed)) {
                return;
            }
            note.text = trimmed;
            note.sent = false;
            if (note.link.isEmpty()) note.link = device(context);
            write(context, notes);
        }
        soon(context);
    }

    static String newId() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    /**
     * Sends waiting notes, then takes the server's list: its notes replace sent copies here; notes
     * still waiting keep their text. Runs from {@link Sync}, so never on the main thread.
     */
    static void sync(Context context, String token) throws IOException, JSONException {
        String device = device(context);
        for (Note note : all(context)) {
            if (note.sent || (!note.link.isEmpty() && !note.link.equals(device))) continue;
            JSONObject body = new JSONObject().put("id", note.id).put("text", note.text).put("created", note.created);
            Api.note(context, token, body);
            synchronized (LOCK) {
                List<Note> notes = all(context);
                for (Note item : notes) {
                    // Only if it was not edited while it was being sent.
                    if (item.id.equals(note.id) && item.text.equals(note.text)) {
                        item.sent = true;
                        if (item.link.isEmpty()) item.link = device;
                    }
                }
                write(context, notes);
            }
        }
        JSONArray server = Api.notes(context, token).getJSONArray("notes");
        synchronized (LOCK) {
            List<Note> merged = new ArrayList<>();
            List<String> known = new ArrayList<>();
            for (int i = 0; i < server.length(); i++) {
                Note note = Note.of(server.getJSONObject(i));
                note.link = device;
                note.sent = true;
                known.add(note.id);
                merged.add(note);
            }
            for (Note note : all(context)) {
                if (note.sent) continue;  // Sent notes the server no longer lists were removed elsewhere.
                int index = known.indexOf(note.id);
                if (index >= 0) {
                    merged.get(index).text = note.text;
                    merged.get(index).sent = false;
                    merged.get(index).link = note.link;
                } else {
                    merged.add(note);
                }
            }
            write(context, merged);
        }
    }

    /** After unlinking: sent notes live on the server, so only the ones still waiting stay here. */
    static void forgetSent(Context context) {
        synchronized (LOCK) {
            List<Note> waiting = new ArrayList<>();
            for (Note note : all(context)) if (!note.sent) waiting.add(note);
            try {
                write(context, waiting);
            } catch (IOException ignored) {
                // The next write tries again.
            }
        }
    }

    /** Notes this phone can still send to its current link. */
    static boolean waiting(Context context) {
        if (!Sync.linked(context)) return false;
        for (Note note : all(context)) if (!note.sent && !note.stranded(context)) return true;
        return false;
    }

    static int pending(Context context) {
        int count = 0;
        for (Note note : all(context)) if (note.pending() && !note.stranded(context)) count++;
        return count;
    }

    /** Sends waiting notes when the phone is next online, even if the app is closed. */
    static void soon(Context context) {
        if (!Sync.linked(context)) return;
        context.getSystemService(JobScheduler.class).schedule(new JobInfo.Builder(JOB, new ComponentName(context, SyncJob.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPersisted(true)
                .build());
    }

    private static SecretKey key() throws GeneralSecurityException, IOException {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (store.containsAlias(KEY)) return (SecretKey) store.getKey(KEY, null);
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build());
        return generator.generateKey();
    }

    /** The file holds the 12-byte IV, then the AES-GCM ciphertext. */
    private static String read(Context context) throws IOException, GeneralSecurityException {
        ByteArrayOutputStream raw = new ByteArrayOutputStream();
        try (FileInputStream in = new FileInputStream(file(context))) {
            byte[] buffer = new byte[16384];
            for (int n; (n = in.read(buffer)) != -1; ) raw.write(buffer, 0, n);
        }
        byte[] data = raw.toByteArray();
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, data, 0, 12));
        return new String(cipher.doFinal(data, 12, data.length - 12), StandardCharsets.UTF_8);
    }

    private static void write(Context context, List<Note> notes) throws IOException {
        try {
            JSONArray items = new JSONArray();
            for (Note note : notes) items.put(note.json());
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key());
            byte[] sealed = cipher.doFinal(items.toString().getBytes(StandardCharsets.UTF_8));
            byte[] iv = cipher.getIV();
            File temporary = new File(context.getFilesDir(), "notes.bin.tmp");
            try (FileOutputStream out = new FileOutputStream(temporary)) {
                out.write(iv);
                out.write(sealed);
                out.getFD().sync();
            }
            if (!temporary.renameTo(file(context))) throw new IOException("Could not save the note");
        } catch (GeneralSecurityException | JSONException error) {
            throw new IOException(error);
        }
    }
}
