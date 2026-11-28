package me.love765.goodmorning;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.UUID;

/**
 * A file picked in Ask. As in the browser, it gets its upload ID when picked and is uploaded when the message is
 * sent, so a retry after a failure sends the same file under the same ID.
 */
final class Attachment {
    /** The server's limits (chat_uploads.MAX_UPLOAD_BYTES and attachment_ids). */
    static final long MAX_BYTES = 50L << 20;
    static final int MAX_FILES = 100;

    final String uri, name, id;
    final long size;
    boolean uploaded;

    private Attachment(String uri, String name, long size, String id, boolean uploaded) {
        this.uri = uri;
        this.name = name;
        this.size = size;
        this.id = id;
        this.uploaded = uploaded;
    }

    /** A file the phone can no longer read as it was picked: moved, deleted, changed, or its app's permission ended. */
    static final class Unreadable extends IOException {
        final Attachment file;

        Unreadable(Attachment file) {
            this.file = file;
        }
    }

    static Attachment picked(String uri, String name, long size) {
        return new Attachment(uri, uploadName(name), size, newId(), false);
    }

    /** An ID in the server's form, for uploads and drafts. */
    static String newId() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    /**
     * Copies exactly the picked size. A file that changed since it was picked is refused before its last byte is
     * written, so the server never completes a cut-off copy.
     */
    void copy(InputStream in, OutputStream out) throws IOException {
        byte[] buffer = new byte[65536];
        long total = 0;
        int held = -1;
        for (int n; (n = in.read(buffer)) != -1; ) {
            if (n == 0) continue;
            total += n;
            if (total > size) throw new Unreadable(this);
            if (held >= 0) out.write(held);
            out.write(buffer, 0, n - 1);
            held = buffer[n - 1] & 0xff;
        }
        if (total != size) throw new Unreadable(this);
        if (held >= 0) out.write(held);
    }

    JSONObject json() throws JSONException {
        return new JSONObject().put("uri", uri).put("name", name).put("size", size).put("id", id).put("uploaded", uploaded);
    }

    static Attachment from(JSONObject saved) {
        return new Attachment(saved.optString("uri"), saved.optString("name"), saved.optLong("size"),
                saved.optString("id"), saved.optBoolean("uploaded"));
    }

    /**
     * A name the server accepts (chat_uploads.upload_name): no slashes or control characters and at most 240 UTF-8
     * bytes, shortened before its extension. Browsers' file names already meet it; a document provider's may not.
     */
    static String uploadName(String raw) {
        StringBuilder clean = new StringBuilder();
        String text = raw == null ? "" : raw.trim();
        for (int i = 0; i < text.length(); ) {
            int point = text.codePointAt(i);
            i += Character.charCount(point);
            clean.appendCodePoint(point < 32 || point == 127 || point == '/' || point == '\\' ? '_' : point);
        }
        String name = clean.toString();
        if (name.isEmpty() || name.equals(".") || name.equals("..")) name = "file";
        int dot = name.lastIndexOf('.');
        String extension = dot > 0 && name.length() - dot <= 16 ? name.substring(dot) : "";
        String stem = name.substring(0, name.length() - extension.length());
        while (bytes(stem + extension) > 240) stem = stem.substring(0, stem.offsetByCodePoints(stem.length(), -1));
        return stem + extension;
    }

    private static int bytes(String text) {
        return text.getBytes(StandardCharsets.UTF_8).length;
    }

    /** As the browser shows it: whole KB below a megabyte, else MB with one decimal. */
    static String size(long bytes) {
        return bytes < 1 << 20 ? (bytes + 1023) / 1024 + " KB" : String.format(Locale.ROOT, "%.1f MB", bytes / (double) (1 << 20));
    }
}
