package dev.sewellzhong.r1probe.assist;

import java.util.ArrayDeque;
import java.util.Arrays;

/** Keep capture warm, discard playback PCM, retain at most two seconds after hardware drain. */
public final class PlaybackInputBoundary {
    private final ArrayDeque<short[]> pending = new ArrayDeque<>();
    private boolean active, drained;
    public synchronized void start() { clear(); active = true; drained = false; }
    public synchronized void drained() { if (active) drained = true; }
    public synchronized boolean active() { return active; }
    public synchronized void accept(short[] frame) {
        if (!active || !drained) return;
        if (pending.size() >= 100) throw new IllegalStateException("playback_handoff_overflow");
        pending.add(frame.clone());
    }
    public synchronized boolean poll(short[] output) {
        short[] frame = pending.poll();
        if (frame == null) { active = false; return false; }
        System.arraycopy(frame, 0, output, 0, frame.length);
        Arrays.fill(frame, (short)0);
        return true;
    }
    public synchronized void clear() {
        for (short[] frame : pending) Arrays.fill(frame, (short)0);
        pending.clear(); active = false; drained = false;
    }
}
