package me.love765.goodmorning;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import org.json.JSONArray;
import org.junit.Test;

public class UpdatesTest {
    private static String release(String tag, boolean draft, boolean prerelease, String asset) {
        return "{\"tag_name\":\"" + tag + "\",\"name\":\"\",\"draft\":" + draft + ",\"prerelease\":" + prerelease
                + ",\"assets\":[{\"browser_download_url\":\"https://example.test/" + asset + "\"}]}";
    }

    @Test
    public void picksHighestPublishedApkAboveCurrent() throws Exception {
        JSONArray releases = new JSONArray("[" + String.join(",",
                release("deploy/20261021-ship-abc", false, false, "site.apk"),
                release("android-v9", true, false, "draft.apk"),
                release("android-v8", false, true, "beta.apk"),
                release("android-v7", false, false, "notes.txt"),
                release("android-v3", false, false, "GoodMorning-3.apk"),
                release("android-v5", false, false, "GoodMorning-5.apk"),
                release("android-v1", false, false, "GoodMorning-1.apk")) + "]");
        Updates.Release newest = Updates.newest(releases, 2);
        assertEquals(5, newest.code);
        assertEquals("android-v5", newest.name);
        assertEquals("https://example.test/GoodMorning-5.apk", newest.apk);
        assertNull(Updates.newest(releases, 5));
    }
}
