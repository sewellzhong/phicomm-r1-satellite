package dev.sewellzhong.r1probe;

import org.junit.Test;
import static org.junit.Assert.*;

public final class AlexaDecisionTest {
    private void warm(AlexaDecision detector) {
        for (int i = 0; i < 100; i++) {
            assertFalse(detector.acceptFeature(0, i % 3 == 0));
        }
    }

    @Test public void rejectsSpikesAndExactThresholdButAcceptsWindowAboveIt() {
        AlexaDecision detector = new AlexaDecision();
        warm(detector);
        assertFalse(detector.acceptFeature(255, true));
        for (int i = 0; i < 5; i++) { assertFalse(detector.acceptFeature(0, true)); }
        for (int i = 0; i < 5; i++) { assertFalse(detector.acceptFeature(229, true)); }
        assertTrue(detector.acceptFeature(230, true));
        assertEquals(1146f / 1280f, detector.detectedScore(), 0.000001f);
    }

    @Test public void startupAndHighPlateauCannotRetrigger() {
        AlexaDecision detector = new AlexaDecision();
        for (int i = 0; i < 200; i++) { assertFalse(detector.acceptFeature(255, true)); }
        warm(detector);
        for (int i = 0; i < 4; i++) { assertFalse(detector.acceptFeature(255, true)); }
        assertTrue(detector.acceptFeature(255, true));
        for (int i = 0; i < 200; i++) { assertFalse(detector.acceptFeature(255, true)); }
        warm(detector);
        for (int i = 0; i < 4; i++) { assertFalse(detector.acceptFeature(255, true)); }
        assertTrue(detector.acceptFeature(255, true));
    }

    @Test public void cooldownCountsFeaturesNotOnlyInferencesAndResetClearsHistory() {
        AlexaDecision detector = new AlexaDecision();
        warm(detector);
        detector.reset();
        for (int i = 0; i < 99; i++) { assertFalse(detector.acceptFeature(0, i % 3 == 0)); }
        for (int i = 0; i < 5; i++) { assertFalse(detector.acceptFeature(255, true)); }
        warm(detector);
        for (int i = 0; i < 4; i++) { assertFalse(detector.acceptFeature(255, true)); }
        assertTrue(detector.acceptFeature(255, true));
    }

    @Test(expected = IllegalArgumentException.class)
    public void rejectsInvalidQuantizedOutput() {
        new AlexaDecision().acceptFeature(256, true);
    }
}
