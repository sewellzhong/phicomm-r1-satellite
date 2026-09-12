package dev.sewellzhong.r1probe;

import android.content.Context;
import android.os.ParcelFileDescriptor;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import java.util.Locale;

/** APK-side client. Package replacement remains owned by the independent supervisor. */
final class UpdateSupervisorClient {
    static final int PHASE_IDLE = 1;
    static final int PHASE_STAGED = 2;
    static final int PHASE_INSTALLING = 3;
    static final int PHASE_AWAITING_HEALTH = 4;
    static final int PHASE_ROLLING_BACK = 5;
    static final int PHASE_FAILED = 6;
    static final long MIN_APK_BYTES = 4096;
    static final long MAX_APK_BYTES = 64L * 1024L * 1024L;

    interface Transport {
        void submit(Candidate candidate, int archiveFd) throws IOException;
        Response health(Health health) throws IOException;
    }

    static final class Candidate {
        final String operationId;
        final int fromVersion;
        final int toVersion;
        final long apkSize;
        final byte[] apkSha256;
        final byte[] signerSha256;
        final int healthTimeoutSeconds;

        Candidate(String operationId, int fromVersion, int toVersion, long apkSize,
                byte[] apkSha256, byte[] signerSha256, int healthTimeoutSeconds) {
            if (operationId == null || !operationId.matches("[0-9a-f]{32}"))
                throw new IllegalArgumentException("update_operation_id_invalid");
            if (fromVersion <= 0 || toVersion <= fromVersion)
                throw new IllegalArgumentException("update_version_invalid");
            if (apkSize < MIN_APK_BYTES || apkSize > MAX_APK_BYTES)
                throw new IllegalArgumentException("update_apk_size_invalid");
            if (apkSha256 == null || apkSha256.length != 32
                    || signerSha256 == null || signerSha256.length != 32)
                throw new IllegalArgumentException("update_digest_invalid");
            if (healthTimeoutSeconds < 30 || healthTimeoutSeconds > 600)
                throw new IllegalArgumentException("update_health_timeout_invalid");
            this.operationId = operationId;
            this.fromVersion = fromVersion;
            this.toVersion = toVersion;
            this.apkSize = apkSize;
            this.apkSha256 = apkSha256.clone();
            this.signerSha256 = signerSha256.clone();
            this.healthTimeoutSeconds = healthTimeoutSeconds;
        }
    }

    static final class Health {
        final boolean serviceReady;
        final boolean stateLoaded;
        final boolean audioAgentReachable;
        final boolean isolationSafe;
        Health(boolean serviceReady, boolean stateLoaded, boolean audioAgentReachable,
                boolean isolationSafe) {
            this.serviceReady = serviceReady;
            this.stateLoaded = stateLoaded;
            this.audioAgentReachable = audioAgentReachable;
            this.isolationSafe = isolationSafe;
        }
        boolean complete() {
            return serviceReady && stateLoaded && audioAgentReachable && isolationSafe;
        }
    }

    static final class Response {
        final boolean success;
        final int phase;
        final String error;
        Response(boolean success, int phase, String error) {
            if (phase < PHASE_IDLE || phase > PHASE_FAILED)
                throw new IllegalArgumentException("update_response_phase_invalid");
            if (success == (error != null && !error.isEmpty()))
                throw new IllegalArgumentException("update_response_error_invalid");
            this.success = success;
            this.phase = phase;
            this.error = error == null ? "" : error;
        }
    }

    private static final class NativeTransport implements Transport {
        @Override public void submit(Candidate candidate, int archiveFd) throws IOException {
            UpdateSupervisorNative.sendApply(candidate.operationId, candidate.fromVersion,
                    candidate.toVersion, candidate.apkSize, candidate.apkSha256,
                    candidate.signerSha256, candidate.healthTimeoutSeconds, archiveFd);
        }
        @Override public Response health(Health health) throws IOException {
            String[] raw = UpdateSupervisorNative.sendHealth(health.serviceReady,
                    health.stateLoaded, health.audioAgentReachable, health.isolationSafe);
            if (raw == null || raw.length != 3 || !("0".equals(raw[0]) || "1".equals(raw[0])))
                throw new IOException("update_response_invalid");
            try {
                return new Response("1".equals(raw[0]), Integer.parseInt(raw[1]), raw[2]);
            } catch (IllegalArgumentException error) {
                throw new IOException("update_response_invalid", error);
            }
        }
    }

    private final File inbox;
    private final Transport transport;

    static UpdateSupervisorClient create(Context context) {
        return new UpdateSupervisorClient(context.getDir("update-inbox", Context.MODE_PRIVATE),
                new NativeTransport());
    }

    UpdateSupervisorClient(File inbox, Transport transport) {
        if (inbox == null || transport == null) throw new NullPointerException();
        this.inbox = inbox;
        this.transport = transport;
    }

    File candidateFile(String operationId) {
        if (operationId == null || !operationId.matches("[0-9a-f]{32}"))
            throw new IllegalArgumentException("update_operation_id_invalid");
        return new File(inbox, operationId + ".apk");
    }

    void submitExisting(Candidate candidate) throws IOException {
        File archive = candidateFile(candidate.operationId);
        if (!archive.isFile() || archive.length() != candidate.apkSize
                || !archive.getCanonicalFile().getParentFile().equals(inbox.getCanonicalFile()))
            throw new IOException("update_candidate_file_invalid");
        byte[] actual = sha256(archive);
        if (!MessageDigest.isEqual(actual, candidate.apkSha256))
            throw new IOException("update_candidate_hash_mismatch");
        try (ParcelFileDescriptor descriptor = ParcelFileDescriptor.open(
                archive, ParcelFileDescriptor.MODE_READ_ONLY)) {
            transport.submit(candidate, descriptor.getFd());
        }
    }

    Response reportHealth(Health health) throws IOException {
        if (health == null || !health.complete())
            throw new IOException("update_health_incomplete");
        return transport.health(health);
    }

    static byte[] decodeDigest(String value) {
        if (value == null || !value.matches("[0-9a-f]{64}"))
            throw new IllegalArgumentException("update_digest_invalid");
        byte[] result = new byte[32];
        for (int index = 0; index < result.length; index++) {
            int offset = index * 2;
            result[index] = (byte) Integer.parseInt(value.substring(offset, offset + 2), 16);
        }
        return result;
    }

    static String encodeDigest(byte[] value) {
        if (value == null || value.length != 32)
            throw new IllegalArgumentException("update_digest_invalid");
        StringBuilder output = new StringBuilder(64);
        for (byte item : value) output.append(String.format(Locale.ROOT, "%02x", item & 255));
        return output.toString();
    }

    private static byte[] sha256(File source) throws IOException {
        MessageDigest digest;
        try { digest = MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
        byte[] buffer = new byte[8192];
        try (FileInputStream input = new FileInputStream(source)) {
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        } finally { Arrays.fill(buffer, (byte) 0); }
        return digest.digest();
    }
}
