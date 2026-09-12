package dev.sewellzhong.r1probe;

import java.io.IOException;
import org.json.JSONException;
import org.json.JSONObject;

/** Product actions bound to the firmware's centre-key short and long press messages. */
final class R1PhysicalButtonActions implements R1SystemKeyMonitor.Listener {
    interface Timers { boolean stopRinging(); }
    interface Alarms {
        boolean ringing();
        boolean stopRinging() throws IOException;
        boolean snooze() throws IOException;
    }
    interface Audio { void cancel(); }
    interface Provisioning { boolean open(); }
    interface Privacy { boolean toggle(); }
    interface Scheduler {
        Object schedule(Runnable action, long delayMillis);
        void cancel(Object token);
    }

    static final long ALARM_DOUBLE_PRESS_MILLIS = 450;
    static final long PRIVACY_DOUBLE_PRESS_MILLIS = 450;

    private final Timers timers;
    private final Alarms alarms;
    private final Audio audio;
    private final Provisioning provisioning;
    private final Privacy privacy;
    private final Scheduler scheduler;
    private Object pendingAlarmStop;
    private Object pendingPrivacyPress;
    private long stops, snoozes, audioCancels, provisioningOpens, privacyToggles, failures;
    private String lastAction = "none", lastFailure;

    R1PhysicalButtonActions(Timers timers, Alarms alarms, Audio audio,
            Provisioning provisioning, Privacy privacy, Scheduler scheduler) {
        if (timers == null || alarms == null || audio == null || provisioning == null
                || privacy == null || scheduler == null)
            throw new IllegalArgumentException("button_dependencies_required");
        this.timers = timers;
        this.alarms = alarms;
        this.audio = audio;
        this.provisioning = provisioning;
        this.privacy = privacy;
        this.scheduler = scheduler;
    }

    @Override public synchronized void shortPress() {
        if (pendingAlarmStop != null) {
            scheduler.cancel(pendingAlarmStop);
            pendingAlarmStop = null;
            snoozeAlarm();
            return;
        }
        if (alarms.ringing()) {
            pendingAlarmStop = scheduler.schedule(() -> finishAlarmSinglePress(),
                    ALARM_DOUBLE_PRESS_MILLIS);
            lastAction = "alarm_press_pending";
            return;
        }
        if (pendingPrivacyPress != null) {
            scheduler.cancel(pendingPrivacyPress);
            pendingPrivacyPress = null;
            try {
                privacy.toggle();
                privacyToggles++;
                lastAction = "toggle_privacy_mute";
            } catch (RuntimeException error) { failed("privacy_persistence_failed"); }
            return;
        }
        if (!stopRingingOrCancelAudio())
            pendingPrivacyPress = scheduler.schedule(() -> clearPrivacyPress(),
                    PRIVACY_DOUBLE_PRESS_MILLIS);
    }

    private synchronized void clearPrivacyPress() { pendingPrivacyPress = null; }

    private synchronized void finishAlarmSinglePress() {
        if (pendingAlarmStop == null) return;
        pendingAlarmStop = null;
        stopRingingOnly();
    }

    private boolean stopRingingOrCancelAudio() {
        if (stopRingingOnly()) return true;
        audio.cancel();
        audioCancels++;
        lastAction = "cancel_audio";
        return false;
    }

    private boolean stopRingingOnly() {
        boolean stopped = timers.stopRinging();
        boolean alarmWasRinging = alarms.ringing();
        try { stopped |= alarms.stopRinging(); }
        catch (IOException error) {
            // The alarm controller stops local output before persisting its new state. Do not
            // turn a persistence failure into an unrelated voice cancellation.
            stopped |= alarmWasRinging;
            failed("alarm_stop_persistence_failed");
        }
        if (stopped) { stops++; lastAction = "stop_ringing"; }
        return stopped;
    }

    @Override public synchronized void longPress() {
        if (provisioning.open()) {
            provisioningOpens++;
            lastAction = "open_provisioning";
        } else failed("provisioning_unavailable");
    }

    private void snoozeAlarm() {
        try {
            if (!alarms.snooze()) throw new IOException("alarm_not_ringing");
            snoozes++;
            lastAction = "snooze_alarm";
        } catch (IOException error) { failed("alarm_snooze_failed"); }
    }

    synchronized JSONObject snapshot() throws JSONException {
        return new JSONObject().put("last_action", lastAction)
                .put("stops", stops).put("snoozes", snoozes)
                .put("audio_cancels", audioCancels).put("provisioning_opens", provisioningOpens)
                .put("alarm_press_pending", pendingAlarmStop != null)
                .put("privacy_press_pending", pendingPrivacyPress != null)
                .put("privacy_toggles", privacyToggles)
                .put("failures", failures)
                .put("last_failure", lastFailure == null ? JSONObject.NULL : lastFailure);
    }

    synchronized void close() {
        if (pendingAlarmStop != null) scheduler.cancel(pendingAlarmStop);
        if (pendingPrivacyPress != null) scheduler.cancel(pendingPrivacyPress);
        pendingAlarmStop = null;
        pendingPrivacyPress = null;
    }

    private void failed(String reason) {
        failures++;
        lastFailure = reason;
        lastAction = "failed";
    }
}
