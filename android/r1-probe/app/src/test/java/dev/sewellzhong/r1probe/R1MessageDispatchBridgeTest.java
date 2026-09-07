package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertThrows;
import org.junit.Test;

public class R1MessageDispatchBridgeTest {
    @Test public void acceptsExpectedConfigurations() {
        R1MessageDispatchBridge.validate("Home WiFi", "WPA", "password8");
        R1MessageDispatchBridge.validate("Guest", "INSECURE", "");
        R1MessageDispatchBridge.validate("Legacy", "WEP", "abcde");
    }

    @Test public void rejectsBadSsidAndSecurity() {
        assertThrows(IllegalArgumentException.class,
                () -> R1MessageDispatchBridge.validate("bad\nssid", "WPA", "password8"));
        assertThrows(IllegalArgumentException.class,
                () -> R1MessageDispatchBridge.validate("Home", "UNKNOWN", "password8"));
    }

    @Test public void rejectsBadPasswords() {
        assertThrows(IllegalArgumentException.class,
                () -> R1MessageDispatchBridge.validate("Home", "WPA", "short"));
        assertThrows(IllegalArgumentException.class,
                () -> R1MessageDispatchBridge.validate("Legacy", "WEP", "wrong-size"));
    }
}
