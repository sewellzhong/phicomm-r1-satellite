package dev.sewellzhong.r1probe.assist;

/** Authorization for an Alexa wake detected on the vendor AEC output. */
public final class PlaybackWakeCancelGate {
    private PlaybackWakeCancelGate() { }

    /**
     * Vendor AEC-KWS already evaluates the echo-reduced signal. Do not require
     * the ordinary direct-speech VAD result here: that result can be below the
     * raw-energy threshold even when a real Alexa wake was detected.
     */
    public static boolean allow(boolean detected, boolean enabled,
            boolean aecOutputReady, boolean outputSaturated) {
        return detected && enabled && aecOutputReady && !outputSaturated;
    }
}
