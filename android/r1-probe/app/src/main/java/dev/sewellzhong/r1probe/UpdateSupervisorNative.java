package dev.sewellzhong.r1probe;

/** Minimal JNI boundary for SOCK_SEQPACKET and SCM_RIGHTS on Android 5.1. */
final class UpdateSupervisorNative {
    static {
        System.loadLibrary("r1_update_client");
    }

    static native void sendApply(String operationId, int fromVersion, int toVersion,
            long apkSize, byte[] apkSha256, byte[] signerSha256,
            int healthTimeoutSeconds, int archiveFd) throws java.io.IOException;

    static native String[] sendHealth(boolean serviceReady, boolean stateLoaded,
            boolean audioAgentReachable, boolean isolationSafe) throws java.io.IOException;

    private UpdateSupervisorNative() { }
}
