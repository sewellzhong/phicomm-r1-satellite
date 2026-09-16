package dev.sewellzhong.r1probe.assist;

/**
 * Conservative gate for direct speech while a reply is playing.
 *
 * Playback echo must first pass through the vendor AEC path. A direct-barge
 * candidate is only eligible after a stable run of strong, non-reference
 * frames with a non-saturated AEC output. This class deliberately does not
 * retain PCM; the caller owns the audio and the diagnostic counters.
 */
public final class PlaybackBargeInGate {
    public enum Decision { WAIT, ACCEPT, BLOCKED }

    private final int requiredStrongFrames;
    private int strongFrames;
    private String blockReason = "awaiting_aec";

    public PlaybackBargeInGate() { this(6); }

    public PlaybackBargeInGate(int requiredStrongFrames) {
        if (requiredStrongFrames < 1 || requiredStrongFrames > 20)
            throw new IllegalArgumentException("invalid_barge_gate_frames");
        this.requiredStrongFrames = requiredStrongFrames;
    }

    public Decision observe(boolean aecOutputReady, boolean referenceMatched,
            boolean qualifiedSpeech, boolean strongSpeech, boolean outputSaturated) {
        if (!aecOutputReady) {
            strongFrames = 0;
            blockReason = "aec_output_unavailable";
            return Decision.BLOCKED;
        }
        if (outputSaturated) {
            strongFrames = 0;
            blockReason = "aec_output_saturated";
            return Decision.BLOCKED;
        }
        if (referenceMatched) {
            strongFrames = 0;
            blockReason = "playback_reference_match";
            return Decision.WAIT;
        }
        if (!qualifiedSpeech) {
            strongFrames = 0;
            blockReason = "speech_not_qualified";
            return Decision.WAIT;
        }
        if (!strongSpeech) {
            strongFrames = 0;
            blockReason = "speech_not_strong";
            return Decision.WAIT;
        }
        strongFrames++;
        blockReason = "awaiting_stable_speech";
        return strongFrames >= requiredStrongFrames ? Decision.ACCEPT : Decision.WAIT;
    }

    public void reset() {
        strongFrames = 0;
        blockReason = "awaiting_aec";
    }

    public int strongFrames() { return strongFrames; }
    public String blockReason() { return blockReason; }
}
