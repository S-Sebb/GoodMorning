package me.love765.goodmorning;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.nio.charset.StandardCharsets;

public class AttachmentTest {
    @Test
    public void namesMeetTheServersRules() {
        assertEquals("trip plan.pdf", Attachment.uploadName(" trip plan.pdf "));
        assertEquals("a_b_cé_.txt", Attachment.uploadName("a/b\\cé\n.txt"));
        assertEquals("file", Attachment.uploadName(".."));
        assertEquals("file", Attachment.uploadName(null));
        // Long names lose characters before the extension, never splitting a character.
        String name = Attachment.uploadName("资料".repeat(100) + ".docx");
        assertTrue(name.endsWith("资料.docx"));
        assertTrue(name.getBytes(StandardCharsets.UTF_8).length <= 240);
        assertEquals(240, Attachment.uploadName("x".repeat(300) + ".md").length());
    }

    @Test
    public void sizesReadAsInTheBrowser() {
        assertEquals("0 KB", Attachment.size(0));
        assertEquals("1 KB", Attachment.size(1));
        assertEquals("1024 KB", Attachment.size((1 << 20) - 1));
        assertEquals("1.0 MB", Attachment.size(1 << 20));
        assertEquals("50.0 MB", Attachment.size(Attachment.MAX_BYTES));
    }

    @Test
    public void aRestoredFileKeepsItsUploadId() throws Exception {
        Attachment file = Attachment.picked("content://x/1", "notes.txt", 12);
        file.uploaded = true;
        Attachment back = Attachment.from(file.json());
        assertEquals(file.id, back.id);
        assertTrue(back.uploaded && back.id.matches("[a-f0-9]{32}"));
        assertNotEquals(file.id, Attachment.picked("content://x/1", "notes.txt", 12).id);
    }
}
