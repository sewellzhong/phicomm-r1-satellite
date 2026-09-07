package dev.sewellzhong.r1probe;

import android.content.Context;
import android.net.wifi.WifiConfiguration;
import android.net.wifi.WifiManager;
import android.os.Handler;
import android.os.Looper;
import java.io.IOException;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.lang.reflect.Method;
import java.security.SecureRandom;
import org.json.JSONException;
import org.json.JSONObject;

/** Temporary legacy SoftAP and local page probe with persistent crash/restart recovery. */
final class HotspotCapabilityProbe {
    private final WifiManager wifi;
    private final NativeSettings settings;
    private final Handler main = new Handler(Looper.getMainLooper());
    private boolean pending, active;
    private long untilMs;
    private String failure;
    private ServerSocket server;
    private Thread web;

    HotspotCapabilityProbe(Context context, NativeSettings settings) {
        this.settings = settings;
        wifi = (WifiManager) context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        if (settings.hotspotProbePending()) {
            // A previous probe did not close cleanly. Recover connectivity before accepting a new one.
            main.post(this::recoverPreviousProbe);
        }
    }

    synchronized JSONObject open(int seconds) throws Exception {
        if (seconds < 30 || seconds > 120) throw new IllegalArgumentException("invalid_window_seconds");
        if (pending || active || settings.hotspotProbePending()) throw new IllegalStateException("hotspot_window_already_active");
        Method method = WifiManager.class.getDeclaredMethod("setWifiApEnabled", WifiConfiguration.class, boolean.class);
        method.setAccessible(true);
        String suffix = token(4), passphrase = "R1" + token(10) + "!";
        WifiConfiguration configuration = new WifiConfiguration();
        configuration.SSID = "R1-Setup-" + suffix;
        configuration.preSharedKey = passphrase;
        configuration.allowedKeyManagement.set(WifiConfiguration.KeyMgmt.WPA_PSK);
        boolean previousWifi = wifi.isWifiEnabled();
        settings.hotspotProbe(true, previousWifi);
        pending = true; failure = null;
        // Return the ephemeral test credentials over the shell-only socket before Wi-Fi/ADB drops.
        main.postDelayed(() -> activate(method, configuration, previousWifi, seconds), 1500L);
        return new JSONObject().put("hotspot_scheduled", true).put("seconds", seconds)
                .put("test_ssid", configuration.SSID).put("temporary_passphrase", passphrase)
                .put("page", "http://192.168.43.1:8080/");
    }

    private void activate(Method method, WifiConfiguration configuration, boolean previousWifi, int seconds) {
        try {
            Object result = method.invoke(wifi, configuration, true);
            if (result instanceof Boolean && !((Boolean) result)) throw new IllegalStateException("hotspot_rejected");
            synchronized (this) { pending = false; active = true; untilMs = android.os.SystemClock.elapsedRealtime() + seconds * 1000L; }
            startWeb();
            main.postDelayed(() -> restore(previousWifi), seconds * 1000L);
        } catch (Exception e) {
            synchronized (this) { pending = false; active = false; failure = "hotspot_start_failed"; }
            restore(previousWifi);
        }
    }

    private void startWeb() throws IOException {
        server = new ServerSocket(8080);
        web = new Thread(() -> {
            while (active) {
                try (Socket client = server.accept()) {
                    client.setSoTimeout(2000);
                    byte[] discard = new byte[1024]; client.getInputStream().read(discard);
                    byte[] body = "R1 provisioning capability probe passed. No credentials were collected.\n"
                            .getBytes(StandardCharsets.UTF_8);
                    OutputStream output = client.getOutputStream();
                    output.write(("HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: "
                            + body.length + "\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
                    output.write(body); output.flush();
                } catch (IOException e) { if (active) failure = "hotspot_page_failed"; }
            }
        }, "r1-hotspot-page");
        web.setDaemon(true); web.start();
    }

    synchronized void close() {
        if (pending || active || settings.hotspotProbePending()) restore(settings.hotspotProbePreviousWifi());
    }
    private synchronized void recoverPreviousProbe() { restore(settings.hotspotProbePreviousWifi()); }
    private synchronized void restore(boolean previousWifi) {
        pending = false; active = false; untilMs = 0;
        if (server != null) try { server.close(); } catch (IOException ignored) { }
        server = null;
        try {
            Method method = WifiManager.class.getDeclaredMethod("setWifiApEnabled", WifiConfiguration.class, boolean.class);
            method.setAccessible(true); method.invoke(wifi, null, false);
        } catch (Exception e) { failure = "hotspot_restore_failed"; }
        if (previousWifi && !wifi.isWifiEnabled()) wifi.setWifiEnabled(true);
        settings.hotspotProbe(false, previousWifi);
    }

    synchronized JSONObject snapshot() throws JSONException {
        return new JSONObject().put("pending", pending).put("active", active)
                .put("remaining_seconds", untilMs == 0 ? 0 : Math.max(0,
                        (untilMs - android.os.SystemClock.elapsedRealtime() + 999) / 1000))
                .put("failure", failure == null ? JSONObject.NULL : failure);
    }
    private static String token(int length) {
        final char[] alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789".toCharArray();
        SecureRandom random = new SecureRandom(); StringBuilder result = new StringBuilder(length);
        for (int i = 0; i < length; i++) result.append(alphabet[random.nextInt(alphabet.length)]);
        return result.toString();
    }
}
