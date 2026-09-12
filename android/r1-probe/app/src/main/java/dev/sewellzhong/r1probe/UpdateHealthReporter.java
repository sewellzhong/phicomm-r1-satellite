package dev.sewellzhong.r1probe;

import android.content.Context;
import android.content.SharedPreferences;
import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;

/** Replacement-bound health gate. It never sends a partial health frame. */
final class UpdateHealthReporter {
    interface PendingStore {
        boolean pending(String bootIdentity);
        void clear();
    }
    interface Probe { UpdateSupervisorClient.Health inspect(); }

    private final PendingStore store;
    private final Probe probe;
    private final UpdateSupervisorClient client;

    UpdateHealthReporter(PendingStore store, Probe probe, UpdateSupervisorClient client) {
        this.store = store;
        this.probe = probe;
        this.client = client;
    }

    /** Returns true only when another bounded retry is useful. */
    boolean attempt(String bootIdentity) {
        if (!store.pending(bootIdentity)) return false;
        UpdateSupervisorClient.Health health = probe.inspect();
        if (health == null || !health.complete()) return true;
        try {
            UpdateSupervisorClient.Response response = client.reportHealth(health);
            if (response.success || response.phase == UpdateSupervisorClient.PHASE_IDLE
                    || response.phase == UpdateSupervisorClient.PHASE_ROLLING_BACK
                    || response.phase == UpdateSupervisorClient.PHASE_FAILED) {
                store.clear();
                return false;
            }
            return true;
        } catch (IOException | RuntimeException unavailable) {
            return true;
        }
    }

    static final class PreferencesStore implements PendingStore {
        private static final long MAX_REPORT_WINDOW_MILLIS = 620000L;
        private final SharedPreferences preferences;
        PreferencesStore(Context context) {
            preferences = context.getSharedPreferences("r1-update-health", Context.MODE_PRIVATE);
        }
        void markReplacement(String bootIdentity) {
            if (!preferences.edit().putBoolean("pending", true)
                    .putString("boot_identity", bootIdentity)
                    .putLong("marked_elapsed", android.os.SystemClock.elapsedRealtime()).commit())
                throw new IllegalStateException("update_health_marker_failed");
        }
        @Override public boolean pending(String bootIdentity) {
            if (!preferences.getBoolean("pending", false)) return false;
            long marked = preferences.getLong("marked_elapsed", -1L);
            long now = android.os.SystemClock.elapsedRealtime();
            if (!bootIdentity.equals(preferences.getString("boot_identity", ""))
                    || marked < 0L || now < marked || now - marked > MAX_REPORT_WINDOW_MILLIS) {
                clear();
                return false;
            }
            return true;
        }
        @Override public void clear() {
            if (!preferences.edit().clear().commit())
                throw new IllegalStateException("update_health_marker_clear_failed");
        }
    }

    static String bootIdentity() {
        try (BufferedReader reader = new BufferedReader(new FileReader(
                "/proc/sys/kernel/random/boot_id"))) {
            String value = reader.readLine();
            if (value != null && value.matches("[A-Fa-f0-9-]{36}"))
                return value.toLowerCase(java.util.Locale.ROOT);
        } catch (IOException ignored) { }
        try (BufferedReader reader = new BufferedReader(new FileReader("/proc/stat"))) {
            String line;
            while ((line = reader.readLine()) != null)
                if (line.matches("btime [0-9]+")) return line.replace(' ', ':');
        } catch (IOException ignored) { }
        throw new IllegalStateException("update_boot_identity_unavailable");
    }
}
