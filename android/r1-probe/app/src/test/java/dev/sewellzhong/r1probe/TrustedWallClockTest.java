package dev.sewellzhong.r1probe;

import org.junit.Test;
import static org.junit.Assert.*;

public final class TrustedWallClockTest {
    static final class Source implements TrustedWallClock.Source {
        long elapsed;
        long wall = 1_516_800_000_000L;
        public long elapsedMillis() { return elapsed; }
        public long systemWallMillis() { return wall; }
        public String timeZoneId() { return "Asia/Shanghai"; }
    }

    @Test public void authenticatedEpochAdvancesWithMonotonicClock() {
        Source source = new Source(); source.elapsed = 5000;
        TrustedWallClock clock = new TrustedWallClock(source);
        assertFalse(clock.wallTrusted());
        clock.synchronize(1_789_315_200L);
        assertTrue(clock.wallTrusted());
        assertEquals(1_789_315_200_000L, clock.wallMillis());
        source.elapsed += 12_345;
        assertEquals(1_789_315_212_345L, clock.wallMillis());
        assertEquals("Asia/Shanghai", clock.timeZoneId());
    }

    @Test public void invalidEpochNeverMakesClockTrusted() {
        Source source = new Source(); TrustedWallClock clock = new TrustedWallClock(source);
        for (long epoch : new long[] {1_577_836_799L, 4_102_444_801L}) {
            try { clock.synchronize(epoch); fail(); }
            catch (IllegalArgumentException expected) { assertEquals("clock_epoch_invalid", expected.getMessage()); }
        }
        assertFalse(clock.wallTrusted());
    }

    @Test public void monotonicRegressionCannotMoveSynchronizedWallTimeBeforeAnchor() {
        Source source = new Source(); source.elapsed = 100;
        TrustedWallClock clock = new TrustedWallClock(source); clock.synchronize(1_789_315_200L);
        source.elapsed = 50;
        assertEquals(1_789_315_200_000L, clock.wallMillis());
    }
}
