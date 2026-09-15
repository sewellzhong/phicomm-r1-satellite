package dev.sewellzhong.r1probe.assist;

/** Bounds one wake-triggered, hands-free conversation without disabling normal follow-ups. */
public final class ContinuousDialogueGuard {
    public static final int ROUND_LIMIT = 10;
    private volatile int rounds;
    private volatile long limitStops;

    public void reset() { rounds = 0; }
    public void commandStarted() {
        if (rounds >= ROUND_LIMIT) throw new IllegalStateException("continuous_round_limit");
        rounds++;
    }
    public boolean mayStartAnother() { return rounds < ROUND_LIMIT; }
    public void stoppedAtLimit() {
        if (rounds < ROUND_LIMIT) throw new IllegalStateException("continuous_limit_not_reached");
        limitStops++;
    }
    public int rounds() { return rounds; }
    public long limitStops() { return limitStops; }
}
