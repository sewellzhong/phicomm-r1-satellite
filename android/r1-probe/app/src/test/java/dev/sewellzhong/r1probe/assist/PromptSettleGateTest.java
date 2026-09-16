package dev.sewellzhong.r1probe.assist;

import org.junit.Test;
import static org.junit.Assert.*;

public final class PromptSettleGateTest {
    @Test public void dropsPromptTailUntilDeadlineThenOpens() {
        PromptSettleGate gate = new PromptSettleGate(500_000_000L);
        gate.arm(10_000_000_000L);
        assertTrue(gate.discard(10_000_000_001L));
        assertTrue(gate.discard(10_499_999_999L));
        assertFalse(gate.discard(10_500_000_000L));
        assertFalse(gate.armed());
        assertEquals(1, gate.events());
        assertEquals(2, gate.discardedFrames());
    }

    @Test public void rearmingStartsAnIndependentProtectionWindow() {
        PromptSettleGate gate = new PromptSettleGate(100L);
        gate.arm(1_000L); assertTrue(gate.discard(1_050L));
        gate.arm(2_000L); assertTrue(gate.discard(2_050L));
        assertEquals(2, gate.events()); assertEquals(2, gate.discardedFrames());
    }
}
