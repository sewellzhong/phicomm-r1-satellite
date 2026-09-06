package dev.sewellzhong.r1probe.esphome;

/** Mandatory PSK responder; crypto is the pinned ESPHome noise-c implementation. */
public final class NoiseSession implements AutoCloseable {
    static { System.loadLibrary("r1_noise"); }
    private long handle;
    public NoiseSession(byte[] psk, byte[] prologue) { handle = create(psk, prologue); }
    public synchronized byte[] respond(byte[] message) { return handshake(handle, message); }
    public synchronized byte[] encrypt(byte[] data) { return crypt(handle, data, true); }
    public synchronized byte[] decrypt(byte[] data) { return crypt(handle, data, false); }
    @Override public synchronized void close() {
        if (handle != 0) { destroy(handle); handle = 0; }
    }
    private static native long create(byte[] key, byte[] prologue);
    private static native byte[] handshake(long handle, byte[] input);
    private static native byte[] crypt(long handle, byte[] input, boolean encrypt);
    private static native void destroy(long handle);
}
