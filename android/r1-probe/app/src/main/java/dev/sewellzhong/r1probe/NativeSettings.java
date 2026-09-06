package dev.sewellzhong.r1probe;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;
import java.security.SecureRandom;
import java.util.Locale;
import java.util.UUID;

/** Credentials live only in MODE_PRIVATE storage; Android backup is disabled. */
final class NativeSettings {
    private final SharedPreferences prefs;
    NativeSettings(Context context) {
        prefs = context.getSharedPreferences("native-satellite", Context.MODE_PRIVATE);
        synchronized (NativeSettings.class) {
            if (!prefs.getBoolean("split_wait_v1", false)) {
                float old = prefs.getFloat("wait_seconds", 20);
                commit(prefs.edit().putFloat("wait_seconds", old == 20 ? 10 : old)
                    .putFloat("followup_wait_seconds", 15).putBoolean("split_wait_v1", true));
            }
        }
    }
    boolean configured() { return prefs.contains("psk") && prefs.contains("id"); }
    boolean enabled() { return configured() && prefs.getBoolean("enabled", false); }
    boolean listening() { return prefs.getBoolean("listening", false); }
    boolean audioBlocked() { return prefs.getBoolean("audio_blocked", false); }
    String audioBlockReason() { return prefs.getString("audio_block_reason", "audio_backend_stalled"); }
    void blockAudio() { blockAudio("audio_backend_stalled"); }
    void blockAudio(String reason) {
        commit(prefs.edit().putBoolean("audio_blocked", true).putString("audio_block_reason", reason));
    }
    float waitSeconds() { return prefs.getFloat("wait_seconds", 10); }
    float followupWaitSeconds() { return prefs.getFloat("followup_wait_seconds", 15); }
    float quietSeconds() { return prefs.getFloat("quiet_seconds", 1.8f); }
    float commandSeconds() { return prefs.getFloat("command_seconds", 30); }
    int volumePercent() { return Math.round(prefs.getFloat("volume", 0)); }
    synchronized void initializeVolume(int percent) {
        if (!prefs.contains("volume")) setting("volume", Math.max(0, Math.min(100, percent)));
    }
    float speechSpeed() { return prefs.getFloat("speech_speed", .85f); }
    void setting(String key, float value) { commit(prefs.edit().putFloat(key, value)); }
    dev.sewellzhong.r1probe.assist.CommandWindow window() { return window(false); }
    dev.sewellzhong.r1probe.assist.CommandWindow window(boolean followup) {
        return new dev.sewellzhong.r1probe.assist.CommandWindow(followup ? followupWaitSeconds() : waitSeconds(), quietSeconds(), commandSeconds(), 6);
    }
    boolean wakeEnabled() { return prefs.getBoolean("wake_enabled", true); }
    String name() { return prefs.getString("name", ""); }
    String id() { return prefs.getString("id", ""); }
    String mac() { return prefs.getString("mac", ""); }
    String encodedKey() { return prefs.getString("psk", ""); }
    byte[] key() { return Base64.decode(encodedKey(), Base64.NO_WRAP); }
    synchronized void initialize(String name) {
        if (configured()) {
            if (!name().equals(name)) throw new IllegalArgumentException("identity_already_initialized");
            return;
        }
        if (!name.matches("[a-z][a-z0-9-]{0,30}")) throw new IllegalArgumentException("invalid_name");
        byte[] address = new byte[6]; new SecureRandom().nextBytes(address);
        address[0] = (byte) ((address[0] & 0xfc) | 2); // Private unicast protocol ID, not hardware MAC.
        StringBuilder mac = new StringBuilder();
        for (byte value : address) {
            if (mac.length() > 0) mac.append(':');
            mac.append(String.format(Locale.ROOT, "%02X", value & 255));
        }
        commit(prefs.edit().putString("id", UUID.randomUUID().toString()).putString("name", name)
                .putString("mac", mac.toString()).putString("psk", freshKey())
                .putBoolean("enabled", false).putBoolean("listening", false));
    }
    void enable(boolean enabled, boolean listening) {
        if (enabled && !configured()) throw new IllegalStateException("initialization_required");
        SharedPreferences.Editor change = prefs.edit().putBoolean("enabled", enabled).putBoolean("listening", enabled && listening);
        if (enabled && listening) change.putBoolean("audio_blocked", false).remove("audio_block_reason"); // Explicit administrator retry only.
        commit(change);
    }
    void wakeEnabled(boolean enabled) { commit(prefs.edit().putBoolean("wake_enabled", enabled)); }
    void rotate() {
        if (!configured() || enabled()) throw new IllegalStateException("stop_before_rotation");
        commit(prefs.edit().putString("psk", freshKey()));
    }
    private static String freshKey() {
        byte[] key = new byte[32]; new SecureRandom().nextBytes(key);
        try { return Base64.encodeToString(key, Base64.NO_WRAP); }
        finally { java.util.Arrays.fill(key, (byte) 0); }
    }
    private static void commit(SharedPreferences.Editor editor) {
        if (!editor.commit()) throw new IllegalStateException("configuration_write_failed");
    }
}
