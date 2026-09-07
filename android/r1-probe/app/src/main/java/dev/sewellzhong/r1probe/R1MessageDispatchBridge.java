package dev.sewellzhong.r1probe;

import android.annotation.SuppressLint;
import android.content.Context;
import android.os.Parcelable;
import java.lang.reflect.Method;

/** Firmware-3448 bridge to the existing system provisioning service. */
final class R1MessageDispatchBridge {
    private static final int TYPE_WIFI_CONFIG = 262144;
    private static final int TURN_ON = 1;
    private static final int TURN_OFF = 2;

    private final Object manager;
    private final Method sendMessage;

    @SuppressLint("WrongConstant")
    R1MessageDispatchBridge(Context context) throws Exception {
        manager = context.getSystemService("msgcenter");
        if (manager == null) throw new IllegalStateException("message_dispatch_unavailable");
        sendMessage = manager.getClass().getMethod(
                "sendMessage", int.class, int.class, int.class, Parcelable.class);
    }

    void openOriginalProvisioning() throws Exception {
        send(TURN_ON);
    }

    void closeOriginalProvisioning() throws Exception {
        send(TURN_OFF);
    }

    private void send(int command) throws Exception {
        sendMessage.invoke(manager, TYPE_WIFI_CONFIG, command, 0, null);
    }
}
