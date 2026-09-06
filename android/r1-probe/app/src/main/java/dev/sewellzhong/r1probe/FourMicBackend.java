package dev.sewellzhong.r1probe;

interface FourMicBackend {
    String boardVersion();

    int init(int mode);

    int setDebugMode(int enabled);

    int closeAlgorithm(int closed);

    int setWakeUpStatus(int status);

    long openAudioIn(int source);

    int startRecorder(long handle);

    int readData(long handle, byte[] buffer, int length);

    int stopRecorder(long handle);

    int closeAudioIn(long handle);

    int release();
}
