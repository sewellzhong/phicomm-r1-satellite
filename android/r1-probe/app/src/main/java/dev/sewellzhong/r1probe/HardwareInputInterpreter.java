package dev.sewellzhong.r1probe;

/** Converts the R1's raw Linux input events into bounded hardware actions. */
final class HardwareInputInterpreter {
    interface Listener {
        void central(boolean longPress, long durationMs);
        void ringStep(int direction);
    }
    static final int EV_KEY = 1, EV_ABS = 3;
    static final int CENTRAL_KEY = 195, BTN_TOUCH = 330, ABS_X = 0;
    static final long LONG_PRESS_MS = 800;
    static final int RING_STEP_UNITS = 16;
    private final Listener listener;
    private long centralDownMs = -1;
    private boolean touching;
    private int lastPosition = -1, accumulated;

    HardwareInputInterpreter(Listener listener) { this.listener = listener; }

    synchronized void central(int type, int code, int value, long eventMs) {
        if (type != EV_KEY || code != CENTRAL_KEY) return;
        if (value == 1) centralDownMs = eventMs;
        else if (value == 0 && centralDownMs >= 0) {
            long duration = Math.max(0, eventMs - centralDownMs);
            centralDownMs = -1;
            listener.central(duration >= LONG_PRESS_MS, duration);
        }
    }

    synchronized void ring(int type, int code, int value, long eventMs) {
        if (type == EV_KEY && code == BTN_TOUCH) {
            touching = value != 0;
            lastPosition = -1;
            accumulated = 0;
            return;
        }
        if (!touching || type != EV_ABS || code != ABS_X || value < 0 || value > 255) return;
        if (lastPosition < 0) { lastPosition = value; return; }
        int delta = value - lastPosition;
        lastPosition = value;
        if (delta > 128) delta -= 256;
        else if (delta < -128) delta += 256;
        // Reject a discontinuity that is too large to be a sampled finger movement.
        if (Math.abs(delta) > 48) { accumulated = 0; return; }
        accumulated += delta;
        while (accumulated >= RING_STEP_UNITS) {
            accumulated -= RING_STEP_UNITS;
            listener.ringStep(1);
        }
        while (accumulated <= -RING_STEP_UNITS) {
            accumulated += RING_STEP_UNITS;
            listener.ringStep(-1);
        }
    }
}
