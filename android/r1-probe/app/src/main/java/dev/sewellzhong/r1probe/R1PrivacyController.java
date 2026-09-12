package dev.sewellzhong.r1probe;

import org.json.JSONException;
import org.json.JSONObject;

/** Locally owned, fail-closed microphone privacy state. No remote setter is exposed. */
final class R1PrivacyController {
    interface Store { boolean muted(); void save(boolean muted); }
    interface Capture { void stop(); }
    interface Indicator { boolean showMuted(boolean muted); String failure(); }

    private final Store store;
    private final Capture capture;
    private final Indicator indicator;
    private boolean muted;
    private long localToggles, captureStops;
    private String lastFailure;

    R1PrivacyController(Store store, Capture capture, Indicator indicator) {
        if (store == null || capture == null || indicator == null)
            throw new IllegalArgumentException("privacy_dependencies_required");
        this.store = store;
        this.capture = capture;
        this.indicator = indicator;
        muted = store.muted();
    }

    synchronized void applyPersistedState() {
        if (muted) stopCapture();
        updateIndicator();
    }

    /** This is deliberately called only by the physical-button state machine. */
    synchronized boolean toggleFromPhysicalButton() {
        boolean target = !muted;
        store.save(target); // A failed durable write must not report or apply a transient state.
        muted = target;
        localToggles++;
        if (muted) stopCapture();
        updateIndicator();
        return muted;
    }

    synchronized boolean muted() { return muted; }

    synchronized JSONObject snapshot() throws JSONException {
        String indicatorFailure = indicator.failure();
        return new JSONObject().put("muted", muted).put("source", "physical_button")
                .put("remote_unmute_supported", false).put("local_toggles", localToggles)
                .put("capture_stops", captureStops)
                .put("indicator_confirmed", indicatorFailure == null)
                .put("last_failure", indicatorFailure == null ? JSONObject.NULL : indicatorFailure);
    }

    private void stopCapture() {
        capture.stop();
        captureStops++;
    }

    private void updateIndicator() {
        if (!indicator.showMuted(muted)) lastFailure = indicator.failure();
        else lastFailure = null;
    }
}
