package dev.sewellzhong.r1probe.esphome;

import java.io.IOException;
import java.util.Calendar;
import java.util.TimeZone;
import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

public final class NativeAlarmControllerTest {
    static final class MemoryStore implements NativeAlarmController.Store {
        String value = "";
        boolean fail;
        public String load() { return value; }
        public void save(String value) throws IOException {
            if (fail) throw new IOException("store_failed");
            this.value = value;
        }
    }
    static final class FakeClock implements NativeAlarmController.Clock {
        long wall;
        boolean trusted = true;
        String zone = "Asia/Hong_Kong";
        public long wallMillis() { return wall; }
        public boolean wallTrusted() { return trusted; }
        public String timeZoneId() { return zone; }
        void advance(long millis) { wall += millis; }
    }
    static final class FakeRinger implements NativeAlarmController.Ringer {
        boolean active;
        int starts, stops;
        String failure;
        public void start() { starts++; active = failure == null; }
        public void stop() { stops++; active = false; }
        public boolean active() { return active; }
        public String failure() { return failure; }
    }

    private final MemoryStore store = new MemoryStore();
    private final FakeClock clock = new FakeClock();
    private final FakeRinger ringer = new FakeRinger();
    private final NativeAlarmController alarms;

    public NativeAlarmControllerTest() {
        clock.wall = epoch("Asia/Hong_Kong", 2026, 9, 12, 7, 0);
        alarms = new NativeAlarmController(store, clock, ringer);
    }

    @Test public void oneShotAlarmFiresLocallyAndDisables() throws Exception {
        alarms.put("wake", "起床", "2026-09-12", 7, 1, 0, true, 10, -1);
        clock.advance(59_999); alarms.tick(); assertEquals(0, ringer.starts);
        clock.advance(1); alarms.tick();
        JSONObject state = alarms.snapshot();
        assertEquals(1, ringer.starts); assertEquals(1, state.getInt("ringing_count"));
        assertFalse(state.getJSONArray("alarms").getJSONObject(0).getBoolean("enabled"));
        assertEquals(1, state.getLong("fires"));
    }

    @Test public void weeklyAlarmSchedulesNextOccurrenceBeforeRinging() throws Exception {
        int saturday = 1 << 5;
        alarms.put("weekly", "周六", "", 7, 1, saturday, true, 5, -1);
        clock.advance(60_000); alarms.tick();
        JSONObject value = alarms.snapshot().getJSONArray("alarms").getJSONObject(0);
        assertTrue(value.getBoolean("enabled")); assertTrue(value.getLong("next_wall_ms") > clock.wall);
        assertEquals(epoch("Asia/Hong_Kong", 2026, 9, 19, 7, 1), value.getLong("next_wall_ms"));
    }

    @Test public void multipleAlarmsDueTogetherRemainIndependentUntilEachIsStopped() throws Exception {
        alarms.put("medicine", "吃药", "2026-09-12", 7, 1, 0, true, 5, -1);
        alarms.put("meeting", "开会", "2026-09-12", 7, 1, 0, true, 10, -1);
        clock.advance(60_000); alarms.tick();
        JSONObject state = alarms.snapshot();
        assertEquals(2, state.getInt("alarm_count"));
        assertEquals(2, state.getInt("ringing_count"));
        assertEquals(1, ringer.starts);
        assertTrue(alarms.stopRinging("medicine"));
        assertEquals(1, alarms.snapshot().getInt("ringing_count"));
        assertTrue(ringer.active);
        assertTrue(alarms.stopRinging("meeting"));
        assertEquals(0, alarms.snapshot().getInt("ringing_count"));
        assertFalse(ringer.active);
    }

    @Test public void overdueAlarmOutsideGraceIsRecordedWithoutRinging() throws Exception {
        alarms.put("old", "旧闹钟", "2026-09-12", 7, 1, 0, true, 10, -1);
        clock.advance(6 * 60_000L + 1); alarms.tick();
        JSONObject state = alarms.snapshot();
        assertEquals(0, ringer.starts); assertEquals(1, state.getLong("missed"));
        assertFalse(state.getJSONArray("alarms").getJSONObject(0).getBoolean("enabled"));
    }

    @Test public void untrustedClockWaitsThenSchedulesWithoutFalseFire() throws Exception {
        clock.trusted = false;
        alarms.put("daily", "每天", "", 7, 1, 127, true, 10, -1);
        clock.advance(2 * 60_000L); alarms.tick(); assertEquals(0, ringer.starts);
        assertTrue(alarms.snapshot().getBoolean("clock_pending"));
        clock.trusted = true; alarms.tick();
        JSONObject value = alarms.snapshot().getJSONArray("alarms").getJSONObject(0);
        assertFalse(alarms.snapshot().getBoolean("clock_pending"));
        assertEquals(epoch("Asia/Hong_Kong", 2026, 9, 13, 7, 1), value.getLong("next_wall_ms"));
    }

    @Test public void snoozePersistsAndRingsAgain() throws Exception {
        alarms.put("wake", "起床", "2026-09-12", 7, 1, 0, true, 8, -1);
        clock.advance(60_000); alarms.tick();
        assertTrue(alarms.snooze("wake", null)); assertFalse(ringer.active);
        clock.advance(8 * 60_000L - 1); alarms.tick(); assertEquals(1, ringer.starts);
        clock.advance(1); alarms.tick(); assertEquals(2, ringer.starts);
        assertEquals(1, alarms.snapshot().getLong("snoozes"));
    }

    @Test public void restoredRingingAlarmRestartsOutputAndCanBeStopped() throws Exception {
        alarms.put("wake", "起床", "2026-09-12", 7, 1, 0, true, 10, -1);
        clock.advance(60_000); alarms.tick();
        FakeRinger restartedRinger = new FakeRinger();
        NativeAlarmController restarted = new NativeAlarmController(store, clock, restartedRinger);
        restarted.tick(); assertEquals(1, restartedRinger.starts);
        assertTrue(restarted.stopRinging(null)); assertFalse(restartedRinger.active);
    }

    @Test public void optimisticVersionConflictDoesNotMutateAlarm() throws Exception {
        alarms.put("wake", "原名", "2026-09-12", 7, 1, 0, true, 10, 0);
        long version = alarms.snapshot().getLong("version");
        try {
            alarms.put("wake", "错误修改", "2026-09-12", 8, 0, 0, true, 10, 0);
            fail();
        } catch (IOException expected) { assertEquals("alarm_version_conflict", expected.getMessage()); }
        JSONObject state = alarms.snapshot();
        assertEquals(version, state.getLong("version"));
        assertEquals("原名", state.getJSONArray("alarms").getJSONObject(0).getString("name"));
    }

    @Test public void invalidReplacementLeavesExistingAlarmIntact() throws Exception {
        alarms.put("wake", "原名", "2026-09-12", 7, 1, 0, true, 10, -1);
        try {
            alarms.put("wake", "过去", "2026-09-11", 7, 1, 0, true, 10, -1);
            fail();
        } catch (IOException expected) { assertEquals("alarm_time_not_future", expected.getMessage()); }
        assertEquals("原名", alarms.snapshot().getJSONArray("alarms").getJSONObject(0).getString("name"));
    }

    @Test public void failedPersistenceRejectsAndRollsBackConfiguration() throws Exception {
        alarms.put("wake", "原名", "2026-09-12", 7, 1, 0, true, 10, -1);
        store.fail = true;
        try {
            alarms.put("wake", "未保存", "2026-09-12", 8, 0, 0, true, 10, -1);
            fail();
        } catch (IOException expected) { assertEquals("store_failed", expected.getMessage()); }
        JSONObject state = alarms.snapshot();
        assertEquals("原名", state.getJSONArray("alarms").getJSONObject(0).getString("name"));
        assertEquals(1, state.getLong("persistence_failures"));
    }

    @Test public void localPolicyConsumesSuppressedOccurrenceWithoutLatePlayback() throws Exception {
        final boolean[] allowed = {false}; final int[] suppressed = {0};
        NativeAlarmController gated = new NativeAlarmController(store, clock, ringer,
                new NativeAlarmController.Policy() {
                    @Override public boolean allowed() { return allowed[0]; }
                    @Override public void suppressed() { suppressed[0]++; }
                });
        gated.put("quiet", "安静", "2026-09-12", 7, 1, 0, true, 10, -1);
        clock.advance(60_000); gated.tick();
        assertEquals(0, ringer.starts); assertEquals(1, suppressed[0]);
        assertEquals(1, gated.snapshot().getLong("suppressed"));
        assertEquals(0, gated.snapshot().getInt("ringing_count"));
        allowed[0] = true; gated.tick();
        assertEquals(0, ringer.starts);
    }

    private static long epoch(String zone, int year, int month, int day, int hour, int minute) {
        Calendar value = Calendar.getInstance(TimeZone.getTimeZone(zone)); value.clear(); value.setLenient(false);
        value.set(year, month - 1, day, hour, minute, 0); return value.getTimeInMillis();
    }
}
