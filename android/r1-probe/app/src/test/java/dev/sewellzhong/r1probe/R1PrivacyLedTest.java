package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.io.IOException;
import org.junit.Test;

public final class R1PrivacyLedTest {
    private static final class Node implements R1PrivacyLed.Node {
        int value; boolean ignoreWrite, fail;
        @Override public int read() throws IOException { if (fail) throw new IOException(); return value; }
        @Override public void write(int value) throws IOException {
            if (fail) throw new IOException();
            if (!ignoreWrite) this.value = value;
        }
    }

    @Test public void requiresBothNodesToConfirmMutedAndClear() {
        Node first = new Node(), second = new Node(); R1PrivacyLed led = new R1PrivacyLed(first, second);
        assertTrue(led.showMuted(true)); assertEquals(4, first.value); assertEquals(0, second.value);
        assertTrue(led.showMuted(false)); assertEquals(0, first.value); assertEquals(0, second.value);
    }

    @Test public void permissionOrReadbackFailureNeverClaimsSuccess() {
        Node first = new Node(), second = new Node(); first.ignoreWrite = true;
        R1PrivacyLed led = new R1PrivacyLed(first, second);
        assertFalse(led.showMuted(true)); assertEquals("privacy_led_not_confirmed", led.failure());
    }

    @Test public void statusPatternsAreDistinctAndDndDimsOrdinaryStates() {
        Node first = new Node(), second = new Node(); R1PrivacyLed led = new R1PrivacyLed(first, second);
        assertTrue(led.show(R1PrivacyLed.State.LISTENING, false));
        assertEquals(0, first.value); assertEquals(2, second.value);
        assertTrue(led.show(R1PrivacyLed.State.PROCESSING, true));
        assertEquals(0, first.value); assertEquals(1, second.value);
        assertTrue(led.show(R1PrivacyLed.State.MUTED, true));
        assertEquals(4, first.value); assertEquals(0, second.value);
        assertEquals(R1PrivacyLed.State.MUTED, led.confirmedState());
    }

    @Test public void snapshotSeparatesRequestedAndConfirmedState() throws Exception {
        Node first = new Node(), second = new Node(); first.ignoreWrite = true;
        R1PrivacyLed led = new R1PrivacyLed(first, second);
        assertFalse(led.show(R1PrivacyLed.State.MUTED, false));
        assertEquals("muted", led.snapshot().getString("requested_state"));
        assertTrue(led.snapshot().isNull("confirmed_state"));
        assertFalse(led.snapshot().getBoolean("confirmed"));
    }
}
