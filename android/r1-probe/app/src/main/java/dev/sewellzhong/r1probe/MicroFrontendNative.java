package dev.sewellzhong.r1probe;

final class MicroFrontendNative implements AutoCloseable {
    static {
        System.loadLibrary("r1_microfrontend");
    }

    private long pointer;

    MicroFrontendNative() {
        pointer = nativeCreate();
        if (pointer == 0L) {
            throw new IllegalStateException("microfrontend_initialization_failed");
        }
    }

    int process(short[] audio, byte[] features) {
        if (pointer == 0L) {
            throw new IllegalStateException("microfrontend_closed");
        }
        return nativeProcess(pointer, audio, features);
    }

    @Override
    public void close() {
        if (pointer != 0L) {
            nativeDestroy(pointer);
            pointer = 0L;
        }
    }

    private static native long nativeCreate();
    private static native int nativeProcess(long pointer, short[] audio, byte[] features);
    private static native void nativeDestroy(long pointer);
}
