package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.assertFalse;
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

    @Test public void mapsScanSecurityWithoutExposingCapabilities() {
        assertEquals("WPA", R1MessageDispatchBridge.security("[WPA2-PSK-CCMP][ESS]"));
        assertEquals("WEP", R1MessageDispatchBridge.security("[WEP][ESS]"));
        assertEquals("INSECURE", R1MessageDispatchBridge.security("[ESS]"));
        assertEquals("UNSUPPORTED", R1MessageDispatchBridge.security("[WPA2-EAP-CCMP][ESS]"));
    }

    @Test public void extractsOnlyTheRequestedCookie() {
        String headers = "GET / HTTP/1.1\r\nCookie: theme=light; R1SESSION=abc_123; x=y\r\n\r\n";
        assertEquals("abc_123", ProvisioningWebServer.cookie(headers, "R1SESSION"));
        assertNull(ProvisioningWebServer.cookie(headers, "missing"));
    }

    @Test public void oneBrowserOwnsEachProvisioningWindowAndSubmitsOnce() {
        ProvisioningWebServer.Owner owner = new ProvisioningWebServer.Owner();
        String token = owner.claim(null);
        assertTrue(owner.authorized(token));
        assertEquals(token, owner.claim(token));
        assertNull(owner.claim("another-phone"));
        assertTrue(owner.submit());
        assertFalse(owner.submit());
        owner.reset();
        assertFalse(owner.authorized(token));
    }
}
