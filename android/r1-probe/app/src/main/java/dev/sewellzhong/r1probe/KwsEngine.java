package dev.sewellzhong.r1probe;

/**
 * Smallest common API for mutually exclusive, offline KWS candidate tests.
 * Implementations own model state but never own AudioRecord or retain PCM.
 */
interface KwsEngine extends AutoCloseable {
    String engineId();

    String modelId();

    void reset();

    KwsDetection acceptFrame(short[] pcm, int offset, int length, long firstSampleIndex)
            throws Exception;

    KwsMetrics metrics();

    @Override
    void close();
}
