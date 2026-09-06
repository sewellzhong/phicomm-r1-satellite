package dev.sewellzhong.r1probe;

/** Engine-neutral configuration shared by every Alexa KWS candidate. */
final class KwsConfig {
    static final String KEYWORD = "Alexa";
    static final String PRONUNCIATION_IPA = "/əˈlɛksə/";
    static final int SAMPLE_RATE = 16000;
    static final int FRAME_SAMPLES = 320;

    final float threshold;

    KwsConfig(float threshold) {
        if (Float.isNaN(threshold) || threshold < 0.0f || threshold > 1.0f) {
            throw new IllegalArgumentException("threshold_out_of_range");
        }
        this.threshold = threshold;
    }
}
