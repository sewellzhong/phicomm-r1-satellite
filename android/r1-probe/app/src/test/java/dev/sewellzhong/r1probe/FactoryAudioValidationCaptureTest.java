package dev.sewellzhong.r1probe;

import static org.junit.Assert.fail;

import org.junit.Test;

public final class FactoryAudioValidationCaptureTest {
    @Test
    public void acceptsBoundedPlaybackInsideCapture() {
        FactoryAudioValidationCapture.validatePlaybackPlan(10, 5 * 16000 * 2, 9, 15);
    }

    @Test
    public void rejectsPlaybackWithoutLeadAndTailMargin() {
        assertRejected("factory_audio_playback_reference_too_long",
                5, 4 * 16000 * 2, 9, 15);
    }

    @Test
    public void rejectsInvalidObservedMusicVolume() {
        assertRejected("factory_audio_music_volume_invalid",
                10, 5 * 16000 * 2, 16, 15);
    }

    @Test
    public void rejectsUnalignedPlaybackPcm() {
        assertRejected("factory_audio_playback_reference_too_long",
                10, 5 * 16000 * 2 + 1, 9, 15);
    }

    private static void assertRejected(String message, int durationSeconds, int pcmBytes,
            int volumeIndex, int volumeMaxIndex) {
        try {
            FactoryAudioValidationCapture.validatePlaybackPlan(
                    durationSeconds, pcmBytes, volumeIndex, volumeMaxIndex);
            fail("expected rejection");
        } catch (IllegalArgumentException expected) {
            if (!message.equals(expected.getMessage())) throw expected;
        }
    }
}
