package dev.sewellzhong.r1probe;

import java.io.IOException;
import org.json.JSONException;
import org.json.JSONObject;

/** Strict write/readback adapter for the two firmware 3448 LED brightness nodes. */
final class R1PrivacyLed implements R1PrivacyController.Indicator {
    enum State { OFF, DISCONNECTED, LISTENING, PROCESSING, PLAYING, PROVISIONING, MUTED }
    interface Node { int read() throws IOException; void write(int value) throws IOException; }
    interface Driver { int[] setAndRead(int first, int second) throws IOException; }
    private final Driver driver;
    private String failure;
    private State confirmedState;
    private State requestedState;
    private boolean requestedDimmed;
    private int actualFirst = -1, actualSecond = -1;

    R1PrivacyLed() { this(new SystemControlClient()); }
    R1PrivacyLed(Driver driver) { this.driver = driver; }
    R1PrivacyLed(final Node first, final Node second) {
        this((requestedFirst, requestedSecond) -> {
            first.write(requestedFirst); second.write(requestedSecond);
            return new int[]{first.read(), second.read()};
        });
    }

    @Override public synchronized boolean showMuted(boolean muted) {
        return show(muted ? State.MUTED : State.OFF, false);
    }

    synchronized boolean show(State state, boolean dimmed) {
        if (state == requestedState && dimmed == requestedDimmed && failure == null
                && confirmedState == state) return true;
        requestedState = state;
        requestedDimmed = dimmed;
        int[] levels = levels(state, dimmed);
        try {
            int[] actual = driver.setAndRead(levels[0], levels[1]);
            if (actual == null || actual.length != 2) throw new IOException("led_reply_invalid");
            actualFirst = actual[0]; actualSecond = actual[1];
            if (actualFirst != levels[0] || actualSecond != levels[1])
                throw new IOException("led_readback_mismatch");
            failure = null;
            confirmedState = state;
            return true;
        } catch (IOException | RuntimeException error) {
            failure = "privacy_led_not_confirmed";
            return false;
        }
    }

    @Override public synchronized String failure() { return failure; }
    synchronized State confirmedState() { return confirmedState; }
    synchronized JSONObject snapshot() throws JSONException {
        JSONObject result = new JSONObject()
                .put("requested_state", requestedState == null ? JSONObject.NULL
                        : requestedState.name().toLowerCase(java.util.Locale.ROOT))
                .put("confirmed_state", confirmedState == null ? JSONObject.NULL
                        : confirmedState.name().toLowerCase(java.util.Locale.ROOT))
                .put("confirmed", failure == null && requestedState == confirmedState)
                .put("failure", failure == null ? JSONObject.NULL : failure);
        result.put("led0", actualFirst < 0 ? JSONObject.NULL : actualFirst)
                .put("led1", actualSecond < 0 ? JSONObject.NULL : actualSecond);
        return result;
    }

    private static int[] levels(State state, boolean dimmed) {
        int[] result;
        switch (state) {
            case DISCONNECTED: result = new int[]{1, 1}; break;
            case LISTENING: result = new int[]{0, 2}; break;
            case PROCESSING: result = new int[]{0, 4}; break;
            case PLAYING: result = new int[]{2, 2}; break;
            case PROVISIONING: result = new int[]{4, 4}; break;
            case MUTED: result = new int[]{4, 0}; break;
            default: result = new int[]{0, 0};
        }
        // Privacy and provisioning remain unmistakable; DND only dims ordinary states.
        if (dimmed && state != State.MUTED && state != State.PROVISIONING) {
            result[0] = Math.min(1, result[0]); result[1] = Math.min(1, result[1]);
        }
        return result;
    }

}
