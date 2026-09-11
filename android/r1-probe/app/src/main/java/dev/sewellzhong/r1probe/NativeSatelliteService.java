package dev.sewellzhong.r1probe;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.net.ConnectivityManager;
import android.net.Credentials;
import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import dev.sewellzhong.r1probe.esphome.NativeApiConnection;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import org.json.JSONObject;

/** Single authenticated HA owner, persistent opt-in, and shell-only local administration. */
public final class NativeSatelliteService extends Service {
    private NativeSettings settings;
    private AudioDiagnostic diagnostic;
    private HardwareInputMonitor hardware;
    private DeviceCapabilityProbe capabilities;
    private HotspotCapabilityProbe hotspot;
    private R1MessageDispatchBridge originalProvisioning;
    private R1SystemKeyMonitor systemKeys;
    private volatile boolean destroyed;
    private volatile Socket client;
    private volatile LocalSocket adminClient;
    private volatile ServerSocket server;
    private LocalServerSocket control;
    private volatile NativeAudioRuntime audio;
    private volatile NativeAudioHealth health;
    private volatile String state = "initializing", error;
    private volatile long connections, failures;
    private volatile String isolation = "unknown";
    private boolean audioPermitted() {
        isolation = FactoryAudioIsolation.inspect(this);
        if (!FactoryAudioIsolation.permitsAudio(isolation)) {
            if (!settings.audioBlocked()) settings.blockAudio("factory_audio_not_isolated");
            return false;
        }
        return !settings.audioBlocked();
    }
    private Thread worker, controller;
    private volatile PowerManager.WakeLock wakeLock;
    private final android.os.Handler main = new android.os.Handler();
    private final Runnable renewLock = new Runnable() {
        @Override public void run() {
            PowerManager.WakeLock current = wakeLock;
            if (!destroyed && settings.enabled() && current != null) current.acquire(120000L);
            if (!destroyed) main.postDelayed(this, 60000L);
        }
    };
    private NsdManager nsd;
    private NsdManager.RegistrationListener registration;
    private final BroadcastReceiver network = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            // A changed route invalidates in-flight commands; HA reconnects via discovery.
            closeClient();
            synchronized (NativeSatelliteService.this) { unpublish(); if (server != null) publish(); }
        }
    };

    @Override public void onCreate() {
        super.onCreate();
        settings = new NativeSettings(this);
        diagnostic = new AudioDiagnostic(getFilesDir());
        hardware = new HardwareInputMonitor(this, settings);
        capabilities = new DeviceCapabilityProbe(this);
        hotspot = new HotspotCapabilityProbe(this, settings);
        try { originalProvisioning = new R1MessageDispatchBridge(this); }
        catch (Exception ignored) { originalProvisioning = null; }
        try {
            systemKeys = new R1SystemKeyMonitor(this, new R1SystemKeyMonitor.Listener() {
                @Override public void shortPress() {
                    NativeAudioRuntime current = audio;
                    if (current != null) current.cancelAudio(
                            dev.sewellzhong.r1probe.esphome.NativeAudioCoordinator.CancelReason.USER_STOP);
                }
                @Override public void longPress() {
                    if (originalProvisioning == null) return;
                    Thread trigger = new Thread(() -> {
                        try { originalProvisioning.openOriginalProvisioning(); }
                        catch (Exception ignored) { }
                    }, "r1-key-provisioning");
                    trigger.setDaemon(true); trigger.start();
                }
            });
            systemKeys.start();
        } catch (Exception ignored) { systemKeys = null; }
        hardware.start();
        if (settings.enabled()) audioPermitted();
        main.postDelayed(renewLock, 60000L);
        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            manager.createNotificationChannel(new NotificationChannel("native-satellite", "R1 原生语音", NotificationManager.IMPORTANCE_LOW));
            builder = new Notification.Builder(this, "native-satellite");
        } else builder = new Notification.Builder(this);
        startForeground(44, builder.setSmallIcon(R.drawable.ic_probe).setContentTitle("R1 原生中文语音")
                .setContentText("配对后按配置监听；唤醒后上传命令").setOngoing(true).build());
        nsd = (NsdManager) getSystemService(NSD_SERVICE);
        registerReceiver(network, new IntentFilter(ConnectivityManager.CONNECTIVITY_ACTION));
        try {
            control = new LocalServerSocket("r1-native-control");
            controller = new Thread(this::controlLoop, "native-administration");
            worker = new Thread(this::serve, "native-server");
            controller.start(); worker.start();
        } catch (IOException e) { error = "control_unavailable"; stopSelf(); }
    }
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && "stop".equals(intent.getAction())) {
            settings.enable(false, false); closeClient(); stopSelf();
            return START_NOT_STICKY;
        }
        return settings.enabled() ? START_STICKY : START_NOT_STICKY;
    }
    @Override public IBinder onBind(Intent intent) { return null; }

    private void serve() {
        try {
            while (!destroyed) {
                if (!settings.enabled()) { state = settings.configured() ? "disabled" : "uninitialized"; Thread.sleep(200); continue; }
                if (!AudioOwner.acquire(this)) { state = "audio_owned_by_other_runtime"; Thread.sleep(1000); continue; }
                try {
                    PowerManager power = (PowerManager) getSystemService(POWER_SERVICE);
                    wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "r1probe:native");
                    wakeLock.setReferenceCounted(false);
                    // Renew while enabled; never rely on a permanent, unreleased acquisition.
                    wakeLock.acquire(120000L);
                    ServerSocket listener = new ServerSocket();
                    server = listener;
                    listener.setReuseAddress(true); listener.bind(new InetSocketAddress(6053)); listener.setSoTimeout(1000);
                    synchronized (this) { if (!destroyed) publish(); }
                    while (!destroyed && settings.enabled()) {
                        if (!wakeLock.isHeld()) wakeLock.acquire(120000L);
                        state = "waiting_ha";
                        audioPermitted();
                        try {
                            Socket accepted = listener.accept(); client = accepted;
                            if (destroyed || !settings.enabled()) { closeClient(); break; }
                            boolean permitted = audioPermitted();
                            NativeAudioRuntime current = new NativeAudioRuntime(this,
                                    settings.listening() && permitted, this::audioPermitted);
                            current.diagnostic(diagnostic);
                            audio = current;
                            byte[] key = settings.key();
                            try {
                                connections++;
                                state = "handshaking";
                                new NativeApiConnection(accepted, settings.name(), settings.mac(), current, true).run(key);
                                error = null;
                            } catch (IOException | RuntimeException | LinkageError e) {
                                if (!destroyed && settings.enabled()) { failures++; error = "native_connection_or_audio_failed"; }
                            } finally {
                                Arrays.fill(key, (byte) 0); closeClient();
                                current.closed();
                                // Never let a replacement capture race a previous AudioRecord/AudioTrack.
                                long cleanupDeadline = System.nanoTime() + 5_000_000_000L;
                                while (!current.terminated()) {
                                    state = "waiting_audio_release";
                                    if (System.nanoTime() >= cleanupDeadline) {
                                        // Preserve management/HA connectivity after restart, but do not retry a
                                        // known blocked audio backend until an administrator explicitly requests it.
                                        settings.blockAudio(); closeServer();
                                        android.os.Process.killProcess(android.os.Process.myPid());
                                        return;
                                    }
                                    Thread.sleep(100);
                                }
                                audio = null;
                            }
                            if (!destroyed) Thread.sleep(250);
                        } catch (SocketTimeoutException ignored) { }
                    }
                } catch (IOException | RuntimeException e) {
                    if (!destroyed && settings.enabled()) { error = "native_listener_failed"; failures++; }
                    if (!destroyed) Thread.sleep(2000);
                } finally {
                    synchronized (this) { unpublish(); }
                    closeServer();
                    if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
                    wakeLock = null;
                    if (audio == null || audio.terminated()) AudioOwner.release(this);
                }
            }
        } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
        finally {
            closeClient(); closeServer();
            NativeAudioRuntime current = audio;
            if (current != null) current.closed();
            if (current == null || current.terminated()) AudioOwner.release(this);
            state = "stopped";
        }
    }

    private void controlLoop() {
        while (!destroyed) {
            try (LocalSocket socket = control.accept()) {
                adminClient = socket;
                Credentials peer = socket.getPeerCredentials();
                if (peer.getUid() != 0 && peer.getUid() != 2000) continue;
                socket.setSoTimeout(5000);
                JSONObject response;
                try {
                    ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                    int value;
                    while ((value = socket.getInputStream().read()) != -1 && value != '\n') {
                        if (bytes.size() >= 4096) throw new IOException("request_too_large");
                        bytes.write(value);
                    }
                    JSONObject command = new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8));
                    String action = command.getString("action");
                    JSONObject actionResponse = null;
                    switch (action) {
                        case "diagnostic-arm":
                        case "diagnostic-start":
                            if(audio==null || !"listening".equals(audio.status())) throw new IllegalStateException("idle_listener_required");
                            if("diagnostic-arm".equals(action)) diagnostic.arm(command.optInt("seconds",30));
                            else diagnostic.start(command.optInt("seconds",30));
                            diagnostic.event(System.nanoTime(),"format=PCM_S16LE,rate=16000,channels=1,purpose=silence_diagnosis,utc_ms="+System.currentTimeMillis());
                            break;
                        case "diagnostic-stop": diagnostic.stop("requested"); break;
                        case "diagnostic-clear": diagnostic.clear(command.getString("sha256")); break;
                        case "diagnostic-status": case "diagnostic-export": break;
                        case "diagnostic-window":
                            if (audio == null || !settings.listening()) throw new IllegalStateException("listener_required");
                            audio.diagnosticWindow(command.optBoolean("followup", false),command.optInt("prompt_index",-1));
                            break;
                        case "audio-check":
                            if (!audioPermitted() || settings.enabled() || (health != null && health.alive())) throw new IllegalStateException("stop_before_audio_check");
                            NativeAudioHealth check = new NativeAudioHealth(() -> {
                                settings.blockAudio();
                                android.os.Process.killProcess(android.os.Process.myPid());
                            });
                            if (!check.start()) throw new IllegalStateException("audio_owned_by_other_runtime");
                            health = check;
                            break;
                        case "initialize": settings.initialize(command.getString("name")); break;
                        case "start":
                            boolean listen = command.optBoolean("listen", false);
                            settings.enable(true, listen);
                            if (listen) audioPermitted();
                            closeClient();
                            // Update Android's restart policy after configuration was persisted.
                            startService(new Intent(this, NativeSatelliteService.class));
                            break;
                        case "stop": settings.enable(false, false); closeClient(); closeServer(); break;
                        case "rotate": settings.rotate(); break;
                        case "hardware-reset": hardware.reset(); break;
                        case "capability-status": break;
                        case "bluetooth-discoverable": capabilities.openDiscoverable(command.optInt("seconds", 60)); break;
                        case "bluetooth-close": capabilities.closeDiscoverable(); break;
                        case "ble-window": capabilities.openBle(command.optInt("seconds", 60)); break;
                        case "ble-close": capabilities.stopBle(); break;
                        case "hotspot-window": actionResponse = hotspot.open(command.optInt("seconds", 120)); break;
                        case "hotspot-close": hotspot.close(); break;
                        case "original-provisioning-open":
                            if (originalProvisioning == null) throw new IllegalStateException("message_dispatch_unavailable");
                            originalProvisioning.openOriginalProvisioning();
                            break;
                        case "original-provisioning-close":
                            if (originalProvisioning == null) throw new IllegalStateException("message_dispatch_unavailable");
                            originalProvisioning.closeOriginalProvisioning();
                            break;
                        case "provisioning-recover":
                            if (originalProvisioning == null) throw new IllegalStateException("message_dispatch_unavailable");
                            originalProvisioning.recoverWifi();
                            break;
                        case "provisioning-handoff-probe":
                            if (originalProvisioning == null) throw new IllegalStateException("message_dispatch_unavailable");
                            actionResponse = originalProvisioning.probeHandoff();
                            break;
                        case "status": case "pairing": break;
                        default: throw new IllegalArgumentException("unsupported_action");
                    }
                    response = action.startsWith("diagnostic-") && !"diagnostic-window".equals(action)
                            ? diagnosticSnapshot() : snapshot();
                    if (action.equals("capability-status") || action.equals("hardware-reset")
                            || action.startsWith("bluetooth-") || action.startsWith("ble-")
                            || action.startsWith("hotspot-") || action.startsWith("original-provisioning-")
                            || action.equals("provisioning-recover") || action.equals("provisioning-handoff-probe"))
                        response = capabilitySnapshot();
                    if (actionResponse != null) {
                        java.util.Iterator<String> keys = actionResponse.keys();
                        while (keys.hasNext()) { String key = keys.next(); response.put(key, actionResponse.get(key)); }
                    }
                    if("diagnostic-export".equals(action)) {
                        if(!diagnostic.hash().equals(command.getString("sha256"))) throw new IllegalStateException("capture_changed");
                        long offset=command.getLong("offset");
                        response.put("offset",offset).put("data",android.util.Base64.encodeToString(diagnostic.read(offset),android.util.Base64.NO_WRAP));
                    }
                    if ("pairing".equals(action)) {
                        if (!settings.configured()) throw new IllegalStateException("initialization_required");
                        response.put("noise_psk", settings.encodedKey());
                    }
                } catch (Exception e) { response = new JSONObject().put("error", "control_request_rejected"); }
                socket.getOutputStream().write((response.toString() + "\n").getBytes(StandardCharsets.UTF_8));
            } catch (Exception ignored) { /* No request/exception text: administration can carry secrets. */ }
            finally { adminClient = null; }
        }
    }
    private JSONObject diagnosticSnapshot() throws Exception {
        boolean ready=diagnostic.ready();
        return new JSONObject().put("active",diagnostic.active()).put("armed",diagnostic.armed()).put("ready",ready)
                .put("reason",diagnostic.reason()).put("records",diagnostic.records()).put("bytes",diagnostic.bytes())
                .put("max_offer_us",diagnostic.maxOfferNanos()/1000)
                .put("max_producer_us",diagnostic.maxProducerNanos()/1000)
                .put("max_capture_producer_us",diagnostic.maxCaptureProducerNanos()/1000)
                .put("max_playback_producer_us",diagnostic.maxPlaybackProducerNanos()/1000)
                .put("producer_over_budget",diagnostic.producerOverBudget())
                .put("sha256",ready?diagnostic.hash():JSONObject.NULL);
    }
    private JSONObject snapshot() throws org.json.JSONException {
        NativeAudioRuntime current = audio;
        isolation = FactoryAudioIsolation.inspect(this);
        String currentError = settings.audioBlocked() ? settings.audioBlockReason()
                : current != null && current.authenticated() ? current.failureCode() : error;
        return new JSONObject().put("status", settings.audioBlocked() ? "audio_blocked" : current == null ? state : current.status())
                .put("audio_blocked", settings.audioBlocked()).put("factory_isolation", isolation)
                .put("last_error", currentError == null ? JSONObject.NULL : currentError)
                .put("configured", settings.configured()).put("enabled", settings.enabled())
                .put("volume_percent", settings.volumePercent()).put("wait_seconds", settings.waitSeconds()).put("followup_wait_seconds", settings.followupWaitSeconds()).put("quiet_seconds", settings.quietSeconds())
                .put("command_seconds", settings.commandSeconds()).put("speech_speed", settings.speechSpeed())
                .put("listen", settings.listening()).put("name", settings.name()).put("device_id", settings.id())
                .put("protocol_mac", settings.mac()).put("connections", connections).put("failures", failures)
                .put("port", 6053).put("audio_opened", current != null && current.audioOpened())
                .put("audio", current == null ? JSONObject.NULL : current.diagnostics())
                .put("health", health == null ? JSONObject.NULL : health.snapshot())
                .put("hardware", hardware.snapshot());
    }
    private JSONObject capabilitySnapshot() throws org.json.JSONException {
        return new JSONObject().put("hardware", hardware.snapshot())
                .put("system_keys", systemKeys == null ? JSONObject.NULL : systemKeys.snapshot())
                .put("capabilities", capabilities.snapshot()).put("hotspot", hotspot.snapshot())
                .put("original_provisioning_bridge", originalProvisioning != null)
                .put("original_provisioning_page", "http://192.168.43.1:8080/")
                .put("original_provisioning_result", originalProvisioning == null
                        ? "unavailable" : originalProvisioning.lastResult())
                .put("original_provisioning_stage", originalProvisioning == null
                        ? "unavailable" : originalProvisioning.stage())
                .put("original_provisioning_pending", originalProvisioning != null
                        && originalProvisioning.pending());
    }
    private synchronized void publish() {
        if (registration != null || destroyed || !settings.enabled()) return;
        NsdServiceInfo info = new NsdServiceInfo();
        info.setServiceName(settings.name()); info.setServiceType("_esphomelib._tcp."); info.setPort(6053);
        info.setAttribute("version", "2026.8.0"); info.setAttribute("mac", settings.mac().replace(":", "").toLowerCase(java.util.Locale.ROOT));
        info.setAttribute("platform", "R1"); info.setAttribute("network", "wifi");
        info.setAttribute("api_encryption", "Noise_NNpsk0_25519_ChaChaPoly_SHA256");
        info.setAttribute("project_name", "sewellzhong.r1-satellite"); info.setAttribute("project_version", "0.89-reply-wake-interruption");
        registration = new NsdManager.RegistrationListener() {
            @Override public void onServiceRegistered(NsdServiceInfo serviceInfo) { }
            @Override public void onRegistrationFailed(NsdServiceInfo serviceInfo, int code) { error = "discovery_registration_failed"; }
            @Override public void onServiceUnregistered(NsdServiceInfo serviceInfo) { }
            @Override public void onUnregistrationFailed(NsdServiceInfo serviceInfo, int code) { }
        };
        try { nsd.registerService(info, NsdManager.PROTOCOL_DNS_SD, registration); }
        catch (RuntimeException e) { registration = null; error = "discovery_unavailable"; }
    }
    private synchronized void unpublish() {
        if (registration != null) {
            try { nsd.unregisterService(registration); } catch (RuntimeException ignored) { }
            registration = null;
        }
    }
    private void closeClient() {
        Socket current = client; if (current != null) try { current.close(); } catch (IOException ignored) { }
    }
    private void closeServer() {
        ServerSocket current = server; server = null;
        if (current != null) try { current.close(); } catch (IOException ignored) { }
    }
    @Override public void onDestroy() {
        diagnostic.stop("service_destroyed");
        hardware.stop(); capabilities.close(); hotspot.close();
        if (systemKeys != null) systemKeys.stop();
        if (originalProvisioning != null) try { originalProvisioning.serviceDestroyed(); }
        catch (Exception ignored) { }
        destroyed = true; main.removeCallbacks(renewLock); closeClient(); closeServer(); unpublish();
        unregisterReceiver(network);
        if (health != null) health.cancel();
        // API22 close() alone does not reliably wake a pending LocalServerSocket.accept().
        // Connect a rejected same-UID peer first so the old listener cannot consume a future admin request.
        if (control != null) {
            try (LocalSocket wake = new LocalSocket()) {
                wake.connect(new android.net.LocalSocketAddress("r1-native-control"));
            } catch (IOException ignored) { }
            try { control.close(); } catch (IOException ignored) { }
        }
        try { if (adminClient != null) adminClient.close(); } catch (IOException ignored) { }
        if (controller != null) {
            try { controller.join(1000); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
        }
        // Socket close wakes the owner; allow its cleanup/finally blocks to finish normally.
        stopForeground(true);
        super.onDestroy();
    }
}
