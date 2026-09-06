package dev.sewellzhong.r1probe.assist;

/** Two-stage endpoint driven by WebRTC VAD decisions, one decision per 20 ms frame. */
public final class CommandWindow {
    public enum Decision { WAIT, START, CONTINUE, END, TIMEOUT, DONE }
    private final int waitLimit, quietLimit, commandLimit, onsetFrames;
    /** Legacy WS profile; native runtime supplies its persisted configuration explicitly. */
    public CommandWindow() { this(6, 1.2f, 20); }
    public CommandWindow(float waitSeconds, float quietSeconds, float commandSeconds) {
        this(waitSeconds, quietSeconds, commandSeconds, 4);
    }
    public CommandWindow(float waitSeconds, float quietSeconds, float commandSeconds, int onsetFrames) {
        if (onsetFrames < 4 || onsetFrames > 15) throw new IllegalArgumentException("invalid_onset");
        this.onsetFrames = onsetFrames;
        if (!(!Float.isNaN(waitSeconds) && !Float.isInfinite(waitSeconds)) || !(!Float.isNaN(quietSeconds) && !Float.isInfinite(quietSeconds)) || !(!Float.isNaN(commandSeconds) && !Float.isInfinite(commandSeconds))
                || waitSeconds < 1 || waitSeconds > 120 || quietSeconds < .2f || quietSeconds > 10
                || commandSeconds < 5 || commandSeconds > 120) throw new IllegalArgumentException("invalid_window");
        waitLimit = Math.round(waitSeconds * 50);
        quietLimit = Math.round(quietSeconds * 50);
        commandLimit = Math.round(commandSeconds * 50);
    }
    /** Re-enter the same window after empty STT; elapsed time includes the rejected run. */
    public void resumeAfterEmpty(long elapsedMillis) {
        waitingFrames = (int)Math.min(waitLimit, Math.max(0, elapsedMillis / 20));
        recentSpeech = consecutiveStrong = consecutiveSpeech = commandFrames = quietFrames = voicedFrames = 0;
        started = ended = false;
        onsetReason = "none";
    }
    private int recentSpeech, consecutiveStrong;
    private String onsetReason = "none";
    public String onsetReason() { return onsetReason; }
    private int waitingFrames;
    private int consecutiveSpeech;
    private int commandFrames;
    private int quietFrames;
    private int voicedFrames;

    public int waitLimitMillis() { return waitLimit * 20; }
    public int waitingMillis() { return waitingFrames * 20; }
    public int commandMillis() { return commandFrames * 20; }
    public String endReason() { return commandFrames >= commandLimit ? "command_limit" : "trailing_silence"; }
    public int voicedMillis() { return voicedFrames * 20; }
    private boolean started;
    private boolean ended;

    public Decision accept(boolean speech) {
        consecutiveSpeech = speech ? consecutiveSpeech + 1 : 0;
        return advance(speech, consecutiveSpeech >= onsetFrames, consecutiveSpeech, consecutiveSpeech);
    }

    /** Native onset: sustained low-level speech, or a shorter high-SNR utterance. */
    public Decision acceptQualified(boolean speech, boolean strong) {
        if (ended) return Decision.DONE;
        if (started) return advance(speech, false, 0, 0);
        recentSpeech = ((recentSpeech << 1) | (speech ? 1 : 0)) & 0x7fff;
        consecutiveStrong = strong && speech ? consecutiveStrong + 1 : 0;
        int voiced = Integer.bitCount(recentSpeech);
        boolean ready = voiced >= 10 || consecutiveStrong >= 6;
        if (ready) onsetReason = consecutiveStrong >= 6 ? "strong_voice" : "sustained_voice";
        return advance(speech, ready, 32-Integer.numberOfLeadingZeros(recentSpeech), voiced);
    }

    private Decision advance(boolean speech, boolean onsetConfirmed, int onsetLength, int onsetVoiced) {
        if (ended) { return Decision.DONE; }
        if (!started) {
            if (waitingFrames >= waitLimit) { ended = true; return Decision.TIMEOUT; }
            waitingFrames++;
            if (onsetConfirmed) {
                started = true;
                commandFrames = onsetLength;
                voicedFrames = onsetVoiced;
                return Decision.START;
            }
            if (waitingFrames >= waitLimit) { // Only real post-prompt audio frames count.
                ended = true;
                return Decision.TIMEOUT;
            }
            return Decision.WAIT;
        }
        commandFrames++;
        if (speech) { voicedFrames++; }
        quietFrames = speech ? 0 : quietFrames + 1;
        if (quietFrames >= quietLimit || commandFrames >= commandLimit) { // First reached endpoint wins.
            ended = true;
            return Decision.END;
        }
        return Decision.CONTINUE;
    }
}
