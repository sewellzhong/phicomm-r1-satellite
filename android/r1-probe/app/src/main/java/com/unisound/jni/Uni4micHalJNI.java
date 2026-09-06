package com.unisound.jni;

/**
 * Java ABI exposed by the system-provided R1 four-microphone JNI bridge.
 *
 * <p>The native library is deliberately not bundled in this APK. Android 5.1 resolves the
 * firmware copy from /system/lib on supported R1 firmware.</p>
 */
public final class Uni4micHalJNI {
    private static final Uni4micHalJNI INSTANCE = new Uni4micHalJNI();

    static {
        System.loadLibrary("Uni4micHalJNI");
    }

    private Uni4micHalJNI() {
    }

    public static Uni4micHalJNI getInstance() {
        return INSTANCE;
    }

    private native int initHal(int mode);

    private native int releaseHal();

    public int init(int mode) {
        return initHal(mode);
    }

    public int release() {
        return releaseHal();
    }

    public native long openAudioIn(int source);

    public native int readData(long handle, byte[] buffer, int length);

    public native int startRecorder(long handle);

    public native int stopRecorder(long handle);

    public native int closeAudioIn(long handle);

    public native int close4MicAlgorithm(int closed);

    public native String get4MicBoardVersion();

    public native int get4MicDoaResult();

    public native int get4MicOneShotReady();

    public native int set4MicDebugMode(int enabled);

    public native int set4MicDelayTime(int milliseconds);

    public native int set4MicOneShotReady(int ready);

    public native int set4MicOneShotStartLen(int length);

    public native int set4MicUtteranceTimeLen(int length);

    public native int set4MicWakeUpStatus(int status);

    public native int set4MicWakeupStartLen(int length);
}
