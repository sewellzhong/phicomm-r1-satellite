package dev.sewellzhong.r1probe;

import java.io.IOException;

/** No shell/path parameters are exposed: only the two protocol operations exist. */
final class SystemControlClient implements R1PrivacyLed.Driver {
    @Override public int[] setAndRead(int first, int second) throws IOException {
        int[] actual = SystemControlNative.setLed(first, second);
        if (actual == null || actual.length != 2) throw new IOException("system_control_led_reply_invalid");
        return actual;
    }

    void reboot() throws IOException { SystemControlNative.reboot(); }
}
