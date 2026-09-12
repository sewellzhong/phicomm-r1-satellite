package dev.sewellzhong.r1probe.esphome;

import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.io.IOException;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Persistent HA timer mirror. Countdown ownership stays local after an authenticated event. */
public final class NativeTimerController {
    public interface Store {
        String load();
        void save(String value) throws IOException;
    }
    public interface Clock {
        long elapsedMillis();
        long wallMillis();
        boolean wallTrusted();
    }
    public interface Alarm {
        void start();
        void stop();
        boolean active();
        String failure();
    }
    private static final int SCHEMA = 1;
    private static final int MAX_TIMERS = 32;
    private static final int MAX_TOMBSTONES = 64;
    private static final long RETRY_MILLIS = 5000;

    private static final class Timer {
        final String id;
        String name;
        long totalSeconds;
        long remainingAtSaveMillis;
        long savedWallMillis;
        long deadlineElapsedMillis;
        boolean waitingForClock;
        boolean running;
        Timer(String id) { this.id = id; }
    }

    private final Store store;
    private final Clock clock;
    private final Alarm alarm;
    private final LinkedHashMap<String, Timer> active = new LinkedHashMap<>();
    private final LinkedHashSet<String> ringing = new LinkedHashSet<>();
    private final LinkedHashSet<String> tombstones = new LinkedHashSet<>();
    private long events, started, updated, cancelled, finished, localFinished, localStops;
    private long invalidEvents, persistenceFailures, clockWaits, alarmFailures;
    private long nextAlarmAttempt;
    private String lastAlarmFailure;

    public NativeTimerController(Store store, Clock clock, Alarm alarm) {
        if (store == null || clock == null || alarm == null)
            throw new IllegalArgumentException("timer_dependencies_required");
        this.store = store; this.clock = clock; this.alarm = alarm;
        restore(store.load());
    }

    public synchronized boolean message(int type, byte[] payload) throws IOException {
        if (type != MessageIds.VoiceAssistantTimerEventResponse) return false;
        events++;
        EsphomeApi.VoiceAssistantTimerEventResponse event;
        try { event = EsphomeApi.VoiceAssistantTimerEventResponse.parseFrom(payload); }
        catch (IOException | RuntimeException error) { invalidEvents++; throw new IOException("timer_event_invalid"); }
        String id = checkedId(event.getTimerId(), "timer_id_invalid");
        String name = checked(event.getName(), 256, "timer_name_invalid");
        switch (event.getEventType()) {
            case VOICE_ASSISTANT_TIMER_STARTED:
                started++;
                upsert(id, name, event.getTotalSeconds(), event.getSecondsLeft(), event.getIsActive());
                break;
            case VOICE_ASSISTANT_TIMER_UPDATED:
                updated++;
                upsert(id, name, event.getTotalSeconds(), event.getSecondsLeft(), event.getIsActive());
                break;
            case VOICE_ASSISTANT_TIMER_CANCELLED:
                cancelled++;
                remove(id, true);
                break;
            case VOICE_ASSISTANT_TIMER_FINISHED:
                finished++;
                active.remove(id);
                if (!tombstones.contains(id)) ringing.add(id);
                persist();
                ensureAlarm();
                break;
            default:
                invalidEvents++;
                throw new IOException("timer_event_type_invalid");
        }
        return true;
    }

    public synchronized void tick() {
        long now = clock.elapsedMillis();
        boolean changed = false;
        Iterator<Map.Entry<String, Timer>> iterator = active.entrySet().iterator();
        while (iterator.hasNext()) {
            Timer timer = iterator.next().getValue();
            if (!timer.running) continue;
            if (timer.waitingForClock) {
                if (!clock.wallTrusted()) continue;
                timer.waitingForClock = false;
                timer.savedWallMillis = clock.wallMillis();
                timer.deadlineElapsedMillis = saturatingAdd(now, timer.remainingAtSaveMillis);
                changed = true;
            }
            if (now < timer.deadlineElapsedMillis) continue;
            iterator.remove();
            ringing.add(timer.id);
            localFinished++;
            changed = true;
        }
        if (changed) {
            try { persist(); } catch (IOException error) { persistenceFailures++; }
        }
        ensureAlarm();
    }

    /** Stops every currently ringing timer; active countdowns are not cancelled. */
    public synchronized boolean stopRinging() {
        if (ringing.isEmpty() && !alarm.active()) return false;
        for (String id : ringing) addTombstone(id);
        ringing.clear();
        alarm.stop();
        localStops++;
        try { persist(); } catch (IOException error) { persistenceFailures++; }
        return true;
    }

    public synchronized void close() { alarm.stop(); }
    public synchronized boolean ringing() { return !ringing.isEmpty(); }
    public synchronized int activeCount() { return active.size(); }
    public synchronized int ringingCount() { return ringing.size(); }

    public synchronized JSONObject snapshot() throws JSONException {
        long now = clock.elapsedMillis();
        JSONArray values = new JSONArray();
        for (Timer timer : active.values()) {
            long left = (!timer.running || timer.waitingForClock) ? timer.remainingAtSaveMillis
                    : Math.max(0, timer.deadlineElapsedMillis - now);
            values.put(new JSONObject().put("id", timer.id).put("name", timer.name)
                    .put("total_seconds", timer.totalSeconds)
                    .put("seconds_left", (left + 999) / 1000)
                    .put("is_active", timer.running)
                    .put("clock_pending", timer.waitingForClock));
        }
        return new JSONObject().put("active_count", active.size()).put("ringing_count", ringing.size())
                .put("alarm_active", alarm.active()).put("alarm_failure",
                        alarm.failure() == null ? JSONObject.NULL : alarm.failure())
                .put("timers", values).put("events", events).put("started", started)
                .put("updated", updated).put("cancelled", cancelled).put("finished", finished)
                .put("local_finished", localFinished).put("local_stops", localStops)
                .put("invalid_events", invalidEvents).put("persistence_failures", persistenceFailures)
                .put("clock_waits", clockWaits).put("alarm_failures", alarmFailures);
    }

    private void upsert(String id, String name, long totalSeconds, long secondsLeft,
            boolean isActive) throws IOException {
        if (secondsLeft == 0) { remove(id, false); return; }
        if (totalSeconds == 0 || secondsLeft > totalSeconds) {
            invalidEvents++;
            throw new IOException("timer_duration_invalid");
        }
        Timer timer = active.get(id);
        if (timer == null && active.size() >= MAX_TIMERS) {
            invalidEvents++;
            throw new IOException("timer_capacity_exceeded");
        }
        if (timer == null) { timer = new Timer(id); active.put(id, timer); }
        timer.name = name;
        timer.totalSeconds = totalSeconds;
        timer.remainingAtSaveMillis = secondsLeft * 1000L;
        timer.savedWallMillis = clock.wallMillis();
        timer.running = isActive;
        timer.deadlineElapsedMillis = isActive
                ? saturatingAdd(clock.elapsedMillis(), timer.remainingAtSaveMillis) : Long.MAX_VALUE;
        timer.waitingForClock = false;
        ringing.remove(id);
        tombstones.remove(id);
        if (ringing.isEmpty()) alarm.stop();
        persist();
    }

    private void remove(String id, boolean remember) throws IOException {
        active.remove(id);
        boolean wasRinging = ringing.remove(id);
        if (remember || wasRinging) addTombstone(id);
        if (ringing.isEmpty()) alarm.stop();
        persist();
    }

    private void ensureAlarm() {
        if (ringing.isEmpty() || alarm.active() || clock.elapsedMillis() < nextAlarmAttempt) return;
        alarm.start();
        String failure = alarm.failure();
        if (failure != null && !failure.equals(lastAlarmFailure)) {
            alarmFailures++;
            lastAlarmFailure = failure;
        }
        nextAlarmAttempt = clock.elapsedMillis() + RETRY_MILLIS;
    }

    private void restore(String encoded) {
        if (encoded == null || encoded.isEmpty()) return;
        try {
            JSONObject root = new JSONObject(encoded);
            if (root.getInt("schema") != SCHEMA) throw new JSONException("schema");
            JSONArray timers = root.optJSONArray("active");
            long nowElapsed = clock.elapsedMillis(), nowWall = clock.wallMillis();
            if (timers != null) for (int i = 0; i < timers.length() && active.size() < MAX_TIMERS; i++) {
                JSONObject value = timers.getJSONObject(i);
                Timer timer = new Timer(checkedId(value.getString("id"), "id"));
                timer.name = checked(value.optString("name", ""), 256, "name");
                timer.totalSeconds = value.getLong("total_seconds");
                timer.remainingAtSaveMillis = value.getLong("remaining_ms");
                timer.savedWallMillis = value.getLong("saved_wall_ms");
                timer.running = value.optBoolean("is_active", true);
                if (timer.totalSeconds <= 0 || timer.remainingAtSaveMillis <= 0) throw new JSONException("duration");
                if (!timer.running) {
                    timer.deadlineElapsedMillis = Long.MAX_VALUE;
                } else if (clock.wallTrusted() && timer.savedWallMillis > 0 && nowWall >= timer.savedWallMillis) {
                    timer.remainingAtSaveMillis = Math.max(0,
                            timer.remainingAtSaveMillis - (nowWall - timer.savedWallMillis));
                    timer.deadlineElapsedMillis = saturatingAdd(nowElapsed, timer.remainingAtSaveMillis);
                } else {
                    timer.waitingForClock = true;
                    timer.deadlineElapsedMillis = Long.MAX_VALUE;
                    clockWaits++;
                }
                if (timer.remainingAtSaveMillis == 0) ringing.add(timer.id);
                else active.put(timer.id, timer);
            }
            JSONArray ringingValues = root.optJSONArray("ringing");
            if (ringingValues != null) for (int i = 0; i < ringingValues.length(); i++)
                ringing.add(checked(ringingValues.getString(i), 128, "ringing"));
            JSONArray completed = root.optJSONArray("tombstones");
            if (completed != null) for (int i = 0; i < completed.length(); i++)
                addTombstone(checked(completed.getString(i), 128, "tombstone"));
        } catch (Exception error) {
            active.clear(); ringing.clear(); tombstones.clear(); invalidEvents++;
        }
    }

    private void persist() throws IOException {
        try {
            long nowElapsed = clock.elapsedMillis();
            JSONObject root = new JSONObject().put("schema", SCHEMA);
            JSONArray timers = new JSONArray();
            for (Timer timer : active.values()) {
                long left = (!timer.running || timer.waitingForClock) ? timer.remainingAtSaveMillis
                        : Math.max(0, timer.deadlineElapsedMillis - nowElapsed);
                timers.put(new JSONObject().put("id", timer.id).put("name", timer.name)
                        .put("total_seconds", timer.totalSeconds).put("remaining_ms", left)
                        .put("saved_wall_ms", clock.wallMillis()).put("is_active", timer.running));
            }
            JSONArray ringingValues = new JSONArray();
            for (String id : ringing) ringingValues.put(id);
            JSONArray completed = new JSONArray();
            for (String id : tombstones) completed.put(id);
            store.save(root.put("active", timers).put("ringing", ringingValues)
                    .put("tombstones", completed).toString());
        } catch (JSONException error) { throw new IOException("timer_persistence_encode_failed", error); }
    }

    private void addTombstone(String id) {
        tombstones.remove(id);
        tombstones.add(id);
        while (tombstones.size() > MAX_TOMBSTONES)
            tombstones.remove(tombstones.iterator().next());
    }

    private static String checked(String value, int limit, String failure) throws IOException {
        if (value == null || value.length() > limit)
            throw new IOException(failure);
        for (int i = 0; i < value.length(); i++) if (Character.isISOControl(value.charAt(i)))
            throw new IOException(failure);
        return value;
    }

    private static String checkedId(String value, String failure) throws IOException {
        String result = checked(value, 128, failure);
        if (result.isEmpty()) throw new IOException(failure);
        return result;
    }

    private static long saturatingAdd(long first, long second) {
        return second > Long.MAX_VALUE - first ? Long.MAX_VALUE : first + second;
    }
}
