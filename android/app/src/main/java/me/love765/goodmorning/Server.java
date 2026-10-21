package me.love765.goodmorning;

import android.content.Context;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/** The GoodMorning server this app opens, saved as an https origin. */
final class Server {
    static final String DEFAULT = "https://gm.love765.me";
    private static final String KEY = "server";

    private Server() {}

    static String get(Context context) {
        return context.getSharedPreferences("app", Context.MODE_PRIVATE).getString(KEY, null);
    }

    static void set(Context context, String origin) {
        context.getSharedPreferences("app", Context.MODE_PRIVATE).edit().putString(KEY, origin).apply();
    }

    /** Returns the https origin of a typed address, or null when it is not one. */
    static String origin(String typed) {
        String text = typed.trim();
        if (!text.contains("://")) text = "https://" + text;
        try {
            URI uri = new URI(text);
            String path = uri.getRawPath() == null ? "" : uri.getRawPath();
            if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null || uri.getRawUserInfo() != null
                    || !path.replace("/", "").isEmpty() || uri.getRawQuery() != null || uri.getRawFragment() != null) return null;
            return "https://" + uri.getHost().toLowerCase(Locale.ROOT) + (uri.getPort() == -1 ? "" : ":" + uri.getPort());
        } catch (URISyntaxException error) {
            return null;
        }
    }

    /** True when the server's Digital Asset Links vouch for this app, false when they do not. */
    static boolean supportsApp(Context context, String origin) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(origin + "/.well-known/assetlinks.json").openConnection();
        connection.setConnectTimeout(10000);
        connection.setReadTimeout(10000);
        connection.setInstanceFollowRedirects(false);
        try {
            if (connection.getResponseCode() != 200) return false;
            return read(connection.getInputStream(), 65536).contains("\"" + context.getPackageName() + "\"");
        } finally {
            connection.disconnect();
        }
    }

    static String read(InputStream input, int limit) throws IOException {
        try (InputStream in = input) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            for (int n; (n = in.read(buffer)) != -1; ) {
                out.write(buffer, 0, n);
                if (out.size() > limit) throw new IOException("Response too large");
            }
            return out.toString(StandardCharsets.UTF_8.name());
        }
    }
}
