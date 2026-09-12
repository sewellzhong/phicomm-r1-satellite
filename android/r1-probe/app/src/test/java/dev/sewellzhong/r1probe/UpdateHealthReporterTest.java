package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.io.File;
import java.io.IOException;
import org.junit.Test;

public final class UpdateHealthReporterTest {
    private static final class Store implements UpdateHealthReporter.PendingStore {
        boolean pending = true;
        String boot = "boot-a";
        @Override public boolean pending(String current) {
            if (!boot.equals(current)) { pending = false; return false; }
            return pending;
        }
        @Override public void clear() { pending = false; }
    }
    private static final class Transport implements UpdateSupervisorClient.Transport {
        int calls;
        boolean fail;
        UpdateSupervisorClient.Response response = new UpdateSupervisorClient.Response(
                true, UpdateSupervisorClient.PHASE_IDLE, "");
        @Override public void submit(UpdateSupervisorClient.Candidate candidate, int fd) { }
        @Override public UpdateSupervisorClient.Response health(
                UpdateSupervisorClient.Health health) throws IOException {
            calls++;
            if (fail) throw new IOException("unavailable");
            return response;
        }
    }

    private static UpdateHealthReporter reporter(Store store, Transport transport,
            UpdateSupervisorClient.Health health) {
        return new UpdateHealthReporter(store, () -> health,
                new UpdateSupervisorClient(new File("."), transport));
    }

    @Test public void partialHealthWaitsWithoutContactingSupervisor() {
        Store store = new Store(); Transport transport = new Transport();
        assertTrue(reporter(store, transport,
                new UpdateSupervisorClient.Health(true, true, false, true)).attempt("boot-a"));
        assertEquals(0, transport.calls); assertTrue(store.pending);
    }

    @Test public void completeHealthCommitsAndClearsMarker() {
        Store store = new Store(); Transport transport = new Transport();
        assertFalse(reporter(store, transport,
                new UpdateSupervisorClient.Health(true, true, true, true)).attempt("boot-a"));
        assertEquals(1, transport.calls); assertFalse(store.pending);
    }

    @Test public void transportFailureKeepsSameBootRetryable() {
        Store store = new Store(); Transport transport = new Transport(); transport.fail = true;
        assertTrue(reporter(store, transport,
                new UpdateSupervisorClient.Health(true, true, true, true)).attempt("boot-a"));
        assertTrue(store.pending);
    }

    @Test public void rebootNeverConvertsOldMarkerIntoHealth() {
        Store store = new Store(); Transport transport = new Transport();
        assertFalse(reporter(store, transport,
                new UpdateSupervisorClient.Health(true, true, true, true)).attempt("boot-b"));
        assertEquals(0, transport.calls); assertFalse(store.pending);
    }

    @Test public void terminalSupervisorPhaseStopsRetries() {
        Store store = new Store(); Transport transport = new Transport();
        transport.response = new UpdateSupervisorClient.Response(false,
                UpdateSupervisorClient.PHASE_ROLLING_BACK, "update_health_failed");
        assertFalse(reporter(store, transport,
                new UpdateSupervisorClient.Health(true, true, true, true)).attempt("boot-a"));
        assertFalse(store.pending);
    }
}
