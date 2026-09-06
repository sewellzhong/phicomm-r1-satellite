package dev.sewellzhong.r1probe;

import android.content.res.AssetManager;

/** Device-only contract checks using real JNI and TFLite, with generated silence. */
final class AlexaEngineProbe {
    static void run(AssetManager assets) throws Exception {
        AlexaKwsEngine engine = new AlexaKwsEngine(assets);
        try {
            short[] frame = new short[322];
            long expectedInferences = -1;
            int expectedMaximum = -1;
            for (int pass = 0; pass < 2; pass++) {
                if (pass > 0) { engine.reset(); }
                for (int i = 0; i < 150; i++) {
                    if (engine.acceptFrame(frame, 1, 320, i * 320L).detected) {
                        throw new IllegalStateException("silence_detection");
                    }
                }
                if (engine.metrics().audioSamples != 48000 || engine.inferenceCount() != 99) {
                    throw new IllegalStateException("streaming_count_mismatch");
                }
                if (pass == 0) {
                    expectedInferences = engine.inferenceCount();
                    expectedMaximum = engine.maximumRawScore();
                } else if (expectedInferences != engine.inferenceCount()
                        || expectedMaximum != engine.maximumRawScore()) {
                    throw new IllegalStateException("reset_not_reproducible");
                }
            }
            try {
                engine.acceptFrame(frame, 1, 320, 0);
                throw new IllegalStateException("discontinuity_accepted");
            } catch (IllegalArgumentException expected) { }
            try {
                engine.acceptFrame(frame, 1, 319, 48000);
                throw new IllegalStateException("wrong_frame_accepted");
            } catch (IllegalArgumentException expected) { }
        } finally {
            engine.close();
        }
        engine.close();
        try {
            engine.acceptFrame(new short[320], 0, 320, 48000);
        } catch (IllegalStateException expected) {
            return;
        }
        throw new IllegalStateException("closed_engine_accepted_audio");
    }

    private AlexaEngineProbe() { }
}
