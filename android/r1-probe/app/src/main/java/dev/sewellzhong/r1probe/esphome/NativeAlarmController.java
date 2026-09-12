package dev.sewellzhong.r1probe.esphome;

import java.io.IOException;
import java.util.Calendar;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.TimeZone;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Persistent local civil-time alarms. Scheduling never depends on an HA connection. */
public final class NativeAlarmController {
    public interface Store {
        String load();
        void save(String value) throws IOException;
    }
    public interface Clock {
        long wallMillis();
        boolean wallTrusted();
        String timeZoneId();
    }
    public interface Ringer {
        void start();
        void stop();
        boolean active();
        String failure();
    }
    public interface Policy {
        boolean allowed();
        void suppressed();
    }

    private static final int SCHEMA = 1;
    private static final int MAX_ALARMS = 32;
    private static final long LATE_GRACE_MILLIS = 5 * 60 * 1000L;
    private static final long RETRY_MILLIS = 5000L;

    private static final class AlarmValue {
        final String id;
        String name;
        String date;
        int minuteOfDay;
        int weekdays;
        int snoozeMinutes;
        boolean enabled;
        long nextWallMillis;
        long snoozeWallMillis;
        long lastOccurrenceWallMillis;
        long revision;
        AlarmValue(String id) { this.id = id; }
    }

    private final Store store;
    private final Clock clock;
    private final Ringer ringer;
    private final Policy policy;
    private final LinkedHashMap<String, AlarmValue> alarms = new LinkedHashMap<>();
    private final LinkedHashSet<String> ringing = new LinkedHashSet<>();
    private long version;
    private long fires, stops, snoozes, missed, invalidRequests, persistenceFailures;
    private long clockWaits, ringerFailures, suppressed, nextRingerAttempt;
    private boolean clockPending;
    private String scheduledZone;
    private String lastRingerFailure;

    public NativeAlarmController(Store store, Clock clock, Ringer ringer) {
        this(store, clock, ringer, new Policy() {
            @Override public boolean allowed() { return true; }
            @Override public void suppressed() { }
        });
    }

    public NativeAlarmController(Store store, Clock clock, Ringer ringer, Policy policy) {
        if (store == null || clock == null || ringer == null)
            throw new IllegalArgumentException("alarm_dependencies_required");
        if (policy == null) throw new IllegalArgumentException("alarm_policy_required");
        this.store = store; this.clock = clock; this.ringer = ringer; this.policy = policy;
        scheduledZone = safeZone(clock.timeZoneId());
        restore(store.load());
    }

    public synchronized void put(String id, String name, String date, int hour, int minute,
            int weekdays, boolean enabled, int snoozeMinutes, long expectedVersion) throws IOException {
        checkVersion(expectedVersion);
        id = checked(id, 128, "alarm_id_invalid");
        name = checked(name, 256, "alarm_name_invalid");
        date = date == null ? "" : checked(date, 10, "alarm_date_invalid");
        if (hour < 0 || hour > 23 || minute < 0 || minute > 59 || weekdays < 0 || weekdays > 127
                || snoozeMinutes < 1 || snoozeMinutes > 60 || (!date.isEmpty() && weekdays != 0)
                || (date.isEmpty() && weekdays == 0)) reject("alarm_schedule_invalid");
        if (!date.isEmpty()) try { parseDate(date); }
        catch (RuntimeException error) { reject("alarm_date_invalid"); }
        AlarmValue current = alarms.get(id);
        if (current == null && alarms.size() >= MAX_ALARMS) reject("alarm_capacity_exceeded");
        AlarmValue candidate = new AlarmValue(id);
        candidate.name = name; candidate.date = date; candidate.minuteOfDay = hour * 60 + minute;
        candidate.weekdays = weekdays; candidate.enabled = enabled; candidate.snoozeMinutes = snoozeMinutes;
        candidate.nextWallMillis = enabled && clock.wallTrusted() ? nextOccurrence(candidate, clock.wallMillis(), true) : 0;
        if (enabled && clock.wallTrusted() && candidate.nextWallMillis == 0) reject("alarm_time_not_future");
        String before = encodeState();
        AlarmValue value = current == null ? candidate : current;
        if (current != null) {
            value.name = candidate.name; value.date = candidate.date; value.minuteOfDay = candidate.minuteOfDay;
            value.weekdays = candidate.weekdays; value.enabled = candidate.enabled;
            value.snoozeMinutes = candidate.snoozeMinutes; value.nextWallMillis = candidate.nextWallMillis;
        } else alarms.put(id, value);
        value.snoozeWallMillis = 0; value.lastOccurrenceWallMillis = 0;
        ringing.remove(id);
        value.revision = ++version;
        if (ringing.isEmpty()) ringer.stop();
        commitOrRollback(before);
    }

    public synchronized void delete(String id, long expectedVersion) throws IOException {
        checkVersion(expectedVersion);
        id = checked(id, 128, "alarm_id_invalid");
        if (!alarms.containsKey(id)) reject("alarm_not_found");
        String before = encodeState();
        alarms.remove(id);
        ringing.remove(id); version++;
        if (ringing.isEmpty()) ringer.stop();
        commitOrRollback(before);
    }

    public synchronized void enable(String id, boolean enabled, long expectedVersion) throws IOException {
        checkVersion(expectedVersion);
        AlarmValue value = alarms.get(checked(id, 128, "alarm_id_invalid"));
        if (value == null) reject("alarm_not_found");
        long next = enabled && clock.wallTrusted() ? nextOccurrence(value, clock.wallMillis(), true) : 0;
        if (enabled && clock.wallTrusted() && next == 0) reject("alarm_time_not_future");
        String before = encodeState();
        value.enabled = enabled; value.snoozeWallMillis = 0; value.nextWallMillis = next;
        ringing.remove(value.id);
        value.revision = ++version;
        if (ringing.isEmpty()) ringer.stop();
        commitOrRollback(before);
    }

    /** Stops one alarm, or every local alarm when id is null/empty. */
    public synchronized boolean stopRinging(String id) throws IOException {
        boolean changed;
        if (id == null || id.isEmpty()) { changed = !ringing.isEmpty(); ringing.clear(); }
        else changed = ringing.remove(checked(id, 128, "alarm_id_invalid"));
        if (!changed && !ringer.active()) return false;
        if (ringing.isEmpty()) ringer.stop();
        stops++;
        try { persist(); }
        catch (IOException error) { persistenceFailures++; throw error; }
        return true;
    }

    /** Snoozes one ringing alarm, or every ringing alarm when id is null/empty. */
    public synchronized boolean snooze(String id, Integer minutes) throws IOException {
        if (!clock.wallTrusted()) reject("alarm_clock_untrusted");
        LinkedHashSet<String> targets = new LinkedHashSet<>();
        if (id == null || id.isEmpty()) targets.addAll(ringing);
        else if (ringing.contains(checked(id, 128, "alarm_id_invalid"))) targets.add(id);
        if (targets.isEmpty()) reject("alarm_not_ringing");
        long now = clock.wallMillis();
        for (String target : targets) {
            AlarmValue value = alarms.get(target);
            int delay = minutes == null ? value.snoozeMinutes : minutes;
            if (delay < 1 || delay > 60) reject("alarm_snooze_invalid");
        }
        String before = encodeState();
        for (String target : targets) {
            AlarmValue value = alarms.get(target);
            int delay = minutes == null ? value.snoozeMinutes : minutes;
            value.snoozeWallMillis = saturatingAdd(now, delay * 60_000L);
            value.revision = ++version; ringing.remove(target); snoozes++;
        }
        if (ringing.isEmpty()) ringer.stop();
        commitOrRollback(before);
        return true;
    }

    public synchronized void tick() {
        if (!clock.wallTrusted()) {
            if (!clockPending) { clockPending = true; clockWaits++; }
            return;
        }
        long now = clock.wallMillis();
        String zone = safeZone(clock.timeZoneId());
        boolean changed = false;
        if (clockPending || !zone.equals(scheduledZone)) {
            clockPending = false; scheduledZone = zone;
            for (AlarmValue value : alarms.values()) {
                if (value.enabled) {
                    value.nextWallMillis = nextOccurrence(value, now, true);
                    if (value.nextWallMillis == 0 && !value.date.isEmpty()) {
                        value.enabled = false; missed++; value.revision = ++version;
                    }
                }
            }
            changed = true;
        }
        for (AlarmValue value : alarms.values()) {
            long due = value.snoozeWallMillis > 0 ? value.snoozeWallMillis : value.nextWallMillis;
            if (due <= 0 || now < due || ringing.contains(value.id)) continue;
            boolean fire = now - due <= LATE_GRACE_MILLIS && due != value.lastOccurrenceWallMillis;
            if (fire) {
                value.lastOccurrenceWallMillis = due;
                if (policy.allowed()) { ringing.add(value.id); fires++; }
                else { suppressed++; policy.suppressed(); }
            } else missed++;
            if (value.snoozeWallMillis > 0) value.snoozeWallMillis = 0;
            else if (value.date.isEmpty()) value.nextWallMillis = nextOccurrence(value,
                    fire ? due + 1000 : now, false);
            else { value.enabled = false; value.nextWallMillis = 0; }
            value.revision = ++version; changed = true;
        }
        if (changed) try { persist(); } catch (IOException error) { persistenceFailures++; }
        ensureRinger();
    }

    public synchronized JSONObject snapshot() throws JSONException {
        JSONArray values = new JSONArray();
        for (AlarmValue value : alarms.values()) values.put(new JSONObject()
                .put("id", value.id).put("name", value.name).put("date", value.date)
                .put("hour", value.minuteOfDay / 60).put("minute", value.minuteOfDay % 60)
                .put("weekdays", value.weekdays).put("enabled", value.enabled)
                .put("snooze_minutes", value.snoozeMinutes)
                .put("next_wall_ms", value.nextWallMillis > 0 ? value.nextWallMillis : JSONObject.NULL)
                .put("snooze_wall_ms", value.snoozeWallMillis > 0 ? value.snoozeWallMillis : JSONObject.NULL)
                .put("ringing", ringing.contains(value.id)).put("revision", value.revision));
        return new JSONObject().put("schema", SCHEMA).put("version", version)
                .put("alarm_count", alarms.size()).put("ringing_count", ringing.size())
                .put("ringer_active", ringer.active()).put("ringer_failure",
                        ringer.failure() == null ? JSONObject.NULL : ringer.failure())
                .put("clock_pending", clockPending || !clock.wallTrusted()).put("time_zone", scheduledZone)
                .put("alarms", values).put("fires", fires).put("stops", stops).put("snoozes", snoozes)
                .put("missed", missed).put("invalid_requests", invalidRequests)
                .put("persistence_failures", persistenceFailures).put("clock_waits", clockWaits)
                .put("ringer_failures", ringerFailures).put("suppressed", suppressed);
    }

    public synchronized void close() { ringing.clear(); ringer.stop(); }
    public synchronized boolean ringing() { return !ringing.isEmpty(); }

    private void ensureRinger() {
        if (ringing.isEmpty() || ringer.active() || clock.wallMillis() < nextRingerAttempt) return;
        ringer.start();
        String failure = ringer.failure();
        if (failure != null && !failure.equals(lastRingerFailure)) {
            ringerFailures++; lastRingerFailure = failure;
        }
        nextRingerAttempt = saturatingAdd(clock.wallMillis(), RETRY_MILLIS);
    }

    private long nextOccurrence(AlarmValue value, long after, boolean strictlyFuture) {
        TimeZone zone = TimeZone.getTimeZone(scheduledZone);
        if (!value.date.isEmpty()) {
            int[] date = parseDate(value.date);
            Calendar candidate = Calendar.getInstance(zone); candidate.clear(); candidate.setLenient(false);
            candidate.set(date[0], date[1] - 1, date[2], value.minuteOfDay / 60, value.minuteOfDay % 60, 0);
            try {
                long result = candidate.getTimeInMillis();
                return result > after || (!strictlyFuture && result >= after) ? result : 0;
            } catch (IllegalArgumentException error) { return 0; }
        }
        Calendar day = Calendar.getInstance(zone); day.setTimeInMillis(after);
        for (int add = 0; add <= 7; add++) {
            Calendar date = (Calendar) day.clone(); date.add(Calendar.DATE, add);
            Calendar candidate = Calendar.getInstance(zone); candidate.clear(); candidate.setLenient(false);
            candidate.set(date.get(Calendar.YEAR), date.get(Calendar.MONTH), date.get(Calendar.DAY_OF_MONTH),
                    value.minuteOfDay / 60, value.minuteOfDay % 60, 0);
            candidate.set(Calendar.MILLISECOND, 0);
            try {
                long result = candidate.getTimeInMillis();
                int bit = weekdayBit(candidate.get(Calendar.DAY_OF_WEEK));
                if ((value.weekdays & bit) != 0 && (result > after || (!strictlyFuture && result >= after))) return result;
            } catch (IllegalArgumentException ignored) { }
        }
        return 0;
    }

    private String encodeState() throws IOException {
        try {
            JSONObject root = new JSONObject().put("schema", SCHEMA).put("version", version)
                    .put("time_zone", scheduledZone).put("fires", fires).put("stops", stops)
                    .put("snoozes", snoozes).put("missed", missed).put("suppressed", suppressed);
            JSONArray values = new JSONArray();
            for (AlarmValue value : alarms.values()) values.put(new JSONObject()
                    .put("id", value.id).put("name", value.name).put("date", value.date)
                    .put("minute_of_day", value.minuteOfDay).put("weekdays", value.weekdays)
                    .put("snooze_minutes", value.snoozeMinutes).put("enabled", value.enabled)
                    .put("next_wall_ms", value.nextWallMillis).put("snooze_wall_ms", value.snoozeWallMillis)
                    .put("last_occurrence_wall_ms", value.lastOccurrenceWallMillis).put("revision", value.revision));
            root.put("alarms", values).put("ringing", new JSONArray(ringing));
            return root.toString();
        } catch (JSONException error) { throw new IOException("alarm_persistence_encoding_failed", error); }
    }

    private void persist() throws IOException { store.save(encodeState()); }

    private void commitOrRollback(String before) throws IOException {
        try { persist(); }
        catch (IOException error) {
            restore(before); persistenceFailures++;
            nextRingerAttempt = 0;
            if (ringing.isEmpty()) ringer.stop(); else ensureRinger();
            throw error;
        }
    }

    private void restore(String encoded) {
        alarms.clear(); ringing.clear(); version = 0;
        fires = stops = snoozes = missed = suppressed = 0;
        if (encoded == null || encoded.isEmpty()) return;
        try {
            JSONObject root = new JSONObject(encoded);
            if (root.getInt("schema") != SCHEMA) throw new JSONException("schema");
            version = root.optLong("version", 0); scheduledZone = safeZone(root.optString("time_zone", scheduledZone));
            fires = root.optLong("fires"); stops = root.optLong("stops"); snoozes = root.optLong("snoozes");
            missed = root.optLong("missed"); suppressed = Math.max(0, root.optLong("suppressed"));
            JSONArray values = root.getJSONArray("alarms");
            if (values.length() > MAX_ALARMS) throw new JSONException("capacity");
            for (int i = 0; i < values.length(); i++) {
                JSONObject item = values.getJSONObject(i);
                AlarmValue value = new AlarmValue(checked(item.getString("id"), 128, "id"));
                value.name = checked(item.optString("name", ""), 256, "name"); value.date = item.optString("date", "");
                if (!value.date.isEmpty()) parseDate(value.date);
                value.minuteOfDay = item.getInt("minute_of_day"); value.weekdays = item.getInt("weekdays");
                value.snoozeMinutes = item.getInt("snooze_minutes"); value.enabled = item.getBoolean("enabled");
                if (value.minuteOfDay < 0 || value.minuteOfDay >= 1440 || value.weekdays < 0 || value.weekdays > 127
                        || value.snoozeMinutes < 1 || value.snoozeMinutes > 60
                        || (!value.date.isEmpty() && value.weekdays != 0) || (value.date.isEmpty() && value.weekdays == 0))
                    throw new JSONException("schedule");
                value.nextWallMillis = item.optLong("next_wall_ms"); value.snoozeWallMillis = item.optLong("snooze_wall_ms");
                value.lastOccurrenceWallMillis = item.optLong("last_occurrence_wall_ms"); value.revision = item.optLong("revision");
                alarms.put(value.id, value);
            }
            JSONArray active = root.optJSONArray("ringing");
            if (active != null) for (int i = 0; i < active.length(); i++) {
                String id = checked(active.getString(i), 128, "ringing"); if (alarms.containsKey(id)) ringing.add(id);
            }
            if (!clock.wallTrusted()) { clockPending = true; clockWaits++; }
        } catch (Exception error) {
            alarms.clear(); ringing.clear(); version = 0; invalidRequests++;
        }
    }

    private void checkVersion(long expected) throws IOException {
        if (expected >= 0 && expected != version) reject("alarm_version_conflict");
    }
    private void reject(String reason) throws IOException { invalidRequests++; throw new IOException(reason); }
    private static String checked(String value, int max, String reason) throws IOException {
        if (value == null || value.length() > max) throw new IOException(reason);
        for (int i = 0; i < value.length(); i++) if (Character.isISOControl(value.charAt(i))) throw new IOException(reason);
        if (max == 128 && value.isEmpty()) throw new IOException(reason);
        return value;
    }
    private static int[] parseDate(String value) {
        if (!value.matches("\\d{4}-\\d{2}-\\d{2}")) throw new IllegalArgumentException("date");
        int year = Integer.parseInt(value.substring(0, 4)), month = Integer.parseInt(value.substring(5, 7)), day = Integer.parseInt(value.substring(8, 10));
        Calendar check = Calendar.getInstance(TimeZone.getTimeZone("UTC")); check.clear(); check.setLenient(false);
        check.set(year, month - 1, day); check.getTimeInMillis(); return new int[]{year, month, day};
    }
    private static int weekdayBit(int calendarDay) {
        return 1 << ((calendarDay + 5) % 7); // Monday=bit0 ... Sunday=bit6.
    }
    private static String safeZone(String value) {
        if (value == null || value.isEmpty()) return "UTC";
        TimeZone zone = TimeZone.getTimeZone(value);
        return "GMT".equals(zone.getID()) && !value.startsWith("GMT") ? "UTC" : zone.getID();
    }
    private static long saturatingAdd(long a, long b) {
        return b > 0 && a > Long.MAX_VALUE - b ? Long.MAX_VALUE : a + b;
    }
}
