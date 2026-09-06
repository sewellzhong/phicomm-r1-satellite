package dev.sewellzhong.r1probe.assist;

import java.util.Arrays;

/** Two seconds of 16 kHz S16LE mono, held only in memory. Single capture-thread owner. */
public final class PcmPrebuffer {
    private final byte[] ring = new byte[64000];
    private int next;
    private int size;

    public void append(short[] frame) {
        if (frame == null || frame.length != 320) {
            throw new IllegalArgumentException("expected_20ms_frame");
        }
        for (short sample : frame) {
            ring[next] = (byte) sample;
            next = (next + 1) % ring.length;
            ring[next] = (byte) (sample >>> 8);
            next = (next + 1) % ring.length;
        }
        size = Math.min(size + 640, ring.length);
    }

    public byte[] snapshot() { return snapshot(100); }

    /** Latest maxFrames of 20 ms, without modifying the retained history. */
    public byte[] snapshot(int maxFrames) {
        if (maxFrames < 0 || maxFrames > 100) {
            throw new IllegalArgumentException("invalid_history_frames");
        }
        int length = Math.min(size, maxFrames * 640);
        byte[] result = new byte[length];
        int start = (next - length + ring.length) % ring.length;
        int first = Math.min(length, ring.length - start);
        System.arraycopy(ring, start, result, 0, first);
        System.arraycopy(ring, 0, result, first, length - first);
        return result;
    }

    public void clear() {
        Arrays.fill(ring, (byte) 0);
        next = size = 0;
    }
}
