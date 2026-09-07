package dev.sewellzhong.r1probe;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattServer;
import android.bluetooth.BluetoothGattServerCallback;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.AdvertiseCallback;
import android.bluetooth.le.AdvertiseData;
import android.bluetooth.le.AdvertiseSettings;
import android.bluetooth.le.BluetoothLeAdvertiser;
import android.content.Context;
import android.content.pm.PackageManager;
import android.net.wifi.WifiConfiguration;
import android.net.wifi.WifiManager;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelUuid;
import java.io.File;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.json.JSONException;
import org.json.JSONObject;

/** Time-bounded, credential-free hardware feasibility probes for firmware 3448. */
final class DeviceCapabilityProbe {
    private static final int GATT_INVALID_OFFSET = 7;
    private static final UUID BLE_SERVICE = UUID.fromString("71e44a10-5688-4f41-9d41-9d8d21f8a101");
    private static final UUID BLE_VALUE = UUID.fromString("71e44a11-5688-4f41-9d41-9d8d21f8a101");
    private final Context context;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final BluetoothAdapter bluetooth = BluetoothAdapter.getDefaultAdapter();
    private final WifiManager wifi;
    private int previousScanMode = BluetoothAdapter.SCAN_MODE_NONE;
    private boolean discoverableActive, bleActive;
    private long discoverableUntilMs, bleUntilMs;
    private String bluetoothFailure, bleFailure;
    private BluetoothGattServer gattServer;
    private BluetoothLeAdvertiser advertiser;
    private int bleConnections;
    private final BluetoothGattServerCallback gattCallback = new BluetoothGattServerCallback() {
        @Override public void onConnectionStateChange(android.bluetooth.BluetoothDevice device, int status, int newState) {
            synchronized (DeviceCapabilityProbe.this) {
                if (status == BluetoothGatt.GATT_SUCCESS && newState == android.bluetooth.BluetoothProfile.STATE_CONNECTED)
                    bleConnections++;
            }
        }
        @Override public void onCharacteristicReadRequest(android.bluetooth.BluetoothDevice device, int requestId,
                int offset, BluetoothGattCharacteristic characteristic) {
            BluetoothGattServer current = gattServer;
            if (current == null) return;
            byte[] value = characteristic.getValue();
            if (value == null || offset < 0 || offset > value.length) {
                current.sendResponse(device, requestId, GATT_INVALID_OFFSET, offset, null);
                return;
            }
            current.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, offset,
                    java.util.Arrays.copyOfRange(value, offset, value.length));
        }
    };
    private final AdvertiseCallback advertiseCallback = new AdvertiseCallback() {
        @Override public void onStartFailure(int errorCode) {
            synchronized (DeviceCapabilityProbe.this) { bleFailure = "ble_advertise_failed_" + errorCode; bleActive = false; }
            stopBle();
        }
    };

    DeviceCapabilityProbe(Context context) {
        this.context = context;
        wifi = (WifiManager) context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
    }

    synchronized void openDiscoverable(int seconds) throws Exception {
        validateSeconds(seconds);
        if (bluetooth == null || !bluetooth.isEnabled()) throw new IllegalStateException("bluetooth_unavailable");
        previousScanMode = bluetooth.getScanMode();
        setScanMode(BluetoothAdapter.SCAN_MODE_CONNECTABLE_DISCOVERABLE, seconds);
        bluetoothFailure = null; discoverableActive = true;
        discoverableUntilMs = android.os.SystemClock.elapsedRealtime() + seconds * 1000L;
        main.removeCallbacks(closeDiscoverable); main.postDelayed(closeDiscoverable, seconds * 1000L);
    }
    private final Runnable closeDiscoverable = new Runnable() { @Override public void run() { closeDiscoverable(); } };
    synchronized void closeDiscoverable() {
        if (!discoverableActive || bluetooth == null) return;
        try { setScanMode(previousScanMode, 1); }
        catch (Exception e) { bluetoothFailure = "bluetooth_restore_failed"; }
        discoverableActive = false; discoverableUntilMs = 0;
    }

    synchronized void openBle(int seconds) throws Exception {
        validateSeconds(seconds);
        if (bleActive) throw new IllegalStateException("ble_window_already_active");
        BluetoothManager manager = (BluetoothManager) context.getSystemService(Context.BLUETOOTH_SERVICE);
        if (manager == null || bluetooth == null || !bluetooth.isEnabled()) throw new IllegalStateException("ble_unavailable");
        advertiser = bluetooth.getBluetoothLeAdvertiser();
        if (advertiser == null) throw new IllegalStateException("ble_advertiser_unavailable");
        gattServer = manager.openGattServer(context, gattCallback);
        if (gattServer == null) throw new IllegalStateException("gatt_server_unavailable");
        BluetoothGattService service = new BluetoothGattService(BLE_SERVICE, BluetoothGattService.SERVICE_TYPE_PRIMARY);
        BluetoothGattCharacteristic value = new BluetoothGattCharacteristic(BLE_VALUE,
                BluetoothGattCharacteristic.PROPERTY_READ, BluetoothGattCharacteristic.PERMISSION_READ);
        value.setValue("r1-capability".getBytes(StandardCharsets.UTF_8)); service.addCharacteristic(value);
        if (!gattServer.addService(service)) { stopBle(); throw new IllegalStateException("gatt_service_rejected"); }
        AdvertiseSettings settings = new AdvertiseSettings.Builder().setConnectable(true)
                .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)
                .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_MEDIUM).setTimeout(0).build();
        AdvertiseData data = new AdvertiseData.Builder().setIncludeDeviceName(false)
                .addServiceUuid(new ParcelUuid(BLE_SERVICE)).build();
        bleFailure = null; bleConnections = 0; bleActive = true;
        bleUntilMs = android.os.SystemClock.elapsedRealtime() + seconds * 1000L;
        advertiser.startAdvertising(settings, data, advertiseCallback);
        main.removeCallbacks(closeBle); main.postDelayed(closeBle, seconds * 1000L);
    }
    private final Runnable closeBle = new Runnable() { @Override public void run() { stopBle(); } };
    synchronized void stopBle() {
        main.removeCallbacks(closeBle);
        if (advertiser != null) try { advertiser.stopAdvertising(advertiseCallback); } catch (RuntimeException ignored) { }
        if (gattServer != null) try { gattServer.close(); } catch (RuntimeException ignored) { }
        advertiser = null; gattServer = null; bleActive = false; bleUntilMs = 0;
    }

    synchronized JSONObject snapshot() throws JSONException {
        PackageManager packages = context.getPackageManager();
        boolean bleFeature = packages.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE);
        return new JSONObject()
                .put("input_event0_readable", new File("/dev/input/event0").canRead())
                .put("input_event1_readable", new File("/dev/input/event1").canRead())
                .put("led0_writable", new File("/sys/class/leds/multi_leds0/brightness").canWrite())
                .put("led1_writable", new File("/sys/class/leds/multi_leds1/brightness").canWrite())
                .put("bluetooth_available", bluetooth != null)
                .put("bluetooth_enabled", bluetooth != null && bluetooth.isEnabled())
                .put("bluetooth_discoverable", bluetooth != null && bluetooth.getScanMode() == BluetoothAdapter.SCAN_MODE_CONNECTABLE_DISCOVERABLE)
                .put("discoverable_window", discoverableActive)
                .put("discoverable_remaining_seconds", remaining(discoverableUntilMs))
                .put("bluetooth_failure", bluetoothFailure == null ? JSONObject.NULL : bluetoothFailure)
                .put("ble_feature", bleFeature)
                .put("ble_advertiser", bluetooth != null && bluetooth.isEnabled() && bluetooth.getBluetoothLeAdvertiser() != null)
                .put("ble_window", bleActive).put("ble_connections", bleConnections)
                .put("ble_remaining_seconds", remaining(bleUntilMs))
                .put("ble_failure", bleFailure == null ? JSONObject.NULL : bleFailure)
                .put("legacy_hotspot_api", method(WifiManager.class, "setWifiApEnabled", WifiConfiguration.class, boolean.class))
                .put("wifi_enabled", wifi != null && wifi.isWifiEnabled());
    }
    private static boolean method(Class<?> type, String name, Class<?>... parameters) {
        try { type.getDeclaredMethod(name, parameters); return true; }
        catch (NoSuchMethodException e) { return false; }
    }
    private void setScanMode(int mode, int seconds) throws Exception {
        try {
            Method method = BluetoothAdapter.class.getDeclaredMethod("setScanMode", int.class, int.class);
            method.setAccessible(true);
            Object result = method.invoke(bluetooth, mode, seconds);
            if (result instanceof Boolean && !((Boolean) result)) throw new IllegalStateException("scan_mode_rejected");
        } catch (NoSuchMethodException missingDuration) {
            Method method = BluetoothAdapter.class.getDeclaredMethod("setScanMode", int.class);
            method.setAccessible(true);
            Object result = method.invoke(bluetooth, mode);
            if (result instanceof Boolean && !((Boolean) result)) throw new IllegalStateException("scan_mode_rejected");
        }
    }
    private static int remaining(long until) {
        return until == 0 ? 0 : (int) Math.max(0, (until - android.os.SystemClock.elapsedRealtime() + 999) / 1000);
    }
    private static void validateSeconds(int seconds) {
        if (seconds < 15 || seconds > 120) throw new IllegalArgumentException("invalid_window_seconds");
    }
    void close() { closeDiscoverable(); stopBle(); }
}
