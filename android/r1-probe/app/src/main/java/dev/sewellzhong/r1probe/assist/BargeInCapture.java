package dev.sewellzhong.r1probe.assist;

import java.util.Arrays;

/**
 * Bounded PCM retained while the cancelled Assist run releases its player.
 * Single capture-thread owner; contents are wiped whenever ownership ends.
 */
public final class BargeInCapture {
    private static final int FRAME_BYTES = 640;
    private static final int MAX_BYTES = 160000; // Native coordinator's five-second prebuffer limit.
    private final byte[] pcm = new byte[MAX_BYTES];
    private int size;

    public void start(byte[] onset) {
        clear();
        if (onset == null || onset.length == 0 || onset.length % FRAME_BYTES != 0
                || onset.length > MAX_BYTES) {
            throw new IllegalArgumentException("invalid_barge_in_onset");
        }
        System.arraycopy(onset, 0, pcm, 0, onset.length);
        size = onset.length;
    }

    /** Returns false when the five-second handoff is full; no partial frame is retained. */
    public boolean append(short[] frame) {
        if (frame == null || frame.length != 320) throw new IllegalArgumentException("expected_20ms_frame");
        if (size + FRAME_BYTES > pcm.length) return false;
        for (short sample : frame) {
            pcm[size++] = (byte) sample;
            pcm[size++] = (byte) (sample >>> 8);
        }
        return true;
    }

    public int bytes() { return size; }

    public byte[] snapshot() { return Arrays.copyOf(pcm, size); }

    public void clear() {
        Arrays.fill(pcm, (byte) 0);
        size = 0;
    }
}
