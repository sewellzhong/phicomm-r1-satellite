package dev.sewellzhong.r1probe;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.json.JSONException;
import org.json.JSONObject;

/** Strict write/readback adapter for the two firmware 3448 LED brightness nodes. */
final class R1PrivacyLed implements R1PrivacyController.Indicator {
    enum State { OFF, DISCONNECTED, LISTENING, PROCESSING, PLAYING, PROVISIONING, MUTED }
    interface Node { int read() throws IOException; void write(int value) throws IOException; }
    private static final String LED0 = "/sys/class/leds/multi_leds0/brightness";
    private static final String LED1 = "/sys/class/leds/multi_leds1/brightness";
    private final Node first, second;
    private String failure;
    private State confirmedState;
    private State requestedState;
    private boolean requestedDimmed;

    R1PrivacyLed() { this(fileNode(LED0), fileNode(LED1)); }
    R1PrivacyLed(Node first, Node second) { this.first = first; this.second = second; }

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
            first.write(levels[0]); second.write(levels[1]);
            if (first.read() != levels[0] || second.read() != levels[1])
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
        try { result.put("led0", first.read()).put("led1", second.read()); }
        catch (IOException | RuntimeException error) {
            result.put("led0", JSONObject.NULL).put("led1", JSONObject.NULL);
        }
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

    private static Node fileNode(final String path) {
        return new Node() {
            @Override public int read() throws IOException {
                byte[] bytes = new byte[16];
                try (FileInputStream input = new FileInputStream(new File(path))) {
                    int count = input.read(bytes);
                    if (count <= 0) throw new IOException("empty_led_state");
                    return Integer.parseInt(new String(bytes, 0, count, StandardCharsets.US_ASCII).trim());
                }
            }
            @Override public void write(int value) throws IOException {
                try (FileOutputStream output = new FileOutputStream(new File(path))) {
                    output.write(Integer.toString(value).getBytes(StandardCharsets.US_ASCII));
                    output.flush();
                }
            }
        };
    }
}
