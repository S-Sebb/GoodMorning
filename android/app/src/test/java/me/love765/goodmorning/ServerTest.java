package me.love765.goodmorning;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import org.junit.Test;

public class ServerTest {
    @Test
    public void acceptsOnlyHttpsOrigins() {
        assertEquals("https://gm.love765.me", Server.origin("gm.love765.me"));
        assertEquals("https://gm.love765.me", Server.origin(" HTTPS://GM.love765.me/ "));
        assertEquals("https://example.test:8443", Server.origin("https://example.test:8443"));
        for (String typed : new String[] {"", "http://gm.love765.me", "https://", "https://user@gm.love765.me",
                "https://gm.love765.me/chat", "https://gm.love765.me/?next=x", "https://gm.love765.me/#x",
                "javascript:alert(1)", "https://bad host"}) {
            assertNull(typed, Server.origin(typed));
        }
    }
}
