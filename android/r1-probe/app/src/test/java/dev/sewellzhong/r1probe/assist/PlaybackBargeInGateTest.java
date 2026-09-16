package dev.sewellzhong.r1probe.assist;

import org.junit.Test;
import static org.junit.Assert.assertEquals;

public final class PlaybackBargeInGateTest {
    @Test public void requiresStableStrongNonReferenceFrames() {
        PlaybackBargeInGate gate = new PlaybackBargeInGate(3);
        assertEquals(PlaybackBargeInGate.Decision.WAIT,
                gate.observe(true, false, true, true, false));
        assertEquals(PlaybackBargeInGate.Decision.WAIT,
                gate.observe(true, false, true, true, false));
        assertEquals(PlaybackBargeInGate.Decision.ACCEPT,
                gate.observe(true, false, true, true, false));
    }

    @Test public void referenceMatchResetsCandidate() {
        PlaybackBargeInGate gate = new PlaybackBargeInGate(2);
        gate.observe(true, false, true, true, false);
        assertEquals(PlaybackBargeInGate.Decision.WAIT,
                gate.observe(true, true, true, true, false));
        assertEquals(PlaybackBargeInGate.Decision.WAIT,
                gate.observe(true, false, true, true, false));
    }

    @Test public void unavailableOrSaturatedAecBlocksAndResets() {
        PlaybackBargeInGate gate = new PlaybackBargeInGate(2);
        gate.observe(true, false, true, true, false);
        assertEquals(PlaybackBargeInGate.Decision.BLOCKED,
                gate.observe(false, false, true, true, false));
        assertEquals("aec_output_unavailable", gate.blockReason());
        assertEquals(PlaybackBargeInGate.Decision.BLOCKED,
                gate.observe(true, false, true, true, true));
        assertEquals("aec_output_saturated", gate.blockReason());
    }

    @Test public void weakOrUnqualifiedSpeechDoesNotAccumulate() {
        PlaybackBargeInGate gate = new PlaybackBargeInGate(2);
        gate.observe(true, false, true, true, false);
        gate.observe(true, false, false, true, false);
        assertEquals(PlaybackBargeInGate.Decision.WAIT,
                gate.observe(true, false, true, true, false));
    }
}
