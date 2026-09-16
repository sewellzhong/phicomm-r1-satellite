package dev.sewellzhong.r1probe.assist;

/** Drops the bounded tail after a local prompt before command VAD is armed. */
public final class PromptSettleGate {
    private final long durationNanos;
    private long notBefore;
    private boolean armed;
    private long events;
    private long discardedFrames;

    public PromptSettleGate(long durationNanos) {
        if (durationNanos < 0) throw new IllegalArgumentException("invalid_prompt_settle");
        this.durationNanos = durationNanos;
    }

    public void arm(long nowNanos) {
        if (nowNanos < 0) throw new IllegalArgumentException("invalid_prompt_clock");
        armed = true; notBefore = nowNanos + durationNanos; events++;
    }

    public boolean discard(long nowNanos) {
        if (!armed) return false;
        if (nowNanos < notBefore) { discardedFrames++; return true; }
        armed = false; return false;
    }

    public boolean armed() { return armed; }
    public long events() { return events; }
    public long discardedFrames() { return discardedFrames; }
}
