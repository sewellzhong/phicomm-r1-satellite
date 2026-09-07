package dev.sewellzhong.r1probe;

import android.annotation.SuppressLint;
import android.content.Context;
import android.net.wifi.WifiConfiguration;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.net.wifi.SupplicantState;
import android.net.wifi.ScanResult;
import android.os.Handler;
import android.os.Looper;
import android.os.Parcelable;
import android.os.SystemClock;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Pattern;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONArray;
import org.json.JSONObject;

/** Firmware-3448 bridge to the existing system provisioning service. */
final class R1MessageDispatchBridge {
    private static final int TYPE_WIFI_CONFIG = 262144;
    private static final int TURN_ON = 1;
    private static final int TURN_OFF = 2;

    private final Object manager;
    private final Method sendMessage;
    private final WifiManager wifi;
    private final NativeSettings settings;
    private final ProvisioningHandoffStore handoff;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ProvisioningWebServer web;
    private final Runnable expireWindow;
    private final Runnable stopOriginal;
    private volatile String lastResult;
    private volatile long openedAtMs;
    private volatile byte[] scanCache = "[]".getBytes(StandardCharsets.UTF_8);
    private static final AtomicBoolean WIFI_TRANSITION = new AtomicBoolean();

    @SuppressLint("WrongConstant")
    R1MessageDispatchBridge(Context context) throws Exception {
        manager = context.getSystemService("msgcenter");
        if (manager == null) throw new IllegalStateException("message_dispatch_unavailable");
        sendMessage = manager.getClass().getMethod(
                "sendMessage", int.class, int.class, int.class, Parcelable.class);
        wifi = (WifiManager) context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        settings = new NativeSettings(context);
        handoff = new ProvisioningHandoffStore(context);
        lastResult = settings.provisioningResult();
        web = new ProvisioningWebServer(context, this::scanWifi, this::configureWifi);
        expireWindow = this::recoverWifi;
        stopOriginal = () -> {
            try { send(TURN_OFF); } catch (Exception ignored) { }
            beginWifiRecovery("closed");
        };
        if (settings.provisioningPending()) {
            int networkId = settings.provisioningNetworkId();
            if (shouldResumeHandoff(settings.provisioningStage(), handoff.present())) resumeWifiHandoff();
            else if (shouldResumeTarget(settings.provisioningStage(), networkId)) resumeWifiTarget(networkId);
            else recoverWifi();
        }
    }

    void openOriginalProvisioning() throws Exception {
        if (WIFI_TRANSITION.get()) throw new IllegalStateException("wifi_recovery_in_progress");
        main.removeCallbacks(expireWindow);
        main.removeCallbacks(stopOriginal);
        web.close();
        clearHandoff();
        // Capture a per-window snapshot before NetControl changes wlan0 to AP mode;
        // firmware 3448 clears scan results while SoftAP is active.
        scanCache = scanWifi();
        web.start();
        settings.provisioningWindow();
        try { send(TURN_ON); }
        catch (Exception error) { recoverWifi(); throw error; }
        result("waiting_for_phone");
        openedAtMs = SystemClock.elapsedRealtime();
        main.postDelayed(expireWindow, 300000L);
    }

    void closeOriginalProvisioning() throws Exception {
        if (WIFI_TRANSITION.get()) throw new IllegalStateException("wifi_transition_in_progress");
        main.removeCallbacks(expireWindow);
        main.removeCallbacks(stopOriginal);
        web.close();
        scanCache = "[]".getBytes(StandardCharsets.UTF_8);
        // NetControl starts SoftAP asynchronously. Sending OFF immediately after ON
        // can be overtaken by the late AP enable and leave a timerless hotspot.
        long delay = Math.max(0L, 5000L - (SystemClock.elapsedRealtime() - openedAtMs));
        if (delay > 0L) main.postDelayed(stopOriginal, delay);
        else {
            try { send(TURN_OFF); } finally { beginWifiRecovery("closed"); }
        }
    }

    void serviceDestroyed() throws Exception {
        main.removeCallbacks(expireWindow);
        main.removeCallbacks(stopOriginal);
        web.close();
        // Network changes can recreate the Android service while the handoff worker
        // is still active. Let that worker finish and keep its encrypted restart state.
        if (!WIFI_TRANSITION.get()) closeOriginalProvisioning();
    }

    void recoverWifi() {
        main.removeCallbacks(expireWindow);
        main.removeCallbacks(stopOriginal);
        web.close();
        scanCache = "[]".getBytes(StandardCharsets.UTF_8);
        try { send(TURN_OFF); } catch (Exception ignored) { }
        beginWifiRecovery("recovered");
    }

    private void beginWifiRecovery(String successResult) {
        clearHandoff();
        settings.provisioningRecovering();
        lastResult = "recovering";
        if (!WIFI_TRANSITION.compareAndSet(false, true)) return;
        Thread worker = new Thread(() -> {
            try {
                disableSoftAp();
                for (int attempt = 0; attempt < 40; attempt++) {
                    if (!wifi.isWifiEnabled()) wifi.setWifiEnabled(true);
                    if (wifi.isWifiEnabled()) {
                        settings.provisioningFinished(successResult);
                        lastResult = successResult;
                        return;
                    }
                    SystemClock.sleep(500L);
                }
                result("recovery_failed");
            } finally { WIFI_TRANSITION.set(false); }
        }, "r1-wifi-recovery");
        worker.setDaemon(true);
        worker.start();
    }

    private void disableSoftAp() {
        try {
            Method method = WifiManager.class.getDeclaredMethod(
                    "setWifiApEnabled", WifiConfiguration.class, boolean.class);
            method.setAccessible(true);
            method.invoke(wifi, null, false);
        } catch (Exception ignored) { }
    }

    String lastResult() { return settings.provisioningResult(); }
    boolean pending() { return settings.provisioningPending(); }
    String stage() { return settings.provisioningStage(); }

    JSONObject probeHandoff() throws Exception {
        if (settings.provisioningPending() || WIFI_TRANSITION.get())
            throw new IllegalStateException("wifi_transition_in_progress");
        JSONObject expected = new JSONObject().put("ssid", "handoff-probe")
                .put("secure", "WPA").put("password", "synthetic-password");
        handoff.save(expected);
        try {
            JSONObject actual = handoff.load();
            if (!expected.toString().equals(actual.toString()))
                throw new IllegalStateException("handoff_roundtrip_failed");
            return new JSONObject().put("handoff_probe", true);
        } finally {
            handoff.clear();
        }
    }

    private byte[] scanWifi() throws Exception {
        if (wifi.startScan()) SystemClock.sleep(2200L);
        List<ScanResult> results = wifi.getScanResults();
        if (results == null || results.isEmpty()) return scanCache.clone();
        Map<String, ScanResult> strongest = new LinkedHashMap<>();
        if (results != null) for (ScanResult item : results) {
            if (item == null || item.SSID == null || item.SSID.length() == 0 || hasControl(item.SSID)) continue;
            ScanResult prior = strongest.get(item.SSID);
            if (prior == null || item.level > prior.level) strongest.put(item.SSID, item);
        }
        List<ScanResult> ordered = new java.util.ArrayList<>(strongest.values());
        Collections.sort(ordered, (left, right) -> Integer.compare(right.level, left.level));
        JSONArray array = new JSONArray();
        for (ScanResult item : ordered) {
            String secure = security(item.capabilities);
            if ("UNSUPPORTED".equals(secure)) continue;
            array.put(new JSONObject().put("ssid", item.SSID)
                    .put("level", WifiManager.calculateSignalLevel(item.level, 4)).put("secure", secure));
        }
        byte[] encoded = array.toString().getBytes(StandardCharsets.UTF_8);
        if (array.length() > 0) scanCache = encoded;
        return encoded.clone();
    }

    static String security(String capabilities) {
        String value = capabilities == null ? "" : capabilities.toUpperCase(java.util.Locale.US);
        if (value.contains("WEP")) return "WEP";
        if (value.contains("PSK")) return "WPA";
        if (value.contains("SAE") || value.contains("EAP")) return "UNSUPPORTED";
        return "INSECURE";
    }

    private void configureWifi(JSONObject request) throws Exception {
        String ssid = request.getString("ssid"), secure = request.optString("secure", "INSECURE");
        String password = request.optString("password", "");
        validate(ssid, secure, password);
        if (!WIFI_TRANSITION.compareAndSet(false, true))
            throw new IllegalStateException("wifi_transition_in_progress");
        try {
            handoff.save(request);
            settings.provisioningHandoff();
            lastResult = "switching_to_station";
            // Firmware 3448 rejects addNetwork while wlan0 is serving its SoftAP.
            // Stop the AP first, then persist the submitted configuration.
            send(TURN_OFF);
            web.close();
            scanCache = "[]".getBytes(StandardCharsets.UTF_8);
            SystemClock.sleep(2500L);
            enableStation();
            WifiConfiguration configuration = configuration(ssid, secure, password);
            int network = saveWifiConfiguration(configuration);
            settings.provisioningApplying(network);
            handoff.clear();
            connectWifi(network);
            settings.provisioningFinished("connected");
            lastResult = "connected";
            WIFI_TRANSITION.set(false);
        } catch (Exception error) {
            result("failed");
            clearHandoff();
            WIFI_TRANSITION.set(false);
            beginWifiRecovery("recovered_after_" + failureCode(error));
            throw error;
        }
    }

    private int saveWifiConfiguration(WifiConfiguration configuration) {
        List<WifiConfiguration> existing = wifi.getConfiguredNetworks();
        if (existing != null) for (WifiConfiguration item : existing)
            if (configuration.SSID.equals(item.SSID)) { configuration.networkId = item.networkId; break; }
        int network = configuration.networkId >= 0 ? wifi.updateNetwork(configuration) : wifi.addNetwork(configuration);
        if (network < 0 || !wifi.saveConfiguration()) throw new IllegalStateException("wifi_configuration_rejected");
        return network;
    }

    private void connectWifi(int network) {
        enableStation();
        for (int attempt = 0; attempt < 3; attempt++) {
            wifi.disconnect();
            SystemClock.sleep(500L);
            if (!wifi.enableNetwork(network, true) || !wifi.reconnect()) continue;
            for (int wait = 0; wait < 24; wait++) {
                WifiInfo info = wifi.getConnectionInfo();
                if (info != null && info.getNetworkId() == network
                        && info.getSupplicantState() == SupplicantState.COMPLETED) return;
                SystemClock.sleep(500L);
            }
        }
        throw new IllegalStateException("wifi_connect_timeout");
    }

    private void enableStation() {
        for (int wait = 0; wait < 20 && !wifi.isWifiEnabled(); wait++) {
            wifi.setWifiEnabled(true);
            SystemClock.sleep(500L);
        }
        if (!wifi.isWifiEnabled()) throw new IllegalStateException("wifi_enable_timeout");
    }

    private void resumeWifiTarget(int network) {
        if (!WIFI_TRANSITION.compareAndSet(false, true)) return;
        result("resuming_target");
        Thread worker = new Thread(() -> {
            boolean failed = false;
            String failure = "failure";
            try {
                clearHandoff();
                try { send(TURN_OFF); } catch (Exception ignored) { }
                disableSoftAp();
                connectWifi(network);
                settings.provisioningFinished("connected");
                lastResult = "connected";
            } catch (Exception error) {
                result("failed");
                failed = true;
                failure = failureCode(error);
            } finally {
                WIFI_TRANSITION.set(false);
            }
            if (failed) beginWifiRecovery("recovered_after_" + failure);
        }, "r1-wifi-target-resume");
        worker.setDaemon(true);
        worker.start();
    }

    private void resumeWifiHandoff() {
        if (!WIFI_TRANSITION.compareAndSet(false, true)) return;
        result("resuming_handoff");
        Thread worker = new Thread(() -> {
            boolean failed = false;
            String failure = "failure";
            try {
                JSONObject request = handoff.load();
                String ssid = request.getString("ssid");
                String secure = request.optString("secure", "INSECURE");
                String password = request.optString("password", "");
                validate(ssid, secure, password);
                try { send(TURN_OFF); } catch (Exception ignored) { }
                disableSoftAp();
                enableStation();
                int network = saveWifiConfiguration(configuration(ssid, secure, password));
                settings.provisioningApplying(network);
                handoff.clear();
                connectWifi(network);
                settings.provisioningFinished("connected");
                lastResult = "connected";
            } catch (Exception error) {
                result("failed");
                clearHandoff();
                failed = true;
                failure = failureCode(error);
            } finally {
                WIFI_TRANSITION.set(false);
            }
            if (failed) beginWifiRecovery("recovered_after_" + failure);
        }, "r1-wifi-handoff-resume");
        worker.setDaemon(true);
        worker.start();
    }

    static boolean shouldResumeTarget(String stage, int networkId) {
        return "applying".equals(stage) && networkId >= 0;
    }

    static boolean shouldResumeHandoff(String stage, boolean present) {
        return "handoff".equals(stage) && present;
    }

    static String failureCode(Exception error) {
        String message = error == null ? null : error.getMessage();
        if ("wifi_request_too_large".equals(message) || "handoff_key_unavailable".equals(message)
                || "handoff_write_failed".equals(message) || "handoff_missing".equals(message)
                || "handoff_clear_failed".equals(message) || "handoff_roundtrip_failed".equals(message)
                || "wifi_enable_timeout".equals(message)
                || "wifi_configuration_rejected".equals(message) || "wifi_connect_timeout".equals(message))
            return message;
        return "failure";
    }

    private void clearHandoff() {
        try { handoff.clear(); } catch (Exception ignored) { }
    }

    private void result(String value) {
        lastResult = value;
        settings.provisioningResult(value);
    }

    static void validate(String ssid, String secure, String password) {
        int bytes = ssid == null ? 0 : ssid.getBytes(StandardCharsets.UTF_8).length;
        if (bytes < 1 || bytes > 32 || hasControl(ssid)) throw new IllegalArgumentException("invalid_ssid");
        if (!("WPA".equals(secure) || "WEP".equals(secure) || "INSECURE".equals(secure)))
            throw new IllegalArgumentException("invalid_security");
        if ("WPA".equals(secure) && !((password.length() >= 8 && password.length() <= 63)
                || (password.length() == 64 && Pattern.matches("[0-9A-Fa-f]{64}", password))))
            throw new IllegalArgumentException("invalid_wpa_password");
        if ("WEP".equals(secure) && !(password.length() == 5 || password.length() == 13
                || ((password.length() == 10 || password.length() == 26) && Pattern.matches("[0-9A-Fa-f]+", password))))
            throw new IllegalArgumentException("invalid_wep_password");
    }

    private static boolean hasControl(String value) {
        for (int index = 0; index < value.length(); index++) if (Character.isISOControl(value.charAt(index))) return true;
        return false;
    }

    private static WifiConfiguration configuration(String ssid, String secure, String password) {
        WifiConfiguration result = new WifiConfiguration();
        result.SSID = quote(ssid);
        if ("WPA".equals(secure)) {
            result.allowedKeyManagement.set(WifiConfiguration.KeyMgmt.WPA_PSK);
            result.preSharedKey = password.length() == 64 && Pattern.matches("[0-9A-Fa-f]{64}", password) ? password : quote(password);
        } else if ("WEP".equals(secure)) {
            result.allowedKeyManagement.set(WifiConfiguration.KeyMgmt.NONE);
            result.allowedAuthAlgorithms.set(WifiConfiguration.AuthAlgorithm.OPEN);
            result.allowedAuthAlgorithms.set(WifiConfiguration.AuthAlgorithm.SHARED);
            result.wepKeys[0] = (password.length() == 10 || password.length() == 26) ? password : quote(password);
            result.wepTxKeyIndex = 0;
        } else result.allowedKeyManagement.set(WifiConfiguration.KeyMgmt.NONE);
        return result;
    }

    private static String quote(String value) { return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""; }

    private void send(int command) throws Exception {
        sendMessage.invoke(manager, TYPE_WIFI_CONFIG, command, 0, null);
    }
}
