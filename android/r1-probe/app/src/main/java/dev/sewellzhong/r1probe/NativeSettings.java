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
    synchronized void setting(String key, float value) { commit(prefs.edit().putFloat(key, value)); }
    synchronized int adjustVolume(int delta) {
        int target = Math.max(0, Math.min(100, volumePercent() + delta));
        if (target != volumePercent()) commit(prefs.edit().putFloat("volume", target));
        return target;
    }
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
    boolean hotspotProbePending() { return prefs.getBoolean("hotspot_probe_pending", false); }
    boolean hotspotProbePreviousWifi() { return prefs.getBoolean("hotspot_probe_previous_wifi", true); }
    void hotspotProbe(boolean pending, boolean previousWifi) {
        commit(prefs.edit().putBoolean("hotspot_probe_pending", pending)
                .putBoolean("hotspot_probe_previous_wifi", previousWifi));
    }
    boolean provisioningPending() { return prefs.getBoolean("original_provisioning_pending", false); }
    void provisioning(boolean pending) {
        commit(prefs.edit().putBoolean("original_provisioning_pending", pending));
    }
    String provisioningStage() { return prefs.getString("original_provisioning_stage", "idle"); }
    int provisioningNetworkId() { return prefs.getInt("original_provisioning_network_id", -1); }
    String provisioningResult() { return prefs.getString("original_provisioning_result", "none"); }
    void provisioningWindow() {
        commit(prefs.edit().putBoolean("original_provisioning_pending", true)
                .putString("original_provisioning_stage", "window")
                .remove("original_provisioning_network_id")
                .putString("original_provisioning_result", "waiting_for_phone"));
    }
    void provisioningApplying(int networkId) {
        commit(prefs.edit().putBoolean("original_provisioning_pending", true)
                .putString("original_provisioning_stage", "applying")
                .putInt("original_provisioning_network_id", networkId)
                .putString("original_provisioning_result", "applying"));
    }
    void provisioningHandoff() {
        commit(prefs.edit().putBoolean("original_provisioning_pending", true)
                .putString("original_provisioning_stage", "handoff")
                .remove("original_provisioning_network_id")
                .putString("original_provisioning_result", "switching_to_station"));
    }
    void provisioningRecovering() {
        commit(prefs.edit().putBoolean("original_provisioning_pending", true)
                .putString("original_provisioning_stage", "recovering")
                .remove("original_provisioning_network_id")
                .putString("original_provisioning_result", "recovering"));
    }
    void provisioningFinished(String result) {
        commit(prefs.edit().putBoolean("original_provisioning_pending", false)
                .putString("original_provisioning_stage", "idle")
                .remove("original_provisioning_network_id")
                .putString("original_provisioning_result", result));
    }
    void provisioningResult(String result) {
        commit(prefs.edit().putString("original_provisioning_result", result));
    }
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
