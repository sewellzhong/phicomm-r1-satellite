package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.io.IOException;
import org.json.JSONObject;
import org.junit.Test;

public final class R1PhysicalButtonActionsTest {
    private static final class Timers implements R1PhysicalButtonActions.Timers {
        boolean ringing;
        @Override public boolean stopRinging() { boolean result = ringing; ringing = false; return result; }
    }
    private static final class Alarms implements R1PhysicalButtonActions.Alarms {
        boolean ringing, failStop, failSnooze;
        @Override public boolean ringing() { return ringing; }
        @Override public boolean stopRinging() throws IOException {
            if (!ringing) return false;
            ringing = false;
            if (failStop) throw new IOException("store_failed");
            return true;
        }
        @Override public boolean snooze() throws IOException {
            if (failSnooze) throw new IOException("store_failed");
            if (!ringing) return false;
            ringing = false;
            return true;
        }
    }
    private static final class Count {
        int audio, provisioning, privacy; boolean failPrivacy;
    }
    private static final class Scheduler implements R1PhysicalButtonActions.Scheduler {
        Runnable pending;
        @Override public Object schedule(Runnable action, long delayMillis) {
            assertEquals(R1PhysicalButtonActions.ALARM_DOUBLE_PRESS_MILLIS, delayMillis);
            pending = action; return action;
        }
        @Override public void cancel(Object token) {
            if (pending == token) pending = null;
        }
        void run() { Runnable action = pending; pending = null; action.run(); }
    }

    private static R1PhysicalButtonActions actions(Timers timers, Alarms alarms, Count count,
            Scheduler scheduler) {
        return new R1PhysicalButtonActions(timers, alarms, () -> count.audio++,
                () -> { count.provisioning++; return true; },
                () -> { if (count.failPrivacy) throw new IllegalStateException("store_failed");
                    count.privacy++; return (count.privacy & 1) == 1; }, scheduler);
    }

    @Test public void shortPressStopsEveryRingerBeforeCancellingAudio() throws Exception {
        Timers timers = new Timers(); timers.ringing = true;
        Alarms alarms = new Alarms(); alarms.ringing = true;
        Scheduler scheduler = new Scheduler(); Count count = new Count();
        R1PhysicalButtonActions actions = actions(timers, alarms, count, scheduler);
        actions.shortPress();
        assertTrue(alarms.ringing); assertTrue(actions.snapshot().getBoolean("alarm_press_pending"));
        scheduler.run();
        assertFalse(timers.ringing); assertFalse(alarms.ringing); assertEquals(0, count.audio);
        JSONObject state = actions.snapshot();
        assertEquals("stop_ringing", state.getString("last_action"));
        assertEquals(1, state.getLong("stops"));
    }

    @Test public void stoppingTimerDoesNotArmPrivacyGesture() throws Exception {
        Timers timers = new Timers(); timers.ringing = true;
        R1PhysicalButtonActions actions = actions(timers, new Alarms(), new Count(), new Scheduler());
        actions.shortPress();
        assertFalse(actions.snapshot().getBoolean("privacy_press_pending"));
    }

    @Test public void idleShortPressCancelsCurrentAudio() throws Exception {
        Count count = new Count(); R1PhysicalButtonActions actions = actions(
                new Timers(), new Alarms(), count, new Scheduler());
        actions.shortPress();
        assertEquals(1, count.audio);
        assertEquals("cancel_audio", actions.snapshot().getString("last_action"));
    }

    @Test public void idleDoublePressTogglesPrivacyAfterImmediateAudioStop() throws Exception {
        Count count = new Count(); Scheduler scheduler = new Scheduler();
        R1PhysicalButtonActions actions = actions(new Timers(), new Alarms(), count, scheduler);
        actions.shortPress(); actions.shortPress();
        assertEquals(1, count.audio); assertEquals(1, count.privacy);
        assertEquals("toggle_privacy_mute", actions.snapshot().getString("last_action"));
        assertFalse(actions.snapshot().getBoolean("privacy_press_pending"));
    }

    @Test public void privacyPersistenceFailureIsContainedAndReported() throws Exception {
        Count count = new Count(); count.failPrivacy = true; Scheduler scheduler = new Scheduler();
        R1PhysicalButtonActions actions = actions(new Timers(), new Alarms(), count, scheduler);
        actions.shortPress(); actions.shortPress();
        assertEquals("failed", actions.snapshot().getString("last_action"));
        assertEquals("privacy_persistence_failed", actions.snapshot().getString("last_failure"));
    }

    @Test public void ringingDoublePressSnoozesWithoutFirstStopping() throws Exception {
        Alarms alarms = new Alarms(); alarms.ringing = true;
        Scheduler scheduler = new Scheduler(); Count count = new Count();
        R1PhysicalButtonActions actions = actions(new Timers(), alarms, count, scheduler);
        actions.shortPress(); actions.shortPress();
        assertFalse(alarms.ringing); assertEquals(0, count.provisioning);
        assertEquals("snooze_alarm", actions.snapshot().getString("last_action"));
        assertEquals(null, scheduler.pending);
    }

    @Test public void longPressAlwaysKeepsFirmwareProvisioningGesture() throws Exception {
        Alarms alarms = new Alarms(); alarms.ringing = true;
        Count count = new Count(); R1PhysicalButtonActions actions = actions(
                new Timers(), alarms, count, new Scheduler());
        actions.longPress();
        assertEquals(1, count.provisioning); assertTrue(alarms.ringing);
        assertEquals("open_provisioning", actions.snapshot().getString("last_action"));
    }

    @Test public void failedSnoozeDoesNotOpenProvisioning() throws Exception {
        Alarms alarms = new Alarms(); alarms.ringing = true; alarms.failSnooze = true;
        Count count = new Count(); R1PhysicalButtonActions actions = actions(
                new Timers(), alarms, count, new Scheduler());
        actions.shortPress(); actions.shortPress();
        assertTrue(alarms.ringing); assertEquals(0, count.provisioning);
        JSONObject state = actions.snapshot();
        assertEquals("failed", state.getString("last_action"));
        assertEquals("alarm_snooze_failed", state.getString("last_failure"));
    }

    @Test public void failedStopStillDoesNotCancelUnrelatedAudio() throws Exception {
        Alarms alarms = new Alarms(); alarms.ringing = true; alarms.failStop = true;
        Scheduler scheduler = new Scheduler(); Count count = new Count();
        R1PhysicalButtonActions actions = actions(new Timers(), alarms, count, scheduler);
        actions.shortPress(); scheduler.run();
        assertEquals(0, count.audio);
        JSONObject state = actions.snapshot();
        assertEquals("stop_ringing", state.getString("last_action"));
        assertEquals(1, state.getLong("failures"));
    }

    @Test public void closeCancelsPendingSinglePress() throws Exception {
        Alarms alarms = new Alarms(); alarms.ringing = true;
        Scheduler scheduler = new Scheduler(); R1PhysicalButtonActions actions = actions(
                new Timers(), alarms, new Count(), scheduler);
        actions.shortPress(); actions.close();
        assertEquals(null, scheduler.pending);
        assertFalse(actions.snapshot().getBoolean("alarm_press_pending"));
        assertFalse(actions.snapshot().getBoolean("privacy_press_pending"));
        assertTrue(alarms.ringing);
    }
}
