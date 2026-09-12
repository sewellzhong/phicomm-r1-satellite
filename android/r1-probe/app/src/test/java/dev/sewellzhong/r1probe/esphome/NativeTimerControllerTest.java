package dev.sewellzhong.r1probe.esphome;

import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.io.IOException;
import org.junit.Test;
import static org.junit.Assert.*;

public final class NativeTimerControllerTest {
    static final class MemoryStore implements NativeTimerController.Store {
        String value = "";
        public String load() { return value; }
        public void save(String value) { this.value = value; }
    }
    static final class FakeClock implements NativeTimerController.Clock {
        long elapsed, wall = 1_800_000_000_000L;
        boolean trusted = true;
        public long elapsedMillis() { return elapsed; }
        public long wallMillis() { return wall; }
        public boolean wallTrusted() { return trusted; }
        void advance(long millis) { elapsed += millis; wall += millis; }
    }
    static final class FakeAlarm implements NativeTimerController.Alarm {
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
    private final FakeAlarm alarm = new FakeAlarm();
    private final NativeTimerController timers = new NativeTimerController(store, clock, alarm);

    private byte[] event(EsphomeApi.VoiceAssistantTimerEvent type, String id,
            int total, int left, boolean active) {
        return EsphomeApi.VoiceAssistantTimerEventResponse.newBuilder().setEventType(type)
                .setTimerId(id).setName("厨房").setTotalSeconds(total)
                .setSecondsLeft(left).setIsActive(active).build().toByteArray();
    }
    private void send(EsphomeApi.VoiceAssistantTimerEvent type, String id,
            int total, int left, boolean active) throws Exception {
        assertTrue(timers.message(MessageIds.VoiceAssistantTimerEventResponse,
                event(type, id, total, left, active)));
    }

    @Test public void countdownUsesMonotonicClockAndRingsLocally() throws Exception {
        send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_STARTED,
                "timer-1", 10, 10, true);
        assertEquals(1, timers.activeCount());
        clock.advance(9999); timers.tick();
        assertEquals(0, alarm.starts);
        clock.advance(1); timers.tick();
        assertEquals(0, timers.activeCount()); assertEquals(1, timers.ringingCount());
        assertEquals(1, alarm.starts); assertTrue(alarm.active);
    }

    @Test public void updateAndCancelReplaceDeadlineWithoutRinging() throws Exception {
        send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_STARTED,
                "timer-1", 30, 30, true);
        clock.advance(20000);
        send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_UPDATED,
                "timer-1", 60, 40, true);
        clock.advance(39000); timers.tick(); assertEquals(0, alarm.starts);
        send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_CANCELLED,
                "timer-1", 0, 0, false);
        clock.advance(10000); timers.tick();
        assertEquals(0, timers.activeCount()); assertEquals(0, alarm.starts);
    }

    @Test public void inactiveUpdatePausesAndLaterUpdateResumesCountdown() throws Exception {
        send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_STARTED,
                "timer-1", 30, 30, true);
        clock.advance(5000);
        send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_UPDATED,
                "timer-1", 30, 25, false);
        clock.advance(60000); timers.tick();
        assertEquals(1, timers.activeCount()); assertEquals(0, alarm.starts);
        assertFalse(timers.snapshot().getJSONArray("timers").getJSONObject(0).getBoolean("is_active"));
        send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_UPDATED,
                "timer-1", 30, 25, true);
        clock.advance(25000); timers.tick();
        assertEquals(1, alarm.starts);
    }

    @Test public void restartSubtractsTrustedWallTimeAndRingsOverdueTimer() throws Exception {
        send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_STARTED,
                "timer-1", 10, 10, true);
        FakeClock restartedClock = new FakeClock();
        restartedClock.wall = clock.wall + 12000;
        FakeAlarm restartedAlarm = new FakeAlarm();
        NativeTimerController restarted = new NativeTimerController(store, restartedClock, restartedAlarm);
        restarted.tick();
        assertEquals(0, restarted.activeCount()); assertEquals(1, restarted.ringingCount());
        assertEquals(1, restartedAlarm.starts);
    }

    @Test public void untrustedRestartWaitsInsteadOfClaimingAnIncorrectExpiry() throws Exception {
        send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_STARTED,
                "timer-1", 10, 10, true);
        FakeClock restartedClock = new FakeClock();
        restartedClock.trusted = false; restartedClock.wall = 0;
        FakeAlarm restartedAlarm = new FakeAlarm();
        NativeTimerController restarted = new NativeTimerController(store, restartedClock, restartedAlarm);
        restartedClock.advance(20000); restarted.tick();
        assertEquals(1, restarted.activeCount()); assertEquals(0, restartedAlarm.starts);
        assertTrue(restarted.snapshot().getJSONArray("timers").getJSONObject(0).getBoolean("clock_pending"));
        restartedClock.trusted = true; restartedClock.wall = 1_800_000_000_000L; restarted.tick();
        restartedClock.advance(10000); restarted.tick();
        assertEquals(1, restartedAlarm.starts);
    }

    @Test public void localStopTombstonePreventsReconnectFinishFromRingingTwice() throws Exception {
        send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_FINISHED,
                "timer-1", 10, 0, false);
        assertTrue(timers.stopRinging()); assertFalse(alarm.active);
        send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_FINISHED,
                "timer-1", 10, 0, false);
        timers.tick();
        assertEquals(0, timers.ringingCount()); assertEquals(1, alarm.starts);
    }

    @Test public void freshStartReusesIdAfterOldCompletion() throws Exception {
        send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_FINISHED,
                "timer-1", 10, 0, false);
        timers.stopRinging();
        send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_STARTED,
                "timer-1", 5, 5, true);
        clock.advance(5000); timers.tick();
        assertEquals(2, alarm.starts); assertEquals(1, timers.ringingCount());
    }

    @Test public void malformedAndExcessTimersFailClosed() throws Exception {
        try {
            send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_STARTED,
                    "", 10, 10, true);
            fail();
        } catch (IOException expected) { assertEquals("timer_id_invalid", expected.getMessage()); }
        try {
            send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_STARTED,
                    "bad\nid", 10, 10, true);
            fail();
        } catch (IOException expected) { assertEquals("timer_id_invalid", expected.getMessage()); }
        for (int i = 0; i < 32; i++) send(
                EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_STARTED,
                "capacity-" + i, 10, 10, true);
        try {
            send(EsphomeApi.VoiceAssistantTimerEvent.VOICE_ASSISTANT_TIMER_STARTED,
                    "overflow", 10, 10, true);
            fail();
        } catch (IOException expected) { assertEquals("timer_capacity_exceeded", expected.getMessage()); }
    }

    @Test public void unrelatedProtocolMessagesAreNotConsumed() throws Exception {
        assertFalse(timers.message(MessageIds.PingRequest, new byte[0]));
    }
}
