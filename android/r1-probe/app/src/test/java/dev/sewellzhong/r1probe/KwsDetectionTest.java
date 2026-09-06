package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class KwsDetectionTest {
    @Test
    public void acceptsAlexaDetection() {
        KwsDetection detection = new KwsDetection(true, "Alexa", 16000L, 0.9f);
        assertTrue(detection.detected);
        assertEquals(16000L, detection.endSampleIndex);
    }

    @Test(expected = IllegalArgumentException.class)
    public void rejectsDifferentWakeWord() {
        new KwsDetection(true, "OtherWord", 16000L, 0.9f);
    }
}
