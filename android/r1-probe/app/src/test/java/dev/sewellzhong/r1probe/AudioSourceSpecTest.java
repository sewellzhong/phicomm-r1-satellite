package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class AudioSourceSpecTest {
    @Test
    public void mapsAllRequiredSources() {
        assertEquals("voice_communication", AudioSourceSpec.nameOf(7));
        assertEquals("voice_recognition", AudioSourceSpec.nameOf(6));
        assertEquals("mic", AudioSourceSpec.nameOf(1));
    }

    @Test(expected = IllegalArgumentException.class)
    public void rejectsUnknownSource() {
        AudioSourceSpec.nameOf(99);
    }
}

