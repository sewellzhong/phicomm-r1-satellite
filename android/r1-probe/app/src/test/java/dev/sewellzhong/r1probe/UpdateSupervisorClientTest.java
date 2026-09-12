package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.io.File;
import java.io.IOException;
import org.junit.Test;

public final class UpdateSupervisorClientTest {
    private static final byte[] DIGEST = new byte[32];

    private static final class Transport implements UpdateSupervisorClient.Transport {
        int healthCalls;
        UpdateSupervisorClient.Response response = new UpdateSupervisorClient.Response(
                true, UpdateSupervisorClient.PHASE_IDLE, "");
        boolean fail;
        @Override public void submit(UpdateSupervisorClient.Candidate candidate, int fd) { }
        @Override public UpdateSupervisorClient.Response health(
                UpdateSupervisorClient.Health health) throws IOException {
            healthCalls++;
            if (fail) throw new IOException("unavailable");
            return response;
        }
    }

    @Test public void candidateIsStrictAndDefensivelyCopiesDigests() {
        byte[] apk = DIGEST.clone(); byte[] signer = DIGEST.clone();
        UpdateSupervisorClient.Candidate candidate = new UpdateSupervisorClient.Candidate(
                "0123456789abcdef0123456789abcdef", 117, 118, 4096,
                apk, signer, 180);
        apk[0] = 1; signer[0] = 2;
        assertEquals(0, candidate.apkSha256[0]);
        assertEquals(0, candidate.signerSha256[0]);
    }

    @Test(expected = IllegalArgumentException.class)
    public void candidateRejectsNonIncreasingVersion() {
        new UpdateSupervisorClient.Candidate("0123456789abcdef0123456789abcdef",
                117, 117, 4096, DIGEST, DIGEST, 180);
    }

    @Test public void digestCodecRequiresCanonicalLowercaseHex() {
        String value = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
        assertEquals(value, UpdateSupervisorClient.encodeDigest(
                UpdateSupervisorClient.decodeDigest(value)));
        try {
            UpdateSupervisorClient.decodeDigest(value.toUpperCase(java.util.Locale.ROOT));
        } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("uppercase digest accepted");
    }

    @Test public void incompleteHealthIsNeverSent() {
        Transport transport = new Transport();
        UpdateSupervisorClient client = new UpdateSupervisorClient(new File("."), transport);
        try {
            client.reportHealth(new UpdateSupervisorClient.Health(true, true, false, true));
        } catch (IOException expected) {
            assertEquals("update_health_incomplete", expected.getMessage());
            assertEquals(0, transport.healthCalls);
            return;
        }
        throw new AssertionError("partial health accepted");
    }
}
