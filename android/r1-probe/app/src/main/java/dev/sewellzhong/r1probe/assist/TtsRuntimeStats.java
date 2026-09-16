package dev.sewellzhong.r1probe.assist;

/** Bounded counters for one or more Assist runs; no text or URL is retained. */
public final class TtsRuntimeStats {
    private boolean responseSeen;
    private boolean streamSeen;
    private long responses;
    private long streams;
    private long playbackCompleted;
    private long playbackFailed;

    public void beginRun() { responseSeen = false; streamSeen = false; }

    /** Records the first TTS response event for the current run. */
    public void response(boolean streaming) {
        if (!responseSeen) { responses++; responseSeen = true; }
        if (streaming && !streamSeen) { streams++; streamSeen = true; }
    }

    /** Records terminal playback only for a run that actually produced TTS. */
    public void finish(boolean success) {
        if (!responseSeen) return;
        if (success) playbackCompleted++; else playbackFailed++;
        responseSeen = false; streamSeen = false;
    }

    public boolean responseSeen() { return responseSeen; }
    public long responses() { return responses; }
    public long streams() { return streams; }
    public long playbackCompleted() { return playbackCompleted; }
    public long playbackFailed() { return playbackFailed; }
}
