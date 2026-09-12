package dev.sewellzhong.r1probe.esphome;

import java.io.IOException;
import java.util.Calendar;
import java.util.TimeZone;
import org.json.JSONException;
import org.json.JSONObject;

/** Persistent local do-not-disturb policy. Voice replies are intentionally outside this gate. */
public final class NativeDndController {
    public interface Store {
        String load();
        void save(String value) throws IOException;
    }
    public interface Clock {
        long wallMillis();
        boolean wallTrusted();
        String timeZoneId();
    }

    private static final int SCHEMA = 1;
    private final Store store;
    private final Clock clock;
    private boolean manual;
    private boolean scheduleEnabled;
    private int startMinute = 22 * 60;
    private int endMinute = 7 * 60;
    private boolean alarmsAllowed = true;
    private long version;
    private long suppressedAnnouncements;
    private long suppressedAlarms;
    private long persistenceFailures;
    private boolean restoreFailed;

    public NativeDndController(Store store, Clock clock) {
        if (store == null || clock == null) throw new IllegalArgumentException("dnd_dependencies_required");
        this.store = store; this.clock = clock;
        restore(store.load());
    }

    public synchronized void configure(boolean manual, boolean scheduleEnabled,
            int startHour, int startMinute, int endHour, int endMinute,
            boolean alarmsAllowed, long expectedVersion) throws IOException {
        if (expectedVersion >= 0 && expectedVersion != version) throw new IOException("dnd_version_conflict");
        if (startHour < 0 || startHour > 23 || startMinute < 0 || startMinute > 59
                || endHour < 0 || endHour > 23 || endMinute < 0 || endMinute > 59
                || startHour == endHour && startMinute == endMinute)
            throw new IOException("dnd_schedule_invalid");
        String before = encode();
        this.manual = manual; this.scheduleEnabled = scheduleEnabled;
        this.startMinute = startHour * 60 + startMinute;
        this.endMinute = endHour * 60 + endMinute;
        this.alarmsAllowed = alarmsAllowed; version++;
        try { store.save(encode()); }
        catch (IOException error) {
            persistenceFailures++;
            restore(before);
            throw error;
        }
    }

    public synchronized boolean active() {
        if (manual) return true;
        if (!scheduleEnabled) return false;
        // A configured quiet period fails closed while civil time is unavailable.
        if (!clock.wallTrusted()) return true;
        Calendar now = Calendar.getInstance(safeZone(clock.timeZoneId()));
        now.setTimeInMillis(clock.wallMillis());
        int minute = now.get(Calendar.HOUR_OF_DAY) * 60 + now.get(Calendar.MINUTE);
        return startMinute < endMinute
                ? minute >= startMinute && minute < endMinute
                : minute >= startMinute || minute < endMinute;
    }

    public synchronized boolean announcementsAllowed() { return !active(); }
    public synchronized boolean alarmsAllowed() { return !active() || alarmsAllowed; }
    public synchronized void suppressedAnnouncement() { suppressedAnnouncements++; }
    public synchronized void suppressedAlarm() { suppressedAlarms++; }

    public synchronized JSONObject snapshot() throws JSONException {
        String source = !active() ? "none" : manual ? "manual"
                : !clock.wallTrusted() ? "clock_untrusted" : "schedule";
        return new JSONObject().put("schema", SCHEMA).put("version", version)
                .put("manual", manual).put("schedule_enabled", scheduleEnabled)
                .put("start_hour", startMinute / 60).put("start_minute", startMinute % 60)
                .put("end_hour", endMinute / 60).put("end_minute", endMinute % 60)
                .put("alarms_allowed", alarmsAllowed).put("active", active())
                .put("source", source).put("clock_trusted", clock.wallTrusted())
                .put("time_zone", safeZone(clock.timeZoneId()).getID())
                .put("dim_light_requested", active())
                .put("suppressed_announcements", suppressedAnnouncements)
                .put("suppressed_alarms", suppressedAlarms)
                .put("persistence_failures", persistenceFailures)
                .put("restore_failed", restoreFailed);
    }

    private String encode() throws IOException {
        try {
            return new JSONObject().put("schema", SCHEMA).put("version", version)
                    .put("manual", manual).put("schedule_enabled", scheduleEnabled)
                    .put("start_minute", startMinute).put("end_minute", endMinute)
                    .put("alarms_allowed", alarmsAllowed)
                    .put("suppressed_announcements", suppressedAnnouncements)
                    .put("suppressed_alarms", suppressedAlarms).toString();
        } catch (JSONException error) { throw new IOException("dnd_persistence_encoding_failed", error); }
    }

    private void restore(String encoded) {
        manual = scheduleEnabled = false; startMinute = 22 * 60; endMinute = 7 * 60;
        alarmsAllowed = true; version = suppressedAnnouncements = suppressedAlarms = 0;
        if (encoded == null || encoded.isEmpty()) return;
        try {
            JSONObject root = new JSONObject(encoded);
            if (root.getInt("schema") != SCHEMA) throw new JSONException("schema");
            int start = root.getInt("start_minute"), end = root.getInt("end_minute");
            if (start < 0 || start >= 1440 || end < 0 || end >= 1440 || start == end)
                throw new JSONException("schedule");
            version = root.getLong("version");
            if (version < 0) throw new JSONException("version");
            manual = root.getBoolean("manual"); scheduleEnabled = root.getBoolean("schedule_enabled");
            startMinute = start; endMinute = end; alarmsAllowed = root.getBoolean("alarms_allowed");
            suppressedAnnouncements = Math.max(0, root.optLong("suppressed_announcements"));
            suppressedAlarms = Math.max(0, root.optLong("suppressed_alarms"));
            restoreFailed = false;
        } catch (Exception error) {
            // Corrupt policy must not silently resume unsolicited audio. HA/voice can replace it.
            manual = true; scheduleEnabled = false; startMinute = 22 * 60; endMinute = 7 * 60;
            alarmsAllowed = true; version = suppressedAnnouncements = suppressedAlarms = 0;
            restoreFailed = true;
        }
    }

    private static TimeZone safeZone(String value) {
        if (value == null || value.isEmpty()) return TimeZone.getTimeZone("UTC");
        TimeZone zone = TimeZone.getTimeZone(value);
        return "GMT".equals(zone.getID()) && !value.startsWith("GMT") ? TimeZone.getTimeZone("UTC") : zone;
    }
}
