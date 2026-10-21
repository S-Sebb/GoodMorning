package me.love765.goodmorning;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** The server's app API and this phone's app token, kept encrypted by a key that never leaves the phone. */
final class Api {
    private static final String KEY = "goodmorning-app-token";

    /** An answer other than success; 403 means the link was revoked. */
    static final class Failure extends IOException {
        final int status;
        final String error;

        Failure(int status, String error) {
            super("HTTP " + status);
            this.status = status;
            this.error = error;
        }
    }

    private Api() {}

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences("link", Context.MODE_PRIVATE);
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

    static void saveToken(Context context, String token) throws GeneralSecurityException, IOException {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        String sealed = Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP) + ":"
                + Base64.encodeToString(cipher.doFinal(token.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP);
        prefs(context).edit().putString("token", sealed).putString("server", Server.get(context)).apply();
    }

    /** The token for the current server, or null when this phone is not linked to it. */
    static String token(Context context) {
        SharedPreferences prefs = prefs(context);
        String sealed = prefs.getString("token", null);
        if (sealed == null || !sealed.contains(":") || !String.valueOf(Server.get(context)).equals(prefs.getString("server", null))) return null;
        try {
            String[] parts = sealed.split(":");
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)));
            return new String(cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)), StandardCharsets.UTF_8);
        } catch (GeneralSecurityException | IOException | IllegalArgumentException error) {
            return null;
        }
    }

    static void forget(Context context) {
        prefs(context).edit().clear().apply();
    }

    private static JSONObject request(Context context, String method, String path, JSONObject body, String header, String value)
            throws IOException, JSONException {
        HttpURLConnection connection = (HttpURLConnection) new URL(Server.get(context) + path).openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(20000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestMethod(method);
        connection.setRequestProperty("Accept", "application/json");
        if (header != null && value != null) connection.setRequestProperty(header, value);
        try {
            if (body != null) {
                byte[] raw = body.toString().getBytes(StandardCharsets.UTF_8);
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json");
                connection.setFixedLengthStreamingMode(raw.length);
                try (OutputStream out = connection.getOutputStream()) {
                    out.write(raw);
                }
            }
            int status = connection.getResponseCode();
            InputStream stream = status < 400 ? connection.getInputStream() : connection.getErrorStream();
            String text = stream == null ? "" : Server.read(stream, 4 << 20);
            if (status >= 300) {
                String error = "";
                try {
                    error = new JSONObject(text).optString("error");
                } catch (JSONException ignored) {
                    // Not every failure has a JSON body.
                }
                throw new Failure(status, error);
            }
            return new JSONObject(text);
        } finally {
            connection.disconnect();
        }
    }

    static JSONObject pair(Context context, String label) throws IOException, JSONException {
        return request(context, "POST", "/api/app/pair", new JSONObject().put("label", label), null, null);
    }

    static JSONObject claim(Context context, String secret) throws IOException, JSONException {
        return request(context, "GET", "/api/app/pair", null, "X-GoodMorning-Pairing", secret);
    }

    static JSONObject sync(Context context, String token, long after) throws IOException, JSONException {
        return request(context, "GET", "/api/app/sync?after=" + after, null, "X-GoodMorning-App", token);
    }

    static JSONObject chat(Context context, String token, String text, String chat) throws IOException, JSONException {
        JSONObject body = new JSONObject().put("text", text);
        if (chat != null) body.put("chat", chat);
        return request(context, "POST", "/api/app/chat", body, "X-GoodMorning-App", token);
    }
}
