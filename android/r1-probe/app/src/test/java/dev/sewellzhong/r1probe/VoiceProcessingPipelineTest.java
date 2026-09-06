package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.util.Random;
import org.junit.Test;

public final class VoiceProcessingPipelineTest {
    @Test
    public void preservesLengthAndRaisesQuietActiveSignalWithoutClipping() {
        Random random = new Random(7L);
        short[] noise = new short[16000];
        short[] speech = new short[32000];
        for (int index = 0; index < noise.length; index++) {
            noise[index] = (short) (random.nextInt(41) - 20);
        }
        for (int index = 0; index < speech.length; index++) {
            int sample = random.nextInt(41) - 20;
            if (index >= 8000 && index < 24000) {
                sample += (int) Math.round(45.0 * Math.sin(2.0 * Math.PI * 440.0 * index / 16000.0));
            }
            speech[index] = (short) sample;
        }

        VoiceProcessingPipeline.Result result = VoiceProcessingPipeline.process(noise, speech);

        assertEquals(speech.length, result.samples.length);
        assertEquals(0, result.clippedSamples);
        assertTrue(result.activeFrames > 0);
        assertTrue(result.maximumGainDb > 0.0);
        assertTrue(rms(result.samples, 8000, 16000) > rms(speech, 8000, 16000));
    }

    @Test
    public void attenuatesInactiveNoiseInsteadOfApplyingFixedGain() {
        Random random = new Random(31L);
        short[] calibration = new short[16000];
        short[] inactive = new short[32000];
        for (int index = 0; index < calibration.length; index++) {
            calibration[index] = (short) (random.nextInt(81) - 40);
        }
        for (int index = 0; index < inactive.length; index++) {
            inactive[index] = (short) (random.nextInt(81) - 40);
        }

        VoiceProcessingPipeline.Result result = VoiceProcessingPipeline.process(
                calibration, inactive);

        assertEquals(inactive.length, result.samples.length);
        assertEquals(0, result.clippedSamples);
        assertTrue(rms(result.samples, 0, result.samples.length)
                < rms(inactive, 0, inactive.length));
    }

    private static double rms(short[] samples, int offset, int length) {
        double sum = 0.0;
        for (int index = 0; index < length; index++) {
            double value = samples[offset + index];
            sum += value * value;
        }
        return Math.sqrt(sum / length);
    }
}
