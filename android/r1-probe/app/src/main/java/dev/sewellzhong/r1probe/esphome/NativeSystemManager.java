package dev.sewellzhong.r1probe.esphome;

import org.json.JSONObject;

/** Persistent two-phase system operations and a bounded, read-only device snapshot. */
public final class NativeSystemManager {
    public interface Store {
        String load();
        void save(String value);
    }
    public interface Diagnostics { JSONObject snapshot() throws Exception; }
    public interface Actions {
        void dispatch(String operation, Failure failure) throws Exception;
    }
    public interface Failure { void failed(String reason); }

    private static final int SCHEMA = 1;
    private final Store store;
    private final Diagnostics diagnostics;
    private final Actions actions;
    private final String serviceInstance;
    private final String bootIdentity;
    private JSONObject lifecycle;

    public NativeSystemManager(Store store, Diagnostics diagnostics, Actions actions,
            String serviceInstance, String bootIdentity) {
        if (store == null || diagnostics == null || actions == null
                || !token(serviceInstance) || !token(bootIdentity))
            throw new IllegalArgumentException("system_dependencies_required");
        this.store = store; this.diagnostics = diagnostics; this.actions = actions;
        this.serviceInstance = serviceInstance; this.bootIdentity = bootIdentity;
        restore();
    }

    public synchronized JSONObject request(String operation, String requestId) throws Exception {
        if (!requestId.matches("[a-f0-9]{32}"))
            throw new IllegalArgumentException("system_request_id_invalid");
        if ("status".equals(operation)) return snapshot(requestId, operation);
        if (!"restart_service".equals(operation) && !"reboot_device".equals(operation))
            throw new IllegalArgumentException("system_operation_invalid");
        if ("requested".equals(lifecycle.optString("state")))
            throw new IllegalStateException("system_operation_busy");
        lifecycle = new JSONObject().put("schema", SCHEMA).put("id", requestId)
                .put("operation", operation).put("state", "requested")
                .put("origin_service", serviceInstance).put("origin_boot", bootIdentity)
                .put("error", JSONObject.NULL);
        save();
        return snapshot(requestId, operation);
    }

    public void dispatch(String operation) throws Exception {
        actions.dispatch(operation, reason -> failed(operation, reason));
    }

    public synchronized void failed(String operation, String reason) {
        if (!operation.equals(lifecycle.optString("operation"))
                || !"requested".equals(lifecycle.optString("state"))) return;
        String safe = reason != null && reason.matches("system_[a-z0-9_]{1,64}")
                ? reason : "system_operation_failed";
        try {
            lifecycle.put("state", "failed").put("error", safe);
            save();
        } catch (Exception ignored) { /* The prior requested record remains fail-closed. */ }
    }

    public synchronized JSONObject snapshot(String requestId, String operation) throws Exception {
        JSONObject result = diagnostics.snapshot();
        if (result == null) throw new IllegalStateException("system_diagnostics_unavailable");
        result.put("schema", SCHEMA).put("request_id", requestId).put("operation", operation)
                .put("last_operation_id", lifecycle.optString("id", ""))
                .put("last_operation", lifecycle.optString("operation", "none"))
                .put("last_operation_state", lifecycle.optString("state", "none"))
                .put("last_operation_error", lifecycle.isNull("error")
                        ? JSONObject.NULL : lifecycle.optString("error"));
        return result;
    }

    private void restore() {
        try {
            String encoded = store.load();
            lifecycle = encoded == null || encoded.isEmpty() ? empty() : new JSONObject(encoded);
            if (lifecycle.optInt("schema") != SCHEMA) lifecycle = empty();
        } catch (Exception ignored) { lifecycle = empty(); }
        if (!"requested".equals(lifecycle.optString("state"))) return;
        String operation = lifecycle.optString("operation");
        boolean completed = "restart_service".equals(operation)
                && !serviceInstance.equals(lifecycle.optString("origin_service"));
        completed |= "reboot_device".equals(operation)
                && !bootIdentity.equals(lifecycle.optString("origin_boot"));
        if (completed) {
            try {
                lifecycle.put("state", "completed").put("error", JSONObject.NULL);
                save();
            } catch (Exception error) {
                lifecycle = empty();
            }
        }
    }

    private static JSONObject empty() {
        JSONObject value = new JSONObject();
        try {
            return value.put("schema", SCHEMA).put("id", "")
                    .put("operation", "none").put("state", "none").put("error", JSONObject.NULL);
        } catch (Exception impossible) { throw new IllegalStateException(impossible); }
    }
    private void save() {
        try { store.save(lifecycle.toString()); }
        catch (RuntimeException error) { throw error; }
        catch (Exception error) { throw new IllegalStateException("system_persistence_failed", error); }
    }
    private static boolean token(String value) {
        return value != null && value.matches("[A-Za-z0-9._:-]{1,128}");
    }
}
