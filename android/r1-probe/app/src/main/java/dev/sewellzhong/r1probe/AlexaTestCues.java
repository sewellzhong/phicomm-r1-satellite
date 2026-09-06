package dev.sewellzhong.r1probe;

import java.io.File;

/** Generated diagnostic tones only; no microphone audio is written. */
final class AlexaTestCues {
    static void play(File cacheDirectory, boolean end) throws Exception {
        int toneSamples = end ? 8000 : 12800; // end 500 ms, start 800 ms
        int gapSamples = 4800; // 300 ms
        short[] samples = new short[end ? toneSamples * 2 + gapSamples : toneSamples];
        for (int burst = 0; burst < (end ? 2 : 1); burst++) {
            int base = burst * (toneSamples + gapSamples);
            for (int i = 0; i < toneSamples; i++) {
                double ramp = Math.min(1.0, Math.min(i, toneSamples - 1 - i) / 160.0);
                samples[base + i] = (short) (6000 * ramp
                        * Math.sin(2 * Math.PI * (end ? 700 : 1000) * i / 16000));
            }
        }
        File cue = File.createTempFile("alexa-cue-", ".wav", cacheDirectory);
        try {
            MonoWavIo.write(cue, samples);
            AudioPlayback.play(cue);
        } finally {
            if (!cue.delete()) { cue.deleteOnExit(); }
        }
    }

    private AlexaTestCues() { }
}
