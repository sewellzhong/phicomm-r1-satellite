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
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ProvisioningWebServer web;
    private final Runnable closeWeb;
    private final Runnable stopOriginal;
    private volatile String lastResult = "none";
    private volatile long openedAtMs;

    @SuppressLint("WrongConstant")
    R1MessageDispatchBridge(Context context) throws Exception {
        manager = context.getSystemService("msgcenter");
        if (manager == null) throw new IllegalStateException("message_dispatch_unavailable");
        sendMessage = manager.getClass().getMethod(
                "sendMessage", int.class, int.class, int.class, Parcelable.class);
        wifi = (WifiManager) context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        web = new ProvisioningWebServer(context, this::scanWifi, this::configureWifi);
        closeWeb = web::close;
        stopOriginal = () -> {
            try { send(TURN_OFF); } catch (Exception ignored) { }
        };
    }

    void openOriginalProvisioning() throws Exception {
        main.removeCallbacks(closeWeb);
        main.removeCallbacks(stopOriginal);
        web.close();
        web.start();
        // Capture fresh station-mode results before NetControl changes wlan0 to AP mode.
        if (wifi.startScan()) SystemClock.sleep(2200L);
        try { send(TURN_ON); }
        catch (Exception error) { web.close(); throw error; }
        lastResult = "waiting_for_phone";
        openedAtMs = SystemClock.elapsedRealtime();
        main.postDelayed(closeWeb, 300000L);
    }

    void closeOriginalProvisioning() throws Exception {
        main.removeCallbacks(closeWeb);
        main.removeCallbacks(stopOriginal);
        web.close();
        // NetControl starts SoftAP asynchronously. Sending OFF immediately after ON
        // can be overtaken by the late AP enable and leave a timerless hotspot.
        long delay = Math.max(0L, 5000L - (SystemClock.elapsedRealtime() - openedAtMs));
        if (delay > 0L) main.postDelayed(stopOriginal, delay);
        else send(TURN_OFF);
    }

    String lastResult() { return lastResult; }

    private byte[] scanWifi() throws Exception {
        if (wifi.startScan()) SystemClock.sleep(2200L);
        List<ScanResult> results = wifi.getScanResults();
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
        return array.toString().getBytes(StandardCharsets.UTF_8);
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
        WifiConfiguration configuration = configuration(ssid, secure, password);
        lastResult = "applying";
        try {
            send(TURN_OFF);
            web.close();
            // NetControl restores the previous station after stopping its AP. Let that
            // firmware operation settle before selecting the submitted network.
            SystemClock.sleep(2500L);
            connectWifi(configuration);
            lastResult = "connected";
        } catch (Exception error) {
            lastResult = "failed";
            throw error;
        }
    }

    private void connectWifi(WifiConfiguration configuration) {
        if (!wifi.isWifiEnabled() && !wifi.setWifiEnabled(true)) throw new IllegalStateException("wifi_enable_failed");
        for (int wait = 0; wait < 20 && !wifi.isWifiEnabled(); wait++) SystemClock.sleep(500L);
        if (!wifi.isWifiEnabled()) throw new IllegalStateException("wifi_enable_timeout");
        List<WifiConfiguration> existing = wifi.getConfiguredNetworks();
        if (existing != null) for (WifiConfiguration item : existing)
            if (configuration.SSID.equals(item.SSID)) { configuration.networkId = item.networkId; break; }
        int network = configuration.networkId >= 0 ? wifi.updateNetwork(configuration) : wifi.addNetwork(configuration);
        if (network < 0 || !wifi.saveConfiguration()) throw new IllegalStateException("wifi_configuration_rejected");
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
