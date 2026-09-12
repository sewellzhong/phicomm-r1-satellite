package dev.sewellzhong.r1probe.esphome;

import java.io.IOException;
import java.util.Calendar;
import java.util.TimeZone;
import org.junit.Test;
import static org.junit.Assert.*;

public final class NativeDndControllerTest {
    private static final class MemoryStore implements NativeDndController.Store {
        String value = ""; boolean fail;
        public String load() { return value; }
        public void save(String value) throws IOException {
            if (fail) throw new IOException("dnd_persistence_failed");
            this.value = value;
        }
    }
    private static final class FakeClock implements NativeDndController.Clock {
        long wall; boolean trusted = true; String zone = "Asia/Hong_Kong";
        public long wallMillis() { return wall; }
        public boolean wallTrusted() { return trusted; }
        public String timeZoneId() { return zone; }
        void local(int hour, int minute) {
            Calendar value = Calendar.getInstance(TimeZone.getTimeZone(zone)); value.clear();
            value.set(2026, Calendar.SEPTEMBER, 12, hour, minute, 0); wall = value.getTimeInMillis();
        }
    }

    @Test public void manualAndCrossMidnightScheduleAreLocal() throws Exception {
        MemoryStore store = new MemoryStore(); FakeClock clock = new FakeClock(); clock.local(21, 59);
        NativeDndController dnd = new NativeDndController(store, clock);
        dnd.configure(false, true, 22, 0, 7, 0, true, 0);
        assertFalse(dnd.active());
        clock.local(22, 0); assertTrue(dnd.active());
        clock.local(6, 59); assertTrue(dnd.active());
        clock.local(7, 0); assertFalse(dnd.active());
        dnd.configure(true, false, 22, 0, 7, 0, false, 1);
        assertTrue(dnd.active()); assertFalse(dnd.alarmsAllowed());
        assertTrue(dnd.snapshot().getBoolean("dim_light_requested"));
    }

    @Test public void untrustedScheduledClockFailsClosedButManualOffDoesNot() throws Exception {
        MemoryStore store = new MemoryStore(); FakeClock clock = new FakeClock();
        NativeDndController dnd = new NativeDndController(store, clock);
        dnd.configure(false, true, 22, 0, 7, 0, true, 0);
        clock.trusted = false;
        assertTrue(dnd.active());
        assertEquals("clock_untrusted", dnd.snapshot().getString("source"));
        dnd.configure(false, false, 22, 0, 7, 0, true, 1);
        assertFalse(dnd.active());
    }

    @Test public void persistenceIsAtomicAndRestored() throws Exception {
        MemoryStore store = new MemoryStore(); FakeClock clock = new FakeClock();
        NativeDndController first = new NativeDndController(store, clock);
        first.configure(true, true, 23, 15, 6, 45, false, 0);
        NativeDndController restored = new NativeDndController(store, clock);
        assertTrue(restored.snapshot().getBoolean("manual"));
        assertEquals(23, restored.snapshot().getInt("start_hour"));
        store.fail = true;
        try { restored.configure(false, false, 20, 0, 8, 0, true, 1); fail(); }
        catch (IOException expected) { assertEquals("dnd_persistence_failed", expected.getMessage()); }
        assertTrue(restored.snapshot().getBoolean("manual"));
        assertEquals(1, restored.snapshot().getLong("version"));
        assertEquals(1, restored.snapshot().getLong("persistence_failures"));
    }

    @Test public void rejectsStaleOrDegenerateConfiguration() throws Exception {
        MemoryStore store = new MemoryStore(); FakeClock clock = new FakeClock();
        NativeDndController dnd = new NativeDndController(store, clock);
        try { dnd.configure(false, true, 22, 0, 22, 0, true, 0); fail(); }
        catch (IOException expected) { assertEquals("dnd_schedule_invalid", expected.getMessage()); }
        dnd.configure(false, false, 22, 0, 7, 0, true, 0);
        try { dnd.configure(true, false, 22, 0, 7, 0, true, 0); fail(); }
        catch (IOException expected) { assertEquals("dnd_version_conflict", expected.getMessage()); }
    }

    @Test public void corruptStateIsVisibleAndUsesSafeDefaults() throws Exception {
        MemoryStore store = new MemoryStore(); store.value = "{\"schema\":9}";
        NativeDndController dnd = new NativeDndController(store, new FakeClock());
        assertTrue(dnd.snapshot().getBoolean("restore_failed"));
        assertTrue(dnd.active()); assertTrue(dnd.alarmsAllowed());
    }
}
