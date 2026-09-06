package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class KwsMetricsTest {
    @Test
    public void computesRealTimeFactorFromPcmTimeline() {
        KwsMetrics metrics = new KwsMetrics(160000L, 2_500_000_000L, 1L, 1L);
        assertEquals(0.25, metrics.realTimeFactor(), 0.000001);
    }

    @Test
    public void emptyInputHasZeroRealTimeFactor() {
        assertEquals(0.0, new KwsMetrics(0L, 0L, 0L, 0L).realTimeFactor(), 0.0);
    }
}
