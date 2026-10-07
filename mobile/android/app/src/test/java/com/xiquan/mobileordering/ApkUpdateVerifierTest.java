package com.xiquan.mobileordering;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import org.junit.Test;

public class ApkUpdateVerifierTest {
    @Test
    public void calculatesAndMatchesLowercaseSha256() throws Exception {
        File file = File.createTempFile("xiquan-update", ".apk");
        try {
            Files.write(file.toPath(), "xiquan".getBytes(StandardCharsets.UTF_8));
            String expected = "edfd59800a284eb6d33e23ebb9e2e4f67c2e206a586eaa127f913c033cd3eead";

            assertEquals(expected, ApkUpdateVerifier.calculateSha256(file));
            assertTrue(ApkUpdateVerifier.matches(file, expected));
            assertFalse(ApkUpdateVerifier.matches(file, "0".repeat(64)));
        } finally {
            assertTrue(file.delete() || !file.exists());
        }
    }
}
