package dev.sewellzhong.r1probe;

/** WebRTC VAD via pinned libfvad; API 22 ARMv7, 16 kHz / 20 ms. Single-thread owner. */
final class CommandVad implements AutoCloseable {
    static { System.loadLibrary("r1_vad"); }
    private long pointer;
    private final short[] normalized = new short[320];
    CommandVad() { reset(); }
    void reset() {
        close(); pointer = nativeCreate();
        if (pointer == 0) { throw new IllegalStateException("command_vad_init_failed"); }
    }
    boolean speechForQuietR1(short[] pcm) {
        dev.sewellzhong.r1probe.assist.SpeechEvidence.scaleForVad(pcm, normalized);
        return speech(normalized);
    }
    boolean speech(short[] pcm) {
        int result = nativeProcess(pointer, pcm);
        if (result < 0) { throw new IllegalStateException("command_vad_failed"); }
        return result == 1;
    }
    @Override public void close() {
        if (pointer != 0) { nativeDestroy(pointer); pointer = 0; }
    }
    private static native long nativeCreate();
    private static native int nativeProcess(long pointer, short[] pcm);
    private static native void nativeDestroy(long pointer);
}
