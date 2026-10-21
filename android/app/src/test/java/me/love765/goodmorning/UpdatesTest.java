package me.love765.goodmorning;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import org.json.JSONObject;
import org.junit.Test;

public class UpdatesTest {
    private static JSONObject release(int code, String apk) throws Exception {
        return new JSONObject().put("code", code).put("name", "0." + code).put("apk", apk);
    }

    @Test
    public void offersOnlyAHigherBuildWithAGitHubApk() throws Exception {
        Updates.Release newer = Updates.newer(release(6, "https://github.com/S-Sebb/GoodMorning/releases/download/android-v6/GoodMorning-0.6.apk"), 5);
        assertEquals(6, newer.code);
        assertEquals("0.6", newer.name);
        assertNull(Updates.newer(release(5, "https://github.com/x/GoodMorning.apk"), 5));
        assertNull(Updates.newer(release(6, "https://evil.test/GoodMorning.apk"), 5));
        assertNull(Updates.newer(release(6, "https://github.com/x/notes.txt"), 5));
        assertNull(Updates.newer(new JSONObject(), 5));  // The server knows no release yet.
    }
}
