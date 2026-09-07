package dev.sewellzhong.r1probe;

/** Same-process relay from Android's focused window to the persistent hardware monitor. */
final class HardwareInputRelay {
    interface Listener {
        void central(int action, long eventMs);
        void ring(int action, int position, long eventMs);
    }
    private static volatile Listener listener;
    private HardwareInputRelay() { }
    static void attach(Listener value) { listener = value; }
    static void detach(Listener value) { if (listener == value) listener = null; }
    static void central(int action, long eventMs) {
        Listener current = listener; if (current != null) current.central(action, eventMs);
    }
    static void ring(int action, int position, long eventMs) {
        Listener current = listener; if (current != null) current.ring(action, position, eventMs);
    }
    static int normalizePosition(float value, float minimum, float maximum) {
        if (maximum <= minimum) return 0;
        return Math.max(0, Math.min(255, Math.round((value - minimum) * 255f / (maximum - minimum))));
    }
}
