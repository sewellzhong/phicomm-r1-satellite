package dev.sewellzhong.r1probe.assist;

/** Recorder stays warm. Discard prompt-time PCM; retain the first frame crossing completion. */
public final class PromptAudioBoundary {
    private volatile boolean complete;
    private final short[] handoff = new short[320];
    private int size;
    public void complete() { complete = true; }
    public boolean accept(short[] frame, int count) {
        if (count < 1 || count > 320) throw new IllegalArgumentException("prompt_frame_size");
        if (!complete) return false;
        System.arraycopy(frame, 0, handoff, 0, count); size = count;
        return true;
    }
    public int copyTo(short[] output) {
        System.arraycopy(handoff, 0, output, 0, size);
        java.util.Arrays.fill(handoff, (short)0);
        int result=size;size=0;return result;
    }
}
