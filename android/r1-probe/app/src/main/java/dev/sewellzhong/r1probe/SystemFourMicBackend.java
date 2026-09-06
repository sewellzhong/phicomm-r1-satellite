package dev.sewellzhong.r1probe;

import com.unisound.jni.Uni4micHalJNI;

final class SystemFourMicBackend implements FourMicBackend {
    private final Uni4micHalJNI bridge;

    private SystemFourMicBackend(Uni4micHalJNI bridge) {
        this.bridge = bridge;
    }

    static SystemFourMicBackend load() {
        return new SystemFourMicBackend(Uni4micHalJNI.getInstance());
    }

    @Override
    public String boardVersion() {
        return bridge.get4MicBoardVersion();
    }

    @Override
    public int init(int mode) {
        return bridge.init(mode);
    }

    @Override
    public int setDebugMode(int enabled) {
        return bridge.set4MicDebugMode(enabled);
    }

    @Override
    public int closeAlgorithm(int closed) {
        return bridge.close4MicAlgorithm(closed);
    }

    @Override
    public int setWakeUpStatus(int status) {
        return bridge.set4MicWakeUpStatus(status);
    }

    @Override
    public long openAudioIn(int source) {
        return bridge.openAudioIn(source);
    }

    @Override
    public int startRecorder(long handle) {
        return bridge.startRecorder(handle);
    }

    @Override
    public int readData(long handle, byte[] buffer, int length) {
        return bridge.readData(handle, buffer, length);
    }

    @Override
    public int stopRecorder(long handle) {
        return bridge.stopRecorder(handle);
    }

    @Override
    public int closeAudioIn(long handle) {
        return bridge.closeAudioIn(handle);
    }

    @Override
    public int release() {
        return bridge.release();
    }
}
