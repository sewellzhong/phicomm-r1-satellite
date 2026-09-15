package com.unisound.jni;

/** Minimal ABI-compatible declaration for the AEC library already present on R1 firmware 3448. */
public final class AEC {
    // The vendor JNI implementation resolves this exact field name and type.
    @SuppressWarnings("unused")
    int a;

    static {
        System.loadLibrary("aec");
    }

    public AEC(int sampleRate, int channels) {
        a = init(sampleRate, channels);
    }

    private native int init(int sampleRate, int channels);
    public native byte[] getlast();
    public native byte[] process(byte[] microphone, byte[] reference);
    public native int process2(byte[] microphone, int microphoneSamples,
            byte[] reference, int referenceSamples, byte[] output);
    public native void release();
    public native void reset(float microphoneGain, float referenceGain);
    public native int setOptionInt(int option, int value);
}
