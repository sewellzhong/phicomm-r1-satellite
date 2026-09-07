package dev.sewellzhong.r1probe;

import android.annotation.SuppressLint;
import android.content.Context;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import org.json.JSONObject;

/** Observes firmware key messages without reading SELinux-protected evdev nodes. */
final class R1SystemKeyMonitor {
    interface Listener { void shortPress(); void longPress(); }
    private static final int TYPE_INPUT_KEY = 256;
    static final int NONE = 0, SHORT = 1, LONG = 2;

    private final Object manager;
    private final Class<?> receiverType;
    private final Method register, unregister;
    private final Listener listener;
    private Object receiver;
    private long shortPresses, longPresses;
    private String failure;

    @SuppressLint("WrongConstant")
    R1SystemKeyMonitor(Context context, Listener listener) throws Exception {
        this.listener = listener;
        manager = context.getSystemService("msgcenter");
        if (manager == null) throw new IllegalStateException("message_dispatch_unavailable");
        receiverType = Class.forName("android.os.MessageDispatchManager$MessageReceiver");
        register = manager.getClass().getMethod("registerMessageReceiver", receiverType, int.class);
        unregister = manager.getClass().getMethod("unregisterMessageReceiver", receiverType);
    }

    synchronized void start() {
        if (receiver != null) return;
        try {
            receiver = Proxy.newProxyInstance(receiverType.getClassLoader(), new Class<?>[]{receiverType},
                    (proxy, method, args) -> {
                        if ("notifyMsg".equals(method.getName()) && args != null && args.length >= 2) {
                            int event = eventFor(((Integer) args[0]).intValue(), ((Integer) args[1]).intValue());
                            if (event == SHORT) { synchronized (this) { shortPresses++; } listener.shortPress(); }
                            else if (event == LONG) { synchronized (this) { longPresses++; } listener.longPress(); }
                        } else if ("toString".equals(method.getName())) return "R1SystemKeyReceiver";
                        else if ("hashCode".equals(method.getName())) return System.identityHashCode(proxy);
                        else if ("equals".equals(method.getName())) return proxy == args[0];
                        return null;
                    });
            register.invoke(manager, receiver, TYPE_INPUT_KEY);
            failure = null;
        } catch (Exception error) {
            receiver = null;
            failure = "system_key_registration_failed";
        }
    }

    synchronized void stop() {
        if (receiver != null) try { unregister.invoke(manager, receiver); }
        catch (Exception ignored) { }
        receiver = null;
    }

    synchronized JSONObject snapshot() throws org.json.JSONException {
        return new JSONObject().put("running", receiver != null)
                .put("short_presses", shortPresses).put("long_presses", longPresses)
                .put("failure", failure == null ? JSONObject.NULL : failure);
    }

    static int eventFor(int what, int argument) {
        if (what != TYPE_INPUT_KEY) return NONE;
        if (argument == 1) return SHORT;
        if (argument == 5) return LONG;
        return NONE;
    }
}
