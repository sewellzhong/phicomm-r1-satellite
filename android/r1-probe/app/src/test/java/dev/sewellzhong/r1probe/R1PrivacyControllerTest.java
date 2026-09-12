package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class R1PrivacyControllerTest {
    private static final class Store implements R1PrivacyController.Store {
        boolean muted, fail;
        @Override public boolean muted() { return muted; }
        @Override public void save(boolean value) {
            if (fail) throw new IllegalStateException("store_failed");
            muted = value;
        }
    }
    private static final class Capture implements R1PrivacyController.Capture {
        int stops;
        @Override public void stop() { stops++; }
    }
    private static final class Indicator implements R1PrivacyController.Indicator {
        boolean value, succeeds = true;
        @Override public boolean showMuted(boolean muted) { value = muted; return succeeds; }
        @Override public String failure() { return succeeds ? null : "privacy_led_not_confirmed"; }
    }

    @Test public void persistedMuteStopsCaptureBeforeServing() throws Exception {
        Store store = new Store(); store.muted = true;
        Capture capture = new Capture(); Indicator indicator = new Indicator();
        R1PrivacyController privacy = new R1PrivacyController(store, capture, indicator);
        privacy.applyPersistedState();
        assertTrue(privacy.muted()); assertEquals(1, capture.stops); assertTrue(indicator.value);
        assertFalse(privacy.snapshot().getBoolean("remote_unmute_supported"));
    }

    @Test public void onlyLocalTogglePersistsAndStopsOnMute() {
        Store store = new Store(); Capture capture = new Capture(); Indicator indicator = new Indicator();
        R1PrivacyController privacy = new R1PrivacyController(store, capture, indicator);
        assertTrue(privacy.toggleFromPhysicalButton());
        assertTrue(store.muted); assertEquals(1, capture.stops);
        assertFalse(privacy.toggleFromPhysicalButton());
        assertFalse(store.muted); assertEquals(1, capture.stops);
    }

    @Test(expected = IllegalStateException.class)
    public void persistenceFailureDoesNotApplyTransientMute() {
        Store store = new Store(); store.fail = true;
        R1PrivacyController privacy = new R1PrivacyController(store, new Capture(), new Indicator());
        privacy.toggleFromPhysicalButton();
    }

    @Test public void unconfirmedLedIsReportedWithoutUnmuting() throws Exception {
        Store store = new Store(); Indicator indicator = new Indicator(); indicator.succeeds = false;
        R1PrivacyController privacy = new R1PrivacyController(store, new Capture(), indicator);
        privacy.toggleFromPhysicalButton();
        assertTrue(privacy.muted()); assertFalse(privacy.snapshot().getBoolean("indicator_confirmed"));
        assertEquals("privacy_led_not_confirmed", privacy.snapshot().getString("last_failure"));
    }
}
