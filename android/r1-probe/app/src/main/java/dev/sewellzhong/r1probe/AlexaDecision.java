package dev.sewellzhong.r1probe;

import java.util.Arrays;

/** ESPHome 2026.8.0 streaming_model semantics, evaluated once per new output. */
final class AlexaDecision {
    static final int CUTOFF = 229; // int(0.9 * 255), upstream configuration mapping
    static final int WINDOW = 5;
    static final int COOL_OFF_FEATURES = 100;
    private final int[] recent = new int[WINDOW];
    private int index;
    private int last;
    private int coolOff;
    private float detectedScore;

    AlexaDecision() {
        reset();
    }

    void reset() {
        Arrays.fill(recent, 0);
        index = 0;
        last = 0;
        coolOff = COOL_OFF_FEATURES;
        detectedScore = 0;
    }

    /** Called for every 10 ms feature, including features with no new inference. */
    boolean acceptFeature(int output, boolean newOutput) {
        if (newOutput) {
            if (output < 0 || output > 255) {
                throw new IllegalArgumentException("invalid_uint8_score");
            }
            last = output;
            recent[index] = output;
            index = (index + 1) % WINDOW;
        }
        if (last < CUTOFF && coolOff > 0) {
            coolOff--;
        }
        if (!newOutput || coolOff > 0) {
            return false;
        }
        int sum = 0;
        for (int score : recent) {
            sum += score;
        }
        if (sum <= CUTOFF * WINDOW) {
            return false;
        }
        float score = sum / (WINDOW * 256.0f);
        // Clear the probability history without resetting streaming model state.
        reset();
        detectedScore = score;
        return true;
    }

    float detectedScore() {
        return detectedScore;
    }
}
