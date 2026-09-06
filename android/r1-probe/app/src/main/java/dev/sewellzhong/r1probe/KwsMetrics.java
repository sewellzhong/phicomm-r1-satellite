package dev.sewellzhong.r1probe;

/** Runtime counters use monotonic nanoseconds and exclude model initialization. */
final class KwsMetrics {
    final long audioSamples;
    final long wallNanos;
    final long cpuNanos;
    final long maximumFrameNanos;

    KwsMetrics(long audioSamples, long wallNanos, long cpuNanos, long maximumFrameNanos) {
        if (audioSamples < 0L || wallNanos < 0L || cpuNanos < 0L || maximumFrameNanos < 0L) {
            throw new IllegalArgumentException("negative_metric");
        }
        this.audioSamples = audioSamples;
        this.wallNanos = wallNanos;
        this.cpuNanos = cpuNanos;
        this.maximumFrameNanos = maximumFrameNanos;
    }

    double realTimeFactor() {
        if (audioSamples == 0L) {
            return 0.0;
        }
        double audioNanos = audioSamples * 1_000_000_000.0 / KwsConfig.SAMPLE_RATE;
        return wallNanos / audioNanos;
    }
}
