package dev.sewellzhong.r1probe.assist;

import org.junit.Test;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public final class PlaybackWakeCancelGateTest {
    @Test public void vendorAecWakeCanCancelWithoutOrdinaryVadQualification() {
        assertTrue(PlaybackWakeCancelGate.allow(true, true, true, false));
    }

    @Test public void disabledUnavailableOrSaturatedOutputCannotCancel() {
        assertFalse(PlaybackWakeCancelGate.allow(true, false, true, false));
        assertFalse(PlaybackWakeCancelGate.allow(true, true, false, false));
        assertFalse(PlaybackWakeCancelGate.allow(true, true, true, true));
        assertFalse(PlaybackWakeCancelGate.allow(false, true, true, false));
    }
}
