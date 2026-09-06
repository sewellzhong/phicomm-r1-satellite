package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class KwsConfigTest {
    @Test
    public void fixesAlexaAndAudioContract() {
        assertEquals("Alexa", KwsConfig.KEYWORD);
        assertEquals("/əˈlɛksə/", KwsConfig.PRONUNCIATION_IPA);
        assertEquals(16000, KwsConfig.SAMPLE_RATE);
        assertEquals(320, KwsConfig.FRAME_SAMPLES);
    }

    @Test
    public void acceptsThresholdEndpoints() {
        assertEquals(0.0f, new KwsConfig(0.0f).threshold, 0.0f);
        assertEquals(1.0f, new KwsConfig(1.0f).threshold, 0.0f);
    }

    @Test(expected = IllegalArgumentException.class)
    public void rejectsThresholdAboveOne() {
        new KwsConfig(1.01f);
    }
}
